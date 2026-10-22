"""The engine's real loop against a scripted controller (no hardware, no driver)."""

import sys
import threading
import time

import pytest

import vgamepad as vg
from conftest import dualsense_input
import dualsense_reader as r
import engine as eng
import mapping as m
import output as o


class ScriptedController:
    """Plays input reports; records writes and feature report requests."""

    def __init__(self, bus):
        self.bus = bus
        self.simple = bus == "bt"        # Bluetooth starts in simple mode until the feature report
        self.state = {}
        self.written = []
        self.features = []
        self.lock = threading.Lock()

    def open_path(self, path):
        pass

    def close(self):
        pass

    def get_feature_report(self, rid, n):
        self.features.append(rid)
        self.simple = False
        return [rid] + [0] * (n - 1)

    def read(self, n, timeout):
        time.sleep(0.002)
        with self.lock:
            st = dict(self.state)
        gyro = st.pop("gyro", (0, 0, 0))
        if self.simple:
            return dualsense_input("bt_simple", **st)
        rep = dualsense_input("usb" if self.bus == "usb" else "bt", **st)
        at = (1 if self.bus == "usb" else 2) + 15
        for i, v in enumerate(gyro):
            rep[at + 2 * i:at + 2 * i + 2] = list(int(v).to_bytes(2, "little", signed=True))
        return rep

    def write(self, data):
        self.written.append(bytes(data))
        return len(data)

    def set(self, **kw):
        with self.lock:
            self.state.update(kw)


@pytest.fixture
def run(monkeypatch):
    engines = []

    def start(bus):
        ctrl = ScriptedController(bus)
        hid = sys.modules["hid"]
        hid.devices = [{"vendor_id": r.SONY_VID, "product_id": 0x0CE6, "bus_type": 1 if bus == "usb" else 2,
                        "usage_page": 1, "usage": 5, "path": b"x"}]
        monkeypatch.setattr(hid, "device", lambda: ctrl)
        vg.VX360Gamepad.created.clear()
        e = eng.Engine()
        e.start()
        engines.append(e)
        return e, ctrl

    yield start
    for e in engines:
        e.shutdown()
        e.join(timeout=3)
    sys.modules["hid"].devices = []


def wait(cond, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.mark.parametrize("bus, mode", [("usb", "USB"), ("bt", "Bluetooth (full mode)")])
def test_xbox_mode_end_to_end(run, bus, mode):
    e, ctrl = run(bus)
    assert wait(lambda: e.snapshot()["mode"] == mode)
    if bus == "bt":
        assert 0x05 in ctrl.features                 # switched out of simple mode
    e.set_xbox(True)
    assert wait(lambda: vg.VX360Gamepad.created and e.snapshot()["xbox"])
    pad = vg.VX360Gamepad.created[-1]
    ctrl.set(l2=180, r2=40, b0=0x08 | 0x20, lx=255)
    assert wait(lambda: pad.report.bLeftTrigger == 180 and pad.report.bRightTrigger == 40)
    assert pad.report.wButtons & m.XBOX["A"] and pad.report.sThumbLX == 32767

    # a game rumbles → the controller gets a rumble report for this connection type
    pad.rumble(200, 50)
    out_len, start = (o.USB_OUT_LEN, 1) if bus == "usb" else (o.BT_OUT_LEN, 3)

    def rumbled():
        for w in ctrl.written[-5:]:
            if len(w) == out_len and w[start + o.OFF_MOTOR_LEFT] == 200 and w[start + o.OFF_MOTOR_RIGHT] == 50:
                return True
        return False
    assert wait(rumbled)


def test_remap_deadzone_and_gyro_in_the_loop(run):
    e, ctrl = run("usb")
    e.set_mapping({"remap": {"Touchpad": "Back"}, "rs_deadzone": 20})
    e.set_gyro({"enabled": True, "activate": "Always", "deadzone": 0, "game_deadzone": 0, "full_speed": 120})
    e.set_xbox(True)
    assert wait(lambda: vg.VX360Gamepad.created and e.snapshot()["xbox"])
    pad = vg.VX360Gamepad.created[-1]
    ctrl.set(b2=0x02, rx=140, ry=120)                    # touchpad click, small right-stick drift
    assert wait(lambda: pad.report.wButtons == m.XBOX["Back"])
    assert pad.report.sThumbRX == 0 and pad.report.sThumbRY == 0
    ctrl.set(gyro=(0, round(-60 * 16.4), 0))            # turning right at 60 °/s
    assert wait(lambda: pad.report.sThumbRX > 15000)
    assert e.snapshot()["gyro"]["active"]


def test_preview_reaches_the_controller_in_native_mode(run):
    e, ctrl = run("bt")
    assert wait(lambda: e.snapshot()["mode"].startswith("Bluetooth (full"))
    effect = o.effect_feedback(2, 8)
    e.set_preview(effect, effect)

    def sent():
        for w in ctrl.written[-5:]:
            if len(w) == o.BT_OUT_LEN and bytes(w[3 + o.OFF_RIGHT_TRIGGER:3 + o.OFF_RIGHT_TRIGGER + 11]) == effect:
                return o.bt_crc(w[:-4]) == int.from_bytes(w[-4:], "little")
        return False
    assert wait(sent)
    assert not vg.VX360Gamepad.created                    # no virtual pad needed for a preview


def test_reconnects_after_the_cable_is_pulled(run, monkeypatch):
    e, ctrl = run("usb")
    assert wait(lambda: e.snapshot()["mode"] == "USB")
    # the cable is pulled and the controller comes back over Bluetooth
    hid = sys.modules["hid"]
    new = ScriptedController("bt")
    hid.devices = [{"vendor_id": r.SONY_VID, "product_id": 0x0CE6, "bus_type": 2, "usage_page": 1,
                    "usage": 5, "path": b"y"}]
    monkeypatch.setattr(hid, "device", lambda: new)

    def unplugged(n, t):
        raise OSError("device disconnected")
    monkeypatch.setattr(ctrl, "read", unplugged)
    assert wait(lambda: e.snapshot()["mode"] == "Bluetooth (full mode)", seconds=6)
    assert 0x05 in new.features
