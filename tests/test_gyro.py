"""Gyro aiming (gyro.py) and how it is added to the right stick."""

import math

import pytest

import gyro as gy
import mapping as m

DEG = gy.RAW_PER_DEG


def state(pitch=0.0, yaw=0.0, roll=0.0, bias=(0, 0, 0), **kw):
    d = {"Gyro": tuple(round(b + v * DEG) for b, v in zip(bias, (pitch, yaw, roll))),
         "L2": 0, "L1": False, "Touching": False}
    d.update(kw)
    return d


def aim(**cfg):
    g = gy.GyroAim({"enabled": True, "activate": "Always", **cfg})
    g.bias = (0.0, 0.0, 0.0)
    return g


def test_off_by_default():
    g = gy.GyroAim()
    g.bias = (0.0, 0.0, 0.0)
    assert g.update(state(yaw=200)) == (0.0, 0.0)


def test_no_gyro_data_no_output():
    assert aim().update({"L2": 0}) == (0.0, 0.0)


def test_turning_right_pushes_right_and_tilting_up_pushes_up():
    g = aim(game_deadzone=0, deadzone=0)
    x, y = g.update(state(yaw=-60))           # yaw is counter-clockwise positive
    assert x > 0 and y == pytest.approx(0)
    x, y = g.update(state(pitch=60))
    assert y > 0 and x == pytest.approx(0)


def test_inverts_and_roll():
    g = aim(game_deadzone=0, deadzone=0, invert_x=True, invert_y=True)
    x, _ = g.update(state(yaw=-60))
    _, y = g.update(state(pitch=60))
    assert x < 0 and y < 0
    g = aim(game_deadzone=0, deadzone=0, turn_axis="roll")
    assert g.update(state(yaw=-60))[0] == 0
    assert g.update(state(roll=-60))[0] > 0


def test_speed_scale_and_full_push():
    g = aim(game_deadzone=0, deadzone=0, full_speed=120)
    assert g.update(state(yaw=-60))[0] == pytest.approx(0.5, abs=0.01)
    assert g.update(state(yaw=-500))[0] == pytest.approx(1.0)


def test_deadzone_stops_jitter():
    g = aim(deadzone=3)
    assert g.update(state(yaw=2, pitch=1)) == (0.0, 0.0)


def test_game_deadzone_is_skipped():
    g = aim(game_deadzone=20, deadzone=1)
    x, _ = g.update(state(yaw=-1.5))          # just past our deadzone
    assert 0.2 <= x < 0.21


def test_activation():
    g = aim(activate="While L2 is held")
    assert g.update(state(yaw=-100)) == (0.0, 0.0) and not g.active
    assert g.update(state(yaw=-100, L2=200))[0] > 0 and g.active
    g = aim(activate="While L1 is held")
    assert g.update(state(yaw=-100, L1=True))[0] > 0
    g = aim(activate="While touching the touchpad")
    assert g.update(state(yaw=-100))[0] == 0
    assert g.update(state(yaw=-100, Touching=True))[0] > 0


def test_first_report_sets_the_rest_point():
    g = gy.GyroAim({"enabled": True, "activate": "Always", "deadzone": 0, "game_deadzone": 0})
    rest = (12, -30, 7)
    assert g.update({"Gyro": rest}) == (0.0, 0.0)
    assert g.update(state(yaw=-60, bias=rest))[0] == pytest.approx(0.5, abs=0.01)


def test_drift_is_corrected_while_still_but_not_while_turning():
    g = aim()
    drift = (0, 10, 0)                          # 0.6 °/s of yaw drift
    for _ in range(5000):
        g.update({"Gyro": drift})
    assert g.bias[1] == pytest.approx(10, abs=0.5)
    before = g.bias
    for _ in range(500):
        g.update(state(yaw=90))               # a real turn must not be learned as drift
    assert g.bias == before


def test_calibrate_averages_while_still():
    g = aim()
    g.calibrate(samples=10)
    for i in range(10):
        assert g.update({"Gyro": (100 + i % 2, -50, 3), "L2": 0}) == (0.0, 0.0)   # no output meanwhile
    assert not g.calibrating
    assert g.bias == pytest.approx((100.5, -50, 3))


def test_clean():
    c = gy.clean({"full_speed": 9999, "activate": "Never", "turn_axis": "x", "enabled": 1})
    assert c["full_speed"] == 360 and c["activate"] == gy.DEFAULTS["activate"]
    assert c["turn_axis"] == "yaw" and c["enabled"] is True


# ---------------------------------------------------------------- added to the stick

def test_combine_adds_and_stays_in_the_circle():
    assert m.combine((0, 0), (0.5, 0)) == (round(0.5 * 32767), 0)
    x, y = m.combine((32767, 0), (0.0, 1.0))
    assert math.hypot(x, y) <= 32767 * 1.0001


def test_gyro_goes_through_the_mapping():
    d = {"LX": 128, "LY": 128, "RX": 128, "RY": 128, "L2": 0, "R2": 0, "D-pad": "-"}
    without = m.DEFAULT.apply(d)
    with_gyro = m.DEFAULT.apply(d, add_right=(0.5, -0.25))
    assert with_gyro[:5] == without[:5]
    assert with_gyro[5] == pytest.approx(16384, abs=200) and with_gyro[6] == pytest.approx(-8192, abs=200)
    assert m.DEFAULT.apply(d, add_right=(0.0, 0.0)) == without
