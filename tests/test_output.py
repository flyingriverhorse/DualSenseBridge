"""Output reports (rumble, triggers, light bar), Bluetooth CRC32, trigger effects."""

import pytest

import output as o


def crc32_reference(data):
    """Bit-by-bit CRC-32 (IEEE, reflected), written independently of zlib."""
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xEDB88320 if crc & 1 else 0)
    return crc ^ 0xFFFFFFFF


def crc_ok(report):
    return int.from_bytes(report[-4:], "little") == crc32_reference(bytes([0xA2]) + report[:-4])


def common(report, bluetooth):
    start = 3 if bluetooth else 1
    return report[start:start + o.COMMON_LEN]


def test_crc_reference_matches_the_standard_check_value():
    assert crc32_reference(b"123456789") == 0xCBF43926


def test_bt_crc_uses_the_0xa2_seed():
    data = bytes(range(74))
    assert o.bt_crc(data) == crc32_reference(b"\xa2" + data)


# ---------------------------------------------------------------- DualSense

def test_usb_rumble_report():
    rep = o.Output().report(200, 50, bluetooth=False)
    assert len(rep) == 48 and rep[0] == 0x02
    c = common(rep, False)
    assert c[o.OFF_FLAG0] == o.FLAG0_COMPAT_VIBRATION | o.FLAG0_HAPTICS_SELECT
    assert (c[o.OFF_MOTOR_LEFT], c[o.OFF_MOTOR_RIGHT]) == (200, 50)


def test_bluetooth_report_layout_and_crc():
    rep = o.Output().report(10, 20, bluetooth=True)
    assert len(rep) == 78 and rep[0] == 0x31 and rep[2] == 0x10
    c = common(rep, True)
    assert (c[o.OFF_MOTOR_LEFT], c[o.OFF_MOTOR_RIGHT]) == (10, 20)
    assert crc_ok(rep)


def test_bluetooth_sequence_counts_and_wraps():
    out = o.Output()
    seqs = [out.report(0, 0, True)[1] >> 4 for _ in range(18)]
    assert seqs == list(range(16)) + [0, 1]
    # USB reports do not use the counter
    out.report(0, 0, False)
    assert out.report(0, 0, True)[1] >> 4 == 2


def test_motor_values_are_masked_to_a_byte():
    c = common(o.Output().report(256 + 7, -1, False), False)
    assert (c[o.OFF_MOTOR_LEFT], c[o.OFF_MOTOR_RIGHT]) == (7, 255)


@pytest.mark.parametrize("bluetooth", [False, True])
def test_trigger_effects_and_flags(bluetooth):
    l2, r2 = o.effect_feedback(2, 3), o.effect_weapon(3, 5, 7)
    rep = o.Output().report(0, 0, bluetooth, l2=l2, r2=r2)
    c = common(rep, bluetooth)
    assert c[o.OFF_FLAG0] & o.FLAG0_LEFT_TRIGGER and c[o.OFF_FLAG0] & o.FLAG0_RIGHT_TRIGGER
    assert bytes(c[o.OFF_LEFT_TRIGGER:o.OFF_LEFT_TRIGGER + 11]) == l2
    assert bytes(c[o.OFF_RIGHT_TRIGGER:o.OFF_RIGHT_TRIGGER + 11]) == r2
    if bluetooth:
        assert crc_ok(rep)


def test_triggers_left_alone_when_not_given():
    c = common(o.Output().report(0, 0, False), False)
    assert not c[o.OFF_FLAG0] & (o.FLAG0_LEFT_TRIGGER | o.FLAG0_RIGHT_TRIGGER)


def test_light_bar_and_setup():
    c = common(o.Output().report(0, 0, False, light=(1, 2, 300), setup=True), False)
    assert c[1] & o.FLAG1_LIGHTBAR
    assert (c[o.OFF_LIGHT_R], c[o.OFF_LIGHT_G], c[o.OFF_LIGHT_B]) == (1, 2, 300 & 0xFF)
    assert c[o.OFF_FLAG2] & o.FLAG2_LIGHTBAR_SETUP
    assert c[o.OFF_LIGHTBAR_SETUP] == o.LIGHTBAR_SETUP_LIGHT_OUT


def test_hd_mode_sends_no_rumble_flags():
    # HD haptics: rumble emulation must stay off so audio reaches the actuators
    c = common(o.Output().report(200, 200, False, hd=True, r2=o.effect_off()), False)
    assert not c[o.OFF_FLAG0] & (o.FLAG0_COMPAT_VIBRATION | o.FLAG0_HAPTICS_SELECT)
    assert c[o.OFF_MOTOR_LEFT] == c[o.OFF_MOTOR_RIGHT] == 0
    assert c[o.OFF_FLAG0] & o.FLAG0_RIGHT_TRIGGER


# ---------------------------------------------------------------- DualShock 4

def test_ds4_usb():
    rep = o.Output().report(100, 30, False, light=(9, 8, 7), model="ds4")
    assert len(rep) == 32 and rep[0] == 0x05 and rep[1] == 0x07
    assert list(rep[4:9]) == [30, 100, 9, 8, 7]       # small motor first on DS4


def test_ds4_bluetooth():
    rep = o.Output().report(100, 30, True, model="ds4")
    assert len(rep) == 78 and rep[0] == 0x11 and rep[1] == 0xC0 and rep[3] == 0x07
    assert list(rep[6:11]) == [30, 100, 0, 0, 64]     # default light: dim blue
    assert crc_ok(rep)


# ---------------------------------------------------------------- trigger effects

def zones(e):
    return [z for z in range(10) if int.from_bytes(e[1:3], "little") >> z & 1]


def forces(e):
    f = int.from_bytes(e[3:7], "little")
    return [(f >> (3 * z)) & 7 for z in range(10)]


def test_off():
    assert o.effect_off() == bytes([0x05] + [0] * 10)


def test_feedback():
    e = o.effect_feedback(start=3, strength=4)
    assert e[0] == 0x21 and zones(e) == list(range(3, 10))
    assert forces(e) == [0, 0, 0] + [3] * 7


def test_weapon():
    e = o.effect_weapon(start=2, end=3, strength=6)
    assert e[0] == 0x25 and zones(e) == [2, 3] and e[3] == 5


def test_weapon_end_is_kept_after_start():
    assert zones(o.effect_weapon(start=7, end=1)) == [7, 8]


def test_vibration():
    e = o.effect_vibration(start=5, amplitude=8, frequency=300)
    assert e[0] == 0x26 and zones(e) == [5, 6, 7, 8, 9] and e[9] == 255
    assert forces(e)[5:] == [7] * 5


def test_multi_feedback():
    e = o.effect_multi_feedback([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
    assert zones(e) == list(range(1, 10))
    assert forces(e) == [0, 0, 1, 2, 3, 4, 5, 6, 7, 7]
    assert o.effect_multi_feedback([0] * 10) == o.effect_off()
    assert o.effect_multi_feedback([3]) == o.effect_multi_feedback([3] + [0] * 9)


def test_slope_grows():
    f = forces(o.effect_slope(start=1, end=8, start_strength=1, end_strength=8))
    assert f[0] == 0 and f[1] == 0 and f[8] == 7 and f[9] == 7
    assert f[1:] == sorted(f[1:])


def test_bow_galloping_machine():
    b = o.effect_bow(start=1, end=4, strength=4, snap=6)
    assert b[0] == 0x22 and zones(b) == [1, 4] and int.from_bytes(b[3:5], "little") == 3 | 5 << 3
    g = o.effect_galloping(start=1, end=9, first_foot=1, second_foot=3, frequency=6)
    assert g[0] == 0x23 and zones(g) == [1, 9] and g[3] == 3 | 1 << 3 and g[4] == 6
    m = o.effect_machine(start=1, end=9, amplitude_a=2, amplitude_b=6, frequency=8, period=2)
    assert m[0] == 0x27 and zones(m) == [1, 9] and m[3] == 2 | 6 << 3 and (m[4], m[5]) == (8, 2)


@pytest.mark.parametrize("mode", [m for m in o.MAKERS if m not in ("off", "multi")])
def test_every_effect_is_11_bytes_even_with_wild_values(mode):
    for v in (-100, 0, 1, 5, 999):
        import inspect
        args = {k: v for k in inspect.signature(o.MAKERS[mode]).parameters}
        e = o.MAKERS[mode](**args)
        assert isinstance(e, bytes) and len(e) == 11


def test_effect_from_dict():
    assert o.effect_from_dict(None) == o.effect_off()
    assert o.effect_from_dict({"mode": "feedback", "start": 3, "strength": 4, "_note": "x"}) == \
        o.effect_feedback(3, 4)
    assert o.effect_from_dict({"mode": "multi", "strengths": [1] * 10}) == o.effect_multi_feedback([1] * 10)
    with pytest.raises(ValueError):
        o.effect_from_dict({"mode": "laser"})
