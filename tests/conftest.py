"""Shared test setup: no controller, no ViGEmBus, no Windows needed.

`hid` and `vgamepad` are replaced by small fakes so the parsing, mapping and
output code can be tested on any machine (and in CI).
"""

import enum
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))


# ---------------------------------------------------------------- fake hid

class FakeHid(types.ModuleType):
    """hid.enumerate() returns whatever a test puts in `devices`."""

    def __init__(self):
        super().__init__("hid")
        self.devices = []

    def enumerate(self, vid=0, pid=0):
        return [d for d in self.devices
                if (not vid or d["vendor_id"] == vid) and (not pid or d["product_id"] == pid)]

    class device:  # noqa: N801 (same name as hidapi)
        def open_path(self, path):
            raise OSError("fake hid: no hardware in tests")


sys.modules["hid"] = FakeHid()


# ---------------------------------------------------------------- fake vgamepad

class XUSB_BUTTON(enum.IntFlag):  # noqa: N801 (same name as vgamepad); real XInput values
    XUSB_GAMEPAD_DPAD_UP = 0x0001
    XUSB_GAMEPAD_DPAD_DOWN = 0x0002
    XUSB_GAMEPAD_DPAD_LEFT = 0x0004
    XUSB_GAMEPAD_DPAD_RIGHT = 0x0008
    XUSB_GAMEPAD_START = 0x0010
    XUSB_GAMEPAD_BACK = 0x0020
    XUSB_GAMEPAD_LEFT_THUMB = 0x0040
    XUSB_GAMEPAD_RIGHT_THUMB = 0x0080
    XUSB_GAMEPAD_LEFT_SHOULDER = 0x0100
    XUSB_GAMEPAD_RIGHT_SHOULDER = 0x0200
    XUSB_GAMEPAD_GUIDE = 0x0400
    XUSB_GAMEPAD_A = 0x1000
    XUSB_GAMEPAD_B = 0x2000
    XUSB_GAMEPAD_X = 0x4000
    XUSB_GAMEPAD_Y = 0x8000


class FakeReport:
    wButtons = 0
    bLeftTrigger = 0
    bRightTrigger = 0
    sThumbLX = sThumbLY = sThumbRX = sThumbRY = 0


class VX360Gamepad:
    created = []

    def __init__(self):
        self.report = FakeReport()
        self.updates = 0
        self.rumble_callback = None
        VX360Gamepad.created.append(self)

    def update(self):
        self.updates += 1

    def register_notification(self, callback_function):
        self.rumble_callback = callback_function

    def unregister_notification(self):
        self.rumble_callback = None

    def reset(self):
        self.report = FakeReport()

    def rumble(self, large, small):
        """What a game does: send rumble to the virtual pad."""
        self.rumble_callback(None, None, large, small, 0, None)


vgamepad = types.ModuleType("vgamepad")
vgamepad.XUSB_BUTTON = XUSB_BUTTON
vgamepad.VX360Gamepad = VX360Gamepad
sys.modules["vgamepad"] = vgamepad


# ---------------------------------------------------------------- report builders

def dualsense_input(bus, lx=128, ly=128, rx=128, ry=128, l2=0, r2=0,
                    b0=0x08, b1=0, b2=0, battery_byte=None, touching=False):
    """A DualSense input report as the controller sends it.
    bus: 'usb' (0x01, 64 bytes), 'bt' (0x31, 78 bytes) or 'bt_simple' (0x01, 10 bytes).
    b0 low nibble = D-pad (8 = released), high nibble = face buttons."""
    if bus == "bt_simple":
        return [0x01, lx, ly, rx, ry, b0, b1, b2, l2, r2]
    if bus == "usb":
        r, o = [0] * 64, 1
        r[0] = 0x01
    elif bus == "bt":
        r, o = [0] * 78, 2
        r[0], r[1] = 0x31, 0x10
    else:
        raise ValueError(bus)
    r[o:o + 6] = [lx, ly, rx, ry, l2, r2]
    r[o + 6] = 0x55                     # sequence counter: must not be read as a button
    r[o + 7], r[o + 8], r[o + 9] = b0, b1, b2
    r[o + 32] = 0x80 if not touching else 0x01    # first touch point: bit 7 set = no finger
    if battery_byte is not None:
        r[o + 52] = battery_byte
    return r
