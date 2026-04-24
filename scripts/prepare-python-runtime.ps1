$ErrorActionPreference = 'Stop'

# ── Configuration ─────────────────────────────────────────────────────
# Set NOWORK_PYTHON to your conda Python directory before running, e.g.:
#   $env:NOWORK_PYTHON = 'C:\Users\you\.conda\envs\nowork'
$sourcePython = if ($env:NOWORK_PYTHON) { $env:NOWORK_PYTHON } else { Write-Host 'ERROR: Set $env:NOWORK_PYTHON to your conda Python directory (e.g. C:\Users\you\.conda\envs\nowork)'; exit 1 }
$targetPython = 'src-tauri\resources\python'
$allowlistFile = 'scripts\package-allowlist.txt'

$python = Join-Path $sourcePython 'python.exe'
if (!(Test-Path $python)) {
  Write-Host "ERROR: python.exe not found under NOWORK_PYTHON: $python"
  exit 1
}

if (!(Test-Path $allowlistFile)) {
  Write-Host "ERROR: Allowlist not found: $allowlistFile"
  Write-Host "Run:  python scripts\resolve-packages.py --source $sourcePython"
  exit 1
}

# ── Step 1: Copy Python runtime (excluding site-packages) ─────────────
Write-Host "`n[1/3] Copying Python runtime from $sourcePython ..."

if (Test-Path $targetPython) {
  Remove-Item $targetPython -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $targetPython | Out-Null

# Copy everything EXCEPT Lib/site-packages (we handle that separately)
Get-ChildItem $sourcePython -Exclude 'Lib' | ForEach-Object {
  Copy-Item $_.FullName $targetPython -Recurse -Force
}

# Copy Lib/ itself but skip site-packages
$targetLib = Join-Path $targetPython 'Lib'
$sourceLib = Join-Path $sourcePython 'Lib'
New-Item -ItemType Directory -Force -Path $targetLib | Out-Null

Get-ChildItem $sourceLib -Exclude 'site-packages' | ForEach-Object {
  Copy-Item $_.FullName $targetLib -Recurse -Force
}

# ── Step 2: Copy filtered site-packages ───────────────────────────────
Write-Host "`n[2/3] Copying filtered site-packages ..."

$sourceSP = Join-Path $sourcePython 'Lib\site-packages'
$targetSP = Join-Path $targetPython 'Lib\site-packages'
New-Item -ItemType Directory -Force -Path $targetSP | Out-Null

# Read allowlist
$allowlist = Get-Content $allowlistFile -Encoding UTF8 | Where-Object { $_.Trim() -and !$_.StartsWith('#') }

$totalItems = $allowlist.Count
$copiedItems = 0
$missingItems = 0

foreach ($pattern in $allowlist) {
  $pattern = $pattern.Trim()
  if (!$pattern) { continue }

  # Handle paths with backslash (e.g. "win32\lib\win32con")
  $sourceItem = Join-Path $sourceSP $pattern

  if (Test-Path $sourceItem) {
    $targetParent = Split-Path (Join-Path $targetSP $pattern) -Parent
    if (!(Test-Path $targetParent)) {
      New-Item -ItemType Directory -Force -Path $targetParent | Out-Null
    }
    Copy-Item $sourceItem (Join-Path $targetSP $pattern) -Recurse -Force
    $copiedItems++
  } else {
    $missingItems++
    Write-Host "  SKIP (not found): $pattern" -ForegroundColor Yellow
  }
}

Write-Host "  Copied: $copiedItems / $totalItems items ($missingItems not found in source)"

# ── Step 3: Summary ───────────────────────────────────────────────────
Write-Host "`n[3/3] Done!"
Write-Host "  Target: $targetPython"
$spSize = (Get-ChildItem $targetSP -Recurse | Measure-Object -Property Length -Sum).Sum
Write-Host "  site-packages size: $([math]::Round($spSize / 1MB, 1)) MB"
