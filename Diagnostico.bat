@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" miopusclip.py diagnostico --probar-gpu
echo.
pause
