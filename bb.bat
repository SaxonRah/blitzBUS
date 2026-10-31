@echo off
rem blitzBUS: every command goes through scripts\bb.ps1. "bb help" lists them.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bb.ps1" %*
exit /b %ERRORLEVEL%
