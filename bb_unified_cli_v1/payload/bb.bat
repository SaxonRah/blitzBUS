@echo off
setlocal
set CMD=%~1
if "%CMD%"=="" set CMD=run
if /I "%CMD%"=="install" (
  python "%~dp0scripts\install_overlay.py" %2 %3 %4 %5 %6 %7 %8 %9
  exit /b %ERRORLEVEL%
)
if /I "%CMD%"=="upgrade" (
  python "%~dp0scripts\upgrade_v04.py" %2 %3 %4 %5 %6 %7 %8 %9
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
rem BB_UNIFIED_CLI_V1: additive dispatcher; original five commands above are unchanged.
if /I "%CMD%"=="dos" (
  python "%~dp0scripts\bb_cli.py" %*
  exit /b %ERRORLEVEL%
)
if /I "%CMD%"=="cpu" (
  python "%~dp0scripts\bb_cli.py" %*
  exit /b %ERRORLEVEL%
)
if /I "%CMD%"=="tools" (
  python "%~dp0scripts\bb_cli.py" %*
  exit /b %ERRORLEVEL%
)
if /I "%CMD%"=="help" (
  python "%~dp0scripts\bb_cli.py" help
  exit /b %ERRORLEVEL%
)
echo Usage: bb.bat install ^| upgrade ^| restore ^| build ^| run ^| dos ^| cpu ^| tools ^| help
exit /b 2
