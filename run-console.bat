@echo off
title AirTouch (consola)
cd /d "%~dp0"
".venv\Scripts\python.exe" -m airtouch %*
pause
