@echo off
REM ============================================================================
REM  boot\install_windows.bat — Niblit Windows Service Installer
REM ============================================================================
REM  Run as Administrator for best results.
REM  Requires NSSM (https://nssm.cc) for Windows Service; falls back to Task
REM  Scheduler if NSSM is not found on PATH.
REM ============================================================================

setlocal enabledelayedexpansion

REM Locate the Niblit root (one level up from this script)
set "NIBLIT_ROOT=%~dp0.."
for %%i in ("%NIBLIT_ROOT%") do set "NIBLIT_ROOT=%%~fi"

REM Find Python
set "PYTHON="
for %%p in (python.exe python3.exe) do (
    if not defined PYTHON (
        where %%p >nul 2>&1 && set "PYTHON=%%p"
    )
)
if not defined PYTHON (
    echo [niblit] ERROR: Python not found. Install Python 3.10+ from python.org
    pause
    exit /b 1
)
echo [niblit] Python: %PYTHON%
echo [niblit] Root  : %NIBLIT_ROOT%

REM Install Python requirements
if exist "%NIBLIT_ROOT%\requirements.txt" (
    echo [niblit] Installing Python requirements...
    "%PYTHON%" -m pip install -r "%NIBLIT_ROOT%\requirements.txt" --quiet
    echo [niblit] Requirements installed
)

REM Try NSSM first
where nssm.exe >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [niblit] Installing Windows Service via NSSM...
    nssm install NiblitAI "%PYTHON%" "%NIBLIT_ROOT%\app.py"
    nssm set NiblitAI AppDirectory "%NIBLIT_ROOT%"
    nssm set NiblitAI AppEnvironmentExtra "NIBLIT_BOOT_MODE=service"
    nssm set NiblitAI DisplayName "Niblit AI System"
    nssm set NiblitAI Description "Niblit autonomous AI — OS integration layer"
    nssm set NiblitAI Start SERVICE_AUTO_START
    nssm start NiblitAI
    echo [niblit] OK  NiblitAI Windows Service installed and started
    echo [niblit]     Control: nssm {start^|stop^|restart^|status} NiblitAI
    goto :done
)

REM Fallback: Task Scheduler
echo [niblit] NSSM not found. Installing via Task Scheduler (ONLOGON)...
set "BAT=%NIBLIT_ROOT%\boot\niblit_start.bat"
(
    echo @echo off
    echo cd /d "%NIBLIT_ROOT%"
    echo set NIBLIT_BOOT_MODE=service
    echo "%PYTHON%" app.py
) > "%BAT%"

schtasks /Create /TN "NiblitAI" /TR "\"%BAT%\"" /SC ONLOGON /RL HIGHEST /F
if %ERRORLEVEL% equ 0 (
    echo [niblit] OK  Niblit scheduled to start at logon via Task Scheduler
    echo [niblit]     Script: %BAT%
    echo [niblit]     Download NSSM from https://nssm.cc for a proper Windows Service
) else (
    echo [niblit] WARN  Task Scheduler setup failed. Run manually: %BAT%
)

:done
echo.
echo [niblit] Niblit Windows installation complete!
echo [niblit] Reboot or log off / on to test auto-start.
pause
endlocal
