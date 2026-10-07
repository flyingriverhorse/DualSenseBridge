# Downloads the latest ViGEmBus and HidHide installers into build\drivers\
# so the setup can bundle them. Used by scripts\build.bat and the GitHub release workflow.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root "build\drivers"
New-Item -ItemType Directory -Force -Path $out | Out-Null

function Get-Latest($repo, $target) {
    $headers = @{ "User-Agent" = "DualSenseBridge" }
    if ($env:GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN" }
    $rel = Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/$repo/releases/latest"
    $asset = $rel.assets | Where-Object { $_.name -like "*.exe" -and $_.name -like "*x64*" } | Select-Object -First 1
    if (-not $asset) { $asset = $rel.assets | Where-Object { $_.name -like "*.exe" } | Select-Object -First 1 }
    if (-not $asset) { Write-Warning "No installer found in $repo $($rel.tag_name)"; return }
    Write-Host "$repo $($rel.tag_name): $($asset.name)"
    Invoke-WebRequest -Headers $headers -Uri $asset.browser_download_url -OutFile (Join-Path $out $target)
}

Get-Latest "nefarius/ViGEmBus" "ViGEmBus_setup.exe"
Get-Latest "nefarius/HidHide" "HidHide_setup.exe"
