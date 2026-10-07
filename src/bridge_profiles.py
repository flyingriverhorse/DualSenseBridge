"""Reading trigger profiles from profiles.json (shared by bridge.py and app.py)."""

import json
import os
import sys


def profiles_path():
    """Next to the .exe (editable) if present, else the copy bundled inside it, else next to this file."""
    if getattr(sys, "frozen", False):
        beside = os.path.join(os.path.dirname(sys.executable), "profiles.json")
        if os.path.exists(beside):
            return beside
        return os.path.join(sys._MEIPASS, "profiles.json")
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "profiles.json"))


def read_profiles():
    path = profiles_path()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def resolve_profile(profiles, name):
    """Game entry + its preset → {"L2": {...}, "R2": {...}}."""
    entry = profiles[name]
    presets = profiles.get("_presets", {})
    base = presets.get(entry.get("preset"), {}) if entry.get("preset") else {}
    if entry.get("preset") and not base:
        sys.exit(f"Profile '{name}' uses unknown preset '{entry['preset']}'")
    return {"L2": entry.get("L2", base.get("L2")), "R2": entry.get("R2", base.get("R2"))}
