@echo off
cd /d "%~dp0"
title SmartCut (en la red de la casa)
if not exist ".venv\Scripts\python.exe" (
  echo Primero ejecuta INSTALAR.bat
  pause
  exit /b 1
)
set MIOPUSCLIP_RED=1
echo Abriendo SmartCut para esta PC y para la Mac...
echo Aqui abajo salen la direccion, el usuario y la clave para la Mac.
echo (no cierres esta ventana mientras lo usas)
".venv\Scripts\python.exe" app.py
pause
