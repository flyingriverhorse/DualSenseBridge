"""Engine decisions that need no thread and no hardware."""

import pytest

import engine as eng
from output import effect_off, effect_feedback, OFF_FLAG0, FLAG0_LEFT_TRIGGER, FLAG0_RIGHT_TRIGGER


class FakeDevice:
    def __init__(self):
        self.written = []

    def write(self, data):
        self.written.append(bytes(data))
        return len(data)


@pytest.fixture
def e():
    x = eng.Engine()
    x._info = {"model": "dualsense", "path": b"p"}
    x._device = FakeDevice()
    return x


def xbox_on(x):
    x._pad = object()      # anything not None means "virtual pad exists"


# ---------------------------------------------------------------- light bar

def test_light_auto(e):
    assert e._light() == eng.COLOR_NATIVE
    xbox_on(e)
    assert e._light() == eng.COLOR_XBOX


def test_light_low_battery_only_when_not_charging(e):
    e._battery, e._charging = 10, "no"
    assert e._light() == eng.COLOR_LOW_BATTERY
    e._charging = "charging"
    assert e._light() == eng.COLOR_NATIVE


def test_light_custom_off_brightness(e):
    e.set_light("custom", (200, 100, 50), brightness=50)
    assert e._light() == (100, 50, 25)
    e.set_light("off")
    assert e._light() == (0, 0, 0)
    e.set_light("auto", brightness=250)
    assert e.brightness == 100


# ---------------------------------------------------------------- triggers

def test_xbox_off_leaves_triggers_to_native_games(e):
    assert e._triggers(0) == (None, None, "")


def test_xbox_on_without_profile_resets_triggers(e):
    xbox_on(e)
    assert e._triggers(0) == (effect_off(), effect_off(), "")


def test_xbox_on_with_profile(e):
    xbox_on(e)
    l2, r2 = effect_feedback(1, 2), effect_feedback(5, 8)
    e.set_profile("g", l2, r2)
    assert e._triggers(0)[:2] == (l2, r2)


def test_triggers_given_back_once_after_xbox_off(e):
    e._reset_triggers = True
    assert e._triggers(0)[:2] == (effect_off(), effect_off())


def test_ds4_never_gets_trigger_effects(e):
    e._info["model"] = "ds4"
    xbox_on(e)
    e.set_profile("g", effect_feedback(), effect_feedback())
    assert e._triggers(0) == (None, None, "")


def test_trigger_test_walks_through_the_steps(e):
    e._test_started, e._test_until = 100.0, 100.0 + eng.TEST_SECONDS * len(eng.TEST_STEPS)
    names = [e._triggers(100.0 + eng.TEST_SECONDS * i + 0.1)[2] for i in range(len(eng.TEST_STEPS))]
    assert names == [n for n, _ in eng.TEST_STEPS]


# ---------------------------------------------------------------- trigger kick

def test_kick_needs_a_jump_and_a_minimum(e):
    xbox_on(e)
    e.set_react(True)
    e._rumble = [eng.KICK_MIN + 10, 0]
    e._update_kick(10.0)
    assert e._kick_until == pytest.approx(10.0 + eng.KICK_SECONDS)
    assert e._triggers(10.05)[:2] == e._kick
    # steady rumble: no new kick
    e._kick_until = 0
    e._update_kick(11.0)
    assert e._kick_until == 0


def test_no_kick_when_disabled(e):
    xbox_on(e)
    e._rumble = [255, 255]
    e._update_kick(1.0)
    assert e._kick_until == 0


# ---------------------------------------------------------------- output writes

def test_output_is_written_once_until_something_changes(e):
    xbox_on(e)
    e._send_output(bluetooth=False)
    e._send_output(bluetooth=False)
    assert len(e._device.written) == 1
    e._rumble = [120, 40]
    e._send_output(bluetooth=False)
    assert len(e._device.written) == 2


def test_triggers_reset_after_xbox_off_is_sent_once(e):
    e._reset_triggers = True
    e._send_output(bluetooth=True)
    first = e._device.written[-1]
    assert first[3 + OFF_FLAG0] & (FLAG0_LEFT_TRIGGER | FLAG0_RIGHT_TRIGGER)
    assert e._reset_triggers is False
    e._need_setup = True                   # force another write
    e._send_output(bluetooth=True)
    assert not e._device.written[-1][3 + OFF_FLAG0] & (FLAG0_LEFT_TRIGGER | FLAG0_RIGHT_TRIGGER)


def test_no_rumble_reaches_the_controller_in_native_mode(e):
    e._rumble = [200, 200]                 # stale value from the pad
    e._send_output(bluetooth=False)
    assert e.snapshot()["rumble"] == (0, 0)
