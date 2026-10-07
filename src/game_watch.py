"""
Automatic game detection — watches which program is in the foreground.

Every 2 seconds it asks Windows for the foreground window's process and reports
its .exe name when it changes. The app then looks the name up:
  1. games the user set up with "Remember for this game" (settings.json), then
  2. the "_exe" lists in profiles.json,
and switches the trigger profile and Xbox mode. Desktop, the app itself, launchers
and other non-game programs are ignored, so alt-tabbing does not undo anything.
"""

import ctypes
import os
import threading
import time

POLL_SECONDS = 2.0

# Never treated as a game (lower case)
IGNORE = {
    "explorer.exe", "dualsensebridge.exe", "python.exe", "pythonw.exe", "searchhost.exe",
    "shellexperiencehost.exe", "startmenuexperiencehost.exe", "taskmgr.exe", "applicationframehost.exe",
    "lockapp.exe", "textinputhost.exe", "systemsettings.exe", "cmd.exe", "powershell.exe",
    "windowsterminal.exe", "conhost.exe", "steam.exe", "steamwebhelper.exe", "epicgameslauncher.exe",
    "eadesktop.exe", "galaxyclient.exe", "battle.net.exe", "ubisoftconnect.exe", "xboxpcapp.exe",
    "gamebar.exe", "discord.exe", "chrome.exe", "msedge.exe", "firefox.exe", "code.exe", "claude.exe",
    "nvidia overlay.exe", "nvcontainer.exe", "obs64.exe", "spotify.exe", "sonar.exe",
    "steelseriesgg.exe", "steelseriesggclient.exe",
}


def foreground_exe():
    """Lower-case .exe name of the program owning the foreground window, or None."""
    try:
        user32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = k32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            buf = ctypes.create_unicode_buffer(1024)
            n = ctypes.c_ulong(len(buf))
            if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                return None
            return os.path.basename(buf.value).lower()
        finally:
            k32.CloseHandle(h)
    except Exception:
        return None


class GameWatcher(threading.Thread):
    """Calls on_change(exe) from its own thread whenever a new non-ignored program
    comes to the foreground."""

    def __init__(self, on_change):
        super().__init__(daemon=True)
        self.on_change = on_change
        self.current = None
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        while self._running:
            exe = foreground_exe()
            if exe and exe not in IGNORE and exe != self.current:
                self.current = exe
                try:
                    self.on_change(exe)
                except Exception:
                    pass
            time.sleep(POLL_SECONDS)


def known_games(profiles):
    """{exe: profile key} from the "_exe" lists in profiles.json."""
    table = {}
    for key, entry in profiles.items():
        if key.startswith("_") or not isinstance(entry, dict):
            continue
        for exe in entry.get("_exe", []):
            table[exe.lower()] = key
    return table
