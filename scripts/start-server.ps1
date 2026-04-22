$ErrorActionPreference = 'Stop'

# Set NOWORK_PYTHON to your Python executable, or it falls back to PATH.
#   $env:NOWORK_PYTHON = 'C:\Users\you\.conda\envs\nowork\python.exe'
$python = if ($env:NOWORK_PYTHON) { $env:NOWORK_PYTHON } else { 'python' }
$env:PYTHONPATH = 'server'

& $python -m pip install -r 'server/requirements.txt'
& $python -m app.run
