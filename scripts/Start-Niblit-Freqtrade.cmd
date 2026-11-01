@echo off
setlocal
set "PROFILE=%LOCALAPPDATA%\Niblit\trading\dry-run.json"
if not exist "%PROFILE%" (
  "%~dp0freqtrade\niblit-freqtrade-worker.exe" --prepare-profile --mode dry-run --output "%PROFILE%"
  if errorlevel 1 goto failed
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Niblit-Freqtrade.ps1" -ConfigPath "%PROFILE%" -EnableTradingControls
if errorlevel 1 goto failed
exit /b 0
:failed
echo Review FREQTRADE_DESKTOP_PROFILES.md and the profile's state logs.
pause
exit /b 1
