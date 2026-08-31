@echo off
title AirTouch
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo No se encuentra el entorno virtual. Ejecuta primero: install.bat
    pause
    exit /b 1
)
".venv\Scripts\pythonw.exe" -m airtouch %*
