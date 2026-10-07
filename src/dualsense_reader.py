"""
DualSense reader — stage 1
Finds the controller, detects the connection type (USB / Bluetooth), switches
Bluetooth to full mode and prints triggers, sticks and buttons live.

Setup: setup.bat (or: pip install hidapi)
Run:   run_reader.bat (or: python dualsense_reader.py) — Ctrl+C to quit
"""

import os
import sys
import time

try:
    import hid  # pip install hidapi
except ImportError:
    sys.exit("hidapi not found. Run first:  pip install hidapi")

SONY_VID = 0x054C
DUALSENSE_PIDS = {0x0CE6: "DualSense", 0x0DF2: "DualSense Edge"}
DS4_PIDS = {0x05C4: "DualShock 4", 0x09CC: "DualShock 4", 0x0BA0: "DualShock 4 (USB adapter)"}
ALL_PIDS = {**DUALSENSE_PIDS, **DS4_PIDS}

USB_REPORT_LEN = 64
BT_REPORT_LEN = 78

DPAD = ["Up", "Up-Right", "Right", "Down-Right", "Down", "Down-Left", "Left", "Up-Left", "-"]


# ---------------------------------------------------------------- discovery

def model_of(info):
    """'dualsense' or 'ds4'."""
    return "ds4" if info.get("product_id") in DS4_PIDS else "dualsense"


def find_controller():
    """Return hidapi info for the first DualSense (or DualShock 4), or None.
    The dict gets two extra keys: 'model' ('dualsense' / 'ds4') and 'name'."""
    candidates = [dict(d) for d in hid.enumerate(SONY_VID, 0)
                  if d.get("product_id") in ALL_PIDS]
    if not candidates:
        return None
    for d in candidates:
        d["model"] = model_of(d)
        d["name"] = ALL_PIDS[d["product_id"]]
    # Prefer a DualSense over a DualShock 4 if both are connected
    # If the controller shows up both over USB and Bluetooth, prefer USB
    candidates.sort(key=lambda d: (d["model"] != "dualsense", bus_type(d) != "USB"))
    # Windows may list several HID collections: pick the gamepad one (usage 0x05)
    for d in candidates:
        if d.get("usage_page") == 0x01 and d.get("usage") == 0x05:
            return d
    return candidates[0]


def bus_type(info):
    """hidapi 0.14+ reports bus_type: 1 = USB, 2 = Bluetooth. Older versions: None."""
    bt = info.get("bus_type")
    if bt is None:
        return None
    try:
        bt = int(bt)
    except (TypeError, ValueError):
        return None
    if info.get("product_id") == 0x0BA0:  # Sony wireless adapter looks like USB
        return "USB"
    return {1: "USB", 2: "Bluetooth"}.get(bt)


# ---------------------------------------------------------------- parsing

def parse_report(report, bus_hint=None, model="dualsense"):
    """Parse a raw report. Returns (mode, state dict) or (None, None)."""
    if not report:
        return None, None
    if model == "ds4":
        return _parse_ds4(report, bus_hint)
    rid = report[0]
    n = len(report)

    if rid == 0x31 and n >= 12:
        # Bluetooth full mode: data starts one byte later (report[1] is a sequence/tag byte)
        return "Bluetooth (full mode)", _parse_full(report, offset=2)

    if rid == 0x01:
        is_usb = (bus_hint == "USB") or (bus_hint is None and n == USB_REPORT_LEN)
        if is_usb and n >= 54:
            return "USB", _parse_full(report, offset=1)
        if n >= 10:
            return "Bluetooth (simple mode)", _parse_simple(report)

    return None, None


def _parse_full(r, offset):
    """USB 0x01 (offset=1) and BT 0x31 (offset=2) share the same layout."""
    o = offset
    state = {
        "LX": r[o + 0], "LY": r[o + 1], "RX": r[o + 2], "RY": r[o + 3],
        "L2": r[o + 4], "R2": r[o + 5],
    }
    state.update(_parse_buttons(r[o + 7], r[o + 8], r[o + 9]))
    if len(r) > o + 52:
        b = r[o + 52]                       # report[53] on USB
        level = b & 0x0F
        charging = (b & 0xF0) >> 4
        state["Battery"] = min(level * 10 + 5, 100)
        state["Charging"] = {0: "no", 1: "charging", 2: "full"}.get(charging, f"?({charging})")
    return state


def _parse_simple(r):
    """Bluetooth simple mode (0x01, short): triggers in bytes 8 and 9."""
    state = {"LX": r[1], "LY": r[2], "RX": r[3], "RY": r[4], "L2": r[8], "R2": r[9]}
    state.update(_parse_buttons(r[5], r[6], r[7]))
    return state


def _parse_ds4(r, bus_hint):
    """DualShock 4: USB 0x01 (64 bytes), Bluetooth 0x11 (full) or 0x01 (short)."""
    rid, n = r[0], len(r)
    if rid == 0x11 and n >= 40:
        mode, o = "Bluetooth (full mode)", 3
    elif rid == 0x01 and (bus_hint == "USB" or (bus_hint is None and n == USB_REPORT_LEN)) and n >= 32:
        mode, o = "USB", 1
    elif rid == 0x01 and n >= 10:
        state = _parse_simple(r)
        state["Mute"] = False
        return "Bluetooth (simple mode)", state
    else:
        return None, None
    state = {"LX": r[o], "LY": r[o + 1], "RX": r[o + 2], "RY": r[o + 3],
             "L2": r[o + 7], "R2": r[o + 8]}
    state.update(_parse_buttons(r[o + 4], r[o + 5], r[o + 6]))
    state["Mute"] = False                    # DS4 has no mute button (those bits are a counter)
    b = r[o + 29]
    level, cable = b & 0x0F, bool(b & 0x10)
    state["Battery"] = min(level * 10 + 5, 100)
    state["Charging"] = ("full" if level >= 10 else "charging") if cable else "no"
    return mode, state


def _parse_buttons(b0, b1, b2):
    return {
        "D-pad": DPAD[b0 & 0x0F] if (b0 & 0x0F) <= 8 else "?",
        "Square": bool(b0 & 0x10), "Cross": bool(b0 & 0x20),
        "Circle": bool(b0 & 0x40), "Triangle": bool(b0 & 0x80),
        "L1": bool(b1 & 0x01), "R1": bool(b1 & 0x02),
        "L2 button": bool(b1 & 0x04), "R2 button": bool(b1 & 0x08),
        "Create": bool(b1 & 0x10), "Options": bool(b1 & 0x20),
        "L3": bool(b1 & 0x40), "R3": bool(b1 & 0x80),
        "PS": bool(b2 & 0x01), "Touchpad": bool(b2 & 0x02), "Mute": bool(b2 & 0x04),
    }


# ---------------------------------------------------------------- Bluetooth full mode

def enable_full_mode(device, model="dualsense"):
    """Reading the calibration feature report switches Bluetooth to full reports
    (DualSense: 0x05 → 0x31 reports, DualShock 4: 0x02 → 0x11 reports)."""
    try:
        if model == "ds4":
            device.get_feature_report(0x02, 37)
        else:
            device.get_feature_report(0x05, 41)
        return True
    except (OSError, ValueError, IOError):
        return False


# ---------------------------------------------------------------- display

def bar(value, width=20):
    filled = round(value / 255 * width)
    return "█" * filled + "·" * (width - filled)


def draw(mode, d, count):
    pressed = [k for k, v in d.items() if v is True]
    lines = [
        f"Connection: {mode:<24} Reports: {count}",
        "",
        f"L2 {d['L2']:>3} {bar(d['L2'])}    R2 {d['R2']:>3} {bar(d['R2'])}",
        f"Left stick  X {d['LX']:>3}  Y {d['LY']:>3}      Right stick  X {d['RX']:>3}  Y {d['RY']:>3}",
        f"D-pad: {d['D-pad']:<12}",
        f"Pressed: {', '.join(pressed) if pressed else '-':<70}",
    ]
    if "Battery" in d:
        lines.append(f"Battery: {d['Battery']:<3}%  ({d['Charging']})        ")
    else:
        lines.append(" " * 40)
    lines += ["", "Ctrl+C to quit"]
    # Move the cursor home and overwrite (no full clear, so it doesn't flicker)
    sys.stdout.write("\x1b[H" + "\n".join(s + "\x1b[K" for s in lines) + "\x1b[J")
    sys.stdout.flush()


# ---------------------------------------------------------------- main loop

def main():
    os.system("")  # enables ANSI escape codes in the Windows console

    info = find_controller()
    if info is None:
        print("No DualSense or DualShock 4 found. Is it plugged in, or connected over Bluetooth?")
        print("Sony devices found:", [hex(d["product_id"]) for d in hid.enumerate(SONY_VID, 0)] or "none")
        return 1

    name = info["name"]
    hint = bus_type(info)
    print(f"Found: {name}  (connection hint: {hint or 'unknown, will tell from reports'})")

    device = hid.device()
    try:
        device.open_path(info["path"])
    except (OSError, IOError) as e:
        print("Could not open the controller:", e)
        print("Another program (Steam, DS4Windows) may be holding it; close it and try again.")
        return 1

    full_mode_requested = False
    last_retry = 0.0
    count = 0
    first_frame = True

    try:
        while True:
            report = device.read(BT_REPORT_LEN, 1000)
            if not report:
                continue
            mode, state = parse_report(report, hint, info["model"])
            if state is None:
                continue

            if mode.endswith("simple mode)"):
                if not full_mode_requested:
                    full_mode_requested = enable_full_mode(device, info["model"])
                elif time.time() - last_retry > 3:
                    # Feature report was sent but still in simple mode: retry
                    last_retry = time.time()
                    enable_full_mode(device, info["model"])

            if first_frame:
                sys.stdout.write("\x1b[2J")
                first_frame = False
            count += 1
            draw(mode, state, count)
    except KeyboardInterrupt:
        print("\nShutting down.")
    except (OSError, IOError) as e:
        print("\nConnection lost:", e)
    finally:
        device.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
