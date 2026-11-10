@echo off
cd /d "%~dp0"
title MiOpusClip
if not exist ".venv\Scripts\python.exe" (
  echo Primero ejecuta INSTALAR.bat
  pause
  exit /b 1
)
set "FUENTE=%~1"
if "%FUENTE%"=="" set /p "FUENTE=Pega el link de YouTube o la ruta del video y Enter: "
if "%FUENTE%"=="" exit /b 1
".venv\Scripts\python.exe" miopusclip.py todo "%FUENTE%"
echo.
pause
