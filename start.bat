@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

where py >nul 2>&1
if %ERRORLEVEL%==0 (
    start "" py -3 "%SCRIPT_DIR%bridge_gui.py"
    exit /b 0
)

where python >nul 2>&1
if %ERRORLEVEL%==0 (
    start "" python "%SCRIPT_DIR%bridge_gui.py"
    exit /b 0
)

echo Python was not found on PATH.
echo Install Python 3.10+ and run start.bat again.
pause
exit /b 1
