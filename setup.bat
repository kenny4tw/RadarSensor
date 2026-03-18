@echo off
echo ============================================================
echo   Water Velocity / Distance Measurement - Setup
echo ============================================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo.
    echo Please install Python 3.10 or newer from:
    echo   https://www.python.org/downloads/
    echo.
    echo IMPORTANT: Check "Add Python to PATH" during installation!
    echo.
    pause
    exit /b 1
)

echo [1/2] Python found:
python --version
echo.

echo [2/2] Installing required packages ...
python -m pip install --upgrade pip
python -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo [ERROR] Package installation failed. Check your internet connection.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Setup complete!
echo ============================================================
echo.
echo Usage examples:
echo   python surface_velocity.py velocity --port COM3
echo   python surface_velocity.py distance --port COM3
echo.
echo Run "python surface_velocity.py --help" for all options.
echo.
pause
