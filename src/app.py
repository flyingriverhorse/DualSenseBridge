"""
DualSense Bridge — small window + tray icon.

Start: double-click the "DualSense Bridge" shortcut that setup.bat creates
       (or: .venv\\Scripts\\pythonw.exe app.py). Asks for administrator rights
       once per start, because HidHide needs them.
"""

import ctypes
import json
import os
import queue
import threading
import urllib.request
import webbrowser
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

FROZEN = getattr(sys, "frozen", False)            # running as the PyInstaller .exe
HERE = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
os.chdir(HERE)
if not FROZEN:
    sys.path.insert(0, HERE)

APP_NAME = "DualSense Bridge"
LOW_BATTERY = 15
DEFAULT_OUTPUT = "Windows default speakers"
SETTINGS_DIR = os.path.join(os.environ.get("APPDATA", HERE), "DualSenseBridge")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")
NO_WINDOW = 0x08000000


# ---------------------------------------------------------------- Windows plumbing

from version import __version__, REPO   # noqa: E402


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    parts = sys.argv[1:] if FROZEN else [os.path.abspath(__file__), *sys.argv[1:]]
    args = " ".join(f'"{a}"' for a in parts)
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, args, HERE, 1)
    return rc > 32


def single_instance():
    """False if another copy is already running."""
    ctypes.windll.kernel32.CreateMutexW(None, False, "DualSenseBridge_single_instance")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def message(text):
    ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x40)


def autostart_enabled():
    r = subprocess.run(["schtasks", "/query", "/tn", APP_NAME],
                       capture_output=True, creationflags=NO_WINDOW)
    return r.returncode == 0


def set_autostart(on):
    if on:
        if FROZEN:
            cmd = f'"{sys.executable}" --minimized'
        else:
            pythonw = sys.executable.replace("python.exe", "pythonw.exe")
            cmd = f'"{pythonw}" "{os.path.abspath(__file__)}" --minimized'
        args = ["schtasks", "/create", "/tn", APP_NAME, "/tr", cmd,
                "/sc", "onlogon", "/rl", "highest", "/f"]
    else:
        args = ["schtasks", "/delete", "/tn", APP_NAME, "/f"]
    return subprocess.run(args, capture_output=True, creationflags=NO_WINDOW).returncode == 0


def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(s):
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------- profiles

NAME_FIXES = {"gta": "GTA", "v": "V", "ea": "EA", "fc": "FC", "of": "of", "f": "f",
              "bioshock": "BioShock"}


def display_name(key):
    return " ".join(NAME_FIXES.get(w, w.capitalize()) for w in key.split("_"))


def load_profiles():
    from bridge_profiles import read_profiles, resolve_profile
    profiles = read_profiles()
    games = sorted((k for k in profiles if not k.startswith("_") and k != "off"), key=display_name)
    return profiles, games, resolve_profile


# ---------------------------------------------------------------- tray icon

def make_icon(color):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 18, 60, 50), radius=14, fill=color)
    d.ellipse((12, 26, 24, 38), fill=(255, 255, 255, 230))
    d.ellipse((40, 26, 52, 38), fill=(255, 255, 255, 230))
    return img


COLORS = {"off": (110, 120, 140, 255), "on": (40, 170, 90, 255), "none": (190, 70, 60, 255)}


# ---------------------------------------------------------------- window

class App:
    def __init__(self, root, engine, start_minimized):
        self.root, self.engine = root, engine
        self.settings = load_settings()
        self.q = queue.Queue()
        self.tray = None
        self.tray_state = None
        self.tray_tip_shown = False

        root.title(APP_NAME)
        for base in (getattr(sys, "_MEIPASS", HERE), os.path.dirname(HERE)):   # exe, or running from src/
            try:
                root.iconbitmap(os.path.join(base, "assets", "icon.ico"))
                break
            except Exception:
                pass
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        pad = {"padx": 12, "pady": 4}

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=6, pady=(6, 0))
        main = ttk.Frame(nb)
        opts = ttk.Frame(nb)
        nb.add(main, text="Controller")
        nb.add(opts, text="Settings")

        # controller status
        box = ttk.LabelFrame(main, text="Controller")
        box.pack(fill="x", **pad)
        self.lbl_conn = ttk.Label(box, text="Looking for DualSense…", font=("Segoe UI", 10, "bold"))
        self.lbl_conn.pack(anchor="w", padx=8, pady=(6, 0))
        self.lbl_batt = ttk.Label(box, text="")
        self.lbl_batt.pack(anchor="w", padx=8, pady=(0, 6))

        # xbox mode
        box = ttk.LabelFrame(main, text="Xbox mode")
        box.pack(fill="x", **pad)
        self.btn_xbox = tk.Button(box, text="", width=28, font=("Segoe UI", 11, "bold"),
                                  relief="flat", cursor="hand2", command=self.toggle_xbox)
        self.btn_xbox.pack(padx=8, pady=(8, 2))
        self.lbl_xbox = ttk.Label(box, text="", wraplength=360, justify="left")
        self.lbl_xbox.pack(anchor="w", padx=8, pady=(0, 8))

        # trigger profile
        box = ttk.LabelFrame(main, text="Trigger profile (experimental)")
        self.box_prof = box
        box.pack(fill="x", **pad)
        self.profiles, self.games, self.resolve = load_profiles()
        self.names = ["None (normal triggers)"] + [display_name(g) for g in self.games]
        self.name_to_key = {display_name(g): g for g in self.games}
        self.cmb = ttk.Combobox(box, values=self.names, width=40)
        self.cmb.pack(padx=8, pady=(8, 2))
        self.cmb.bind("<<ComboboxSelected>>", lambda e: self.choose_profile())
        self.cmb.bind("<KeyRelease>", self.filter_profiles)
        self.cmb.bind("<Return>", lambda e: self.choose_profile())
        self.lbl_prof = ttk.Label(box, text="", wraplength=360, justify="left")
        self.lbl_prof.pack(anchor="w", padx=8, pady=(0, 4))
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(row, text="Test trigger effects", command=self.engine.start_test).pack(side="left")
        ttk.Button(row, text="Open joy.cpl", command=lambda: os.startfile("joy.cpl")).pack(side="left", padx=6)

        # automatic switching per game
        box = ttk.LabelFrame(main, text="Per game")
        box.pack(fill="x", **pad)
        self.var_autogame = tk.BooleanVar(value=self.settings.get("auto_game", True))
        ttk.Checkbutton(box, text="Switch profile and Xbox mode automatically when a game starts",
                        variable=self.var_autogame, command=self.save_autogame).pack(anchor="w", padx=8, pady=(6, 0))
        self.lbl_game = ttk.Label(box, text="No game detected yet.", wraplength=440, justify="left")
        self.lbl_game.pack(anchor="w", padx=8, pady=(2, 2))
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=(0, 8))
        self.btn_remember = ttk.Button(row, text="Remember for this game", command=self.remember_game,
                                       state="disabled")
        self.btn_remember.pack(side="left")
        self.btn_forget = ttk.Button(row, text="Forget", command=self.forget_game, state="disabled")
        self.btn_forget.pack(side="left", padx=6)

        # live view
        box = ttk.LabelFrame(main, text="Live")
        box.pack(fill="x", **pad)
        grid = ttk.Frame(box)
        grid.pack(fill="x", padx=8, pady=6)
        ttk.Label(grid, text="L2").grid(row=0, column=0, sticky="w")
        self.bar_l2 = ttk.Progressbar(grid, length=300, maximum=255)
        self.bar_l2.grid(row=0, column=1, padx=6, pady=2)
        ttk.Label(grid, text="R2").grid(row=1, column=0, sticky="w")
        self.bar_r2 = ttk.Progressbar(grid, length=300, maximum=255)
        self.bar_r2.grid(row=1, column=1, padx=6, pady=2)
        self.lbl_live = ttk.Label(box, text="")
        self.lbl_live.pack(anchor="w", padx=8, pady=(0, 6))

        self.build_settings(opts, pad)

        # update notice + errors (below the tabs)
        self.frm_update = ttk.Frame(root)
        self.lbl_update = ttk.Label(self.frm_update, text="", foreground="#1f5fbf")
        self.lbl_update.pack(side="left")
        ttk.Button(self.frm_update, text="Download",
                   command=lambda: webbrowser.open(f"https://github.com/{REPO}/releases/latest")
                   ).pack(side="left", padx=6)
        self.lbl_err = ttk.Label(root, text="", foreground="#b03030", wraplength=380, justify="left")
        self.lbl_err.pack(anchor="w", padx=12, pady=(4, 10))
        self.battery_warned = False
        if self.settings.get("check_updates", True):
            threading.Thread(target=self.check_updates, daemon=True).start()

        # restore last session
        last = self.settings.get("profile")
        self.cmb.set(display_name(last) if last in self.games else self.names[0])
        self.choose_profile(save=False)
        self.engine.set_xbox(self.settings.get("xbox", False))

        from game_watch import GameWatcher, known_games
        self.known = known_games(self.profiles)
        self.native = {e.lower() for e in self.profiles.get("_native_exe", {}).get("list", [])}
        self.game = None                       # last game exe seen in the foreground
        self.watcher = GameWatcher(lambda exe: self.q.put(("game", exe)))
        self.watcher.start()

        self.start_tray()
        if start_minimized:
            root.withdraw()
        root.after(100, self.tick)

    # ------------------------------------------------ settings tab

    def build_settings(self, opts, pad):
        st = self.settings

        box = ttk.LabelFrame(opts, text="Light bar")
        box.pack(fill="x", **pad)
        self.var_light = tk.StringVar(value=st.get("light_mode", "auto"))
        for value, text in [("auto", "Automatic: green in Xbox mode, blue when off, red when the battery is low"),
                            ("custom", "My color"),
                            ("off", "Off")]:
            ttk.Radiobutton(box, text=text, value=value, variable=self.var_light,
                            command=self.apply_light).pack(anchor="w", padx=8, pady=1)
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=(4, 2))
        self.light_color = tuple(st.get("light_color", [255, 0, 180]))
        self.swatch = tk.Label(row, width=4, relief="solid", bd=1, bg=self.hex_color(self.light_color))
        self.swatch.pack(side="left")
        ttk.Button(row, text="Pick color…", command=self.pick_color).pack(side="left", padx=6)
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=(2, 8))
        ttk.Label(row, text="Brightness").pack(side="left")
        self.var_bright = tk.IntVar(value=st.get("brightness", 100))
        ttk.Scale(row, from_=5, to=100, variable=self.var_bright, length=220,
                  command=lambda v: self.apply_light()).pack(side="left", padx=6)

        box = ttk.LabelFrame(opts, text="Triggers")
        box.pack(fill="x", **pad)
        self.var_react = tk.BooleanVar(value=st.get("react", False))
        ttk.Checkbutton(box, text="Kick the triggers when the game rumbles (shots, hits)",
                        variable=self.var_react, command=self.apply_react).pack(anchor="w", padx=8, pady=(6, 0))
        ttk.Label(box, text="DualSense only, in Xbox mode. Works with or without a trigger profile.",
                  foreground="#666").pack(anchor="w", padx=26, pady=(0, 6))

        box = ttk.LabelFrame(opts, text="Sound to vibration (experimental)")
        box.pack(fill="x", **pad)
        self.var_audio = tk.BooleanVar(value=st.get("audio", False))
        ttk.Checkbutton(box, text="Feel the game's sound: bass → left motor, high sounds → right motor",
                        variable=self.var_audio, command=self.apply_audio).pack(anchor="w", padx=8, pady=(6, 0))
        ttk.Label(box, text="Xbox mode, USB or Bluetooth. Adds to the game's own rumble.",
                  foreground="#666").pack(anchor="w", padx=26)
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=(4, 0))
        ttk.Label(row, text="Feel it as", width=11).pack(side="left")
        self.var_ahd = tk.BooleanVar(value=st.get("audio_hd", True))
        ttk.Radiobutton(row, text="HD haptics (DualSense on USB)", value=True, variable=self.var_ahd,
                        command=self.apply_audio).pack(side="left", padx=(6, 0))
        ttk.Radiobutton(row, text="Rumble motors", value=False, variable=self.var_ahd,
                        command=self.apply_audio).pack(side="left", padx=6)
        ttk.Label(box, text="HD haptics fall back to the motors over Bluetooth.", foreground="#666"
                  ).pack(anchor="w", padx=26)
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=(4, 0))
        ttk.Label(row, text="Listen to", width=11).pack(side="left")
        self.var_adev = tk.StringVar(value=st.get("audio_device") or DEFAULT_OUTPUT)
        self.cmb_adev = ttk.Combobox(row, textvariable=self.var_adev, state="readonly", width=44)
        self.cmb_adev.pack(side="left", padx=6)
        self.cmb_adev.bind("<<ComboboxSelected>>", lambda e: self.apply_audio())
        ttk.Button(row, text="↻", width=3, command=self.refresh_outputs).pack(side="left")
        self.refresh_outputs()
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=(4, 0))
        ttk.Label(row, text="Strength", width=11).pack(side="left")
        self.var_astr = tk.IntVar(value=st.get("audio_strength", 100))
        ttk.Scale(row, from_=10, to=200, variable=self.var_astr, length=220,
                  command=lambda v: self.apply_audio()).pack(side="left", padx=6)
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=(2, 0))
        ttk.Label(row, text="Sensitivity", width=11).pack(side="left")
        self.var_asen = tk.IntVar(value=st.get("audio_sensitivity", 50))
        ttk.Scale(row, from_=0, to=100, variable=self.var_asen, length=220,
                  command=lambda v: self.apply_audio()).pack(side="left", padx=6)
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=(4, 0))
        ttk.Button(row, text="Test (plays a sound)", command=self.test_audio).pack(side="left")
        ttk.Label(row, text="Feel: 4 thumps on the left, 4 clicks on the right, then a sweep",
                  foreground="#666").pack(side="left", padx=6)
        self.lbl_audio = ttk.Label(box, text="", foreground="#666")
        self.lbl_audio.pack(anchor="w", padx=8, pady=(2, 6))

        box = ttk.LabelFrame(opts, text="App")
        box.pack(fill="x", **pad)
        self.var_auto = tk.BooleanVar(value=autostart_enabled())
        ttk.Checkbutton(box, text="Start with Windows (in the tray)", variable=self.var_auto,
                        command=self.toggle_autostart).pack(anchor="w", padx=8, pady=(6, 1))
        self.var_batt = tk.BooleanVar(value=st.get("battery_warning", True))
        ttk.Checkbutton(box, text=f"Warn me when the battery drops below {LOW_BATTERY}%",
                        variable=self.var_batt, command=self.save_opts).pack(anchor="w", padx=8, pady=1)
        self.var_upd = tk.BooleanVar(value=st.get("check_updates", True))
        ttk.Checkbutton(box, text="Check for updates when the app starts",
                        variable=self.var_upd, command=self.save_opts).pack(anchor="w", padx=8, pady=(1, 6))
        ttk.Label(opts, text=f"Version {__version__}", foreground="#888").pack(anchor="e", padx=12)

        self.apply_light(save=False)
        self.apply_react(save=False)
        self.apply_audio(save=False)

    @staticmethod
    def hex_color(rgb):
        return "#%02x%02x%02x" % tuple(rgb)

    def pick_color(self):
        from tkinter import colorchooser
        rgb, _ = colorchooser.askcolor(color=self.hex_color(self.light_color), title="Light bar color")
        if rgb:
            self.light_color = tuple(int(c) for c in rgb)
            self.swatch.config(bg=self.hex_color(self.light_color))
            self.var_light.set("custom")
            self.apply_light()

    def apply_light(self, save=True):
        self.engine.set_light(self.var_light.get(), self.light_color, self.var_bright.get())
        if save:
            self.settings.update(light_mode=self.var_light.get(), light_color=list(self.light_color),
                                 brightness=int(self.var_bright.get()))
            save_settings(self.settings)

    def apply_react(self, save=True):
        self.engine.set_react(self.var_react.get())
        if save:
            self.settings["react"] = self.var_react.get()
            save_settings(self.settings)

    def refresh_outputs(self):
        try:
            from audio_haptics import list_outputs
            names = list_outputs()
        except Exception:
            names = []
        self.cmb_adev["values"] = [DEFAULT_OUTPUT] + names

    def audio_device(self):
        v = self.var_adev.get()
        return None if v in ("", DEFAULT_OUTPUT) else v

    def apply_audio(self, save=True):
        self.engine.set_audio(self.var_audio.get(), int(self.var_astr.get()), int(self.var_asen.get()),
                              self.audio_device(), self.var_ahd.get())
        if save:
            self.settings.update(audio=self.var_audio.get(), audio_strength=int(self.var_astr.get()),
                                 audio_sensitivity=int(self.var_asen.get()),
                                 audio_device=self.audio_device(), audio_hd=self.var_ahd.get())
            save_settings(self.settings)

    def test_audio(self):
        threading.Thread(target=self.engine.start_audio_test,
                         args=(int(self.var_astr.get()), int(self.var_asen.get())), daemon=True).start()

    def save_opts(self):
        self.settings.update(battery_warning=self.var_batt.get(), check_updates=self.var_upd.get())
        save_settings(self.settings)

    def check_updates(self):
        """Background thread: compare with the latest GitHub release."""
        try:
            req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest",
                                         headers={"User-Agent": "DualSenseBridge"})
            with urllib.request.urlopen(req, timeout=8) as r:
                tag = json.load(r).get("tag_name", "")
        except Exception:
            return

        def parts(v):
            return tuple(int(x) for x in v.lstrip("v").split("-")[0].split(".") if x.isdigit())

        if tag and parts(tag) > parts(__version__):
            self.q.put(("update", tag))

    def check_battery(self, s):
        level, charging = s["battery"], s["charging"]
        if level is None:
            return
        if charging != "no" or level > LOW_BATTERY + 5:
            self.battery_warned = False
        elif level <= LOW_BATTERY and not self.battery_warned and self.var_batt.get():
            self.battery_warned = True
            if self.tray is not None:
                try:
                    self.tray.notify(f"Controller battery is at {level}%. Time to charge it.", APP_NAME)
                except Exception:
                    pass

    # ------------------------------------------------ actions

    def toggle_xbox(self):
        on = not self.engine.want_xbox
        self.engine.set_xbox(on)
        self.settings["xbox"] = on
        save_settings(self.settings)

    def filter_profiles(self, event):
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            return
        text = self.cmb.get().lower()
        self.cmb["values"] = [n for n in self.names if text in n.lower()] or self.names

    def choose_profile(self, save=True):
        name = self.cmb.get()
        key = self.name_to_key.get(name)
        self.cmb["values"] = self.names
        if key is None:
            self.cmb.set(self.names[0])
            self.engine.set_profile(None, None, None)
            self.lbl_prof.config(text="Triggers behave normally.")
        else:
            from output import effect_from_dict
            p = self.resolve(self.profiles, key)
            self.engine.set_profile(key, effect_from_dict(p["L2"]), effect_from_dict(p["R2"]))
            entry = self.profiles[key]
            preset = self.profiles.get("_presets", {}).get(entry.get("preset"), {})
            lines = [entry.get("_controls", "")]
            if preset.get("_feel"):
                lines.append("Feel: " + preset["_feel"])
            if entry.get("_native_dualsense"):
                lines.append("This game supports DualSense natively: for its own effects, "
                             "turn Xbox mode off and play over USB.")
            self.lbl_prof.config(text="\n".join(l for l in lines if l))
        if save:
            self.settings["profile"] = key
            save_settings(self.settings)

    # ------------------------------------------------ per game

    def game_rule(self, exe):
        """(source, profile key or None, xbox on?) for this exe, or None if unknown."""
        mine = self.settings.get("games", {}).get(exe)
        if mine:
            return "yours", mine.get("profile"), mine.get("xbox", True)
        if exe in self.native:
            return "native DualSense game", None, False
        if exe in self.known:
            return "built-in", self.known[exe], True
        return None

    def on_game(self, exe):
        self.game = exe
        self.btn_remember.config(state="normal")
        rule = self.game_rule(exe)
        self.btn_forget.config(state="normal" if exe in self.settings.get("games", {}) else "disabled")
        if rule is None:
            self.lbl_game.config(text=f"Game: {exe} (not set up). Pick a profile and Xbox mode, "
                                      f"then press \"Remember for this game\".")
            return
        source, key, xbox = rule
        if self.var_autogame.get():
            self.cmb.set(display_name(key) if key in self.games else self.names[0])
            self.choose_profile()
            if self.engine.want_xbox != xbox:
                self.toggle_xbox()
        prof = display_name(key) if key in self.games else "no profile"
        mode = "Xbox mode on" if xbox else "Xbox mode off"
        state = "applied" if self.var_autogame.get() else "auto-switch is off"
        self.lbl_game.config(text=f"Game: {exe} → {prof}, {mode} ({source}, {state})")

    def remember_game(self):
        if not self.game:
            return
        key = self.name_to_key.get(self.cmb.get())
        self.settings.setdefault("games", {})[self.game] = {"profile": key, "xbox": bool(self.engine.want_xbox)}
        save_settings(self.settings)
        self.on_game(self.game)

    def forget_game(self):
        if self.game and self.game in self.settings.get("games", {}):
            del self.settings["games"][self.game]
            save_settings(self.settings)
            self.on_game(self.game)

    def save_autogame(self):
        self.settings["auto_game"] = self.var_autogame.get()
        save_settings(self.settings)
        if self.game:
            self.on_game(self.game)

    def toggle_autostart(self):
        if not set_autostart(self.var_auto.get()):
            self.var_auto.set(autostart_enabled())

    # ------------------------------------------------ tray

    def start_tray(self):
        try:
            import pystray
        except Exception:
            return
        menu = pystray.Menu(
            pystray.MenuItem("Show window", lambda i, it: self.q.put("show"), default=True),
            pystray.MenuItem("Xbox mode", lambda i, it: self.q.put("toggle"),
                             checked=lambda it: self.engine.want_xbox),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda i, it: self.q.put("quit")),
        )
        self.tray = pystray.Icon("DualSenseBridge", make_icon(COLORS["off"]), APP_NAME, menu)
        self.tray.run_detached()

    def hide_to_tray(self):
        if self.tray is None:
            self.quit()
            return
        self.root.withdraw()
        if not self.tray_tip_shown:
            self.tray_tip_shown = True
            try:
                self.tray.notify("Still running in the tray. Right-click the icon to quit.", APP_NAME)
            except Exception:
                pass

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def quit(self):
        self.watcher.stop()
        self.engine.shutdown()
        self.engine.join(timeout=3)
        if self.tray is not None:
            self.tray.stop()
        self.root.destroy()

    # ------------------------------------------------ refresh

    def tick(self):
        while not self.q.empty():
            cmd = self.q.get()
            if isinstance(cmd, tuple) and cmd[0] == "game":
                self.on_game(cmd[1])
                continue
            if isinstance(cmd, tuple) and cmd[0] == "update":
                self.lbl_update.config(text=f"New version {cmd[1]} is available.")
                self.frm_update.pack(anchor="w", padx=12, pady=(4, 0), before=self.lbl_err)
                continue
            if cmd == "show":
                self.show()
            elif cmd == "toggle":
                self.toggle_xbox()
            elif cmd == "quit":
                self.quit()
                return

        s = self.engine.snapshot()
        if s["connected"]:
            self.lbl_conn.config(text=f"● {s['name']} · {s['mode'] or '…'}", foreground="#1f7a3f")
            if s["battery"] is not None:
                self.lbl_batt.config(text=f"Battery {s['battery']}% ({s['charging']})")
            self.check_battery(s)
        else:
            self.lbl_conn.config(text="○ No controller — plug in a DualSense or connect it over Bluetooth",
                                 foreground="#a04030")
            self.lbl_batt.config(text="")
        ds4 = s["model"] == "ds4"
        self.box_prof.config(text="Trigger profile (needs a DualSense)" if ds4
                             else "Trigger profile (experimental)")

        want = self.engine.want_xbox
        if want and s["xbox"]:
            self.btn_xbox.config(text="ON — click to turn off", bg="#2aa05a", fg="white",
                                 activebackground="#23874c")
            hidden = "DualSense hidden from games." if s["hidden"] else "Warning: DualSense NOT hidden."
            self.lbl_xbox.config(text=f"Games see an Xbox 360 controller. {hidden}")
        elif want:
            self.btn_xbox.config(text="Starting… (waiting for controller)", bg="#c9a227", fg="white",
                                 activebackground="#b08d1f")
            self.lbl_xbox.config(text="Turns on as soon as the DualSense is connected.")
        else:
            self.btn_xbox.config(text="OFF — click to turn on", bg="#6e788c", fg="white",
                                 activebackground="#5c6475")
            self.lbl_xbox.config(text="Games see the DualSense as it is. Use this for games "
                                      "with native DualSense support.")

        self.bar_l2["value"] = s["L2"]
        self.bar_r2["value"] = s["R2"]
        live = f"Rumble {s['rumble'][0]} / {s['rumble'][1]}" + ("   ⚡ trigger kick" if s["kick"] else "")
        if s.get("audio") is not None:
            live += f"   ♪ sound {s['audio'][0]} / {s['audio'][1]}"
        if self.var_audio.get() or s.get("audio_error") or s["test"].startswith("Sound test"):
            msg = s.get("audio_error") or (f"Listening to: {s['audio_device']}" if s.get("audio_device") else "Starting…")
            if s.get("audio_mode") and not s.get("audio_error"):
                msg += f"  →  {s['audio_mode']}"
            if not s["xbox"] and not s["test"]:
                msg += "  (active when Xbox mode is on)"
            self.lbl_audio.config(text=msg)
        else:
            self.lbl_audio.config(text="")
        if s["test"]:
            live = f"Testing: {s['test']} — press L2 and R2"
        self.lbl_live.config(text=live)
        self.lbl_err.config(text=s["error"])

        if self.tray is not None:
            state = "none" if not s["connected"] else ("on" if s["xbox"] else "off")
            if state != self.tray_state:
                self.tray_state = state
                self.tray.icon = make_icon(COLORS[state])
                tips = {"none": "no controller", "on": "Xbox mode ON", "off": "Xbox mode OFF"}
                self.tray.title = f"{APP_NAME} — {tips[state]}"
                self.tray.update_menu()

        self.root.after(100, self.tick)


def main():
    if not is_admin():
        if not relaunch_as_admin():
            message("DualSense Bridge needs administrator rights to hide the controller with HidHide.")
        return
    if not single_instance():
        message("DualSense Bridge is already running (look for it in the tray).")
        return

    from engine import Engine
    engine = Engine()
    engine.start()
    root = tk.Tk()
    App(root, engine, start_minimized="--minimized" in sys.argv)
    root.mainloop()


if __name__ == "__main__":
    main()
