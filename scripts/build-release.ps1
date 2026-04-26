$ErrorActionPreference = 'Stop'

# ── Sync version from git tag ──
$tag = git describe --tags --abbrev=0
if (-not $tag) { Write-Error 'No git tag found'; exit 1 }
$version = $tag -replace '^v',''
Write-Host "Building version $version (from tag $tag)"

# Update tauri.conf.json
$confPath = Join-Path $PSScriptRoot '..' 'src-tauri' 'tauri.conf.json'
$conf = Get-Content $confPath -Raw | ConvertFrom-Json
$conf.version = $version
$conf | ConvertTo-Json -Depth 10 | Set-Content $confPath -Encoding UTF8

# Update Cargo.toml
$cargoPath = Join-Path $PSScriptRoot '..' 'src-tauri' 'Cargo.toml'
$cargo = Get-Content $cargoPath -Raw
$cargo = $cargo -replace 'version = "0\.\d+\.\d+"', "version = `"$version`""
Set-Content $cargoPath $cargo -Encoding UTF8

# Update package.json
$pkgPath = Join-Path $PSScriptRoot '..' 'package.json'
$pkg = Get-Content $pkgPath -Raw | ConvertFrom-Json
$pkg.version = $version
$pkg | ConvertTo-Json -Depth 10 | Set-Content $pkgPath -Encoding UTF8

Write-Host 'Version synced to tauri.conf.json, Cargo.toml, package.json'

# Resolve allowlist before copying
if ($env:NOWORK_PYTHON) {
  $python = Join-Path $env:NOWORK_PYTHON 'python.exe'
  if (Test-Path $python) {
    Write-Host 'Resolving package allowlist...'
    & $python scripts\resolve-packages.py --source $env:NOWORK_PYTHON
  }
}

powershell -ExecutionPolicy Bypass -File '.\scripts\prepare-python-runtime.ps1'
powershell -ExecutionPolicy Bypass -File '.\scripts\prepare-server-resources.ps1'
npm run tauri:build
