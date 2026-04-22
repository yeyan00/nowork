$ErrorActionPreference = 'Stop'

$targetServer = 'src-tauri\resources\server'
$targetSitePackages = Join-Path $targetServer 'site-packages'
$targetRuntime = 'src-tauri\resources\runtime'
# Set NOWORK_PYTHON to your conda Python executable before running, e.g.:
#   $env:NOWORK_PYTHON = 'C:\Users\you\.conda\envs\nowork\python.exe'
$python = if ($env:NOWORK_PYTHON) { $env:NOWORK_PYTHON } else { Write-Host 'ERROR: Set $env:NOWORK_PYTHON to your conda Python executable path'; exit 1 }

if (Test-Path $targetServer) {
  Remove-Item $targetServer -Recurse -Force
}

if (Test-Path $targetRuntime) {
  Remove-Item $targetRuntime -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $targetServer | Out-Null
New-Item -ItemType Directory -Force -Path $targetSitePackages | Out-Null
New-Item -ItemType Directory -Force -Path $targetRuntime | Out-Null

# Copy server code and resources
Copy-Item 'server\app' $targetServer -Recurse -Force
Copy-Item 'server\config' $targetServer -Recurse -Force
Copy-Item 'server\skills' $targetServer -Recurse -Force
Copy-Item 'server\requirements.txt' $targetServer -Force

# Create runtime directories
New-Item -ItemType Directory -Force -Path "$targetServer\runtime\logs" | Out-Null
New-Item -ItemType Directory -Force -Path "$targetServer\db" | Out-Null

& $python -m pip install -r 'server\requirements.txt' --target $targetSitePackages
