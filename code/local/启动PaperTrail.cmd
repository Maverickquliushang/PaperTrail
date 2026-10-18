@echo off
setlocal
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch.ps1"
if errorlevel 1 (
    echo.
    echo PaperTrail could not start. Please keep the error above for troubleshooting.
    pause
    exit /b 1
)
endlocal
