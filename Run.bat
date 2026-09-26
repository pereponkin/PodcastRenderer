@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Project Python environment not found: .venv\Scripts\python.exe
    pause
    exit /b 1
)
".venv\Scripts\python.exe" "main.py"
if errorlevel 1 pause
