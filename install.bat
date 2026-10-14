@echo off
cd /d "%~dp0"
echo Installing File Organizer...
py -m pip install --user -r requirements.txt
py windows_setup.py install
echo.
pause
