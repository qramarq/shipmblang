param(
    [Parameter(Mandatory=$true)][string]$CompilerRoot,
    [string]$Generator = ''
)
$ErrorActionPreference = 'Stop'
$source = Join-Path (Resolve-Path -LiteralPath $CompilerRoot).Path 'cpp'
if (-not (Test-Path -LiteralPath (Join-Path $source 'CMakeLists.txt'))) {
    throw 'CompilerRoot must point to your privately supplied compiler source folder containing cpp/CMakeLists.txt.'
}
$build = Join-Path $PSScriptRoot 'build'
$arguments = @('-S', $source, '-B', $build, '-DCMAKE_BUILD_TYPE=Release')
if ($Generator) { $arguments += @('-G', $Generator) }
& cmake @arguments
if ($LASTEXITCODE -ne 0) { throw 'Native CMake configuration failed.' }
& cmake --build $build --config Release
if ($LASTEXITCODE -ne 0) { throw 'Native compilation failed.' }
& ctest --test-dir $build -C Release --output-on-failure
if ($LASTEXITCODE -ne 0) { throw 'Native compiler tests failed.' }
$binary = @((Join-Path $build 'Release/shipmbc_cpp.exe'), (Join-Path $build 'shipmbc_cpp.exe')) |
    Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $binary) { throw 'Build succeeded but shipmbc_cpp.exe was not found.' }
$bin = Join-Path $PSScriptRoot 'bin'
New-Item -ItemType Directory -Force -Path $bin | Out-Null
Copy-Item -LiteralPath $binary -Destination (Join-Path $bin 'shipmbc_cpp.exe')
Write-Output "Native compiler ready: $bin/shipmbc_cpp.exe"
