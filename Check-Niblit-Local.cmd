@echo off
cd /d "%~dp0"
echo Checking the bounded local learning profile. No AI generation or orders.
niblit-env\Scripts\python.exe scripts\check-native-runtime.py
if errorlevel 1 echo Dependencies need attention. No services were reset.
pause
