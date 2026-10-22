"""Gyro aiming: turning the controller moves the right stick of the virtual Xbox pad.

Works in any Xbox game (no mouse needed). The game sees a small stick push for a slow
turn and a full push for a fast one. Most games ignore the first ~20 % of the stick, so
gyro output starts just past that ("game deadzone") or small turns would do nothing.
"""

import math

RAW_PER_DEG = 16.4            # DualSense and DualShock 4: ±2000 °/s over a signed 16-bit value
STILL = 1.5                   # °/s: slower than this counts as "lying still" for drift correction
LEARN = 0.002                 # how fast the drift correction follows (per report, ~250 / s)

ACTIVATE = ["Always", "While L2 is held", "While L1 is held", "While touching the touchpad"]
DEFAULTS = {"enabled": False, "activate": "While L2 is held", "full_speed": 120, "deadzone": 1,
            "game_deadzone": 20, "turn_axis": "yaw", "invert_x": False, "invert_y": False}
LIMITS = {"full_speed": (30, 360), "deadzone": (0, 10), "game_deadzone": (0, 40)}


def clean(cfg):
    cfg = dict(cfg or {})
    out = dict(DEFAULTS)
    for k in ("enabled", "invert_x", "invert_y"):
        out[k] = bool(cfg.get(k, DEFAULTS[k]))
    if cfg.get("activate") in ACTIVATE:
        out["activate"] = cfg["activate"]
    if cfg.get("turn_axis") in ("yaw", "roll"):
        out["turn_axis"] = cfg["turn_axis"]
    for k, (lo, hi) in LIMITS.items():
        try:
            out[k] = max(lo, min(hi, int(cfg.get(k, DEFAULTS[k]))))
        except (TypeError, ValueError):
            pass
    return out


class GyroAim:
    def __init__(self, cfg=None):
        self.cfg = clean(cfg)
        self.bias = None          # raw pitch, yaw, roll while still
        self._calibrating = []
        self.rates = (0.0, 0.0, 0.0)
        self.active = False

    def configure(self, cfg):
        self.cfg = clean(cfg)

    def calibrate(self, samples=250):
        """Average the next `samples` reports as the 'still' value (controller lying on a table)."""
        self._calibrating = [samples]

    @property
    def calibrating(self):
        return bool(self._calibrating)

    def _learn(self, g):
        if self._calibrating:
            left = self._calibrating[0] - 1
            acc = self._calibrating[1:] or [0.0, 0.0, 0.0, 0]
            acc = [acc[0] + g[0], acc[1] + g[1], acc[2] + g[2], acc[3] + 1]
            self._calibrating = [left] + acc
            if left <= 0:
                n = acc[3]
                self.bias = (acc[0] / n, acc[1] / n, acc[2] / n)
                self._calibrating = []
            return
        if self.bias is None:
            self.bias = tuple(float(v) for v in g)
            return
        if max(abs(v - b) for v, b in zip(g, self.bias)) / RAW_PER_DEG < STILL:
            self.bias = tuple(b + (v - b) * LEARN for v, b in zip(g, self.bias))

    def _is_active(self, d):
        a = self.cfg["activate"]
        if a == "Always":
            return True
        if a == "While L2 is held":
            return d.get("L2", 0) > 30 or bool(d.get("L2 button"))
        if a == "While L1 is held":
            return bool(d.get("L1"))
        return bool(d.get("Touching"))

    def update(self, d):
        """Controller state → (x, y) to add to the right stick, each −1…1 (up = +y)."""
        g = d.get("Gyro")
        if g is None:
            self.active = False
            return 0.0, 0.0
        self._learn(g)
        b = self.bias or (0.0, 0.0, 0.0)
        pitch, yaw, roll = ((v - bb) / RAW_PER_DEG for v, bb in zip(g, b))
        self.rates = (pitch, yaw, roll)
        c = self.cfg
        self.active = c["enabled"] and not self.calibrating and self._is_active(d)
        if not self.active:
            return 0.0, 0.0
        turn = yaw if c["turn_axis"] == "yaw" else roll
        x, y = -turn, pitch
        if c["invert_x"]:
            x = -x
        if c["invert_y"]:
            y = -y
        mag = math.hypot(x, y)
        dz, full = c["deadzone"], c["full_speed"]
        if mag <= dz:
            return 0.0, 0.0
        amount = min(1.0, (mag - dz) / max(1e-6, full - dz))
        out = c["game_deadzone"] / 100 + (1 - c["game_deadzone"] / 100) * amount
        return x / mag * out, y / mag * out
