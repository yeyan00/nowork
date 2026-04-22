$ErrorActionPreference = 'Stop'

Start-Process powershell -ArgumentList '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', 'scripts/start-server.ps1'
Start-Sleep -Seconds 2
& powershell -NoExit -ExecutionPolicy Bypass -File 'scripts/start-web.ps1'
