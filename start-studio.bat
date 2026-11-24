@echo off
rem Starts Low Poly Studio for this PC and your phone (same Wi-Fi). Close this window to stop it.
cd /d "%~dp0"
python web\server.py --lan
pause
