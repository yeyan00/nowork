; KillBackendProcesses.nsh
;
; Before installing, kill any residual Python backend processes
; that were spawned by a previous nowork installation.
;
; Precision: only kills python.exe whose ExecutablePath starts with
; the nowork installation directory ($INSTDIR\resources\python\python.exe).
; This avoids killing unrelated Python processes (conda, system, IDE, etc.)

!macro NSIS_HOOK_PREINSTALL
  ; Build the expected python path prefix from the install directory.
  ; We use WMIC to find processes whose ExecutablePath contains our install path.
  ; $INSTDIR already points to the target install dir (e.g. C:\Users\xxx\AppData\Local\nowork)

  Push $0
  Push $1
  Push $2

  DetailPrint "Checking for residual nowork backend processes..."

  ; Use PowerShell to find and kill python processes from our install directory.
  ; - Match by ExecutablePath containing the nowork install dir + resources\python
  ; - Only kill if the process path is under our install location
  ; - Silently skip if none found or if PowerShell fails

  ; Construct the path pattern from $INSTDIR
  ; We need to escape backslashes for the WMIC query
  StrCpy $0 "$INSTDIR\resources\python\python.exe"

  ; Use nsExec to run a PowerShell command (hidden window, no console popup)
  nsExec::ExecToStack `powershell -NoProfile -NonInteractive -WindowStyle Hidden -Command "Get-CimInstance Win32_Process -Filter \\"ExecutablePath LIKE '$0'\\" -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"`

  Pop $1  ; exit code
  Pop $2  ; output text (discard)

  ; Also try to kill the main nowork.exe if running (belt-and-suspenders)
  ; The built-in CheckIfAppIsRunning handles this, but do it early here too.
  nsExec::ExecToStack `taskkill /F /IM nowork.exe 2>nul`
  Pop $1
  Pop $2

  ; Give processes a moment to fully exit
  Sleep 1000

  DetailPrint "Residual process cleanup complete."

  Pop $2
  Pop $1
  Pop $0
!macroend
