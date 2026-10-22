"""
Audio haptics — turns the sound the PC is playing into controller vibration.

Two ways to feel it:
- Rumble motors (USB and Bluetooth): bass → left motor, treble → right motor.
- HD haptics (DualSense over USB): the sound itself is sent to the controller's
  audio channels 3-4, which drive the haptic actuators directly. The controller only
  accepts this while the HID "haptics select" flag is off (see output.py, hd=True);
  game rumble is then mixed in as low sine tones.
- HD haptics over Bluetooth (experimental): the same signal at 3 kHz, streamed in HID
  report 0x32 by the engine (bt_haptics.py).

How: WASAPI loopback of the default speakers (PyAudioWPatch) → every ~10 ms an
FFT of the block → bass energy (20-160 Hz) drives the large/left motor, treble
energy (0.8-5 kHz) the small/right motor. Fast attack, short release, and a noise
gate so quiet background music does not make the controller hum all the time.
"""

import threading
import time

import numpy as np

BASS_BAND = (20, 160)       # Hz → large (left) motor
TREBLE_BAND = (800, 5000)   # Hz → small (right) motor
TOP_DB = -6.0               # this loud (dBFS) = full rumble
RELEASE = 0.80              # per block: how fast the vibration fades
STALE_SECONDS = 0.08        # no audio data for this long = silence (WASAPI sends nothing when idle)
DEVICE_CHECK_SECONDS = 3.0  # re-open if the default speakers change
HD_RATE = 48000             # DualSense speaker device
HD_MAX_BUFFER = 0.04        # seconds of haptic audio kept ready (more = more latency)
HD_LOWPASS_HZ = 700         # the actuators do little above this


def _device(pa, index):
    """Device info, or None if PortAudio cannot describe it (some drivers fail here)."""
    try:
        return pa.get_device_info_by_index(index)
    except Exception:
        return None


LOOPBACK_SUFFIX = " [Loopback]"


def find_dualsense_speaker(pa, pyaudio):
    """The DualSense's own 4-channel speaker device (only exists over USB), or None."""
    wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
    for i in range(pa.get_device_count()):
        d = _device(pa, i)
        if (d and d.get("hostApi") == wasapi["index"] and not d.get("isLoopbackDevice")
                and d["maxOutputChannels"] >= 4 and "dualsense" in d["name"].lower()):
            return d
    return None


def _lowpass_taps(rate, cutoff, n=63):
    t = np.arange(n) - (n - 1) / 2
    h = np.sinc(2 * cutoff / rate * t) * np.hamming(n)
    return (h / h.sum()).astype(np.float32)


def _loopbacks(pa, pyaudio):
    wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
    found = []
    for i in range(pa.get_device_count()):
        d = _device(pa, i)
        if d and d.get("isLoopbackDevice") and d.get("hostApi") == wasapi["index"]:
            found.append(d)
    return wasapi, found


def list_outputs():
    """Names of the speakers/headphones the app can listen to (for the Settings dropdown)."""
    import pyaudiowpatch as pyaudio
    pa = pyaudio.PyAudio()
    try:
        _, found = _loopbacks(pa, pyaudio)
        return [d["name"].replace(LOOPBACK_SUFFIX, "") for d in found]
    finally:
        pa.terminate()


def find_loopback(pa, pyaudio, preferred=None):
    """The WASAPI loopback ("what you hear") device of `preferred` (a name from
    list_outputs) or, if None / not connected, of the Windows default speakers.
    Written by hand because one broken audio device can make the library's helper fail."""
    wasapi, loopbacks = _loopbacks(pa, pyaudio)
    if not loopbacks:
        raise LookupError("Windows reports no loopback (what-you-hear) devices")
    if preferred:
        for d in loopbacks:
            if d["name"].replace(LOOPBACK_SUFFIX, "") == preferred:
                return d
    speakers = _device(pa, wasapi["defaultOutputDevice"])
    if speakers:
        for d in loopbacks:
            if speakers["name"] in d["name"]:
                return d
    return loopbacks[0]


class AudioHaptics(threading.Thread):
    def __init__(self, strength=100, sensitivity=50, device=None):
        super().__init__(daemon=True)
        self.strength = strength          # 0–200 %
        self.sensitivity = sensitivity    # 0–100: higher = reacts to quieter sounds
        self.device = device              # output name to listen to, None = Windows default
        self.error = ""
        self.device_name = ""
        self._running = True
        self._lock = threading.Lock()
        self._levels = (0.0, 0.0)
        self._env = [0.0, 0.0]
        self._last_data = 0.0
        self._window = None
        self._masks = None
        # HD haptics
        self.hd_wanted = False            # set by the engine (DualSense on USB + HD chosen)
        self.hd_active = False            # True while haptic audio is really flowing
        self.game_rumble = (0, 0)         # mixed into the haptic audio as low tones
        self._hd_buf = np.zeros((0, 2), dtype=np.float32)
        self._hd_taps = _lowpass_taps(HD_RATE, HD_LOWPASS_HZ)
        self._hd_tail = np.zeros((len(self._hd_taps) - 1, 2), dtype=np.float32)
        self._phase = [0.0, 0.0]
        # HD haptics over Bluetooth: filled here, sent by the engine thread
        from bt_haptics import BtHapticStream
        self.bt = BtHapticStream()
        self.bt_wanted = False            # set by the engine (DualSense on Bluetooth + HD chosen)

    # ------------------------------------------------ public

    @property
    def bt_active(self):
        """True while sound is being captured for Bluetooth HD haptics."""
        return self.bt_wanted and bool(self.device_name) and not self.error

    def levels(self):
        """(large, small) motor values 0–255 right now (0 while HD haptics carry the sound)."""
        if self.hd_active or self.bt_active:
            return 0, 0
        with self._lock:
            if time.time() - self._last_data > STALE_SECONDS:
                return 0, 0
            bass, treble = self._levels
        k = self.strength / 100
        return min(255, int(bass * 255 * k)), min(255, int(treble * 255 * k * 0.8))

    def stop(self):
        self._running = False

    # ------------------------------------------------ audio thread

    def run(self):
        try:
            import pyaudiowpatch as pyaudio
        except Exception as e:
            self.error = f"Audio capture not available: {e}"
            return
        pa = pyaudio.PyAudio()
        try:
            while self._running:
                try:
                    dev = find_loopback(pa, pyaudio, self.device)
                except Exception as e:
                    self.error = f"No speakers to listen to: {type(e).__name__}: {e}"
                    time.sleep(DEVICE_CHECK_SECONDS)
                    continue
                self._capture(pa, pyaudio, dev)
        finally:
            pa.terminate()

    def _setup(self, rate, frames):
        self._rate = rate
        self._nfft = 1024
        freqs = np.fft.rfftfreq(self._nfft, 1 / rate)
        self._window = np.hanning(frames).astype(np.float32)
        self._ref = self._window.sum() / 2               # FFT magnitude of a full-scale sine
        self._masks = ((freqs >= BASS_BAND[0]) & (freqs < BASS_BAND[1]),
                       (freqs >= TREBLE_BAND[0]) & (freqs < TREBLE_BAND[1]))

    def _process(self, x):
        """x: mono float samples of one block → updates the bass/treble envelopes."""
        if len(x) != len(self._window):
            self._window = np.hanning(len(x)).astype(np.float32)
            self._ref = self._window.sum() / 2
        spec = np.abs(np.fft.rfft(x * self._window, n=self._nfft)) / self._ref
        gate_db = -30.0 - 0.4 * self.sensitivity          # 0 → -30 dB, 100 → -70 dB
        out = []
        for i, mask in enumerate(self._masks):
            band = spec[mask]
            level = float(np.sqrt(np.sum(band * band) / 1.5)) if band.size else 0.0  # band energy
            db = 20 * np.log10(level + 1e-9)
            target = min(1.0, max(0.0, (db - gate_db) / (TOP_DB - gate_db)))
            self._env[i] = max(target, self._env[i] * RELEASE)
            out.append(self._env[i])
        with self._lock:
            self._levels = (out[0], out[1])
            self._last_data = time.time()

    # ------------------------------------------------ HD haptics

    def _hd_push(self, stereo, rate):
        """Captured block (n, 2) → 48 kHz, low-passed, gated, scaled → haptic buffer."""
        if rate != HD_RATE:
            n_out = int(round(len(stereo) * HD_RATE / rate))
            src = np.linspace(0, len(stereo) - 1, n_out)
            idx = np.arange(len(stereo))
            stereo = np.stack([np.interp(src, idx, stereo[:, c]) for c in (0, 1)], axis=1)
        x = np.concatenate([self._hd_tail, stereo.astype(np.float32)])
        self._hd_tail = x[-(len(self._hd_taps) - 1):]
        y = np.stack([np.convolve(x[:, c], self._hd_taps, mode="valid") for c in (0, 1)], axis=1)
        gate = max(self._env)                               # quiet background → no haptics
        y *= min(1.0, gate * 4)
        y = np.tanh(y * 3.0 * self.strength / 100)          # louder, soft-limited
        with self._lock:
            self._hd_buf = np.concatenate([self._hd_buf, y.astype(np.float32)])
            limit = int(HD_MAX_BUFFER * HD_RATE)
            if len(self._hd_buf) > limit:
                self._hd_buf = self._hd_buf[-limit:]

    def _shape(self, stereo):
        """Noise gate + gain + soft limit, as for USB HD haptics (filtering happens later)."""
        gate = max(self._env)                               # quiet background → no haptics
        y = stereo * min(1.0, gate * 4)
        return np.tanh(y * 3.0 * self.strength / 100)

    def _hd_pull(self, n):
        with self._lock:
            take = self._hd_buf[:n]
            self._hd_buf = self._hd_buf[n:]
        out = np.zeros((n, 4), dtype=np.float32)
        out[:len(take), 2:4] = take
        large, small = self.game_rumble                     # game rumble as tones
        t = np.arange(n) / HD_RATE
        for i, (amp, freq) in enumerate(((large / 255 * 0.8, 45.0), (small / 255 * 0.6, 160.0))):
            if amp > 0.01:
                tone = amp * np.sin(self._phase[i] + 2 * np.pi * freq * t)
                out[:, 2] += tone
                out[:, 3] += tone
            self._phase[i] = (self._phase[i] + 2 * np.pi * freq * n / HD_RATE) % (2 * np.pi)
        return (np.clip(out, -1, 1) * 32767).astype(np.int16)

    def _open_hd(self, pa, pyaudio):
        spk = find_dualsense_speaker(pa, pyaudio)
        if spk is None:
            return None

        def out_cb(in_data, frame_count, time_info, status):
            return (self._hd_pull(frame_count).tobytes(), pyaudio.paContinue)

        try:
            st = pa.open(format=pyaudio.paInt16, channels=4, rate=HD_RATE, output=True,
                         output_device_index=spk["index"], frames_per_buffer=480, stream_callback=out_cb)
        except Exception as e:
            self.error = f"HD haptics: could not open the DualSense speaker: {e}"
            return None
        self._hd_buf = np.zeros((0, 2), dtype=np.float32)
        return st

    # ------------------------------------------------ capture

    def _capture(self, pa, pyaudio, dev):
        rate = int(dev["defaultSampleRate"])
        channels = max(1, int(dev["maxInputChannels"]))
        frames = rate // 100                              # 10 ms blocks
        self._setup(rate, frames)
        hd_stream = self._open_hd(pa, pyaudio) if self.hd_wanted else None
        self.hd_active = hd_stream is not None

        def callback(data, frame_count, time_info, status):
            x = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            x = x.reshape(-1, channels)
            self._process(x.mean(axis=1))
            if hd_stream is not None or self.bt_wanted:
                stereo = x[:, :2] if channels >= 2 else np.repeat(x, 2, axis=1)
                if hd_stream is not None:
                    self._hd_push(stereo, rate)
                if self.bt_wanted:
                    self.bt.push(self._shape(stereo), rate)
            return (None, pyaudio.paContinue)

        try:
            stream = pa.open(format=pyaudio.paInt16, channels=channels, rate=rate, input=True,
                             input_device_index=dev["index"], frames_per_buffer=frames,
                             stream_callback=callback)
        except Exception as e:
            self.error = f"Could not listen to '{dev.get('name', '?')}': {e}"
            if hd_stream is not None:
                hd_stream.close()
            self.hd_active = False
            time.sleep(DEVICE_CHECK_SECONDS)
            return
        self.error = ""
        self.device_name = dev.get("name", "").replace(" [Loopback]", "")
        try:
            last_check = time.time()
            while self._running and stream.is_active():
                time.sleep(0.25)
                if self.hd_wanted != (hd_stream is not None):
                    break                                  # HD switched on/off: reopen
                if time.time() - last_check < DEVICE_CHECK_SECONDS:
                    continue
                last_check = time.time()
                try:
                    if find_loopback(pa, pyaudio, self.device)["index"] != dev["index"]:
                        break                              # default speakers changed: reopen
                    if hd_stream is not None and not hd_stream.is_active():
                        break
                except Exception:
                    break
        finally:
            stream.stop_stream()
            stream.close()
            if hd_stream is not None:
                hd_stream.stop_stream()
                hd_stream.close()
            self.hd_active = False


# ---------------------------------------------------------------- test sound

def test_sound_wav(rate=44100):
    """~4.5 s test: 4 bass thumps (left motor), 4 high clicks (right motor), then a low→high sweep."""
    import io
    import wave
    t_total = 4.6
    n = int(rate * t_total)
    out = np.zeros(n, dtype=np.float32)

    def place(start, sig):
        i = int(start * rate)
        out[i:i + len(sig)] += sig[: max(0, n - i)]

    def tone(freq, dur, amp):
        t = np.arange(int(dur * rate)) / rate
        env = np.minimum(1.0, np.minimum(t / 0.005, (dur - t) / 0.03))  # click-free edges
        return (amp * np.sin(2 * np.pi * freq * t) * env).astype(np.float32)

    for k in range(4):                                   # bass thumps
        place(0.1 + k * 0.35, tone(55, 0.18, 0.6))
    for k in range(4):                                   # high clicks
        place(1.7 + k * 0.3, tone(2500, 0.08, 0.35))
    t = np.arange(int(1.4 * rate)) / rate                # sweep 40 Hz → 4 kHz
    f = 40 * (100 ** (t / t[-1]))
    sweep = 0.45 * np.sin(2 * np.pi * np.cumsum(f) / rate)
    place(3.1, (sweep * np.minimum(1, np.minimum(t / 0.05, (t[-1] - t) / 0.05))).astype(np.float32))

    pcm = (np.clip(out, -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def play_test_sound(device=None):
    """Plays the test sound (asynchronously) on `device` (an output name) or the
    Windows default speakers. Returns its length in seconds."""
    if device:
        import pyaudiowpatch as pyaudio
        pa = pyaudio.PyAudio()
        out = None
        try:
            wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            for i in range(pa.get_device_count()):
                d = _device(pa, i)
                if (d and d.get("hostApi") == wasapi["index"] and not d.get("isLoopbackDevice")
                        and d["maxOutputChannels"] > 0 and d["name"] == device):
                    out = d
                    break
        except Exception:
            out = None
        if out is not None:
            import io
            import wave
            rate, ch = int(out["defaultSampleRate"]), int(out["maxOutputChannels"])
            w = wave.open(io.BytesIO(test_sound_wav(rate)))
            mono = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
            data = np.repeat(mono[:, None], ch, axis=1).tobytes()

            def play():
                try:
                    stream = pa.open(format=pyaudio.paInt16, channels=ch, rate=rate, output=True,
                                     output_device_index=out["index"])
                    stream.write(data)
                    stream.stop_stream()
                    stream.close()
                finally:
                    pa.terminate()

            threading.Thread(target=play, daemon=True).start()
            return len(mono) / rate
        pa.terminate()

    import os
    import tempfile
    import winsound
    # winsound cannot play from memory asynchronously, so write a temporary .wav file
    path = os.path.join(tempfile.gettempdir(), "dualsense_bridge_test.wav")
    with open(path, "wb") as f:
        f.write(test_sound_wav())
    winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
    return 4.6
