@echo off
cd /d "%~dp0"
if exist "dist-v1.6\EveLootAnalyzer\EveLootAnalyzer.exe" (
    start "" "dist-v1.6\EveLootAnalyzer\EveLootAnalyzer.exe"
) else (
    python main.py
    if errorlevel 1 pause
)
