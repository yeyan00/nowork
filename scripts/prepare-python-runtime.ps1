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

# Copy everything EXCEPT Lib/site-packages and conda-meta (we handle site-packages separately)
Get-ChildItem $sourcePython -Exclude 'Lib','conda-meta' | ForEach-Object {
  Copy-Item $_.FullName $targetPython -Recurse -Force
}

# Copy Lib/ itself but skip site-packages
$targetLib = Join-Path $targetPython 'Lib'
$sourceLib = Join-Path $sourcePython 'Lib'
New-Item -ItemType Directory -Force -Path $targetLib | Out-Null

Get-ChildItem $sourceLib -Exclude 'site-packages' | ForEach-Object {
  Copy-Item $_.FullName $targetLib -Recurse -Force
}

# Remove __pycache__ from stdlib copy
Get-ChildItem $targetLib -Directory -Recurse -Filter '__pycache__' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force

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
    
    # Immediately clean __pycache__ and .pyc from copied directory
    $copiedDir = Join-Path $targetSP $pattern
    if (Test-Path $copiedDir -PathType Container) {
      Get-ChildItem $copiedDir -Directory -Recurse -Filter '__pycache__' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
      Get-ChildItem $copiedDir -File -Recurse -Filter '*.pyc' -ErrorAction SilentlyContinue | Remove-Item -Force
    }
    $copiedItems++
  } else {
    $missingItems++
    Write-Host "  SKIP (not found): $pattern" -ForegroundColor Yellow
  }
}

Write-Host "  Copied: $copiedItems / $totalItems items ($missingItems not found in source)"

# ── Step 2.1: Add package management tools (pip, setuptools, wheel) ───
# These are not in allowlist (not app dependencies) but needed for user to install extra packages
Write-Host "  Adding pip, setuptools, wheel for user package management..."

$pkgTools = @('pip', 'setuptools', 'wheel')
foreach ($tool in $pkgTools) {
  $srcTool = Join-Path $sourceSP $tool
  if (Test-Path $srcTool) {
    Copy-Item $srcTool (Join-Path $targetSP $tool) -Recurse -Force
    # Clean __pycache__ and .pyc immediately after copy
    $copiedTool = Join-Path $targetSP $tool
    Get-ChildItem $copiedTool -Directory -Recurse -Filter '__pycache__' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
    Get-ChildItem $copiedTool -File -Recurse -Filter '*.pyc' -ErrorAction SilentlyContinue | Remove-Item -Force
    Write-Host "    Copied: $tool"
  } else {
    Write-Host "    SKIP (not found): $tool" -ForegroundColor Yellow
  }
  
  # Also copy .dist-info for metadata (pip needs this)
  $srcDistInfo = Get-ChildItem $sourceSP -Directory -Filter "$tool-*.dist-info" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($srcDistInfo) {
    Copy-Item $srcDistInfo.FullName (Join-Path $targetSP $srcDistInfo.Name) -Recurse -Force
    Write-Host "    Copied: $($srcDistInfo.Name)"
  }
}

# ── Step 2.5: Remove unnecessary files ────────────────────────────────

# 1) __pycache__ / .pyc — runtime bytecode cache, auto-regenerated
$pycacheCount = (Get-ChildItem $targetSP -Directory -Recurse -Filter '__pycache__' -ErrorAction SilentlyContinue).Count
if ($pycacheCount -gt 0) {
  Get-ChildItem $targetSP -Directory -Recurse -Filter '__pycache__' | Remove-Item -Recurse -Force
}
$pycCount = (Get-ChildItem $targetSP -File -Recurse -Filter '*.pyc' -ErrorAction SilentlyContinue).Count
if ($pycCount -gt 0) {
  Get-ChildItem $targetSP -File -Recurse -Filter '*.pyc' | Remove-Item -Force
}
Write-Host "  Cleaned up $pycacheCount __pycache__ dirs, $pycCount .pyc files"

# 2) tests/test/testing directories — dev-only, ~39 MB
$testCount = 0
foreach ($testDir in @('tests', 'test', 'testing')) {
  $found = Get-ChildItem $targetSP -Directory -Recurse -Filter $testDir -ErrorAction SilentlyContinue
  $testCount += $found.Count
  $found | Remove-Item -Recurse -Force
}
Write-Host "  Cleaned up $testCount test directories"

# 3) .pyi stubs — IDE/type-check only, ~2 MB
$pyiCount = (Get-ChildItem $targetSP -File -Recurse -Filter '*.pyi' -ErrorAction SilentlyContinue).Count
if ($pyiCount -gt 0) {
  Get-ChildItem $targetSP -File -Recurse -Filter '*.pyi' | Remove-Item -Force
}
Write-Host "  Cleaned up $pyiCount .pyi stub files"

# 4) .pxd/.pyx Cython sources — already compiled, ~0.5 MB
$cythonCount = (Get-ChildItem $targetSP -File -Recurse -Include '*.pxd','*.pyx' -ErrorAction SilentlyContinue).Count
if ($cythonCount -gt 0) {
  Get-ChildItem $targetSP -File -Recurse -Include '*.pxd','*.pyx' | Remove-Item -Force
}
Write-Host "  Cleaned up $cythonCount Cython source files"

# 5) .dist-info — pip metadata, not needed at runtime, ~3 MB
# Keep pip/setuptools/wheel dist-info for package management
$pkgToolsDistInfo = @('pip-', 'setuptools-', 'wheel-')
$distInfoCount = 0
Get-ChildItem $targetSP -Directory -Filter '*.dist-info' -ErrorAction SilentlyContinue | ForEach-Object {
  $keep = $false
  foreach ($prefix in $pkgToolsDistInfo) {
    if ($_.Name.StartsWith($prefix)) {
      $keep = $true
      break
    }
  }
  if (-not $keep) {
    Remove-Item $_.FullName -Recurse -Force
    $distInfoCount++
  }
}
Write-Host "  Cleaned up $distInfoCount .dist-info directories (kept pip/setuptools/wheel)"

# ── Step 3: Summary ───────────────────────────────────────────────────
Write-Host "`n[3/3] Done!"
Write-Host "  Target: $targetPython"
$spSize = (Get-ChildItem $targetSP -Recurse | Measure-Object -Property Length -Sum).Sum
Write-Host "  site-packages size: $([math]::Round($spSize / 1MB, 1)) MB"
