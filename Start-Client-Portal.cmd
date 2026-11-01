@echo off
cd /d "%~dp0"
niblit-env\Scripts\python.exe scripts\ensure-docker-desktop.py
if errorlevel 1 goto failed
pwsh -NoProfile -File scripts\start-portal-local-model.ps1
if errorlevel 1 goto failed
if exist scripts\launch-memory-desk.py if exist niblit-env\Scripts\python.exe niblit-env\Scripts\python.exe scripts\launch-memory-desk.py
docker compose -f deploy/client-portal/compose.yml -f deploy/client-portal/compose.local-gguf.yml up -d --no-deps portal
if errorlevel 1 goto failed
start "" "http://127.0.0.1:8769/"
exit /b 0
:failed
echo Start Docker Desktop first, then retry. Your stored accounts and conversations are preserved.
pause
exit /b 1
