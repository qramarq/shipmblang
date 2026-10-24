# Windows x64 verification for the portable zip.
# PowerShell 5. Run from any directory:
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\admin\shipmb-worker\shipmblang\tools\win_verify_portable.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\admin\shipmb-worker\shipmblang\tools\win_verify_portable.ps1 -Python C:\Python314\python.exe
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\admin\shipmb-worker\shipmblang\tools\win_verify_portable.ps1 -WithWeights
# -WithWeights also builds the heavy zip. The default run only checks the cached weights.
# Writes C:\Users\admin\shipmb-worker\logs\win-verify-portable.txt

param(
    [string]$Python = 'C:\Python314\python.exe',
    [switch]$WithWeights
)

# PowerShell 5 turns redirected native stderr into terminating errors under 'Stop'.
# Native exit codes are checked explicitly with Check. Cmdlets still stop.
$ErrorActionPreference = 'Continue'
$PSDefaultParameterValues['*:ErrorAction'] = 'Stop'
Set-Location -ErrorAction Stop 'C:\Users\admin\shipmb-worker\shipmblang'
$Root = (Get-Location).Path
$LogDir = 'C:\Users\admin\shipmb-worker\logs'
$Py = $Python
New-Item -ItemType Directory -Force -ErrorAction Stop -Path $LogDir | Out-Null
$Summary = Join-Path $LogDir 'win-verify-portable.txt'
$Helper = Join-Path $LogDir 'win-portable-check.py'
Set-Content -ErrorAction Stop -Path $Summary -Encoding ASCII -Value 'win-verify-portable start'

function Note([string]$line) {
    Add-Content -ErrorAction Stop -Path $Summary -Encoding ASCII -Value $line
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
$hadPythonHome = Test-Path Env:PYTHONHOME
$savedPythonHome = $env:PYTHONHOME
$hadVirtualEnv = Test-Path Env:VIRTUAL_ENV
$savedVirtualEnv = $env:VIRTUAL_ENV
$hadLocal = Test-Path Env:LOCALAPPDATA
$savedLocal = $env:LOCALAPPDATA
$savedVision = @{}
Get-ChildItem Env: | Where-Object { $_.Name -like 'SHIPMB_VISION_*' } | ForEach-Object {
    $savedVision[$_.Name] = $_.Value
}

try {
    if (-not (Test-Path $Py)) {
        throw "Python was not found at $Py"
    }
    $Py = (Resolve-Path $Py).Path
    Note "python=$Py"
    $sha = & git rev-parse HEAD
    Check 'git rev-parse'
    Note "sha=$($sha.Trim())"
    Note "root=$Root"
    if ($WithWeights) {
        Note 'with_weights=requested'
    } else {
        Note 'with_weights=skipped'
    }

    & $Py -m pip install pyinstaller > (Join-Path $LogDir 'portable-pip.txt') 2>&1
    Check 'pip install pyinstaller'

    $buildLog = Join-Path $LogDir 'portable-build.txt'
    $buildArgs = @('tools\build_portable.py')
    if ($WithWeights) {
        $buildArgs += '--with-weights'
    }
    & $Py @buildArgs > $buildLog 2>&1
    Check 'build_portable'

    $portableZip = ''
    $heavyZip = ''
    foreach ($line in (Get-Content -ErrorAction Stop $buildLog)) {
        if ($line -like 'SIZE *') {
            Note $line
        }
        if ($line -like 'portable_zip *') {
            $portableZip = $line.Substring(13).Trim()
        }
        if ($line -like 'with_weights_zip *') {
            $heavyZip = $line.Substring(17).Trim()
        }
    }
    if (-not $portableZip) {
        throw 'the build did not print portable_zip'
    }
    if (-not (Test-Path $portableZip)) {
        throw "missing $portableZip"
    }
    Note "default_zip=$portableZip"
    $required = @(
        'SIZE default_zip_bytes=',
        'SIZE default_unzipped_bytes=',
        'SIZE with_weights_zip_bytes=',
        'SIZE with_weights_unzipped_bytes=',
        'SIZE exe_and_python_uncompressed_bytes=',
        'SIZE exe_and_python_compressed_bytes=',
        'SIZE vision_dll_uncompressed_bytes=',
        'SIZE vision_dll_compressed_bytes=',
        'SIZE llama_quantize_uncompressed_bytes=',
        'SIZE llama_quantize_compressed_bytes=',
        'SIZE vc_runtime_uncompressed_bytes=',
        'SIZE vc_runtime_compressed_bytes=',
        'SIZE vc_vcruntime140_uncompressed_bytes=',
        'SIZE vc_vcruntime140_1_uncompressed_bytes=',
        'SIZE vc_msvcp140_uncompressed_bytes=',
        'SIZE weight_llm_bytes=',
        'SIZE weight_f16_bytes=',
        'SIZE weight_q8_bytes=',
        'SIZE download_bytes=',
        'SIZE weights_on_disk_bytes=',
        'SIZE disk_after_setup_bytes=',
        'SIZE top 1 '
    )
    $buildText = Get-Content -Raw -ErrorAction Stop $buildLog
    foreach ($token in $required) {
        if ($buildText.IndexOf($token) -lt 0) {
            throw "build log is missing $token"
        }
    }
    if ($WithWeights) {
        if ($buildText.IndexOf('SIZE with_weights_zip_bytes=not_built') -ge 0) {
            throw 'with-weights zip was requested but the log says not_built'
        }
        if (-not $heavyZip -or -not (Test-Path $heavyZip)) {
            throw 'the with-weights zip was not written'
        }
        Note "with_weights_zip=$heavyZip"
    } else {
        if ($buildText.IndexOf('SIZE with_weights_zip_bytes=not_built') -lt 0) {
            throw 'the default build should leave the with-weights zip as not_built'
        }
    }

    $checkLog = Join-Path $LogDir 'portable-check-weights.txt'
    & $Py tools\build_portable.py --check-weights > $checkLog 2>&1
    Check 'check-weights'
    $realCache = ''
    foreach ($line in (Get-Content -ErrorAction Stop $checkLog)) {
        if ($line -like 'weights_ok *') {
            $realCache = $line.Substring(11).Trim()
        }
        if ($line -like 'SIZE *') {
            Note $line
        }
    }
    if (-not $realCache) {
        throw 'check-weights did not print weights_ok. Run shipmblang setup --vision once so the cache exists.'
    }
    Note "weight_cache=$realCache"

    @'
import struct
import sys
import zipfile
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
    image = LOG / "portable-sample.png"
    write_png(image, 448, 448, 20)
    program = LOG / "portable-photo.shipmb"
    program.write_text('Look at "' + image.as_posix() + '" and tell me what is in it.\n', encoding="ascii")
    warm = LOG / "portable-warm"
    warm.mkdir(exist_ok=True)
    index = 0
    while index < 12:
        write_png(warm / ("img%02d.png" % index), 448, 448, 30 + index * 17)
        index += 1
    print(program.as_posix())


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
        images.append(LOG / "portable-warm" / ("img%02d.png" % index))
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
        "WARM n=%d median=%.1f p95=%.1f index=%d cold=%.1f cached=%s method=in-process"
        % (len(samples), median, p95, rank, float(cold["elapsed_ms"]), flag_text)
    )
    if len(samples) < 11 or p95 >= 2000 or "true" in flags:
        sys.exit(1)


def zipcheck():
    kind = sys.argv[2]
    path = sys.argv[3]
    with zipfile.ZipFile(path) as archive:
        names = [info.filename.replace("\\", "/") for info in archive.infolist()]
    gguf = [name for name in names if name.lower().endswith(".gguf")]
    bases = [name.rsplit("/", 1)[-1] for name in gguf]
    if kind == "default":
        if gguf:
            print("default zip contains weights: " + ", ".join(gguf))
            sys.exit(1)
        print("default_zip_gguf=none")
        return
    needed = ["MiniCPM-V-4_6-Q4_K_M.gguf", "mmproj-model-q8_0.gguf"]
    for name in needed:
        if name not in bases:
            print("with-weights zip is missing " + name)
            sys.exit(1)
    if "mmproj-model-f16.gguf" in bases:
        print("with-weights zip contains the f16 projector")
        sys.exit(1)
    print("with_weights_zip_gguf=llm,q8")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(2)
    if sys.argv[1] == "prepare":
        prepare()
    elif sys.argv[1] == "latency":
        latency()
    elif sys.argv[1] == "zipcheck":
        zipcheck()
    else:
        sys.exit(2)
'@ | Set-Content -ErrorAction Stop -Path $Helper -Encoding ASCII

    & $Py $Helper zipcheck default $portableZip > (Join-Path $LogDir 'portable-zipcheck.txt') 2>&1
    Check 'default zip has no weights'
    Note 'default_zip_gguf=none'
    if ($WithWeights) {
        & $Py $Helper zipcheck weights $heavyZip > (Join-Path $LogDir 'portable-zipcheck-weights.txt') 2>&1
        Check 'with-weights zip contents'
        Note 'with_weights_zip_gguf=llm,q8'
    }

    $tempRoot = Join-Path $env:TEMP ('shipmblang-portable-' + [guid]::NewGuid().ToString('n'))
    New-Item -ItemType Directory -Force -ErrorAction Stop -Path $tempRoot | Out-Null
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
    if (-not (Test-Path $tar)) {
        throw "tar.exe was not found at $tar"
    }
    & $tar -xf $portableZip -C $tempRoot
    Check 'extract default zip'
    Note "extracted=$tempRoot"

    $tempLocal = Join-Path $tempRoot 'localappdata'
    New-Item -ItemType Directory -Force -ErrorAction Stop -Path $tempLocal | Out-Null
    $env:PATH = 'C:\Windows\System32;C:\Windows'
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
    Get-ChildItem Env: | Where-Object { $_.Name -like 'SHIPMB_VISION_*' } | ForEach-Object {
        Remove-Item -ErrorAction SilentlyContinue "Env:$($_.Name)"
    }
    $env:LOCALAPPDATA = $tempLocal
    Note 'clean_env=PATH is System32 and Windows; LOCALAPPDATA is empty; SHIPMB_VISION_* cleared'

    $exes = @(Get-ChildItem -Path $tempRoot -Recurse -Filter shipmblang.exe)
    if ($exes.Count -ne 1) {
        throw "expected one shipmblang.exe, found $($exes.Count)"
    }
    $exe = $exes[0].FullName
    Note "exe=$exe"
    $bad = @(Get-ChildItem -Path $tempRoot -Recurse -File | Where-Object { $_.Extension -in '.pdb', '.lib', '.exp' })
    if ($bad.Count -ne 0) {
        throw "debug files are in the zip: $($bad[0].FullName)"
    }
    $packedGguf = @(Get-ChildItem -Path $tempRoot -Recurse -Filter *.gguf -File)
    if ($packedGguf.Count -ne 0) {
        throw 'extracted default zip contains a gguf'
    }

    & $exe --version > (Join-Path $LogDir 'portable-version.txt') 2>&1
    Check 'exe --version'
    $versionText = Get-Content -Raw (Join-Path $LogDir 'portable-version.txt')
    if ($versionText -notmatch 'shipmblang') {
        throw 'exe --version did not print shipmblang'
    }
    Note "exe_version=$($versionText.Trim())"

    & $exe (Join-Path $Root 'examples\general_sum.shipmb') --format text > (Join-Path $LogDir 'portable-example.txt') 2>&1
    Check 'exe example'
    $exampleText = Get-Content -Raw (Join-Path $LogDir 'portable-example.txt')
    if ($exampleText -notmatch '27') {
        throw 'exe example did not print 27'
    }
    Note 'exe_example=ok'

    $checkOut = Join-Path $LogDir 'portable-setup-check.txt'
    & $exe setup --vision --check > $checkOut 2>&1
    $checkCode = $LASTEXITCODE
    $checkText = Get-Content -Raw $checkOut
    if ($checkCode -ne 1) {
        throw "setup --vision --check exited $checkCode, expected 1 while weights are missing"
    }
    if ($checkText -notmatch 'missing') {
        throw 'setup --vision --check did not report missing weights'
    }
    Note 'setup_check_missing=ok'

    $destCache = Join-Path $tempLocal 'shipmblang\vision'
    New-Item -ItemType Directory -Force -ErrorAction Stop -Path $destCache | Out-Null
    foreach ($name in @('MiniCPM-V-4_6-Q4_K_M.gguf', 'mmproj-model-f16.gguf', 'mmproj-model-q8_0.gguf')) {
        $source = Join-Path $realCache $name
        if (-not (Test-Path $source)) {
            throw "missing cached weight $source"
        }
        Copy-Item -ErrorAction Stop -Path $source -Destination (Join-Path $destCache $name)
    }
    Note 'weights_copied=ok'

    & $exe setup --vision --yes > (Join-Path $LogDir 'portable-setup.txt') 2>&1
    Check 'exe setup --vision'
    $setupText = Get-Content -Raw (Join-Path $LogDir 'portable-setup.txt')
    if ($setupText -notmatch 'already installed') {
        throw 'setup did not report already installed'
    }
    if ($setupText -notmatch 'already quantized') {
        throw 'setup did not report already quantized'
    }
    Note 'setup_hash_check=ok'

    & $Py $Helper prepare > (Join-Path $LogDir 'portable-prepare.txt') 2>&1
    Check 'prepare images'
    $shipmb = Join-Path $LogDir 'portable-photo.shipmb'
    if (-not (Test-Path $shipmb)) {
        throw "missing $shipmb"
    }
    $e2eStart = Get-Date
    & $exe $shipmb --format text > (Join-Path $LogDir 'portable-e2e.txt') 2>&1
    Check 'exe vision program'
    $e2eSeconds = [int]((Get-Date) - $e2eStart).TotalSeconds
    $answer = Get-Content -Raw (Join-Path $LogDir 'portable-e2e.txt')
    if (-not $answer -or $answer.Trim().Length -lt 1) {
        throw 'exe vision program produced no text'
    }
    Note "exe_e2e=ok seconds=$e2eSeconds includes_model_load=yes"

    $env:PYTHONPATH = $Root
    $latStart = Get-Date
    & $Py $Helper latency > (Join-Path $LogDir 'portable-latency.txt') 2>&1
    $latCode = $LASTEXITCODE
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    foreach ($latLine in (Get-Content (Join-Path $LogDir 'portable-latency.txt'))) {
        if ($latLine -like 'WARM *') {
            Note $latLine
        }
    }
    if ($latCode -ne 0) {
        throw "in-process latency failed with exit $latCode"
    }
    $latSeconds = [int]((Get-Date) - $latStart).TotalSeconds
    Note "latency=ok seconds=$latSeconds method=in-process"

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

    $dlls = @(Get-ChildItem -Path $tempRoot -Recurse -Filter shipmb_vision.dll)
    $quants = @(Get-ChildItem -Path $tempRoot -Recurse -Filter llama-quantize.exe)
    if ($dlls.Count -ne 1) {
        throw "expected one shipmb_vision.dll, found $($dlls.Count)"
    }
    if ($quants.Count -ne 1) {
        throw "expected one llama-quantize.exe, found $($quants.Count)"
    }
    $exeDir = Split-Path -Parent $exe
    foreach ($vcName in @('vcruntime140.dll', 'vcruntime140_1.dll')) {
        $beside = Join-Path $exeDir $vcName
        if (-not (Test-Path $beside)) {
            throw "missing $beside"
        }
    }

    $packedNames = @{}
    Get-ChildItem -Path $tempRoot -Recurse -File | ForEach-Object {
        $packedNames[$_.Name.ToLower()] = $true
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
            if ($depLine -match '^\s+\S+\.dll\s*$') {
                $deps += $depLine.Trim()
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
        } else {
            foreach ($dep in $deps) {
                $lower = $dep.ToLower()
                $redist = @('vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll')
                if ($redist -contains $lower) {
                    if (-not $packedNames.ContainsKey($lower)) {
                        throw "$label depends on $dep but the zip does not contain it"
                    }
                    continue
                }
                if ($lower.StartsWith('api-ms-win-') -or $lower.StartsWith('ext-ms-win-')) {
                    continue
                }
                if ($packedNames.ContainsKey($lower)) {
                    continue
                }
                $system = Join-Path 'C:\Windows\System32' $dep
                $windows = Join-Path 'C:\Windows' $dep
                if (-not (Test-Path $system) -and -not (Test-Path $windows)) {
                    throw "$label depends on $dep, which is not in the zip or in Windows"
                }
            }
            Note 'exe_dependents=ok'
        }
    }

    Show-Dependents 'dll' $dlls[0].FullName $true
    Show-Dependents 'quantize' $quants[0].FullName $true
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
    } else {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    }
    if ($hadPythonHome) {
        $env:PYTHONHOME = $savedPythonHome
    } else {
        Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    }
    if ($hadVirtualEnv) {
        $env:VIRTUAL_ENV = $savedVirtualEnv
    } else {
        Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue
    }
    if ($hadLocal) {
        $env:LOCALAPPDATA = $savedLocal
    } else {
        Remove-Item Env:LOCALAPPDATA -ErrorAction SilentlyContinue
    }
    Get-ChildItem Env: | Where-Object { $_.Name -like 'SHIPMB_VISION_*' } | ForEach-Object {
        Remove-Item -ErrorAction SilentlyContinue "Env:$($_.Name)"
    }
    foreach ($name in $savedVision.Keys) {
        Set-Item -ErrorAction Stop -Path "Env:$name" -Value $savedVision[$name]
    }
}
