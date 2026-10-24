# Build the self-contained shipmblang executable for this operating system.
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
python tools/build_standalone.py @args
exit $LASTEXITCODE
