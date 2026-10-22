"""HD haptics over Bluetooth (experimental).

Over USB the DualSense shows up as a 4-channel sound card and channels 3-4 drive the
haptic actuators (audio_haptics.py). Over Bluetooth there is no sound card; instead the
host streams the actuator signal itself in HID output report 0x32:

    byte 0       0x32 report id
    byte 1       sequence number in the high nibble
    bytes 2-10   packet 0x11 (header 0x91, length 7): FE 00 00 00 00 FF <counter>
    bytes 11-76  packet 0x12 (header 0x92, length 64): 32 stereo frames, signed 8-bit, L R L R…
    bytes 77-137 zero
    bytes 138-141 CRC32 (seed byte 0xA2 + bytes 0-137), little endian

The signal is 3000 frames/s, so one report carries 10.67 ms and about 94 are sent per
second. Protocol research by SAxense (https://apps.sdore.me/SAxense, MPL-2.0); this is an
independent implementation from its description, not a copy of its code.
"""

import numpy as np

from output import bt_crc

REPORT_ID = 0x32
REPORT_LEN = 142
RATE = 3000                       # frames per second (stereo)
FRAMES = 32                       # per report
TICK = FRAMES / RATE              # 10.67 ms
MAX_BUFFER = int(0.10 * RATE)     # frames kept ready; more = more latency
LOWPASS_HZ = 1200                 # below the 1500 Hz Nyquist limit of 3 kHz


def build_report(samples, seq, counter):
    """64 sample bytes (signed 8-bit, L R interleaved) → the 142-byte report."""
    if len(samples) != 2 * FRAMES:
        raise ValueError("need exactly 64 sample bytes")
    r = bytearray(REPORT_LEN)
    r[0] = REPORT_ID
    r[1] = (seq & 0x0F) << 4
    r[2:11] = bytes([0x91, 7, 0xFE, 0, 0, 0, 0, 0xFF, counter & 0xFF])
    r[11:13] = bytes([0x92, 64])
    r[13:77] = bytes(samples)
    r[138:142] = bt_crc(r[:138]).to_bytes(4, "little")
    return bytes(r)


def to_int8(stereo):
    """(n, 2) floats in −1…1 → 2n signed bytes, L R interleaved."""
    x = np.clip(np.asarray(stereo, dtype=np.float32), -1.0, 1.0)
    return np.round(x * 127).astype(np.int8).reshape(-1).tobytes()


def _lowpass_taps(rate, cutoff, n=63):
    t = np.arange(n) - (n - 1) / 2
    h = np.sinc(2 * cutoff / rate * t) * np.hamming(n)
    return (h / h.sum()).astype(np.float32)


class BtHapticStream:
    """Collects audio (any rate) and hands out 0x32 reports at the right pace.

    push() is called from the audio thread, next_report() from the engine thread that owns
    the HID handle, so all controller writes stay on one thread."""

    def __init__(self):
        import threading
        self._lock = threading.Lock()
        self._buf = np.zeros((0, 2), dtype=np.float32)
        self._taps = {}
        self._tail = None
        self._tail_rate = None
        self._pos = 0.0               # fractional read position for resampling
        self._seq = 0
        self._counter = 0
        self._next = None             # time the next report is due
        self.game_rumble = (0, 0)
        self._phase = [0.0, 0.0]
        self.sent = 0
        self.dropped = 0

    # ------------------------------------------------ audio side

    def push(self, stereo, rate):
        """Captured block (n, 2) floats −1…1 at `rate` → filtered, resampled to 3 kHz, buffered."""
        stereo = np.asarray(stereo, dtype=np.float32)
        if len(stereo) == 0:
            return
        if rate not in self._taps:
            self._taps[rate] = _lowpass_taps(rate, LOWPASS_HZ)
        taps = self._taps[rate]
        if self._tail is None or self._tail_rate != rate:
            self._tail = np.zeros((len(taps) - 1, 2), dtype=np.float32)
            self._tail_rate, self._pos = rate, 0.0
        x = np.concatenate([self._tail, stereo])
        self._tail = x[-(len(taps) - 1):]
        y = np.stack([np.convolve(x[:, c], taps, mode="valid") for c in (0, 1)], axis=1)
        # resample by linear interpolation, keeping the phase across blocks
        step = rate / RATE
        idx = np.arange(self._pos, len(y) - 1, step)
        if len(idx):
            self._pos = idx[-1] + step - len(y)
            out = np.stack([np.interp(idx, np.arange(len(y)), y[:, c]) for c in (0, 1)], axis=1)
        else:
            self._pos -= len(y)
            out = np.zeros((0, 2), dtype=np.float32)
        with self._lock:
            self._buf = np.concatenate([self._buf, out.astype(np.float32)])
            if len(self._buf) > MAX_BUFFER:
                self.dropped += len(self._buf) - MAX_BUFFER
                self._buf = self._buf[-MAX_BUFFER:]

    def buffered(self):
        with self._lock:
            return len(self._buf)

    # ------------------------------------------------ controller side

    def _tones(self, n):
        """Game rumble as low tones (like the USB path), so rumble still works while HD is on."""
        out = np.zeros((n, 2), dtype=np.float32)
        t = np.arange(n) / RATE
        large, small = self.game_rumble
        for i, (amp, freq) in enumerate(((large / 255 * 0.8, 45.0), (small / 255 * 0.6, 160.0))):
            if amp > 0.01:
                out += (amp * np.sin(self._phase[i] + 2 * np.pi * freq * t))[:, None]
            self._phase[i] = (self._phase[i] + 2 * np.pi * freq * n / RATE) % (2 * np.pi)
        return out

    def next_report(self, now):
        """The next report if one is due at `now` (seconds, monotonic), else None.
        Nothing is sent while there is neither sound nor rumble (saves Bluetooth bandwidth)."""
        if self._next is None or now - self._next > 3 * TICK:
            self._next = now                 # first call, or fell behind: resync, no burst
        if now < self._next - 1e-4:          # 0.1 ms tolerance for timer rounding
            return None
        self._next += TICK
        with self._lock:
            take = self._buf[:FRAMES]
            self._buf = self._buf[FRAMES:]
        rumbling = max(self.game_rumble) > 2
        if len(take) == 0 and not rumbling:
            return None
        frames = np.zeros((FRAMES, 2), dtype=np.float32)
        frames[:len(take)] = take
        frames += self._tones(FRAMES)
        report = build_report(to_int8(frames), self._seq, self._counter)
        self._seq = (self._seq + 1) & 0x0F
        self._counter = (self._counter + 1) & 0xFF
        self.sent += 1
        return report
