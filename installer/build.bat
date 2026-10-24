@echo off
rem Build script (اسکریپت ساخت) — reproducible one-command Windows build.
rem Usage: installer\build.bat
cd /d "%~dp0.."
.venv\Scripts\pyinstaller --noconfirm --clean installer\darspack.spec || exit /b 1
echo.
echo Build output: dist\DarsPack\DarsPack.exe
