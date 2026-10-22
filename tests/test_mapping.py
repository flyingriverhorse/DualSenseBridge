"""DualSense state → virtual Xbox 360 report."""

import pytest

import vgamepad as vg
from conftest import dualsense_input
import bridge
from dualsense_reader import parse_report

B = vg.XUSB_BUTTON


@pytest.mark.parametrize("value, want", [(0, -32768), (128, 128), (255, 32767)])
def test_axis(value, want):
    assert bridge.axis(value) == want


@pytest.mark.parametrize("value, want", [(0, 32767), (255, -32768)])
def test_axis_inverted(value, want):
    assert bridge.axis(value, invert=True) == want


def test_axis_is_monotonic_and_in_range():
    xs = [bridge.axis(v) for v in range(256)]
    assert xs == sorted(xs) and min(xs) == -32768 and max(xs) == 32767


@pytest.mark.parametrize("ps, xbox", [
    ("Cross", B.XUSB_GAMEPAD_A), ("Circle", B.XUSB_GAMEPAD_B),
    ("Square", B.XUSB_GAMEPAD_X), ("Triangle", B.XUSB_GAMEPAD_Y),
    ("L1", B.XUSB_GAMEPAD_LEFT_SHOULDER), ("R1", B.XUSB_GAMEPAD_RIGHT_SHOULDER),
    ("Create", B.XUSB_GAMEPAD_BACK), ("Options", B.XUSB_GAMEPAD_START),
    ("PS", B.XUSB_GAMEPAD_GUIDE), ("L3", B.XUSB_GAMEPAD_LEFT_THUMB), ("R3", B.XUSB_GAMEPAD_RIGHT_THUMB),
])
def test_buttons(ps, xbox):
    assert bridge.xbox_buttons({ps: True, "D-pad": "-"}) == int(xbox)


@pytest.mark.parametrize("dpad, want", [
    ("Up", B.XUSB_GAMEPAD_DPAD_UP), ("Up-Right", B.XUSB_GAMEPAD_DPAD_UP | B.XUSB_GAMEPAD_DPAD_RIGHT),
    ("Down-Left", B.XUSB_GAMEPAD_DPAD_DOWN | B.XUSB_GAMEPAD_DPAD_LEFT), ("-", 0), ("?", 0),
])
def test_dpad(dpad, want):
    assert bridge.xbox_buttons({"D-pad": dpad}) == int(want)


def test_unmapped_buttons_do_nothing():
    assert bridge.xbox_buttons({"Touchpad": True, "Mute": True, "L2 button": True, "D-pad": "-"}) == 0


@pytest.mark.parametrize("bus", ["usb", "bt", "bt_simple"])
def test_report_to_virtual_pad_end_to_end(bus):
    rep = dualsense_input(bus, lx=0, ly=0, rx=255, ry=255, l2=100, r2=255, b0=0x20 | 0x02, b1=0x20)
    _, d = parse_report(rep)
    pad = vg.VX360Gamepad()
    bridge.write_virtual(pad, d)
    p = pad.report
    assert (p.bLeftTrigger, p.bRightTrigger) == (100, 255)
    assert (p.sThumbLX, p.sThumbLY) == (-32768, 32767)       # left stick up-left
    assert (p.sThumbRX, p.sThumbRY) == (32767, -32768)       # right stick down-right
    assert p.wButtons == int(B.XUSB_GAMEPAD_A | B.XUSB_GAMEPAD_DPAD_RIGHT | B.XUSB_GAMEPAD_START)
    assert pad.updates == 1
