@echo off
cd /d "%~dp0"
title MiOpusClip
if not exist ".venv\Scripts\python.exe" (
  echo Primero ejecuta INSTALAR.bat
  pause
  exit /b 1
)
echo Abriendo MiOpusClip en tu navegador... (no cierres esta ventana mientras lo usas)
".venv\Scripts\python.exe" app.py
pause
