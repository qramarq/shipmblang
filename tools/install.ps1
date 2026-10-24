# Place shipmblang.exe on the user PATH, then run shipmblang setup.
# Arguments are passed through, for example:
#   powershell -ExecutionPolicy Bypass -File .\install.ps1 --yes --skip ollama
$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$candidates = @(
    (Join-Path $here 'shipmblang.exe'),
    (Join-Path $here 'dist\shipmblang.exe')
)
$source = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $source) {
    throw 'Could not find shipmblang.exe next to install.ps1.'
}

$destDir = Join-Path $env:LOCALAPPDATA 'ShipMBLang'
New-Item -ItemType Directory -Force -Path $destDir | Out-Null
$dest = Join-Path $destDir 'shipmblang.exe'
Copy-Item -LiteralPath $source -Destination $dest -Force

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $userPath) {
    $userPath = $destDir
} elseif ($userPath.Split(';') -notcontains $destDir) {
    $userPath = "$userPath;$destDir"
}
[Environment]::SetEnvironmentVariable('Path', $userPath, 'User')
if ($env:Path.Split(';') -notcontains $destDir) {
    $env:Path = "$env:Path;$destDir"
}

Write-Host "Installed $dest"
Write-Host 'New terminals will see shipmblang on PATH. This window may need to be reopened.'
& $dest setup @args
exit $LASTEXITCODE
