@echo off
cd /d "%~dp0"
if exist "%~dp0shipmblang.exe" (
  "%~dp0shipmblang.exe" notebook %*
) else (
  python -m shipmblang notebook %*
)
if errorlevel 1 pause
