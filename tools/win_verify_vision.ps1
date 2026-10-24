# Windows x64 verification for native vision.
# PowerShell 5. Run from any directory:
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\admin\shipmb-worker\shipmblang\tools\win_verify_vision.ps1
# Writes C:\Users\admin\shipmb-worker\logs\win-verify.txt

$ErrorActionPreference = 'Stop'
Set-Location 'C:\Users\admin\shipmb-worker\shipmblang'
$Root = (Get-Location).Path
$LogDir = 'C:\Users\admin\shipmb-worker\logs'
$Py = 'C:\Python314\python.exe'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Summary = Join-Path $LogDir 'win-verify.txt'
$Helper = Join-Path $LogDir 'win-vision-check.py'
Set-Content -Path $Summary -Encoding ASCII -Value 'win-verify start'

function Note([string]$line) {
    Add-Content -Path $Summary -Encoding ASCII -Value $line
    Write-Host $line
}

function Check([string]$step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$step failed with exit $LASTEXITCODE"
    }
}

$savedPath = $env:PATH
$hadPythonPath = Test-Path Env:PYTHONPATH
$savedPythonPath = $env:PYTHONPATH

try {
    if (-not (Test-Path $Py)) {
        throw "Python was not found at $Py"
    }
    $sha = & git rev-parse HEAD
    Check 'git rev-parse'
    Note "sha=$($sha.Trim())"
    Note "root=$Root"

    & git -c core.autocrlf=false checkout HEAD -- native/shipmb_vision .gitattributes
    Check 'refresh line endings'

    if (Test-Path 'native\shipmb_vision\build') {
        Remove-Item -Recurse -Force 'native\shipmb_vision\build'
    }
    $buildStart = Get-Date
    & $Py tools\build_vision.py > (Join-Path $LogDir 'build.txt') 2>&1
    Check 'build_vision'
    $buildSeconds = [int]((Get-Date) - $buildStart).TotalSeconds
    Note "build=ok seconds=$buildSeconds"

    & ctest --test-dir native\shipmb_vision\build -C Release --output-on-failure > (Join-Path $LogDir 'ctest.txt') 2>&1
    Check 'ctest'
    Note 'ctest=ok'

    & $Py -m unittest discover -s tests > (Join-Path $LogDir 'unittest.txt') 2>&1
    Check 'unittest'
    Note 'unittest=ok'

    $env:PYTHONPATH = $Root
    & $Py tests\test_compiler_sync.py > (Join-Path $LogDir 'compiler-sync.txt') 2>&1
    $syncCode = $LASTEXITCODE
    if ($hadPythonPath) {
        $env:PYTHONPATH = $savedPythonPath
    } else {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    }
    if ($syncCode -ne 0) {
        throw "compiler sync failed with exit $syncCode"
    }
    Note 'compiler_sync=ok'

    $setupStart = Get-Date
    & $Py -m shipmblang setup --vision --yes > (Join-Path $LogDir 'setup1.txt') 2>&1
    Check 'setup --vision first'
    $setupSeconds = [int]((Get-Date) - $setupStart).TotalSeconds
    Note "setup1=ok seconds=$setupSeconds"

    & $Py -m shipmblang setup --vision --yes > (Join-Path $LogDir 'setup2.txt') 2>&1
    Check 'setup --vision second'
    $second = Get-Content -Raw (Join-Path $LogDir 'setup2.txt')
    if ($second -notmatch 'already installed') {
        throw 'second setup did not report already installed'
    }
    if ($second -notmatch 'already quantized') {
        throw 'second setup did not report already quantized'
    }
    Note 'setup2=idempotent'

    $cache = Join-Path $env:LOCALAPPDATA 'shipmblang\vision'
    $expected = @{
        'MiniCPM-V-4_6-Q4_K_M.gguf' = '6b0c74962c44bc6bf4b655b9b02c13eda9d5a0491543ae976d1ac18e4b7892e2'
        'mmproj-model-f16.gguf' = 'ca931d861d0801d9003e50697cd764721a334107c0e0415a51168ee1938462de'
        'mmproj-model-q8_0.gguf' = 'cc6e95b117ade93ca9dfc5a81998d14a19b9ae8ce4eb44658a20b55407a7d54f'
    }
    foreach ($name in $expected.Keys) {
        $path = Join-Path $cache $name
        if (-not (Test-Path $path)) {
            throw "missing weight $path"
        }
        $hash = (Get-FileHash -Algorithm SHA256 -Path $path).Hash.ToLower()
        if ($hash -ne $expected[$name]) {
            throw "hash mismatch $name got $hash"
        }
        Note "hash=$name ok bytes=$((Get-Item $path).Length)"
    }

    @'
import struct
import sys
import zlib
from pathlib import Path

LOG = Path(r"C:\Users\admin\shipmb-worker\logs")


def write_png(path, width, height, red):
    rows = []
    y = 0
    while y < height:
        pixel = bytes((red, (y + red) % 256, 96))
        rows.append(b"\x00" + pixel * width)
        y += 1
    raw = b"".join(rows)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def prepare():
    image = LOG / "vision-sample.png"
    write_png(image, 448, 448, 20)
    program = LOG / "photo.shipmb"
    program.write_text('Look at "' + image.as_posix() + '" and tell me what is in it.\n', encoding="ascii")
    warm = LOG / "warm"
    warm.mkdir(exist_ok=True)
    index = 0
    while index < 12:
        write_png(warm / ("img%02d.png" % index), 448, 448, 30 + index * 17)
        index += 1
    print(program.as_posix())
    print(image.as_posix())


def nearest_rank_p95(samples):
    ordered = sorted(samples)
    index = max(0, round(0.95 * len(ordered) + 0.5) - 1)
    return ordered[index], index


def latency():
    from shipmblang.standalone import activate_packed_vision_library
    from shipmblang._compiler.vision import VisionEngine

    activate_packed_vision_library()
    images = []
    index = 0
    while index < 12:
        images.append(LOG / "warm" / ("img%02d.png" % index))
        index += 1
    engine = VisionEngine(n_threads=0, max_tokens=16, flash_attn=True, warmup=True, use_gpu=False)
    try:
        rows = []
        index = 0
        while index < len(images):
            prompt = "What is in this image? Reply with one short noun. Variant %d." % index
            payload = engine.query(images[index], prompt, max_tokens=16)
            if not payload.get("ok"):
                print("query failed", payload)
                sys.exit(1)
            rows.append(payload)
            index += 1
    finally:
        engine.close()
    cold = rows[0]
    warm = rows[1:]
    samples = [float(item["elapsed_ms"]) for item in warm]
    ordered = sorted(samples)
    if len(ordered) % 2:
        median = ordered[len(ordered) // 2]
    else:
        median = (ordered[len(ordered) // 2 - 1] + ordered[len(ordered) // 2]) / 2
    p95, rank = nearest_rank_p95(samples)
    flags = []
    for item in warm:
        if item.get("cached"):
            flags.append("true")
        else:
            flags.append("false")
    flag_text = ",".join(flags)
    print(
        "WARM n=%d median=%.1f p95=%.1f index=%d cold=%.1f cached=%s"
        % (len(samples), median, p95, rank, float(cold["elapsed_ms"]), flag_text)
    )
    if len(samples) < 10 or p95 >= 2000 or "true" in flags:
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(2)
    if sys.argv[1] == "prepare":
        prepare()
    elif sys.argv[1] == "latency":
        latency()
    else:
        sys.exit(2)
'@ | Set-Content -Path $Helper -Encoding ASCII

    & $Py $Helper prepare > (Join-Path $LogDir 'prepare.txt') 2>&1
    Check 'prepare images'
    $shipmb = Join-Path $LogDir 'photo.shipmb'
    if (-not (Test-Path $shipmb)) {
        throw "missing $shipmb"
    }

    & $Py -m shipmblang $shipmb --format text > (Join-Path $LogDir 'e2e.txt') 2> (Join-Path $LogDir 'e2e.err')
    Check 'e2e vision program'
    $answer = Get-Content -Raw (Join-Path $LogDir 'e2e.txt')
    if (-not $answer -or $answer.Trim().Length -lt 1) {
        throw 'e2e vision program produced no text'
    }
    Note 'e2e=ok'

    $latStart = Get-Date
    & $Py $Helper latency > (Join-Path $LogDir 'latency.txt') 2>&1
    $latCode = $LASTEXITCODE
    $latText = Get-Content (Join-Path $LogDir 'latency.txt')
    foreach ($latLine in $latText) {
        if ($latLine -like 'WARM *') {
            Note $latLine
        }
    }
    if ($latCode -ne 0) {
        throw "latency failed with exit $latCode"
    }
    $latSeconds = [int]((Get-Date) - $latStart).TotalSeconds
    Note "latency=ok seconds=$latSeconds"

    & $Py -m pip install pyinstaller > (Join-Path $LogDir 'pip-pyinstaller.txt') 2>&1
    Check 'pip install pyinstaller'
    & $Py tools\build_standalone.py --skip-editor > (Join-Path $LogDir 'standalone-build.txt') 2>&1
    Check 'build_standalone'
    $exe = Join-Path $Root 'dist\shipmblang.exe'
    if (-not (Test-Path $exe)) {
        throw "missing $exe"
    }
    Note "standalone_built=ok bytes=$((Get-Item $exe).Length)"

    $env:PATH = $savedPath
    $clean = @()
    foreach ($entry in ($env:PATH -split ';')) {
        if (-not $entry) {
            continue
        }
        $lower = $entry.ToLower()
        if ($lower.Contains('python') -or $lower.Contains('windowsapps')) {
            continue
        }
        $clean += $entry
    }
    $env:PATH = ($clean -join ';')
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    $pythonLeft = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonLeft) {
        throw "python is still on PATH at $($pythonLeft.Source)"
    }
    Note 'python_removed_from_path=ok'

    & $exe --version > (Join-Path $LogDir 'exe-version.txt') 2>&1
    Check 'exe --version'
    $versionText = Get-Content -Raw (Join-Path $LogDir 'exe-version.txt')
    if ($versionText -notmatch 'shipmblang') {
        throw 'exe --version did not print shipmblang'
    }
    Note "exe_version=$($versionText.Trim())"

    & $exe (Join-Path $Root 'examples\general_sum.shipmb') --format text > (Join-Path $LogDir 'exe-example.txt') 2> (Join-Path $LogDir 'exe-example.err')
    Check 'exe example'
    $exampleText = Get-Content -Raw (Join-Path $LogDir 'exe-example.txt')
    if ($exampleText -notmatch '27') {
        throw 'exe example did not print 27'
    }
    Note 'exe_example=ok'

    & $exe setup --vision --check > (Join-Path $LogDir 'exe-check.txt') 2>&1
    Check 'exe setup --vision --check'
    Note 'exe_setup_check=ok'

    & $exe $shipmb --format text > (Join-Path $LogDir 'exe-e2e.txt') 2> (Join-Path $LogDir 'exe-e2e.err')
    Check 'exe vision program'
    $exeAnswer = Get-Content -Raw (Join-Path $LogDir 'exe-e2e.txt')
    if (-not $exeAnswer -or $exeAnswer.Trim().Length -lt 1) {
        throw 'exe vision program produced no text'
    }
    Note 'exe_e2e=ok'

    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path $vswhere)) {
        throw "vswhere was not found at $vswhere"
    }
    $vsRoot = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    Check 'vswhere'
    $vsRoot = "$vsRoot".Trim()
    $dumpbins = @(Get-ChildItem -Path (Join-Path $vsRoot 'VC\Tools\MSVC') -Recurse -Filter dumpbin.exe | Where-Object { $_.FullName -like '*\Hostx64\x64\dumpbin.exe' })
    if ($dumpbins.Count -lt 1) {
        throw 'dumpbin.exe was not found under the VS x64 tools'
    }
    $dumpbin = $dumpbins[0].FullName
    Note "dumpbin=$dumpbin"

    $dll = Join-Path $Root 'shipmblang\_compiler\native\shipmb_vision.dll'
    $quant = Join-Path $Root 'shipmblang\_compiler\native\bin\llama-quantize.exe'
    if (-not (Test-Path $dll)) {
        throw "missing $dll"
    }
    if (-not (Test-Path $quant)) {
        throw "missing $quant"
    }

    function Show-Dependents([string]$label, [string]$path, [bool]$forbidRedist) {
        $lines = @(& $dumpbin /dependents $path)
        if ($LASTEXITCODE -ne 0) {
            throw "dumpbin failed for $path"
        }
        $blob = ($lines -join "`n")
        Set-Content -Path (Join-Path $LogDir "$label-dependents.txt") -Encoding ASCII -Value $blob
        $deps = @()
        foreach ($depLine in $lines) {
            $trim = $depLine.Trim()
            if ($trim -like '*.dll') {
                $deps += $trim
            }
        }
        Note ("dependents_" + $label + "=" + ($deps -join ','))
        if ($forbidRedist) {
            foreach ($banned in @('MSVCP140.dll', 'VCRUNTIME140.dll', 'VCRUNTIME140_1.dll')) {
                foreach ($dep in $deps) {
                    if ($dep.ToLower() -eq $banned.ToLower()) {
                        throw "$label depends on $banned"
                    }
                }
            }
            Note ("static_crt_" + $label + "=ok")
        }
    }

    Show-Dependents 'dll' $dll $true
    Show-Dependents 'quantize' $quant $true
    Show-Dependents 'exe' $exe $false
    Note 'RESULT: PASS'
}
catch {
    Note ("RESULT: FAIL " + $_.Exception.Message)
    throw
}
finally {
    $env:PATH = $savedPath
    if ($hadPythonPath) {
        $env:PYTHONPATH = $savedPythonPath
    }
}
