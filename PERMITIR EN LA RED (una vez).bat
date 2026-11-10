@echo off
cd /d "%~dp0"
title SmartCut - permitir en la red
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Pidiendo permiso de administrador...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
echo.
echo Esto deja que la Mac (u otra compu de tu casa) entre a SmartCut.
echo Abre los puertos 7860 (app) y 7861 (editor) solo para redes PRIVADAS.
echo.
netsh advfirewall firewall delete rule name="MiOpusClip" >nul 2>&1
netsh advfirewall firewall add rule name="MiOpusClip" dir=in action=allow protocol=TCP localport=7860-7861 profile=private
echo.
echo Tu red ahora mismo:
powershell -NoProfile -Command "Get-NetConnectionProfile | Format-Table Name,InterfaceAlias,NetworkCategory -AutoSize"
echo Si dice "Public", Windows bloquea a la Mac.
choice /c SN /m "Marcar tu red como Privada (solo hazlo si es la red de tu casa)"
if errorlevel 2 goto fin
powershell -NoProfile -Command "Get-NetConnectionProfile | Where-Object {$_.NetworkCategory -eq 'Public'} | Set-NetConnectionProfile -NetworkCategory Private"
echo Listo: red marcada como Privada.
:fin
echo.
echo Ahora abre "ABRIR SmartCut en red.bat".
pause
