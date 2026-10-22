"""Profile editor logic and the engine's live preview."""

import json

import pytest

import output
import profile_editor as pe
from bridge_profiles import read_profiles, resolve_profile


@pytest.mark.parametrize("mode", pe.MODES)
def test_defaults_build_and_draw(mode):
    d = pe.defaults(mode)
    assert d["mode"] == mode
    assert len(pe.to_bytes(d)) == 11
    assert len(pe.zone_view(d)) == 10


def test_ranges_cover_every_parameter_of_output_py():
    import inspect
    for mode, params in pe.RANGES.items():
        assert [n for n, _, _ in params] == list(inspect.signature(output.MAKERS[mode]).parameters)


def test_every_shipped_profile_survives_the_editor_unchanged():
    p = read_profiles()
    for key in [k for k in p if not k.startswith("_")]:
        for side, d in resolve_profile(p, key).items():
            assert pe.to_bytes(d) == output.effect_from_dict(d), (key, side)


def test_normalize_clamps_and_fills():
    assert pe.normalize({"mode": "feedback", "start": 99}) == {"mode": "feedback", "start": 9, "strength": 4}
    assert pe.normalize({"mode": "laser"}) == {"mode": "off"}
    assert pe.normalize(None) == {"mode": "off"}
    assert pe.normalize({"mode": "multi", "strengths": [9, -1]})["strengths"] == [8, 0] + [0] * 8
    assert pe.normalize({"mode": "weapon", "start": "x"})["start"] == 4


def test_zone_view():
    assert pe.zone_view({"mode": "feedback", "start": 7, "strength": 5}) == \
        [(0, "")] * 7 + [(5, "resist")] * 3
    w = pe.zone_view({"mode": "weapon", "start": 2, "end": 4, "strength": 6})
    assert w[2] == w[3] == (6, "resist") and w[4] == (6, "snap") and w[5] == (0, "")
    assert all(k == "vibrate" for _, k in pe.zone_view({"mode": "vibration", "start": 0}))


@pytest.mark.parametrize("value, zone", [(0, 0), (25, 0), (26, 1), (128, 5), (255, 9)])
def test_zone_of(value, zone):
    assert pe.zone_of(value) == zone


def test_slug():
    assert pe.slug("  My Gun!! v2 ") == "my_my_gun_v2"
    assert pe.slug("???") == "my_profile"


def test_save_load_delete(tmp_path):
    path = str(tmp_path / "sub" / "my_profiles.json")
    assert pe.load_user(path) == {}
    key = pe.save_user(path, "Heavy Pull", {"mode": "feedback", "start": 2, "strength": 7}, None)
    got = pe.load_user(path)
    assert key == "my_heavy_pull" and got[key]["_name"] == "Heavy Pull" and got[key]["_user"]
    assert got[key]["R2"] == {"mode": "off"}
    # replace keeps one entry
    pe.save_user(path, "heavy pull", {"mode": "off"}, {"mode": "off"})
    assert list(pe.load_user(path)) == [key]
    assert "_user" not in json.load(open(path))[key]        # the flag is not written to disk
    assert pe.delete_user(path, key) and pe.load_user(path) == {}
    assert not pe.delete_user(path, key)


def test_broken_user_file_is_ignored(tmp_path):
    path = tmp_path / "my_profiles.json"
    path.write_text("{not json")
    assert pe.load_user(str(path)) == {}
    path.write_text(json.dumps({"alan_wake_2": {"L2": {}}, "my_ok": {"L2": {"mode": "feedback"}}}))
    assert list(pe.load_user(str(path))) == ["my_ok"]       # cannot shadow built-in profiles


def test_user_profiles_resolve_like_built_in_ones(tmp_path):
    path = str(tmp_path / "p.json")
    key = pe.save_user(path, "x", {"mode": "feedback", "start": 1, "strength": 2}, {"mode": "off"})
    merged = pe.merge(read_profiles(), pe.load_user(path))
    r = resolve_profile(merged, key)
    assert output.effect_from_dict(r["L2"]) == output.effect_feedback(1, 2)
    assert key not in read_profiles()                       # built-in dict untouched


def test_share_json():
    d = json.loads(pe.share_json("My Gun", {"mode": "feedback"}, None))
    assert d == {"my_gun": {"_controls": "", "L2": {"mode": "feedback", "start": 3, "strength": 4},
                            "R2": {"mode": "off"}}}


# ---------------------------------------------------------------- engine preview

class FakeDevice:
    def __init__(self):
        self.written = []

    def write(self, data):
        self.written.append(bytes(data))


@pytest.fixture
def e():
    import engine
    x = engine.Engine()
    x._info = {"model": "dualsense", "path": b"p"}
    x._device = FakeDevice()
    return x


def test_preview_works_with_xbox_mode_off(e):
    l2, r2 = output.effect_feedback(1, 8), output.effect_weapon()
    e.set_preview(l2, r2)
    assert e._triggers(0) == (l2, r2, "Profile editor preview")


def test_preview_beats_the_game_profile(e):
    e._pad = object()
    e.set_profile("g", output.effect_off(), output.effect_off())
    e.set_preview(output.effect_feedback(), output.effect_feedback())
    assert e._triggers(0)[0] == output.effect_feedback()


def test_clearing_the_preview_gives_the_triggers_back(e):
    e.set_preview(output.effect_feedback(), output.effect_feedback())
    e._send_output(bluetooth=False)
    e.clear_preview()
    assert e._triggers(0)[:2] == (output.effect_off(), output.effect_off())
    e._send_output(bluetooth=False)
    assert e._triggers(0) == (None, None, "")                # handed back to native games once


# ---------------------------------------------------------------- new games

def test_exe_list():
    assert pe.exe_list(r"C:\Games\My Game\Game-Win64.EXE, other ; other.exe") == ["game-win64.exe", "other.exe"]
    assert pe.exe_list(["x", "", "X.exe"]) == ["x.exe"]
    assert pe.exe_list("") == []


def test_a_new_game_gets_its_own_profile(tmp_path):
    path = str(tmp_path / "p.json")
    key = pe.save_user(path, "Indie Shooter", {"mode": "feedback"}, {"mode": "weapon"},
                       exes=r"D:\Steam\common\Indie\IndieShooter.exe")
    merged = pe.merge(read_profiles(), pe.load_user(path))
    assert pe.user_games(merged) == {"indieshooter.exe": key}
    import game_watch
    assert game_watch.known_games(merged)["indieshooter.exe"] == key


def test_your_profile_can_take_over_a_built_in_game(tmp_path):
    path = str(tmp_path / "p.json")
    built_in = read_profiles()["alan_wake_2"]["_exe"][0]
    key = pe.save_user(path, "AW2 heavier", None, {"mode": "feedback", "strength": 8}, exes=[built_in])
    merged = pe.merge(read_profiles(), pe.load_user(path))
    import game_watch
    assert game_watch.known_games(merged)[built_in] == key


def test_one_exe_belongs_to_one_of_your_profiles(tmp_path):
    path = str(tmp_path / "p.json")
    a = pe.save_user(path, "A", None, None, exes=["game.exe", "launcher.exe"])
    b = pe.save_user(path, "B", None, None, exes=["game.exe"])
    got = pe.load_user(path)
    assert got[a]["_exe"] == ["launcher.exe"] and got[b]["_exe"] == ["game.exe"]
    pe.save_user(path, "C", None, None, exes=["launcher.exe"])
    assert "_exe" not in pe.load_user(path)[a]


def test_share_json_with_exe():
    d = json.loads(pe.share_json("X", None, None, ["X.EXE"]))
    assert d["x"]["_exe"] == ["x.exe"]
