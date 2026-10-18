# Get-Arsenal.ps1
# Downloads the latest official HD2 Arsenal installer from the publisher's
# GitHub release repo and verifies its SHA-256 before saving it to Downloads.
# Usage: powershell -ExecutionPolicy Bypass -File .\Get-Arsenal.ps1

$ErrorActionPreference = 'Stop'
$repo = 'Orbit-Studios/hd2arsenal-release'

Write-Host "Asking GitHub for the latest HD2 Arsenal release..."
$release = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/releases/latest" -Headers @{ 'User-Agent' = 'eagle-1-cockpit-mod' }
$asset = $release.assets | Where-Object { $_.name -like 'HD2Arsenal-Setup-*.exe' } | Select-Object -First 1
if (-not $asset) { throw "No HD2Arsenal-Setup-*.exe asset found in $($release.tag_name)" }

$dest = Join-Path $env:USERPROFILE 'Downloads' $asset.name
Write-Host "Downloading $($asset.name) ($([math]::Round($asset.size/1MB)) MB) -> $dest"
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $dest

$expected = ($asset.digest -replace '^sha256:', '').ToLower()
$actual = (Get-FileHash $dest -Algorithm SHA256).Hash.ToLower()
if ($actual -ne $expected) {
    Remove-Item $dest -Force
    throw "SHA-256 mismatch! Expected $expected, got $actual. File deleted."
}
Write-Host "SHA-256 verified: $actual"
Write-Host "Done. Run the installer: $dest"
