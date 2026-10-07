"""Diagnostics run by dev_watch (output -> diag_out.txt). Currently: README screenshots."""
import runpy
import sys
import traceback

sys.stdout.reconfigure(encoding="utf-8")
try:
    runpy.run_path("scripts/screenshots.py", run_name="__main__")
except Exception:
    traceback.print_exc()
