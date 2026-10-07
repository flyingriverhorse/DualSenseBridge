"""Takes the README screenshots and the demo GIF frames of the real window on Windows.
Uses a demo engine with fixed values, so it needs no controller and changes nothing.
Run: .venv\\Scripts\\python.exe scripts\\screenshots.py   → docs\\*.png, docs\\demo.gif"""
import ctypes
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)     # real pixel coordinates
except Exception:
    pass

from PIL import ImageGrab  # noqa: E402

import app  # noqa: E402

app.SETTINGS_FILE = os.path.join(os.environ.get("TEMP", "."), "dsb_screenshot_settings.json")
app.autostart_enabled = lambda: False
app.set_autostart = lambda on: True
try:
    os.remove(app.SETTINGS_FILE)
except OSError:
    pass
import json  # noqa: E402
with open(app.SETTINGS_FILE, "w") as f:
    json.dump({"profile": "silent_hill_f", "xbox": True, "audio": True, "audio_hd": True,
               "react": True, "check_updates": False,
               "audio_device": "SteelSeries Sonar - Gaming (SteelSeries Sonar Virtual Audio Device)",
               "games": {"shf-win64-shipping.exe": {"profile": "silent_hill_f", "xbox": True}}}, f)
import game_watch  # noqa: E402
game_watch.foreground_exe = lambda: None


class DemoEngine:
    want_xbox = True

    def __init__(self):
        self.t = 0.0
        self.still = True          # fixed, good-looking values for the screenshots

    def set_xbox(self, on): self.want_xbox = on
    def set_profile(self, *a): pass
    def set_light(self, *a): pass
    def set_react(self, on): pass
    def set_audio(self, *a): pass
    def start_test(self): pass
    def start_audio_test(self, *a): pass
    def shutdown(self): pass
    def join(self, timeout=None): pass

    def snapshot(self):
        t = self.t
        if self.still:
            l2, r2, rumble = 96, 214, (148, 64)
        else:
            l2 = int(255 * max(0, math.sin(t * 1.3)) ** 2)
            r2 = int(255 * max(0, math.sin(t * 1.3 + 2.2)) ** 2)
            rumble = (int(180 * max(0, math.sin(t * 2.0))), int(90 * max(0, math.sin(t * 3.1 + 1))))
        return {"connected": True, "name": "DualSense", "model": "dualsense", "mode": "USB",
                "battery": 85, "charging": "charging", "xbox": self.want_xbox, "hidden": True,
                "L2": l2, "R2": r2, "rumble": rumble, "test": "", "error": "", "vigem": True,
                "kick": r2 > 200, "audio": None, "audio_error": "",
                "audio_device": "SteelSeries Sonar - Gaming (SteelSeries Sonar Virtual Audio Device)",
                "audio_mode": "HD haptics"}


def grab(root, path):
    root.update()
    time.sleep(0.25)
    root.update()
    import ctypes.wintypes as wt
    hwnd = int(root.wm_frame(), 16)
    rect = wt.RECT()
    # the visible window, without the invisible resize border Windows adds around it
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True)
    img.save(path)
    return img


def main():
    import tkinter as tk
    os.makedirs(DOCS, exist_ok=True)
    root = tk.Tk()
    root.attributes("-topmost", True)
    engine = DemoEngine()
    a = app.App(root, engine, False)
    a.tray and a.tray.stop()
    a.on_game("shf-win64-shipping.exe")
    root.geometry("+80+80")
    nb = root.winfo_children()[0]

    for _ in range(5):
        root.update()
        time.sleep(0.1)
    a.tick()
    nb.select(0)
    grab(root, os.path.join(DOCS, "screenshot-controller.png"))
    nb.select(1)
    grab(root, os.path.join(DOCS, "screenshot-settings.png"))

    # demo GIF: Controller tab with moving triggers and rumble
    nb.select(0)
    engine.still = False
    frames = []
    for i in range(48):
        engine.t = i * 0.13
        a.tick()
        frames.append(grab(root, os.path.join(os.environ.get("TEMP", "."), "dsb_frame.png")).convert("P", palette=1, colors=128))
    frames[0].save(os.path.join(DOCS, "demo.gif"), save_all=True, append_images=frames[1:], duration=90, loop=0, optimize=True)
    root.destroy()
    print("saved docs/screenshot-controller.png, docs/screenshot-settings.png, docs/demo.gif")


main()
sys.stdout.flush()
os._exit(0)      # the tray icon thread would otherwise keep the process alive
