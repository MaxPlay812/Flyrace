@echo off
REM Launch the Clover 4 Race GUI on Windows

cd /d "%~dp0"

REM Optional: activate virtual environment
REM call venv\Scripts\activate.bat

python src\main.py %*
if errorlevel 1 (
    echo.
    echo ERROR: failed to launch. Make sure Python and requirements are installed.
    echo Run:  pip install -r requirements.txt
    pause
)
