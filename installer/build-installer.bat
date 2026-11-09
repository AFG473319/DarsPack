@echo off
rem Build the Windows installer (ساخت نصب‌کننده‌ی ویندوزی) after the onedir build.
rem Usage: installer\build-installer.bat
rem Needs Inno Setup 6 (ISCC) — see docs/dependencies.md.
rem Intellect: this script never downloads or installs Inno Setup itself;
rem install it first with: winget install --id JRSoftware.InnoSetup -e
setlocal
cd /d "%~dp0.."

if not exist dist\DarsPack\DarsPack.exe (
  echo dist\DarsPack\DarsPack.exe not found - running installer\build.bat first...
  call installer\build.bat || exit /b 1
)

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ISCC%" goto have_iscc
set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%ISCC%" goto have_iscc
set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if exist "%ISCC%" goto have_iscc

echo.
echo Inno Setup 6 compiler (ISCC.exe) not found.
echo Install it once with:  winget install --id JRSoftware.InnoSetup -e
echo Then re-run installer\build-installer.bat
exit /b 1

:have_iscc

"%ISCC%" /Q installer\DarsPack.iss || exit /b 1
echo.
echo Build output: dist\DarsPack-Setup.exe
endlocal
