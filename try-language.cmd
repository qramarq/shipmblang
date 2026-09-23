@echo off
cd /d "%~dp0"
python "%~dp0tools\try_language.py" %*
if errorlevel 1 echo Tester exited with an error. See the message above.
pause
