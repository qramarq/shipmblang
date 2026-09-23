$ErrorActionPreference = 'Stop'
$launcher = Join-Path (Split-Path $PSScriptRoot) 'shipmblang-native.cmd'
$source = Join-Path $PSScriptRoot 'examples/general.shipmb'
$compiled = & $launcher $source
if ($LASTEXITCODE -ne 0) { throw "Native compile failed: $compiled" }
$result = $compiled | ConvertFrom-Json
if ($result.target_code.version -ne '0.3') { throw 'Expected general bytecode 0.3.' }
if ($result.runtime) { throw 'Compile-only unexpectedly returned runtime output.' }
$executed = & $launcher $source --run
if ($LASTEXITCODE -ne 0) { throw "Native execution failed: $executed" }
if (($executed | ConvertFrom-Json).runtime.stdout.Trim() -ne '27') { throw 'Expected loop and condition result 27.' }
$artifact = Join-Path ([System.IO.Path]::GetTempPath()) ('shipmb-native-' + [guid]::NewGuid().ToString('N') + '.json')
try {
    [System.IO.File]::WriteAllText($artifact, ($compiled -join "`n"), (New-Object System.Text.UTF8Encoding($false)))
    $replayed = & $launcher --run-artifact $artifact
    if ($LASTEXITCODE -ne 0) { throw "Artifact replay failed: $replayed" }
    if (($replayed | ConvertFrom-Json).runtime.stdout.Trim() -ne '27') { throw 'Expected replay result 27.' }
} finally { Remove-Item -LiteralPath $artifact -ErrorAction SilentlyContinue }
Write-Output 'Native launcher compilation, execution and artifact replay passed.'
