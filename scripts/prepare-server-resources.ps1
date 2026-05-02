$ErrorActionPreference = 'Stop'

$targetServer = 'src-tauri\resources\server'
# site-packages provided by Python runtime, not server resources
$targetRuntime = 'src-tauri\resources\runtime'
# Set NOWORK_PYTHON to your conda environment directory before running, e.g.:
#   $env:NOWORK_PYTHON = 'C:\Users\you\.conda\envs\nowork'
$pythonHome = if ($env:NOWORK_PYTHON) { $env:NOWORK_PYTHON } else { Write-Host 'ERROR: Set $env:NOWORK_PYTHON to your conda environment directory (e.g. C:\Users\you\.conda\envs\nowork)'; exit 1 }
$python = Join-Path $pythonHome 'python.exe'
if (!(Test-Path $python)) {
  Write-Host "ERROR: python.exe not found under NOWORK_PYTHON: $python"
  exit 1
}

if (Test-Path $targetServer) {
  Remove-Item $targetServer -Recurse -Force
}

if (Test-Path $targetRuntime) {
  Remove-Item $targetRuntime -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $targetServer | Out-Null
# site-packages provided by Python runtime
New-Item -ItemType Directory -Force -Path $targetRuntime | Out-Null

# Copy server code and resources
Copy-Item 'server\app' $targetServer -Recurse -Force
# Copy config but exclude personal/local data:
# - use dedicated packaging template config.setup.yaml
# - keep only model examples (no real provider secrets)
# - do not bundle mcp.yaml
# - do not bundle knowledge definitions/content
$targetConfig = Join-Path $targetServer 'config'
New-Item -ItemType Directory -Force -Path $targetConfig | Out-Null
New-Item -ItemType Directory -Force -Path "$targetConfig\models" | Out-Null

Copy-Item 'server\config\config.setup.yaml' "$targetConfig\config.yaml" -Force

Get-ChildItem 'server\config\models\*.example.yaml' -ErrorAction SilentlyContinue | ForEach-Object {
  Copy-Item $_.FullName "$targetConfig\models" -Force
}
if (Test-Path 'server\config\workers') {
  # Exclude test-only agents from release builds
  $testExcludes = @('test-agent.yaml')
  $workerItems = Get-ChildItem 'server\config\workers' -Exclude $testExcludes
  $destWorkers = "$targetConfig\workers"
  New-Item -ItemType Directory -Force -Path $destWorkers | Out-Null
  $workerItems | ForEach-Object {
    Copy-Item $_.FullName $destWorkers -Recurse -Force
  }
}
Copy-Item 'server\skills' $targetServer -Recurse -Force
# requirements.txt not needed at runtime (deps in Python runtime site-packages)

# Create runtime directories
New-Item -ItemType Directory -Force -Path "$targetServer\runtime\logs" | Out-Null
New-Item -ItemType Directory -Force -Path "$targetServer\db" | Out-Null

# NOTE: site-packages are provided by the Python runtime (prepare-python-runtime.ps1)
# No pip install needed at build time
