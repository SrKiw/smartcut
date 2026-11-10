@echo off
cd /d "%~dp0"
title MiOpusClip - comparar transcripciones
if not exist ".venv\Scripts\python.exe" (
  echo Primero ejecuta INSTALAR.bat
  pause
  exit /b 1
)
echo Compara Whisper turbo (el de siempre) con Whisper large-v3 en 10 minutos de un video.
echo Si guardaste la key de ElevenLabs en la app, tambien lo prueba (cuesta unos 4 centavos).
echo.
set "FUENTE=%~1"
if "%FUENTE%"=="" set /p "FUENTE=Arrastra aqui el video (o pega la ruta) y Enter: "
if "%FUENTE%"=="" exit /b 1
set /p "DESDE=Desde que minuto (Enter = 10): "
if "%DESDE%"=="" set "DESDE=10"
set /a SEG=%DESDE%*60
set "MOTORES=whisper:large-v3-turbo,whisper:large-v3"
findstr /b "ELEVENLABS_API_KEY=" .env >nul 2>&1 && set "MOTORES=%MOTORES%,elevenlabs"
".venv\Scripts\python.exe" miopusclip.py comparar "%FUENTE%" --desde %SEG% --motores %MOTORES%
echo.
pause
