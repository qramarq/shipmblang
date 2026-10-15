@echo off
setlocal
set "SHIPMB_NATIVE=%SHIPMB_NATIVE_COMPILER%"
if not defined SHIPMB_NATIVE set "SHIPMB_NATIVE=%~dp0native\bin\shipmbc_cpp.exe"
if not exist "%SHIPMB_NATIVE%" if defined SHIPMB_NATIVE_COMPILER_ROOT (
  echo Native compiler missing; building with native\build.ps1... 1>&2
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0native\build.ps1" -CompilerRoot "%SHIPMB_NATIVE_COMPILER_ROOT%" 1>&2
)
if not exist "%SHIPMB_NATIVE%" (
  echo Native compiler missing. Set SHIPMB_NATIVE_COMPILER to your privately supplied shipmbc_cpp.exe or set SHIPMB_NATIVE_COMPILER_ROOT to your compiler source folder so native\build.ps1 runs automatically. 1>&2
  exit /b 1
)
"%SHIPMB_NATIVE%" %*
exit /b %errorlevel%
