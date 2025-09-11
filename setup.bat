@echo off
echo 🚀 TTS Tool Setup (Windows)
echo =============================

:: Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python is not installed or not in PATH
    echo Please install Python 3.8+ from https://python.org
    pause
    exit /b 1
)

:: Run Python setup script
python setup.py

if %errorlevel% neq 0 (
    echo ❌ Setup failed
    pause
    exit /b 1
)

echo.
echo ✅ Setup completed! Press any key to continue...
pause >nul