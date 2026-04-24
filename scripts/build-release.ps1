$ErrorActionPreference = 'Stop'

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
