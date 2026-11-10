@echo off
cd /d "%~dp0"
title SmartCut - editor
if not exist ".venv\Scripts\python.exe" (
  echo Primero ejecuta INSTALAR.bat
  pause
  exit /b 1
)
echo Abriendo el editor de SmartCut en tu navegador... (no cierres esta ventana mientras lo usas)
".venv\Scripts\python.exe" editor.py
pause
