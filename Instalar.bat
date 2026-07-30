@echo off
REM Doble clic en este archivo instala el plugin Planos Auto en QGIS.
REM Abre QGIS al menos una vez antes de correr esto.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_plugin.ps1"
echo.
pause
