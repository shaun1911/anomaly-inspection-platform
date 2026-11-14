@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set PYTHONUTF8=1
echo Starting AIP dev server...
echo Panel: http://127.0.0.1:8100/panel
echo.
".venv\Scripts\python.exe" scripts\dev_server.py --host 127.0.0.1 --port 8100
pause
