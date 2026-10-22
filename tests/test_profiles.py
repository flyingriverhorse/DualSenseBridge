"""profiles.json: every game resolves and every effect builds."""

import json
import os

import pytest

from bridge_profiles import profiles_path, read_profiles, resolve_profile
from output import effect_from_dict, MAKERS

PROFILES = read_profiles()
GAMES = [k for k in PROFILES if not k.startswith("_")]


def test_path_points_at_the_repo_file():
    assert os.path.samefile(profiles_path(), os.path.join(os.path.dirname(__file__), "..", "profiles.json"))


def test_there_is_an_off_profile():
    assert "off" in GAMES


@pytest.mark.parametrize("name", GAMES)
def test_game_resolves_and_builds(name):
    p = resolve_profile(PROFILES, name)
    for side in ("L2", "R2"):
        e = effect_from_dict(p[side])
        assert len(e) == 11


@pytest.mark.parametrize("name", sorted(PROFILES["_presets"]))
def test_presets_use_known_modes(name):
    for side in ("L2", "R2"):
        d = PROFILES["_presets"][name].get(side)
        if d:
            assert d.get("mode", "off") in MAKERS


def test_exe_names_are_lowercase_exe_and_unique():
    seen = {}
    for name in GAMES:
        for exe in PROFILES[name].get("_exe", []):
            assert exe == exe.lower() and exe.endswith(".exe"), (name, exe)
            assert exe not in seen, f"{exe} in both {seen.get(exe)} and {name}"
            seen[exe] = name


def test_native_exe_list():
    native = PROFILES["_native_exe"]["list"]
    assert native
    for exe in native:
        assert exe == exe.lower() and exe.endswith(".exe")


def test_native_games_are_not_also_xbox_profiles():
    profile_exes = {e for g in GAMES for e in PROFILES[g].get("_exe", [])}
    assert not profile_exes & set(PROFILES["_native_exe"]["list"])


def test_unknown_preset_is_reported():
    with pytest.raises(SystemExit):
        resolve_profile({"g": {"preset": "nope"}, "_presets": {}}, "g")


def test_json_is_valid_utf8():
    with open(profiles_path(), encoding="utf-8") as f:
        json.load(f)
