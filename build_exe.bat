@echo off
echo ============================================================
echo   Building standalone .exe (no Python needed on target PC)
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed. Run setup.bat first.
    pause
    exit /b 1
)

echo [1/4] Installing PyInstaller ...
python -m pip install pyinstaller
echo.

echo [2/4] Installing project dependencies ...
python -m pip install -r "%~dp0requirements.txt"
echo.

echo [3/4] Locating SDK data files ...
:: Determine the acconeer package path dynamically
for /f "delims=" %%P in ('python -c "import pathlib, acconeer.exptool; print(pathlib.Path(acconeer.exptool.__file__).parent)"') do set ACCONEER_PKG=%%P
echo   SDK path: %ACCONEER_PKG%
echo.

echo [4/4] Building executable ...
python -m PyInstaller ^
    --onefile ^
    --name WaterVelocityMeasure ^
    --console ^
    --clean ^
    --collect-all acconeer.exptool ^
    --hidden-import acconeer.exptool.a121 ^
    --hidden-import acconeer.exptool.a121.algo ^
    --hidden-import acconeer.exptool.a121.algo.surface_velocity ^
    --hidden-import acconeer.exptool.a121.algo.distance ^
    --hidden-import acconeer.exptool.a111 ^
    --hidden-import scipy ^
    --hidden-import scipy.signal ^
    "%~dp0surface_velocity.py"

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Build complete!
echo ============================================================
echo.
echo The executable is at:
echo   dist\WaterVelocityMeasure.exe
echo.
echo Copy these files to the target laptop:
echo   - dist\WaterVelocityMeasure.exe
echo.
echo Usage on target PC (no Python needed):
echo   WaterVelocityMeasure.exe velocity --port COM3
echo   WaterVelocityMeasure.exe distance --port COM3
echo.
pause
