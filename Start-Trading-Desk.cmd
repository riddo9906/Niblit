@echo off
"%~dp0niblit-env\Scripts\pythonw.exe" "%~dp0scripts\launch-trading-desk.py"
start "" http://127.0.0.1:8767/
