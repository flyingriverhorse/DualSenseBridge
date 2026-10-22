"""Profile editor logic (no UI): parameter ranges per trigger mode, a per-zone
picture of an effect, and the user's own profiles in %APPDATA%.

The UI lives in editor_tab.py; this module is kept free of tkinter so it can be tested.
"""

import inspect
import json
import os
import re

import output

# (name, low, high) per parameter, in the order shown. Defaults come from output.py.
RANGES = {
    "feedback": [("start", 0, 9), ("strength", 1, 8)],
    "weapon": [("start", 2, 7), ("end", 3, 8), ("strength", 1, 8)],
    "slope": [("start", 0, 8), ("end", 1, 9), ("start_strength", 1, 8), ("end_strength", 1, 8)],
    "bow": [("start", 0, 7), ("end", 1, 8), ("strength", 1, 8), ("snap", 1, 8)],
    "vibration": [("start", 0, 9), ("amplitude", 1, 8), ("frequency", 1, 60)],
    "machine": [("start", 0, 8), ("end", 1, 9), ("amplitude_a", 0, 7), ("amplitude_b", 0, 7),
                ("frequency", 1, 60), ("period", 0, 20)],
    "galloping": [("start", 0, 8), ("end", 1, 9), ("first_foot", 0, 6), ("second_foot", 1, 7),
                  ("frequency", 1, 20)],
}
MODES = ["off", "feedback", "weapon", "slope", "multi", "bow", "vibration", "machine", "galloping"]
MODE_HELP = {
    "off": "No effect: the trigger moves freely.",
    "feedback": "Even resistance from a zone to the end.",
    "weapon": "Resistance between two zones, then it breaks like a gun trigger.",
    "slope": "Resistance that grows (or fades) between two zones.",
    "multi": "Your own resistance for each of the 10 zones.",
    "bow": "Tension builds, then the trigger snaps back.",
    "vibration": "The trigger buzzes from a zone on.",
    "machine": "Buzz that alternates between two strengths.",
    "galloping": "Two-beat pulse, like hooves.",
}
LABELS = {
    "start": "Start zone", "end": "End zone", "strength": "Strength", "snap": "Snap force",
    "start_strength": "Strength at start", "end_strength": "Strength at end",
    "amplitude": "Strength", "frequency": "Speed (Hz)", "amplitude_a": "Strength A",
    "amplitude_b": "Strength B", "period": "Switch every (1/10 s)",
    "first_foot": "First beat", "second_foot": "Second beat",
}
USER_PREFIX = "my_"


def defaults(mode):
    """{"mode": ..., param: default} using output.py's own default values."""
    if mode == "multi":
        return {"mode": "multi", "strengths": [0, 0, 1, 2, 3, 4, 5, 6, 6, 6]}
    if mode == "off" or mode not in RANGES:
        return {"mode": "off"}
    sig = inspect.signature(output.MAKERS[mode]).parameters
    return {"mode": mode, **{name: sig[name].default for name, _, _ in RANGES[mode]}}


def normalize(d):
    """A profile side as the editor holds it: known mode, every parameter present and in range."""
    d = dict(d or {})
    mode = d.get("mode", "off")
    if mode not in MODES:
        mode = "off"
    base = defaults(mode)
    if mode == "multi":
        s = [int(x) for x in (list(d.get("strengths", base["strengths"])) + [0] * 10)[:10]]
        return {"mode": "multi", "strengths": [max(0, min(8, x)) for x in s]}
    for name, lo, hi in RANGES.get(mode, []):
        try:
            v = int(d.get(name, base[name]))
        except (TypeError, ValueError):
            v = base[name]
        base[name] = max(lo, min(hi, v))
    return base


def to_bytes(d):
    return output.effect_from_dict(normalize(d))


# ---------------------------------------------------------------- picture

def zone_view(d):
    """10 (strength 0–8, kind) pairs; kind is 'resist', 'vibrate', 'snap' or ''."""
    d = normalize(d)
    mode = d["mode"]
    view = [(0, "")] * 10
    if mode == "multi":
        return [(s, "resist" if s else "") for s in d["strengths"]]
    if mode in ("feedback", "vibration"):
        s = d.get("strength", d.get("amplitude"))
        kind = "resist" if mode == "feedback" else "vibrate"
        return [(s, kind) if z >= d["start"] else (0, "") for z in range(10)]
    start, end = d.get("start", 0), max(d.get("end", 9), d.get("start", 0) + 1)
    if mode == "slope":
        a, b = d["start_strength"], d["end_strength"]
        return [(round(a + (b - a) * min(1.0, (z - start) / (end - start))), "resist") if z >= start
                else (0, "") for z in range(10)]
    if mode in ("weapon", "bow"):
        s = d["strength"]
        view = [(s, "resist") if start <= z < end else (0, "") for z in range(10)]
        view[min(end, 9)] = (d["snap"] if mode == "bow" else s, "snap")
        return view
    if mode in ("machine", "galloping"):
        s = max(d.get("amplitude_a", 0), d.get("amplitude_b", 0), 1) + 1 if mode == "machine" else 4
        return [(min(s, 8), "vibrate") if start <= z <= end else (0, "") for z in range(10)]
    return view


def zone_of(value):
    """Trigger position 0–255 → zone 0–9."""
    return max(0, min(9, int(value) * 10 // 256))


# ---------------------------------------------------------------- user profiles

def slug(name):
    s = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return USER_PREFIX + (s or "profile")


def exe_list(text):
    """'C:\\Games\\Foo.exe, bar.EXE' → ['foo.exe', 'bar.exe'] (file names only, no duplicates)."""
    items = text if isinstance(text, (list, tuple)) else re.split(r"[,;\n]", text or "")
    out = []
    for item in items:
        name = os.path.basename(str(item).strip().replace("\\", "/")).lower()
        if name and not name.endswith(".exe"):
            name += ".exe"
        if name and name != ".exe" and name not in out:
            out.append(name)
    return out


def load_user(path):
    """{key: entry} from my_profiles.json; missing or broken file → {}."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for key, e in data.items():
        if key.startswith(USER_PREFIX) and isinstance(e, dict):
            out[key] = {"_name": str(e.get("_name") or key[len(USER_PREFIX):]), "_user": True,
                        "_controls": e.get("_controls", "Your profile"),
                        "L2": normalize(e.get("L2")), "R2": normalize(e.get("R2"))}
            exes = exe_list(e.get("_exe", []))
            if exes:
                out[key]["_exe"] = exes
    return out


def save_user(path, name, l2, r2, controls="", exes=None):
    """Adds or replaces a profile; returns its key. `exes`: the game's .exe names, so the
    profile switches on by itself when that game comes to the front."""
    data = load_user(path)
    key = slug(name)
    exes = exe_list(exes or [])
    for other in data.values():                       # one game → one of your profiles
        if other.get("_exe"):
            other["_exe"] = [x for x in other["_exe"] if x not in exes]
            if not other["_exe"]:
                del other["_exe"]
    data[key] = {"_name": name.strip() or key, "_controls": controls or "Your profile",
                 "L2": normalize(l2), "R2": normalize(r2)}
    if exes:
        data[key]["_exe"] = exes
    _write(path, data)
    return key


def delete_user(path, key):
    data = load_user(path)
    if data.pop(key, None) is not None:
        _write(path, data)
        return True
    return False


def _write(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    clean = {k: {kk: v for kk, v in e.items() if kk != "_user"} for k, e in data.items()}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2)
    os.replace(tmp, path)


def merge(profiles, user):
    """Built-in profiles plus the user's, without changing the built-in dict."""
    merged = dict(profiles)
    merged.update(user)
    return merged


def share_json(name, l2, r2, exes=None):
    """A profiles.json entry people can paste into an issue or the file."""
    entry = {"_controls": "", "L2": normalize(l2), "R2": normalize(r2)}
    if exe_list(exes or []):
        entry["_exe"] = exe_list(exes)
    return json.dumps({slug(name)[len(USER_PREFIX):]: entry}, indent=2)


def user_games(profiles):
    """{exe: key} for the user's own profiles (these win over built-in and native lists)."""
    return {exe: k for k, e in profiles.items()
            if isinstance(e, dict) and e.get("_user") for exe in e.get("_exe", [])}
