@echo off
rem Start once (as administrator). Keeps rebuilding the app whenever a ".rebuild" file appears.
net session >nul 2>&1 || (powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" & exit /b)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev_watch.ps1"
