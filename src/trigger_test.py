"""
Trigger effect test — tries every effect for a few seconds, no game needed.
Run: run_trigger_test.bat (or: python trigger_test.py). Press L2/R2 while it runs.
"""

import sys
import time

import hid
from dualsense_reader import find_controller, bus_type, parse_report, enable_full_mode, BT_REPORT_LEN
from output import (Output, effect_off, effect_weapon, effect_vibration, effect_slope,
                    effect_bow, effect_machine, effect_galloping)

STEPS = [
    ("Gun click", effect_weapon(start=2, end=3, strength=6)),
    ("Heavy break", effect_weapon(start=2, end=5, strength=8)),
    ("Swing snap", effect_bow(start=1, end=4, strength=4, snap=6)),
    ("Growing resistance", effect_slope(start=1, end=8, start_strength=1, end_strength=7)),
    ("Rapid fire", effect_vibration(start=2, amplitude=4, frequency=12)),
    ("Heavy machine gun", effect_machine(start=1, end=9, amplitude_a=2, amplitude_b=6, frequency=8, period=2)),
    ("Galloping", effect_galloping(start=1, end=9, first_foot=1, second_foot=3, frequency=6)),
]
SECONDS = 4


def main():
    info = find_controller()
    if info is None:
        print("No DualSense found.")
        return 1
    if info["model"] != "dualsense":
        print("Trigger effects need a DualSense.")
        return 1
    device = hid.device()
    device.open_path(info["path"])
    hint = bus_type(info)
    out = Output()

    # Read one report to know USB vs Bluetooth (and switch BT to full mode)
    mode = None
    while mode is None or mode.endswith("simple mode)"):
        mode, _ = parse_report(device.read(BT_REPORT_LEN, 1000), hint, info["model"])
        if mode and mode.endswith("simple mode)"):
            enable_full_mode(device, info["model"])
    bluetooth = mode.startswith("Bluetooth")
    print(f"Connection: {mode}. Keep pressing L2 and R2.\n")

    try:
        for name, effect in STEPS:
            print(f"-> {name}")
            device.write(out.report(0, 0, bluetooth, l2=effect, r2=effect))
            end = time.time() + SECONDS
            while time.time() < end:
                device.read(BT_REPORT_LEN, 100)   # keep the input queue drained
    except KeyboardInterrupt:
        pass
    finally:
        device.write(out.report(0, 0, bluetooth, l2=effect_off(), r2=effect_off()))
        device.close()
    print("\nDone. Triggers are back to normal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
