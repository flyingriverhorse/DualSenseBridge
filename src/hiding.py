"""
Hiding the real DualSense from games with HidHide — stage 3
The bridge turns hiding on when it starts and off when it exits.
HidHideCLI needs administrator rights.
"""

import ctypes
import os
import subprocess
import sys

CLI_PATHS = [
    r"C:\Program Files\Nefarius Software Solutions\HidHide\x64\HidHideCLI.exe",
    r"C:\Program Files\Nefarius Software Solutions e.U\HidHide\x64\HidHideCLI.exe",
    r"C:\Program Files\Nefarius Software Solutions\HidHide\HidHideCLI.exe",
]


def find_cli():
    for path in CLI_PATHS:
        if os.path.exists(path):
            return path
    return None


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _cli(cli, *args):
    result = subprocess.run([cli, *args], capture_output=True, text=True,
                            creationflags=0x08000000)  # CREATE_NO_WINDOW: no console flash in the .exe
    if result.returncode != 0:
        raise RuntimeError(f"HidHideCLI {' '.join(args)} failed: "
                           f"{(result.stderr or result.stdout).strip()}")
    return result.stdout


def real_exe_path():
    """A venv's python.exe is a redirector that launches the real interpreter;
    the process that opens the HID device is the real one, so that is what
    goes on the HidHide allow list."""
    try:
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, os.getpid())  # PROCESS_QUERY_LIMITED_INFORMATION
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.c_ulong(len(buf))
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            k32.CloseHandle(h)
            return buf.value
        k32.CloseHandle(h)
    except Exception:
        pass
    return sys.executable


def instance_path_from_hid_path(hid_path):
    r"""hidapi path      \\?\HID#{...}_VID&0002054c_PID&0ce6#9&abc&0#{guid}
    → instance path    HID\{...}_VID&0002054C_PID&0CE6\9&ABC&0"""
    if isinstance(hid_path, bytes):
        hid_path = hid_path.decode("utf-8", "ignore")
    p = hid_path
    if p.startswith("\\\\?\\"):
        p = p[4:]
    parts = p.split("#")
    if parts and parts[-1].startswith("{"):
        parts = parts[:-1]
    return "\\".join(parts).upper()


class Hiding:
    """Inside a `with Hiding(hid_path):` block the DualSense is hidden from games."""

    def __init__(self, hid_path):
        self.hid_path = hid_path
        self.cli = find_cli()
        self.active = False

    def __enter__(self):
        if self.cli is None:
            print("WARNING: HidHide not found, no hiding (games may see two controllers).")
            return self
        if not is_admin():
            print("WARNING: not running as administrator, cannot enable hiding. Use run_bridge.bat.")
            return self
        for exe in {real_exe_path(), sys.executable}:
            _cli(self.cli, "--app-reg", exe)
        instance = instance_path_from_hid_path(self.hid_path)
        _cli(self.cli, "--dev-hide", instance)
        _cli(self.cli, "--cloak-on")
        self.active = True
        print(f"Hiding ON: {instance}")
        return self

    def __exit__(self, *_):
        if self.active:
            try:
                _cli(self.cli, "--cloak-off")
                print("Hiding OFF: DualSense is visible to games again.")
            except Exception as e:
                print("Could not turn hiding off:", e, "-> run unhide.bat.")
        return False


if __name__ == "__main__":
    # Emergency: python hiding.py off
    cli = find_cli()
    if cli and len(sys.argv) > 1 and sys.argv[1] == "off":
        _cli(cli, "--cloak-off")
        print("Hiding turned off.")
