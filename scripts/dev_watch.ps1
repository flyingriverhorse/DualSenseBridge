# Developer helper: leave this running.
#  - ".rebuild" appears  → close the app, rebuild dist\DualSenseBridge.exe, start it again
#                          (log: build_log.txt, result: build_status.txt)
#  - ".rundiag" appears  → run scripts\diag.py with the project's Python (output: diag_out.txt)
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$Host.UI.RawUI.WindowTitle = "DualSense Bridge - auto build (leave open)"
Write-Host "Watching $root for rebuild / diagnostic requests... (close this window to stop)"

function Run($log, [string[]]$cmd) {
    # cmd.exe redirection keeps the log as plain UTF-8/ANSI text
    $line = '"' + ($cmd -join '" "') + '"'
    cmd /c "$line >> `"$log`" 2>&1"
    return $LASTEXITCODE
}

function Build {
    "BUILDING $(Get-Date -Format s)" | Set-Content build_status.txt
    Write-Host "`n[$(Get-Date -Format HH:mm:ss)] Rebuild requested"
    Get-Process DualSenseBridge -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 1
    "" | Set-Content build_log.txt
    if ((Run build_log.txt @($py, "-m", "pip", "install", "-q", "-r", "requirements.txt", "pyinstaller")) -ne 0) {
        "FAILED pip $(Get-Date -Format s)" | Set-Content build_status.txt; Write-Host "pip failed"; return }
    $pyiArgs = @($py, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed", "--uac-admin",
        "--name", "DualSenseBridge", "--icon", "assets\icon.ico",
        "--add-data", "profiles.json;.", "--add-data", "assets\icon.ico;assets",
        "--collect-all", "vgamepad", "--hidden-import", "pystray._win32",
        "--paths", "src", "src\app.py")
    if ((Run build_log.txt $pyiArgs) -ne 0) {
        "FAILED pyinstaller $(Get-Date -Format s)" | Set-Content build_status.txt; Write-Host "build failed"; return }
    Copy-Item profiles.json dist\ -Force
    Start-Process (Join-Path $root "dist\DualSenseBridge.exe")
    "OK $(Get-Date -Format s)" | Set-Content build_status.txt
    Write-Host "Built and started."
}

function Diag {
    Write-Host "[$(Get-Date -Format HH:mm:ss)] Diagnostic run"
    "" | Set-Content diag_out.txt
    $rc = Run diag_out.txt @($py, "scripts\diag.py")
    "EXIT $rc" | Add-Content diag_out.txt
}

while ($true) {
    if (Test-Path .rebuild) {
        Remove-Item .rebuild -Force
        try { Build } catch { "FAILED $($_.Exception.Message)" | Set-Content build_status.txt; Write-Host $_ }
    }
    if (Test-Path .rundiag) {
        Remove-Item .rundiag -Force
        try { Diag } catch { "FAILED $($_.Exception.Message)" | Set-Content diag_out.txt }
    }
    Start-Sleep -Seconds 2
}
