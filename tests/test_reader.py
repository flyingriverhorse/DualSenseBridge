"""Input reports: USB, Bluetooth full and simple mode, DualShock 4, discovery."""

import sys

import pytest

from conftest import dualsense_input
import dualsense_reader as r


# ---------------------------------------------------------------- DualSense

@pytest.mark.parametrize("bus, mode", [("usb", "USB"), ("bt", "Bluetooth (full mode)")])
def test_full_reports_share_one_layout(bus, mode):
    rep = dualsense_input(bus, lx=0, ly=255, rx=10, ry=200, l2=77, r2=255)
    got_mode, s = r.parse_report(rep, bus_hint=None)
    assert got_mode == mode
    assert (s["LX"], s["LY"], s["RX"], s["RY"]) == (0, 255, 10, 200)
    assert (s["L2"], s["R2"]) == (77, 255)
    assert s["D-pad"] == "-"
    assert not any(v for k, v in s.items() if v is True)   # sequence byte is not a button


def test_bluetooth_simple_mode_is_recognised():
    mode, s = r.parse_report(dualsense_input("bt_simple", l2=40, r2=90), bus_hint="Bluetooth")
    assert mode == "Bluetooth (simple mode)"
    assert (s["L2"], s["R2"]) == (40, 90)


def test_short_0x01_with_usb_hint_is_not_read_as_usb():
    # a 10-byte report cannot be a USB report, even if hidapi says USB
    mode, _ = r.parse_report(dualsense_input("bt_simple"), bus_hint="USB")
    assert mode == "Bluetooth (simple mode)"


@pytest.mark.parametrize("rep", [[], [0x07] + [0] * 63, [0x31, 0, 0]])
def test_unknown_or_short_reports_are_ignored(rep):
    assert r.parse_report(rep) == (None, None)


BUTTONS = [  # (byte, bit, name)
    (0, 0x10, "Square"), (0, 0x20, "Cross"), (0, 0x40, "Circle"), (0, 0x80, "Triangle"),
    (1, 0x01, "L1"), (1, 0x02, "R1"), (1, 0x04, "L2 button"), (1, 0x08, "R2 button"),
    (1, 0x10, "Create"), (1, 0x20, "Options"), (1, 0x40, "L3"), (1, 0x80, "R3"),
    (2, 0x01, "PS"), (2, 0x02, "Touchpad"), (2, 0x04, "Mute"),
]


@pytest.mark.parametrize("bus", ["usb", "bt", "bt_simple"])
@pytest.mark.parametrize("byte, bit, name", BUTTONS)
def test_each_button_bit(bus, byte, bit, name):
    b = [0x08, 0, 0]
    b[byte] |= bit
    _, s = r.parse_report(dualsense_input(bus, b0=b[0], b1=b[1], b2=b[2]))
    pressed = {k for k, v in s.items() if v is True}
    assert pressed == {name}


@pytest.mark.parametrize("nibble, name", list(enumerate(r.DPAD)))
def test_dpad_directions(nibble, name):
    _, s = r.parse_report(dualsense_input("usb", b0=nibble))
    assert s["D-pad"] == name


def test_dpad_garbage_value():
    _, s = r.parse_report(dualsense_input("usb", b0=0x0C))
    assert s["D-pad"] == "?"


@pytest.mark.parametrize("byte, battery, charging", [
    (0x00, 5, "no"), (0x05, 55, "no"), (0x0A, 100, "no"),
    (0x13, 35, "charging"), (0x2A, 100, "full"),
])
def test_battery(byte, battery, charging):
    _, s = r.parse_report(dualsense_input("usb", battery_byte=byte))
    assert (s["Battery"], s["Charging"]) == (battery, charging)
    _, s = r.parse_report(dualsense_input("bt", battery_byte=byte))
    assert (s["Battery"], s["Charging"]) == (battery, charging)


# ---------------------------------------------------------------- DualShock 4

def ds4_input(bus, lx=1, ly=2, rx=3, ry=4, l2=5, r2=6, b0=0x08, b1=0, b2=0, bat=0):
    if bus == "usb":
        rep, o = [0] * 64, 1
        rep[0] = 0x01
    else:
        rep, o = [0] * 78, 3
        rep[0] = 0x11
    rep[o:o + 9] = [lx, ly, rx, ry, b0, b1, b2, l2, r2]
    rep[o + 29] = bat
    rep[o + 32] = 0x80          # no finger on the touchpad
    return rep


@pytest.mark.parametrize("bus, mode", [("usb", "USB"), ("bt", "Bluetooth (full mode)")])
def test_ds4_reports(bus, mode):
    got_mode, s = r.parse_report(ds4_input(bus, b0=0x28, b2=0x04 | 0x01), "USB" if bus == "usb" else None, "ds4")
    assert got_mode == mode
    assert (s["LX"], s["LY"], s["RX"], s["RY"], s["L2"], s["R2"]) == (1, 2, 3, 4, 5, 6)
    assert s["Cross"] and s["PS"] and s["D-pad"] == "-"
    assert s["Mute"] is False                 # DS4 counter bits are not a mute button


@pytest.mark.parametrize("bat, battery, charging", [(0x03, 35, "no"), (0x15, 55, "charging"), (0x1B, 100, "full")])
def test_ds4_battery(bat, battery, charging):
    _, s = r.parse_report(ds4_input("usb", bat=bat), "USB", "ds4")
    assert (s["Battery"], s["Charging"]) == (battery, charging)


# ---------------------------------------------------------------- discovery

def dev(pid, bus, usage=0x05, path=b"p"):
    return {"vendor_id": r.SONY_VID, "product_id": pid, "bus_type": bus,
            "usage_page": 0x01, "usage": usage, "path": path}


@pytest.mark.parametrize("info, want", [
    ({"bus_type": 1}, "USB"), ({"bus_type": 2}, "Bluetooth"), ({"bus_type": None}, None),
    ({"bus_type": "x"}, None), ({}, None), ({"bus_type": 2, "product_id": 0x0BA0}, "USB"),
])
def test_bus_type(info, want):
    assert r.bus_type(info) == want


@pytest.fixture
def hid():
    fake = sys.modules["hid"]
    yield fake
    fake.devices = []


def test_no_controller(hid):
    hid.devices = [{"vendor_id": r.SONY_VID, "product_id": 0x1234, "path": b"x"}]
    assert r.find_controller() is None


def test_prefers_dualsense_over_ds4_and_usb_over_bluetooth(hid):
    hid.devices = [dev(0x05C4, 1, path=b"ds4"), dev(0x0CE6, 2, path=b"bt"), dev(0x0CE6, 1, path=b"usb")]
    got = r.find_controller()
    assert got["path"] == b"usb" and got["model"] == "dualsense" and got["name"] == "DualSense"


def test_picks_the_gamepad_collection(hid):
    hid.devices = [dev(0x0CE6, 1, usage=0x00, path=b"other"), dev(0x0CE6, 1, usage=0x05, path=b"pad")]
    assert r.find_controller()["path"] == b"pad"


def test_ds4_alone_is_found(hid):
    hid.devices = [dev(0x09CC, 2)]
    got = r.find_controller()
    assert got["model"] == "ds4" and got["name"] == "DualShock 4"


class FeatureDevice:
    def __init__(self, fail=False):
        self.asked, self.fail = [], fail

    def get_feature_report(self, rid, n):
        self.asked.append((rid, n))
        if self.fail:
            raise OSError("no")
        return [rid] + [0] * (n - 1)


def test_enable_full_mode():
    d = FeatureDevice()
    assert r.enable_full_mode(d) and d.asked == [(0x05, 41)]
    d = FeatureDevice()
    assert r.enable_full_mode(d, "ds4") and d.asked == [(0x02, 37)]
    assert r.enable_full_mode(FeatureDevice(fail=True)) is False


# ---------------------------------------------------------------- gyro

def put16(rep, at, v):
    rep[at:at + 2] = list(int(v).to_bytes(2, "little", signed=True))


@pytest.mark.parametrize("bus, o", [("usb", 1), ("bt", 2)])
def test_dualsense_gyro(bus, o):
    rep = dualsense_input(bus)
    for i, v in enumerate((-1640, 32767, -32768)):
        put16(rep, o + 15 + 2 * i, v)
    _, s = r.parse_report(rep)
    assert s["Gyro"] == (-1640, 32767, -32768)


def test_simple_mode_has_no_gyro():
    _, s = r.parse_report(dualsense_input("bt_simple"))
    assert "Gyro" not in s


def test_ds4_gyro():
    rep = ds4_input("usb")
    put16(rep, 1 + 12, 100)
    put16(rep, 1 + 14, -200)
    put16(rep, 1 + 16, 300)
    _, s = r.parse_report(rep, "USB", "ds4")
    assert s["Gyro"] == (100, -200, 300)


@pytest.mark.parametrize("bus", ["usb", "bt"])
def test_touching(bus):
    assert r.parse_report(dualsense_input(bus))[1]["Touching"] is False
    assert r.parse_report(dualsense_input(bus, touching=True))[1]["Touching"] is True


def test_ds4_touching():
    rep = ds4_input("usb")
    assert r.parse_report(rep, "USB", "ds4")[1]["Touching"] is False
    rep[1 + 32] = 0x05
    assert r.parse_report(rep, "USB", "ds4")[1]["Touching"] is True
