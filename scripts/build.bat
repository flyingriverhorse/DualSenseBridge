@echo off
chcp 65001 >nul
cd /d "%~dp0.."
rem Builds dist\DualSenseBridge.exe (needs setup.bat to have run once).
if not exist .venv\Scripts\python.exe (echo Run scripts\setup.bat first. & pause & exit /b 1)

.venv\Scripts\python.exe -m pip install --upgrade pyinstaller || (pause & exit /b 1)
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin ^
  --name DualSenseBridge --icon assets\icon.ico ^
  --add-data "profiles.json;." --add-data "assets\icon.ico;assets" ^
  --collect-all vgamepad --hidden-import pystray._win32 ^
  --paths src src\app.py || (pause & exit /b 1)

copy /y profiles.json dist\ >nul

rem --- Installer (optional): needs Inno Setup 6  (winget install -e --id JRSoftware.InnoSetup)
set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" (
  echo Inno Setup not found, skipping the installer.  Install it with:  winget install -e --id JRSoftware.InnoSetup
  goto done
)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\get_drivers.ps1 || echo Could not download drivers, building the installer without them.
"%ISCC%" /Q installer\DualSenseBridge.iss || (pause & exit /b 1)
echo Built: %CD%\dist\DualSenseBridge-Setup.exe
:done
echo.
echo Built: %CD%\dist\DualSenseBridge.exe
echo profiles.json next to the exe can be edited; the exe also has a built-in copy.
pause
