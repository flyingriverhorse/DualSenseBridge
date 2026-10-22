"""
DualSense output reports — stage 4 (rumble) and trigger effects
Builds the report that drives the two rumble motors and the adaptive triggers,
for USB (0x02) and Bluetooth (0x31, with CRC32).
"""

import zlib

USB_OUT_ID, USB_OUT_LEN = 0x02, 48
BT_OUT_ID, BT_OUT_LEN = 0x31, 78
BT_TAG = 0x10

# "common" block, shared by USB and Bluetooth (47 bytes)
FLAG0_COMPAT_VIBRATION = 0x01   # motors below are valid
FLAG0_HAPTICS_SELECT = 0x02     # use rumble emulation instead of audio haptics
FLAG0_RIGHT_TRIGGER = 0x04      # right trigger effect below is valid
FLAG0_LEFT_TRIGGER = 0x08       # left trigger effect below is valid
COMMON_LEN = 47
OFF_FLAG0 = 0
OFF_MOTOR_RIGHT = 2             # small / high-frequency motor
OFF_MOTOR_LEFT = 3              # large / low-frequency motor
OFF_RIGHT_TRIGGER = 10          # 11 bytes (R2)
OFF_LEFT_TRIGGER = 21           # 11 bytes (L2)
TRIGGER_LEN = 11


# ---------------------------------------------------------------- trigger effects
# The trigger travel is split into 10 zones (0 = rest, 9 = fully pressed).

def _clamp(v, lo, hi):
    return max(lo, min(hi, int(v)))


def effect_off():
    e = bytearray(TRIGGER_LEN)
    e[0] = 0x05
    return bytes(e)


def effect_feedback(start=3, strength=4):
    """Resistance from zone `start` (0–9) to the end, `strength` 1–8."""
    start, strength = _clamp(start, 0, 9), _clamp(strength, 1, 8)
    active, force = 0, 0
    for zone in range(start, 10):
        active |= 1 << zone
        force |= (strength - 1) << (3 * zone)
    e = bytearray(TRIGGER_LEN)
    e[0] = 0x21
    e[1:3] = active.to_bytes(2, "little")
    e[3:7] = force.to_bytes(4, "little")
    return bytes(e)


def effect_weapon(start=4, end=6, strength=6):
    """Resistance between `start` (2–7) and `end` (start+1–8), then it 'breaks' like a gun trigger."""
    start = _clamp(start, 2, 7)
    end = _clamp(end, start + 1, 8)
    strength = _clamp(strength, 1, 8)
    zones = (1 << start) | (1 << end)
    e = bytearray(TRIGGER_LEN)
    e[0] = 0x25
    e[1:3] = zones.to_bytes(2, "little")
    e[3] = strength - 1
    return bytes(e)


def effect_vibration(start=3, amplitude=5, frequency=20):
    """The trigger buzzes from zone `start` on; `amplitude` 1–8, `frequency` 1–255 Hz."""
    start, amplitude = _clamp(start, 0, 9), _clamp(amplitude, 1, 8)
    frequency = _clamp(frequency, 1, 255)
    active, force = 0, 0
    for zone in range(start, 10):
        active |= 1 << zone
        force |= (amplitude - 1) << (3 * zone)
    e = bytearray(TRIGGER_LEN)
    e[0] = 0x26
    e[1:3] = active.to_bytes(2, "little")
    e[3:7] = force.to_bytes(4, "little")
    e[9] = frequency
    return bytes(e)


def effect_multi_feedback(strengths):
    """Resistance per zone: a list of 10 strengths (0 = no resistance in that zone, 1–8)."""
    strengths = [_clamp(x, 0, 8) for x in (list(strengths) + [0] * 10)[:10]]
    if not any(strengths):
        return effect_off()
    active, force = 0, 0
    for zone, st in enumerate(strengths):
        if st > 0:
            active |= 1 << zone
            force |= ((st - 1) & 0x07) << (3 * zone)
    e = bytearray(TRIGGER_LEN)
    e[0] = 0x21
    e[1:3] = active.to_bytes(2, "little")
    e[3:7] = force.to_bytes(4, "little")
    return bytes(e)


def effect_slope(start=1, end=9, start_strength=1, end_strength=8):
    """Resistance that grows (or fades) linearly from `start` to `end`, then holds."""
    start = _clamp(start, 0, 8)
    end = _clamp(end, start + 1, 9)
    a, b = _clamp(start_strength, 1, 8), _clamp(end_strength, 1, 8)
    strengths = [0] * 10
    for zone in range(start, 10):
        t = min(1.0, (zone - start) / (end - start))
        strengths[zone] = round(a + (b - a) * t)
    return effect_multi_feedback(strengths)


def effect_bow(start=1, end=4, strength=4, snap=6):
    """Tension builds from `start` to `end` (0–8), then the trigger snaps back with `snap` force (1–8)."""
    start = _clamp(start, 0, 7)
    end = _clamp(end, start + 1, 8)
    strength, snap = _clamp(strength, 1, 8), _clamp(snap, 1, 8)
    zones = (1 << start) | (1 << end)
    pair = ((strength - 1) & 0x07) | (((snap - 1) & 0x07) << 3)
    e = bytearray(TRIGGER_LEN)
    e[0] = 0x22
    e[1:3] = zones.to_bytes(2, "little")
    e[3:5] = pair.to_bytes(2, "little")
    return bytes(e)


def effect_galloping(start=1, end=9, first_foot=1, second_foot=4, frequency=3):
    """Two-beat pulse like hooves (start 0–8, end start+1–9, feet 0–7, frequency 1–255 Hz)."""
    start = _clamp(start, 0, 8)
    end = _clamp(end, start + 1, 9)
    first_foot = _clamp(first_foot, 0, 6)
    second_foot = _clamp(second_foot, first_foot + 1, 7)
    zones = (1 << start) | (1 << end)
    ratio = (second_foot & 0x07) | ((first_foot & 0x07) << 3)
    e = bytearray(TRIGGER_LEN)
    e[0] = 0x23
    e[1:3] = zones.to_bytes(2, "little")
    e[3] = ratio
    e[4] = _clamp(frequency, 1, 255)
    return bytes(e)


def effect_machine(start=1, end=9, amplitude_a=1, amplitude_b=3, frequency=5, period=3):
    """Alternating buzz between two strengths (amplitudes 0–7, frequency Hz, period in 1/10 s)."""
    start = _clamp(start, 0, 8)
    end = _clamp(end, start + 1, 9)
    pair = (_clamp(amplitude_a, 0, 7) & 0x07) | ((_clamp(amplitude_b, 0, 7) & 0x07) << 3)
    zones = (1 << start) | (1 << end)
    e = bytearray(TRIGGER_LEN)
    e[0] = 0x27
    e[1:3] = zones.to_bytes(2, "little")
    e[3] = pair
    e[4] = _clamp(frequency, 1, 255)
    e[5] = _clamp(period, 0, 255)
    return bytes(e)


MAKERS = {
    "off": lambda: effect_off(),
    "feedback": effect_feedback,
    "weapon": effect_weapon,
    "vibration": effect_vibration,
    "slope": effect_slope,
    "multi": lambda strengths: effect_multi_feedback(strengths),
    "bow": effect_bow,
    "galloping": effect_galloping,
    "machine": effect_machine,
}


def effect_from_dict(d):
    """{"mode": "feedback", "start": 3, "strength": 4} → 11 effect bytes."""
    if not d:
        return effect_off()
    d = dict(d)
    mode = d.pop("mode", "off")
    for k in [k for k in d if k.startswith("_")]:
        d.pop(k)
    if mode not in MAKERS:
        raise ValueError(f"Unknown trigger mode: {mode}")
    return MAKERS[mode](**d)


# ---------------------------------------------------------------- reports

def bt_crc(report_without_crc):
    """CRC32 over the seed byte 0xA2 followed by the report (Bluetooth output)."""
    return zlib.crc32(bytes([0xA2]) + bytes(report_without_crc)) & 0xFFFFFFFF


FLAG1_LIGHTBAR = 0x04            # light bar color below is valid
FLAG1_MOTOR_POWER = 0x40         # motor power level below is valid
OFF_MOTOR_POWER = 36             # low nibble triggers, high nibble rumble/haptics: 0 = full, 1 step = -12.5 %
FLAG2_LIGHTBAR_SETUP = 0x02      # lightbar_setup below is valid
LIGHTBAR_SETUP_LIGHT_OUT = 0x02  # stop the blue startup animation so our color shows
OFF_FLAG2 = 38
OFF_LIGHTBAR_SETUP = 41
OFF_LIGHT_R, OFF_LIGHT_G, OFF_LIGHT_B = 44, 45, 46

DS4_USB_OUT_ID, DS4_USB_OUT_LEN = 0x05, 32
DS4_BT_OUT_ID, DS4_BT_OUT_LEN = 0x11, 78


class Output:
    """Keeps the Bluetooth sequence counter and builds output reports."""

    def __init__(self):
        self.seq = 0

    def report(self, large, small, bluetooth, l2=None, r2=None, light=None, setup=False,
               model="dualsense", hd=False, full_power=False):
        """Rumble always. Trigger effects and light bar color only when given
        (the controller keeps them until changed). `setup` ends the DualSense's
        own startup light animation; send it once after connecting."""
        if model == "ds4":
            return self._ds4(large, small, bluetooth, light)
        c = bytearray(COMMON_LEN)
        if not hd:
            # rumble emulation; this also closes the audio haptics channel
            c[OFF_FLAG0] = FLAG0_COMPAT_VIBRATION | FLAG0_HAPTICS_SELECT
            c[OFF_MOTOR_LEFT] = large & 0xFF
            c[OFF_MOTOR_RIGHT] = small & 0xFF
        # hd=True: no rumble flags at all, so sound sent to the controller's audio
        # channels 3-4 drives the haptic actuators (tested on a DualSense over USB)
        if r2 is not None:
            c[OFF_FLAG0] |= FLAG0_RIGHT_TRIGGER
            c[OFF_RIGHT_TRIGGER:OFF_RIGHT_TRIGGER + TRIGGER_LEN] = r2
        if l2 is not None:
            c[OFF_FLAG0] |= FLAG0_LEFT_TRIGGER
            c[OFF_LEFT_TRIGGER:OFF_LEFT_TRIGGER + TRIGGER_LEN] = l2
        if light is not None:
            c[1] |= FLAG1_LIGHTBAR
            c[OFF_LIGHT_R], c[OFF_LIGHT_G], c[OFF_LIGHT_B] = (int(x) & 0xFF for x in light)
        if full_power:
            # Bluetooth HD haptics: without this the controller may keep a reduced power level
            # from another program (seen as actuators at 12.5 %)
            c[1] |= FLAG1_MOTOR_POWER
            c[OFF_MOTOR_POWER] = 0
        if setup:
            c[OFF_FLAG2] |= FLAG2_LIGHTBAR_SETUP
            c[OFF_LIGHTBAR_SETUP] = LIGHTBAR_SETUP_LIGHT_OUT
        return self._wrap(c, bluetooth)

    def rumble(self, large, small, bluetooth, model="dualsense"):
        return self.report(large, small, bluetooth, model=model)

    @staticmethod
    def _ds4(large, small, bluetooth, light):
        """DualShock 4: rumble + light bar (no adaptive triggers)."""
        r_, g, b = light if light is not None else (0, 0, 64)
        if bluetooth:
            r = bytearray(DS4_BT_OUT_LEN)
            r[0] = DS4_BT_OUT_ID
            r[1] = 0xC0                # HID report with CRC
            r[3] = 0x07                # motors + light bar + flash valid
            o = 6
        else:
            r = bytearray(DS4_USB_OUT_LEN)
            r[0] = DS4_USB_OUT_ID
            r[1] = 0x07
            o = 4
        r[o], r[o + 1] = small & 0xFF, large & 0xFF
        r[o + 2], r[o + 3], r[o + 4] = int(r_) & 0xFF, int(g) & 0xFF, int(b) & 0xFF
        if bluetooth:
            r[DS4_BT_OUT_LEN - 4:] = bt_crc(r[:DS4_BT_OUT_LEN - 4]).to_bytes(4, "little")
        return bytes(r)

    def _wrap(self, common, bluetooth):
        if not bluetooth:
            r = bytearray(USB_OUT_LEN)
            r[0] = USB_OUT_ID
            r[1:1 + COMMON_LEN] = common
            return bytes(r)

        r = bytearray(BT_OUT_LEN)
        r[0] = BT_OUT_ID
        r[1] = (self.seq & 0x0F) << 4
        r[2] = BT_TAG
        r[3:3 + COMMON_LEN] = common
        self.seq = (self.seq + 1) & 0x0F
        crc = bt_crc(r[:BT_OUT_LEN - 4])
        r[BT_OUT_LEN - 4:] = crc.to_bytes(4, "little")
        return bytes(r)
