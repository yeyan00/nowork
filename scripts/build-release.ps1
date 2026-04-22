$ErrorActionPreference = 'Stop'

powershell -ExecutionPolicy Bypass -File '.\scripts\prepare-python-runtime.ps1'
powershell -ExecutionPolicy Bypass -File '.\scripts\prepare-server-resources.ps1'
npm run tauri:build
