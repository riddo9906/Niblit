@echo off
setlocal
rem Keep chat available when the optional trading service is unhealthy.
rem This does not enable execution or change trading credentials/configuration.
set "NIBLIT_TRADING_REQUIRED=false"
cd /d "%~dp0"
"%~dp0niblit.exe"
endlocal
