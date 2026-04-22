$ErrorActionPreference = 'Stop'

# Set NOWORK_PYTHON to your conda Python directory before running, e.g.:
#   $env:NOWORK_PYTHON = 'C:\Users\you\.conda\envs\nowork'
$sourcePython = if ($env:NOWORK_PYTHON) { $env:NOWORK_PYTHON } else { Write-Host 'ERROR: Set $env:NOWORK_PYTHON to your conda Python directory (e.g. C:\Users\you\.conda\envs\nowork)'; exit 1 }
$targetPython = 'src-tauri\resources\python'

if (Test-Path $targetPython) {
  Remove-Item $targetPython -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $targetPython | Out-Null
Copy-Item "$sourcePython\*" $targetPython -Recurse -Force
