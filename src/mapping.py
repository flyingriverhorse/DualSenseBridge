"""Controller state → Xbox values: button remapping, stick and trigger deadzones.

With the default settings the result is exactly what the bridge always did, so
nothing changes for people who never open the Controls tab. No vgamepad import:
the XInput button bits are fixed by Microsoft, so they are written out here.
"""

import math

XBOX = {
    "A": 0x1000, "B": 0x2000, "X": 0x4000, "Y": 0x8000,
    "LB": 0x0100, "RB": 0x0200, "Back": 0x0020, "Start": 0x0010, "Guide": 0x0400,
    "LS (click)": 0x0040, "RS (click)": 0x0080,
    "D-pad Up": 0x0001, "D-pad Down": 0x0002, "D-pad Left": 0x0004, "D-pad Right": 0x0008,
}
TARGETS = list(XBOX) + ["LT (full press)", "RT (full press)", "Nothing"]

DEFAULT_REMAP = {
    "Cross": "A", "Circle": "B", "Square": "X", "Triangle": "Y",
    "L1": "LB", "R1": "RB", "Create": "Back", "Options": "Start", "PS": "Guide",
    "L3": "LS (click)", "R3": "RS (click)",
    "D-pad Up": "D-pad Up", "D-pad Down": "D-pad Down",
    "D-pad Left": "D-pad Left", "D-pad Right": "D-pad Right",
    "Touchpad": "Nothing", "Mute": "Nothing",
}
SOURCES = list(DEFAULT_REMAP)

DEFAULTS = {"ls_deadzone": 0, "rs_deadzone": 0, "trigger_deadzone": 0, "trigger_full": 100,
            "remap": {}}
LIMITS = {"ls_deadzone": (0, 40), "rs_deadzone": (0, 40), "trigger_deadzone": (0, 40),
          "trigger_full": (60, 100)}


def dpad_pressed(dpad):
    """'Up-Right' → {'D-pad Up', 'D-pad Right'}."""
    if not dpad or dpad in ("-", "?"):
        return set()
    return {"D-pad " + part for part in dpad.split("-")}


def axis(value, invert=False):
    """0–255 → −32768…32767 (the original bridge mapping). Y: DualSense down = 255, Xbox up = +."""
    v = value * 257 - 32768
    if invert:
        v = -1 - v
    return max(-32768, min(32767, v))


def stick(x, y, deadzone):
    """Two raw 0–255 axes → Xbox (x, y). Radial deadzone in percent, rescaled so
    movement starts smoothly at its edge instead of jumping."""
    if deadzone <= 0:
        return axis(x), axis(y, invert=True)
    fx, fy = (x - 127.5) / 127.5, (127.5 - y) / 127.5
    mag = math.hypot(fx, fy)
    dz = deadzone / 100
    if mag <= dz:
        return 0, 0
    k = min(1.0, (mag - dz) / (1 - dz)) / mag
    return (max(-32768, min(32767, round(fx * k * 32767))),
            max(-32768, min(32767, round(fy * k * 32767))))


def trigger(value, deadzone, full):
    """0–255 → 0–255 with a deadzone at the start and a full press reached at `full` percent."""
    lo, hi = 255 * deadzone / 100, 255 * full / 100
    if deadzone <= 0 and full >= 100:
        return value
    if value <= lo:
        return 0
    if value >= hi:
        return 255
    return round((value - lo) * 255 / (hi - lo))


def combine(xbox, add):
    """Xbox stick (−32768…32767) + (x, y) in −1…1, kept inside the stick's circle."""
    x, y = xbox[0] / 32767 + add[0], xbox[1] / 32767 + add[1]
    mag = math.hypot(x, y)
    if mag > 1:
        x, y = x / mag, y / mag
    return (max(-32768, min(32767, round(x * 32767))), max(-32768, min(32767, round(y * 32767))))


def clean(cfg):
    """Settings as stored → complete, in-range settings (unknown buttons/targets dropped)."""
    cfg = dict(cfg or {})
    out = {}
    for k, default in DEFAULTS.items():
        if k == "remap":
            continue
        lo, hi = LIMITS[k]
        try:
            out[k] = max(lo, min(hi, int(cfg.get(k, default))))
        except (TypeError, ValueError):
            out[k] = default
    remap = cfg.get("remap") or {}
    out["remap"] = {s: t for s, t in remap.items()
                    if s in DEFAULT_REMAP and t in TARGETS and t != DEFAULT_REMAP[s]}
    return out


class Mapping:
    def __init__(self, cfg=None):
        self.cfg = clean(cfg)
        self.table = {**DEFAULT_REMAP, **self.cfg["remap"]}

    @property
    def is_default(self):
        return self.cfg == clean(None)

    def apply(self, d, add_right=None):
        """State dict from dualsense_reader → (buttons, lt, rt, lx, ly, rx, ry).
        `add_right`: (x, y) in −1…1 added to the right stick (gyro aiming)."""
        c = self.cfg
        pressed = {s for s in SOURCES if not s.startswith("D-pad") and d.get(s)} | dpad_pressed(d.get("D-pad"))
        mask, lt, rt = 0, d["L2"], d["R2"]
        lt = trigger(lt, c["trigger_deadzone"], c["trigger_full"])
        rt = trigger(rt, c["trigger_deadzone"], c["trigger_full"])
        for s in pressed:
            t = self.table[s]
            if t in XBOX:
                mask |= XBOX[t]
            elif t == "LT (full press)":
                lt = 255
            elif t == "RT (full press)":
                rt = 255
        lx, ly = stick(d["LX"], d["LY"], c["ls_deadzone"])
        rx, ry = stick(d["RX"], d["RY"], c["rs_deadzone"])
        if add_right and (add_right[0] or add_right[1]):
            rx, ry = combine((rx, ry), add_right)
        return mask, lt, rt, lx, ly, rx, ry


DEFAULT = Mapping()
