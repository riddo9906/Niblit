@echo off
setlocal
set "PROFILE=%LOCALAPPDATA%\Niblit\trading\live.json"
if not exist "%PROFILE%" (
  "%~dp0freqtrade\niblit-freqtrade-worker.exe" --prepare-profile --mode live --output "%PROFILE%"
  if errorlevel 1 goto failed
  echo Created a STOPPED live profile at "%PROFILE%".
  echo Add exchange credentials privately and review allocation settings before launching again.
  echo See FREQTRADE_DESKTOP_PROFILES.md. No trading services were started.
  pause
  exit /b 0
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Niblit-Freqtrade.ps1" -ConfigPath "%PROFILE%"
if errorlevel 1 goto failed
exit /b 0
:failed
echo Review FREQTRADE_DESKTOP_PROFILES.md and your private profile settings.
pause
exit /b 1
