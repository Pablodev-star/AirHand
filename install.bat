@echo off
title AirTouch - instalacion
cd /d "%~dp0"
echo Creando entorno virtual...
py -3.11 -m venv .venv || python -m venv .venv
echo Instalando dependencias...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
echo Descargando modelos...
".venv\Scripts\python.exe" -c "from airtouch.core import models; models.ensure_models()"
echo.
echo Listo. Ejecuta run.bat para abrir AirTouch.
pause
