@echo off
cd /d "%~dp0"
python -m shipmblang notebook
if errorlevel 1 pause
