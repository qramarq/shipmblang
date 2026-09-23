@echo off
setlocal
set "SHIPMB_NATIVE=%SHIPMB_NATIVE_COMPILER%"
if not defined SHIPMB_NATIVE set "SHIPMB_NATIVE=%~dp0native\bin\shipmbc_cpp.exe"
if not exist "%SHIPMB_NATIVE%" (
  echo Native compiler missing. Set SHIPMB_NATIVE_COMPILER to your privately supplied shipmbc_cpp.exe or build your local compiler sources with native\build.ps1. 1>&2
  exit /b 1
)
"%SHIPMB_NATIVE%" %*
exit /b %errorlevel%
