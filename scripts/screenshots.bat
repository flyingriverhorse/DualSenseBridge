@echo off
rem Re-creates the README images (docs\screenshot-*.png, docs\demo.gif) from the real window.
cd /d "%~dp0.."
if not exist .venv\Scripts\python.exe (echo Run scripts\setup.bat first. & pause & exit /b 1)
.venv\Scripts\python.exe scripts\screenshots.py > screenshots_log.txt 2>&1
type screenshots_log.txt
