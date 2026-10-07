"""
Bridge engine for the UI — runs in a background thread.

- Keeps looking for the controller and reconnects on its own (USB or Bluetooth).
  DualSense gets everything; a DualShock 4 gets mapping, rumble and light bar.
- Xbox mode ON:  virtual Xbox 360 pad + HidHide hiding + rumble + trigger profile
                 (+ optional trigger kick when the game rumbles).
- Xbox mode OFF: the controller is left alone for games that support it natively
                 (only the light bar color is set, once).
- Publishes a status snapshot the UI polls.
"""

import threading
import time

import hid

from dualsense_reader import find_controller, bus_type, parse_report, enable_full_mode, BT_REPORT_LEN
from hiding import Hiding, find_cli, _cli
from output import (Output, effect_off, effect_weapon, effect_vibration, effect_slope,
                    effect_bow, effect_machine, effect_galloping)

TEST_STEPS = [
    ("Gun click", effect_weapon(start=2, end=3, strength=6)),
    ("Heavy break", effect_weapon(start=2, end=5, strength=8)),
    ("Swing snap", effect_bow(start=1, end=4, strength=4, snap=6)),
    ("Growing resistance", effect_slope(start=1, end=8, start_strength=1, end_strength=7)),
    ("Rapid fire", effect_vibration(start=2, amplitude=4, frequency=12)),
    ("Heavy machine gun", effect_machine(start=1, end=9, amplitude_a=2, amplitude_b=6, frequency=8, period=2)),
    ("Galloping", effect_galloping(start=1, end=9, first_foot=1, second_foot=3, frequency=6)),
]
TEST_SECONDS = 4
RECONNECT_SECONDS = 2

# Light bar
COLOR_XBOX = (0, 200, 70)
COLOR_NATIVE = (0, 80, 255)
COLOR_LOW_BATTERY = (255, 30, 0)
LOW_BATTERY = 15            # percent

# Trigger kick when the game rumbles
KICK_SECONDS = 0.12
KICK_RISE = 60              # how much the rumble must jump (0–255)
KICK_MIN = 90               # and how strong it must be


class Engine(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._lock = threading.Lock()
        self._running = True

        # wishes set by the UI
        self.want_xbox = False
        self.profile_name = None
        self.l2_effect = None
        self.r2_effect = None
        self.light_mode = "auto"          # auto | custom | off
        self.light_color = COLOR_XBOX
        self.brightness = 100             # percent
        self.react = False                # trigger kick on rumble
        self._test_until = 0.0
        self._test_started = 0.0

        # status read by the UI
        self.status = {
            "connected": False, "name": "", "model": "", "mode": "", "battery": None,
            "charging": "", "xbox": False, "hidden": False, "L2": 0, "R2": 0,
            "rumble": (0, 0), "test": "", "error": "", "vigem": None, "kick": False,
        }

        # internals
        self._device = None
        self._info = None
        self._pad = None
        self._hiding = None
        self._out = Output()
        self._rumble = [0, 0]
        self._last_rumble = 0
        self._kick_until = 0.0
        self._kick = (None, None)
        self._sent = None
        self._reset_triggers = False
        self._need_setup = True
        self._battery = None
        self._charging = ""
        self._vg = None

    # ------------------------------------------------------------ UI API

    def set_xbox(self, on):
        self.want_xbox = bool(on)

    def set_profile(self, name, l2, r2):
        with self._lock:
            self.profile_name, self.l2_effect, self.r2_effect = name, l2, r2

    def set_light(self, mode, color=None, brightness=None):
        self.light_mode = mode
        if color is not None:
            self.light_color = tuple(int(c) for c in color)
        if brightness is not None:
            self.brightness = max(0, min(100, int(brightness)))

    def set_react(self, on):
        self.react = bool(on)

    def start_test(self):
        self._test_started = time.time()
        self._test_until = self._test_started + TEST_SECONDS * len(TEST_STEPS)

    def shutdown(self):
        self._running = False

    def snapshot(self):
        with self._lock:
            return dict(self.status)

    # ------------------------------------------------------------ helpers

    def _set(self, **kw):
        with self._lock:
            self.status.update(kw)

    @property
    def _model(self):
        return self._info["model"] if self._info else "dualsense"

    def _load_vigem(self):
        if self._vg is None:
            try:
                import vgamepad as vg
                self._vg = vg
                self._set(vigem=True)
            except Exception as e:
                self._set(vigem=False, error=f"ViGEmBus / vgamepad not available: {e}")
        return self._vg

    def _connect(self):
        info = find_controller()
        if info is None:
            return False
        dev = hid.device()
        try:
            dev.open_path(info["path"])
        except (OSError, IOError) as e:
            self._set(error=f"Could not open controller: {e}")
            return False
        self._device, self._info = dev, info
        self._sent = None
        self._need_setup = True
        self._set(connected=True, name=info["name"], model=info["model"], error="")
        return True

    def _disconnect(self):
        self._xbox_off()
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
        self._device = self._info = None
        self._set(connected=False, name="", model="", mode="", battery=None, charging="", L2=0, R2=0)

    def _xbox_on(self):
        vg = self._load_vigem()
        if vg is None:
            self.want_xbox = False
            return
        try:
            self._pad = vg.VX360Gamepad()
        except Exception as e:
            self._pad = None
            self.want_xbox = False
            self._set(error=f"Could not create the virtual Xbox pad: {e}")
            return

        def on_rumble(client, target, large_motor, small_motor, led_number, user_data):
            self._rumble[0], self._rumble[1] = large_motor, small_motor

        self._pad.register_notification(callback_function=on_rumble)
        self._hiding = Hiding(self._info["path"])
        try:
            self._hiding.__enter__()
        except Exception as e:
            self._set(error=f"Hiding failed: {e}")
        self._set(xbox=True, hidden=self._hiding.active)

    def _xbox_off(self):
        if self._pad is not None:
            try:
                self._pad.unregister_notification()
                self._pad.reset()
                self._pad.update()
            except Exception:
                pass
            self._pad = None
            self._reset_triggers = True      # give the triggers back once
        if self._hiding is not None:
            self._hiding.__exit__(None, None, None)
            self._hiding = None
        self._rumble = [0, 0]
        self._set(xbox=False, hidden=False, rumble=(0, 0))

    def _light(self):
        """Light bar color from the settings, scaled by brightness."""
        if self.light_mode == "off":
            return (0, 0, 0)
        if self.light_mode == "custom":
            color = self.light_color
        elif (self._battery is not None and self._battery <= LOW_BATTERY
              and self._charging == "no"):
            color = COLOR_LOW_BATTERY
        else:
            color = COLOR_XBOX if self._pad is not None else COLOR_NATIVE
        k = self.brightness / 100
        return tuple(round(c * k) for c in color)

    def _triggers(self, now):
        """(l2, r2, test name). None means 'leave the triggers alone'."""
        if self._model != "dualsense":
            return None, None, ""
        if now < self._test_until:
            i = min(int((now - self._test_started) // TEST_SECONDS), len(TEST_STEPS) - 1)
            name, effect = TEST_STEPS[i]
            self._reset_triggers = True      # reset after the test
            return effect, effect, name
        if self._pad is not None:
            if now < self._kick_until:
                return self._kick[0], self._kick[1], ""
            if self.profile_name:
                return self.l2_effect, self.r2_effect, ""
            return effect_off(), effect_off(), ""
        if self._reset_triggers:
            return effect_off(), effect_off(), ""
        return None, None, ""                # Xbox mode off: native games own the triggers

    def _update_kick(self, now):
        level = max(self._rumble)
        if (self.react and self._pad is not None and self._model == "dualsense"
                and level >= KICK_MIN and level - self._last_rumble >= KICK_RISE):
            amp = min(8, 3 + level // 50)
            self._kick = (effect_vibration(start=0, amplitude=max(1, amp - 2), frequency=40),
                          effect_vibration(start=0, amplitude=amp, frequency=40))
            self._kick_until = now + KICK_SECONDS
        self._last_rumble = level

    def _send_output(self, bluetooth):
        now = time.time()
        self._update_kick(now)
        l2, r2, test_name = self._triggers(now)
        large, small = (self._rumble if self._pad is not None else (0, 0))
        light = self._light()
        want = (large, small, bluetooth, l2, r2, light)
        if want != self._sent or self._need_setup:
            self._device.write(self._out.report(large, small, bluetooth, l2=l2, r2=r2, light=light,
                                                setup=self._need_setup, model=self._model))
            self._sent = want
            self._need_setup = False
            if l2 is not None and self._pad is None and now >= self._test_until:
                self._reset_triggers = False
        self._set(rumble=(large, small), test=test_name, kick=now < self._kick_until)

    # ------------------------------------------------------------ thread

    def run(self):
        # Clean start: if a previous run crashed with hiding on, turn it off
        cli = find_cli()
        if cli:
            try:
                _cli(cli, "--cloak-off")
            except Exception:
                pass

        try:
            from bridge import write_virtual   # mapping controller → Xbox (needs vgamepad)
        except BaseException as e:           # bridge exits if vgamepad / ViGEmBus is missing
            write_virtual = None
            self._set(vigem=False, error=f"ViGEmBus / vgamepad not available: {e}")

        full_mode_requested = False
        last_retry = 0.0
        while self._running:
            if self._device is None:
                if not self._connect():
                    time.sleep(RECONNECT_SECONDS)
                    continue
                full_mode_requested = False

            try:
                report = self._device.read(BT_REPORT_LEN, 200)
            except (OSError, IOError, ValueError):
                self._disconnect()
                continue
            if not report:
                continue
            mode, d = parse_report(report, bus_type(self._info), self._model)
            if d is None:
                continue
            if mode.endswith("simple mode)") and (not full_mode_requested or time.time() - last_retry > 3):
                full_mode_requested = enable_full_mode(self._device, self._model)
                last_retry = time.time()
            self._battery, self._charging = d.get("Battery"), d.get("Charging", "")

            if self.want_xbox and write_virtual is None:
                self.want_xbox = False
            if self.want_xbox and self._pad is None:
                self._xbox_on()
            elif not self.want_xbox and self._pad is not None:
                self._xbox_off()

            try:
                if self._pad is not None:
                    write_virtual(self._pad, d)
                self._send_output(mode.startswith("Bluetooth"))
            except (OSError, IOError, ValueError):
                self._disconnect()
                continue

            self._set(mode=mode, L2=d["L2"], R2=d["R2"],
                      battery=self._battery, charging=self._charging)

        # leaving: triggers back to normal, default blue light, pad removed, hiding off
        try:
            if self._device is not None and self._sent is not None:
                trig = effect_off() if self._model == "dualsense" else None
                self._device.write(self._out.report(0, 0, self._sent[2], l2=trig, r2=trig,
                                                    light=COLOR_NATIVE, model=self._model))
        except Exception:
            pass
        self._disconnect()
