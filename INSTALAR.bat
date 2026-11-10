@echo off
cd /d "%~dp0"
title Instalando SmartCut
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"
echo.
pause
