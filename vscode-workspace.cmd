@echo off
setlocal
rem Creates a scratch folder with a starter file per ShipMBLang extension and opens it in VS Code.
rem Usage: vscode-workspace.cmd [target-folder]
set "TARGET=%~1"
if "%TARGET%"=="" set "TARGET=%~dp0workspace"
if not exist "%TARGET%" mkdir "%TARGET%"
for %%E in (shipmb smb shiplang) do (
  if not exist "%TARGET%\hello.%%E" (
    > "%TARGET%\hello.%%E" echo "Start with total at 4, then add 8 to total and show total."
    echo Saved %TARGET%\hello.%%E
  ) else (
    echo Kept existing %TARGET%\hello.%%E
  )
)
where code >nul 2>nul
if errorlevel 1 (
  echo VS Code "code" command not found. Install VS Code and enable "Add to PATH".
  pause
  exit /b 1
)
code "%TARGET%" "%TARGET%\hello.shipmb" "%TARGET%\hello.smb" "%TARGET%\hello.shiplang"
endlocal
