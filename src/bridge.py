"""
DualSense → Xbox bridge — stages 2, 3 and 4
Reads the DualSense (using the stage 1 reader) and feeds the values into a
virtual Xbox 360 controller through ViGEmBus. While it runs, the real DualSense
is hidden from games with HidHide; on exit it becomes visible again.
Rumble the game sends to the virtual pad is passed on to the DualSense motors.

Needs:  ViGEmBus and HidHide drivers, pip install hidapi vgamepad
Most people should use the app (app.py). This is the command-line version.
Run (as administrator):
        python bridge.py
        python bridge.py --list
        python bridge.py --rumble-test  → rumbles the controller for 1 s at start
        python bridge.py --profile silent_hill_f  → trigger effects from profiles.json
Test:   Win+R → joy.cpl → only "Controller (Xbox 360 For Windows)" should be listed
"""

import json
import os
import sys
import time

try:
    import vgamepad as vg
except Exception as e:  # ImportError or cannot reach ViGEmBus
    sys.exit(f"Could not load vgamepad: {e}\nIs ViGEmBus installed? If so, try restarting the PC.")

import hid
from dualsense_reader import find_controller, bus_type, parse_report, enable_full_mode, BT_REPORT_LEN
from hiding import Hiding
from output import Output, effect_from_dict, effect_off
from bridge_profiles import read_profiles, resolve_profile

B = vg.XUSB_BUTTON

BUTTON_MAP = {
    "Cross": B.XUSB_GAMEPAD_A,
    "Circle": B.XUSB_GAMEPAD_B,
    "Square": B.XUSB_GAMEPAD_X,
    "Triangle": B.XUSB_GAMEPAD_Y,
    "L1": B.XUSB_GAMEPAD_LEFT_SHOULDER,
    "R1": B.XUSB_GAMEPAD_RIGHT_SHOULDER,
    "Create": B.XUSB_GAMEPAD_BACK,
    "Options": B.XUSB_GAMEPAD_START,
    "PS": B.XUSB_GAMEPAD_GUIDE,
    "L3": B.XUSB_GAMEPAD_LEFT_THUMB,
    "R3": B.XUSB_GAMEPAD_RIGHT_THUMB,
}

UP, DOWN = B.XUSB_GAMEPAD_DPAD_UP, B.XUSB_GAMEPAD_DPAD_DOWN
LEFT, RIGHT = B.XUSB_GAMEPAD_DPAD_LEFT, B.XUSB_GAMEPAD_DPAD_RIGHT
DPAD_MAP = {
    "Up": (UP,), "Up-Right": (UP, RIGHT), "Right": (RIGHT,),
    "Down-Right": (DOWN, RIGHT), "Down": (DOWN,), "Down-Left": (DOWN, LEFT),
    "Left": (LEFT,), "Up-Left": (UP, LEFT), "-": (),
}


def axis(value, invert=False):
    """0–255 → −32768…32767. On the Y axis DualSense down = 255, Xbox up = +."""
    v = value * 257 - 32768
    if invert:
        v = -1 - v
    return max(-32768, min(32767, v))


def xbox_buttons(d):
    mask = 0
    for name, xb in BUTTON_MAP.items():
        if d.get(name):
            mask |= int(xb)
    for xb in DPAD_MAP.get(d.get("D-pad"), ()):
        mask |= int(xb)
    return mask


def write_virtual(pad, d):
    pad.report.wButtons = xbox_buttons(d)
    pad.report.bLeftTrigger = d["L2"]
    pad.report.bRightTrigger = d["R2"]
    pad.report.sThumbLX = axis(d["LX"])
    pad.report.sThumbLY = axis(d["LY"], invert=True)
    pad.report.sThumbRX = axis(d["RX"])
    pad.report.sThumbRY = axis(d["RY"], invert=True)
    pad.update()


def list_profiles(profiles):
    games = [k for k in profiles if not k.startswith("_")]
    width = max(len(g) for g in games)
    print("Available profiles:\n")
    for g in sorted(games):
        e = profiles[g]
        print(f"  {g:<{width}}  {e.get('_controls', '')}")


def load_profile(argv):
    """Returns (name, l2 bytes, r2 bytes) or (None, None, None) without --profile."""
    if "--list" in argv:
        list_profiles(read_profiles())
        sys.exit(0)
    if "--profile" not in argv:
        return None, None, None
    i = argv.index("--profile")
    name = argv[i + 1] if i + 1 < len(argv) else ""
    profiles = read_profiles()
    if name not in profiles or name.startswith("_"):
        list_profiles(profiles)
        sys.exit(f"\nUnknown profile '{name}'.")
    p = resolve_profile(profiles, name)
    return name, effect_from_dict(p["L2"]), effect_from_dict(p["R2"])


def main():
    profile, l2_effect, r2_effect = load_profile(sys.argv)
    info = find_controller()
    if info is None:
        print("No DualSense found. Is it plugged in, or connected over Bluetooth?")
        return 1
    hint = bus_type(info)

    device = hid.device()
    try:
        device.open_path(info["path"])
    except (OSError, IOError) as e:
        print("Could not open the controller:", e)
        return 1

    try:
        pad = vg.VX360Gamepad()
    except Exception as e:
        device.close()
        print("Could not create the virtual Xbox controller:", e)
        print("Is ViGEmBus installed? If so, try restarting the PC.")
        return 1

    # Rumble: ViGEm calls this from its own thread; the main loop sends it to the controller
    rumble = {"large": 0, "small": 0}

    def on_rumble(client, target, large_motor, small_motor, led_number, user_data):
        rumble["large"], rumble["small"] = large_motor, small_motor

    pad.register_notification(callback_function=on_rumble)
    out = Output()
    sent = None                     # (large, small, bluetooth) last sent
    test_until = time.time() + 1.0 if "--rumble-test" in sys.argv else 0.0

    if profile:
        print(f"Trigger profile: {profile}")
    triggers_sent_for = None        # bluetooth flag the triggers were last sent for
    print("Virtual Xbox 360 controller created. Test it with joy.cpl. Ctrl+C to quit.")
    hiding = Hiding(info["path"])
    try:
        hiding.__enter__()
    except Exception as e:
        print("Could not enable hiding:", e)

    full_mode_requested = False
    last_retry = 0.0
    last_print = 0.0
    try:
        while True:
            report = device.read(BT_REPORT_LEN, 1000)
            if not report:
                continue
            mode, d = parse_report(report, hint, info["model"])
            if d is None:
                continue
            if mode.endswith("simple mode)") and (not full_mode_requested or time.time() - last_retry > 3):
                full_mode_requested = enable_full_mode(device, info["model"])
                last_retry = time.time()

            write_virtual(pad, d)

            bluetooth = mode.startswith("Bluetooth")
            if time.time() < test_until:
                want = (200, 200, bluetooth)
            else:
                want = (rumble["large"], rumble["small"], bluetooth)
            if profile and info["model"] == "dualsense" and triggers_sent_for != bluetooth:
                device.write(out.report(want[0], want[1], bluetooth, l2=l2_effect, r2=r2_effect, model=info["model"]))
                triggers_sent_for = bluetooth
                sent = want
            elif want != sent:
                device.write(out.rumble(*want, model=info["model"]))
                sent = want

            if time.time() - last_print > 0.1:
                last_print = time.time()
                sys.stdout.write(f"\r{mode:<24} L2 {d['L2']:>3}  R2 {d['R2']:>3}  "
                                 f"button mask 0x{xbox_buttons(d):04X}  "
                                 f"rumble {want[0]:>3}/{want[1]:>3}   ")
                sys.stdout.flush()
    except KeyboardInterrupt:
        print("\nShutting down.")
    except (OSError, IOError) as e:
        print("\nConnection lost:", e)
    finally:
        try:
            if sent is not None:
                off = effect_off() if profile else None
                device.write(out.report(0, 0, sent[2], l2=off, r2=off, model=info["model"]))
        except Exception:
            pass
        try:
            pad.unregister_notification()
        except Exception:
            pass
        try:
            pad.reset()
            pad.update()
        except Exception:
            pass
        del pad  # removes the virtual controller
        hiding.__exit__(None, None, None)
        device.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
