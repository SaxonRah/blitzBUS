@echo off
setlocal
set CMD=%~1
if "%CMD%"=="" set CMD=run
if /I "%CMD%"=="install" (
  python "%~dp0scripts\install_overlay.py" %2 %3 %4 %5 %6 %7 %8 %9
  exit /b %ERRORLEVEL%
)
if /I "%CMD%"=="upgrade" (
  python "%~dp0scripts\upgrade_v03.py" %2 %3 %4 %5 %6 %7 %8 %9
  exit /b %ERRORLEVEL%
)
if /I "%CMD%"=="restore" (
  python "%~dp0scripts\install_overlay.py" --restore %2 %3 %4 %5 %6 %7 %8 %9
  exit /b %ERRORLEVEL%
)
if /I "%CMD%"=="run" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bb_run.ps1" %2 %3 %4 %5 %6 %7 %8 %9
  exit /b %ERRORLEVEL%
)
if /I "%CMD%"=="build" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bb_run.ps1" -BuildOnly
  exit /b %ERRORLEVEL%
)
echo Usage: bb.bat install ^| upgrade ^| restore ^| build ^| run [-Port COM5] [-Seconds 120] [-NoFlash]
exit /b 2
