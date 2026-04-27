$ErrorActionPreference = 'Stop'

function Write-JsonNoBom {
  param(
    [Parameter(Mandatory = $true)] $Data,
    [Parameter(Mandatory = $true)] [string] $Path
  )

  $json = $Data | ConvertTo-Json -Depth 10
  $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($Path, $json, $utf8NoBom)
}

# ── Sync version from git tag ──
$tag = git describe --tags --abbrev=0
if (-not $tag) { Write-Error 'No git tag found'; exit 1 }
$version = $tag -replace '^v',''
Write-Host "Building version $version (from tag $tag)"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')

# Update tauri.conf.json
$confPath = Join-Path $repoRoot 'src-tauri/tauri.conf.json'
$conf = Get-Content $confPath -Raw | ConvertFrom-Json
$conf.version = $version
Write-JsonNoBom -Data $conf -Path $confPath

# Update Cargo.toml
$cargoPath = Join-Path $repoRoot 'src-tauri/Cargo.toml'
$cargo = Get-Content $cargoPath -Raw
$cargo = $cargo -replace 'version = "0\.\d+\.\d+"', "version = `"$version`""
Set-Content $cargoPath $cargo -Encoding UTF8

# Update root package.json
$pkgPath = Join-Path $repoRoot 'package.json'
$pkg = Get-Content $pkgPath -Raw | ConvertFrom-Json
$pkg.version = $version
Write-JsonNoBom -Data $pkg -Path $pkgPath

# Update web/package.json
$webPkgPath = Join-Path $repoRoot 'web/package.json'
$webPkg = Get-Content $webPkgPath -Raw | ConvertFrom-Json
$webPkg.version = $version
Write-JsonNoBom -Data $webPkg -Path $webPkgPath

Write-Host 'Version synced to tauri.conf.json, Cargo.toml, package.json, web/package.json'

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
