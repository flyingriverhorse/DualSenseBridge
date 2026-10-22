"""HD haptics over Bluetooth: report 0x32 layout, audio → 3 kHz, pacing, engine wiring."""

import numpy as np
import pytest

import bt_haptics as bh
import output as o
from test_output import crc32_reference


def test_report_layout_and_crc():
    samples = bytes(range(64))
    r = bh.build_report(samples, seq=5, counter=300)
    assert len(r) == 142 and r[0] == 0x32 and r[1] == 0x50
    assert r[2:11] == bytes([0x91, 7, 0xFE, 0, 0, 0, 0, 0xFF, 300 & 0xFF])
    assert r[11:13] == bytes([0x92, 64]) and r[13:77] == samples
    assert r[77:138] == bytes(61)
    assert int.from_bytes(r[138:], "little") == crc32_reference(b"\xa2" + r[:138])


def test_report_needs_64_bytes():
    with pytest.raises(ValueError):
        bh.build_report(bytes(63), 0, 0)


def test_int8_is_signed_and_interleaved():
    b = bh.to_int8([[1.0, -1.0], [0.5, 2.0]])
    assert list(np.frombuffer(b, dtype=np.int8)) == [127, -127, 64, 127]


def feed(stream, freq, seconds, rate=48000, amp=0.8, block=480):
    t = np.arange(int(seconds * rate)) / rate
    x = amp * np.sin(2 * np.pi * freq * t)
    stereo = np.stack([x, -x], axis=1)
    for i in range(0, len(stereo), block):
        stream.push(stereo[i:i + block], rate)


@pytest.mark.parametrize("rate", [44100, 48000, 96000])
def test_resampled_to_3khz(rate):
    s = bh.BtHapticStream()
    feed(s, 100, 0.05, rate=rate)
    assert abs(s.buffered() - 0.05 * bh.RATE) <= 3


def drain(s):
    out = []
    t = 0.0
    while s.buffered():
        r = s.next_report(t)
        t += bh.TICK
        if r:
            out.append(np.frombuffer(r[13:77], dtype=np.int8).reshape(-1, 2).astype(float))
    return np.concatenate(out)


def test_low_tones_pass_and_high_tones_are_filtered():
    s = bh.BtHapticStream()
    feed(s, 80, 0.09)
    low = drain(s)[40:]
    s = bh.BtHapticStream()
    feed(s, 2500, 0.09)
    high = drain(s)[40:]
    assert np.abs(low[:, 0]).max() > 80                 # ~0.8 × 127
    assert np.abs(high[:, 0]).max() < 15                # above Nyquist: removed, no aliasing
    assert np.corrcoef(low[:, 0], -low[:, 1])[0, 1] > 0.99   # left and right stay apart


def test_buffer_is_capped():
    s = bh.BtHapticStream()
    feed(s, 100, 1.0)
    assert s.buffered() == bh.MAX_BUFFER and s.dropped > 0


def test_pacing():
    s = bh.BtHapticStream()
    feed(s, 100, 0.05)
    assert s.next_report(10.0) is not None
    assert s.next_report(10.005) is None                # not due yet
    assert s.next_report(10.0 + bh.TICK) is not None
    # a long stall resyncs instead of sending a burst
    assert s.next_report(11.0) is not None
    assert s.next_report(11.001) is None


def test_sequence_and_counter_advance():
    s = bh.BtHapticStream()
    s.game_rumble = (100, 0)                            # keeps reports coming without sound
    reps = [s.next_report(i * bh.TICK) for i in range(18)]
    assert all(reps)
    assert [r[1] >> 4 for r in reps[:17]] == list(range(16)) + [0]
    assert [r[10] for r in reps[:3]] == [0, 1, 2]


def test_silence_sends_nothing_but_rumble_does():
    s = bh.BtHapticStream()
    assert s.next_report(0.0) is None
    s.game_rumble = (200, 0)
    r = s.next_report(1.0)
    assert r is not None and np.abs(np.frombuffer(r[13:77], dtype=np.int8)).max() > 30


# ---------------------------------------------------------------- engine wiring

class FakeAudio:
    def __init__(self):
        self.bt = bh.BtHapticStream()
        self.hd_wanted = self.bt_wanted = False
        self.hd_active = False
        self.device_name, self.error = "Speakers", ""
        self.game_rumble = (0, 0)
        self.strength = self.sensitivity = 50

    @property
    def bt_active(self):
        return self.bt_wanted

    def levels(self):
        return 0, 0


class FakeDevice:
    def __init__(self):
        self.written = []

    def write(self, data):
        self.written.append(bytes(data))


@pytest.fixture
def e():
    import engine
    x = engine.Engine()
    x._info = {"model": "dualsense", "path": b"p"}
    x._device = FakeDevice()
    x._pad = object()
    x._audio = FakeAudio()
    x._audio_wanted = x._audio_hd = True
    return x


def test_bluetooth_hd_streams_0x32_and_drops_rumble_flags(e):
    feed(e._audio.bt, 100, 0.05)
    e._rumble = [150, 60]
    e._send_output(bluetooth=True)
    setup = [w for w in e._device.written if w[0] == 0x31]
    haptic = [w for w in e._device.written if w[0] == 0x32]
    assert setup and haptic and len(haptic[0]) == 142
    c = setup[-1][3:3 + o.COMMON_LEN]
    assert not c[o.OFF_FLAG0] & (o.FLAG0_COMPAT_VIBRATION | o.FLAG0_HAPTICS_SELECT)
    assert c[1] & o.FLAG1_MOTOR_POWER and c[o.OFF_MOTOR_POWER] == 0
    assert e._audio.bt.game_rumble == (150, 60)          # rumble now travels as tones
    assert e.snapshot()["audio_mode"].startswith("HD haptics (Bluetooth")


def test_usb_never_uses_0x32(e):
    e._send_output(bluetooth=False)
    assert not e._audio.bt_wanted
    assert not [w for w in e._device.written if w[0] == 0x32]


def test_motor_choice_keeps_rumble_over_bluetooth(e):
    e._audio_hd = False
    e._rumble = [150, 60]
    e._send_output(bluetooth=True)
    c = e._device.written[-1][3:3 + o.COMMON_LEN]
    assert c[o.OFF_FLAG0] & o.FLAG0_COMPAT_VIBRATION and c[o.OFF_MOTOR_LEFT] == 148   # steps of 4 when sound mixes in
    assert not [w for w in e._device.written if w[0] == 0x32]
