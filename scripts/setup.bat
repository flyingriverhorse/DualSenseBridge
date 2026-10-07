@echo off
chcp 65001 >nul
cd /d "%~dp0.."
rem One-time setup (run from source). Usage: scripts\setup.bat                      -> finds Python automatically
rem                         setup.bat "C:\path\python.exe" -> uses that Python (a venv's python.exe works too)

if exist .venv\Scripts\python.exe goto install

set PY=
if not "%~1"=="" if exist "%~1" set PY="%~1"
if not defined PY py -3 --version >nul 2>nul && set PY=py -3
if not defined PY python --version >nul 2>nul && set PY=python
if not defined PY for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set PY="%%D\python.exe"
if not defined PY for %%D in ("%USERPROFILE%\anaconda3" "%USERPROFILE%\miniconda3" "%LOCALAPPDATA%\anaconda3" "%LOCALAPPDATA%\miniconda3" "C:\ProgramData\anaconda3" "C:\ProgramData\miniconda3") do if exist "%%~D\python.exe" set PY="%%~D\python.exe"

if not defined PY (
  echo No real Python installation found on this PC.
  choice /M "Install Python 3.12 with winget"
  if errorlevel 2 (pause & exit /b 1)
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set PY="%%D\python.exe"
)
if not defined PY (echo Python could not be installed. & pause & exit /b 1)

echo Using Python: %PY%
echo Creating virtual environment...
%PY% -m venv .venv || (echo Could not create the virtual environment. & pause & exit /b 1)

:install
.venv\Scripts\python.exe -m pip install --upgrade -r requirements.txt || (pause & exit /b 1)

echo Creating shortcuts...
powershell -NoProfile -Command ^
  "$w = New-Object -ComObject WScript.Shell;" ^
  "foreach ($p in @('%CD%\DualSense Bridge.lnk', ([Environment]::GetFolderPath('Desktop') + '\DualSense Bridge.lnk'))) {" ^
  "  $s = $w.CreateShortcut($p);" ^
  "  $s.TargetPath = '%CD%\.venv\Scripts\pythonw.exe';" ^
  "  $s.Arguments = '\"%CD%\src\app.py\"';" ^
  "  $s.WorkingDirectory = '%CD%\src';" ^
  "  $s.IconLocation = '%CD%\assets\icon.ico';   $s.Save() }"

echo.
echo Setup done. Start the app with the "DualSense Bridge" shortcut on your desktop.
pause
