@echo off
rem Runs the tests (no controller or driver needed).
cd /d "%~dp0.."
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% -m pip install -q pytest
%PY% -m pytest tests -q
pause
