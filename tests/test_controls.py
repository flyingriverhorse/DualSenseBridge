"""Remapping and deadzones (mapping.py)."""

import math
import random

import pytest

import bridge
import mapping as m
from dualsense_reader import DPAD

BUTTONS = ["Cross", "Circle", "Square", "Triangle", "L1", "R1", "Create", "Options", "PS",
           "L3", "R3", "Touchpad", "Mute", "L2 button", "R2 button"]


def random_state(rng):
    d = {b: rng.random() < 0.3 for b in BUTTONS}
    d.update(LX=rng.randrange(256), LY=rng.randrange(256), RX=rng.randrange(256), RY=rng.randrange(256),
             L2=rng.randrange(256), R2=rng.randrange(256), **{"D-pad": rng.choice(DPAD)})
    return d


def test_default_mapping_is_exactly_the_old_bridge():
    rng = random.Random(1)
    for _ in range(5000):
        d = random_state(rng)
        old = (bridge.xbox_buttons(d), d["L2"], d["R2"], bridge.axis(d["LX"]),
               bridge.axis(d["LY"], invert=True), bridge.axis(d["RX"]), bridge.axis(d["RY"], invert=True))
        assert m.DEFAULT.apply(d) == old


def test_xbox_bits_match_vgamepad():
    import vgamepad as vg
    B = vg.XUSB_BUTTON
    assert m.XBOX["A"] == B.XUSB_GAMEPAD_A and m.XBOX["Guide"] == B.XUSB_GAMEPAD_GUIDE
    assert m.XBOX["LS (click)"] == B.XUSB_GAMEPAD_LEFT_THUMB and m.XBOX["D-pad Right"] == B.XUSB_GAMEPAD_DPAD_RIGHT


def state(**kw):
    d = {b: False for b in BUTTONS}
    d.update(LX=128, LY=128, RX=128, RY=128, L2=0, R2=0, **{"D-pad": "-"})
    d.update(kw)
    return d


def test_swap_two_buttons():
    mp = m.Mapping({"remap": {"Cross": "B", "Circle": "A"}})
    assert mp.apply(state(Cross=True))[0] == m.XBOX["B"]
    assert mp.apply(state(Circle=True))[0] == m.XBOX["A"]


def test_touchpad_can_become_back():
    assert m.DEFAULT.apply(state(Touchpad=True))[0] == 0
    assert m.Mapping({"remap": {"Touchpad": "Back"}}).apply(state(Touchpad=True))[0] == m.XBOX["Back"]


def test_button_to_full_trigger_and_to_nothing():
    mp = m.Mapping({"remap": {"L1": "LT (full press)", "R1": "Nothing"}})
    _, lt, rt, *_ = mp.apply(state(L1=True, R1=True, R2=40))
    assert (lt, rt) == (255, 40)
    assert mp.apply(state(R1=True))[0] == 0


def test_dpad_diagonal_with_remapped_direction():
    mp = m.Mapping({"remap": {"D-pad Up": "Y"}})
    assert mp.apply(state(**{"D-pad": "Up-Right"}))[0] == m.XBOX["Y"] | m.XBOX["D-pad Right"]


def test_clean_drops_bad_settings():
    c = m.clean({"ls_deadzone": 99, "trigger_full": "x", "remap": {"Cross": "A", "Laser": "A", "Circle": "Fly"}})
    assert c == {"ls_deadzone": 40, "rs_deadzone": 0, "trigger_deadzone": 0, "trigger_full": 100, "remap": {}}
    assert m.Mapping(c).is_default is False
    assert m.Mapping({"remap": {"Cross": "A"}}).is_default


# ---------------------------------------------------------------- sticks

def test_deadzone_kills_drift():
    for x, y in [(128, 128), (140, 120), (115, 135)]:
        assert m.stick(x, y, 15) == (0, 0)


def test_deadzone_still_reaches_full_range():
    assert m.stick(255, 128, 20)[0] == 32767
    assert m.stick(0, 128, 20)[0] == -32767
    assert m.stick(128, 0, 20)[1] == 32767          # up is +


def test_deadzone_has_no_jump_at_its_edge():
    dz = 20
    xs = [m.stick(128 + i, 128, dz)[0] for i in range(128)]
    assert xs == sorted(xs)
    first = next(v for v in xs if v)
    assert first < 1200                               # starts near zero, not at 20 %


def test_deadzone_keeps_direction():
    x, y = m.stick(200, 60, 10)
    fx, fy = 200 - 127.5, 127.5 - 60
    assert math.isclose(math.atan2(y, x), math.atan2(fy, fx), abs_tol=1e-3)


def test_diagonal_is_clamped():
    x, y = m.stick(255, 0, 10)
    assert max(abs(x), abs(y)) <= 32767


# ---------------------------------------------------------------- triggers

@pytest.mark.parametrize("v", [0, 1, 128, 255])
def test_trigger_default_is_unchanged(v):
    assert m.trigger(v, 0, 100) == v


def test_trigger_deadzone_and_full_press():
    assert m.trigger(20, 10, 100) == 0
    assert m.trigger(240, 0, 90) == 255
    mid = [m.trigger(v, 10, 90) for v in range(256)]
    assert mid == sorted(mid) and mid[0] == 0 and mid[-1] == 255


def test_end_to_end_through_the_virtual_pad():
    import vgamepad as vg
    pad = vg.VX360Gamepad()
    mp = m.Mapping({"rs_deadzone": 20, "trigger_full": 80, "remap": {"Touchpad": "Back"}})
    bridge.write_virtual(pad, state(RX=135, RY=125, R2=210, Touchpad=True), mp)
    r = pad.report
    assert (r.sThumbRX, r.sThumbRY) == (0, 0)
    assert r.bRightTrigger == 255
    assert r.wButtons == m.XBOX["Back"]
