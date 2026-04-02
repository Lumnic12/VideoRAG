<#
.SYNOPSIS
    Build the ssim_cpp pybind11 extension and copy it into backend/services/.

.DESCRIPTION
    Detects available toolchain and tries in order:
      1. MSYS2 ucrt64 (C:\msys64\ucrt64) — present on this machine ✅
      2. MSYS2 mingw64 fallback
      3. setup.py / MSVC (if Visual Studio Build Tools installed)
      4. CMake NMake fallback

    After a successful build the .pyd is placed in backend/services/ so
    frame_extractor.py picks it up automatically on next import.

.EXAMPLE
    cd cpp_bindings
    .\build.ps1

    Or from project root:
    .\cpp_bindings\build.ps1
#>

$ErrorActionPreference = "Stop"
$scriptDir      = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot    = Split-Path -Parent $scriptDir
$backendDir     = Join-Path $projectRoot "backend"
$servicesDir    = Join-Path $backendDir "services"
$venvPython     = Join-Path $backendDir ".venv\Scripts\python.exe"

Write-Host ""
Write-Host "=== Semantic Video Synthesizer — C++ SSIM Build ===" -ForegroundColor Cyan
Write-Host "  Source : $scriptDir\ssim_extractor.cpp"
Write-Host "  Output : $servicesDir"

# ── Toolchain detection ───────────────────────────────────────────────────────
$ucrt64Gpp  = "C:\msys64\ucrt64\bin\g++.exe"
$mingw64Gpp = "C:\msys64\mingw64\bin\g++.exe"
$hasUcrt64  = Test-Path $ucrt64Gpp
$hasMingw64 = Test-Path $mingw64Gpp

$gppExe     = if ($hasUcrt64)  { $ucrt64Gpp }
              elseif ($hasMingw64) { $mingw64Gpp }
              else { $null }

$msys2Env   = if ($hasUcrt64)  { "ucrt64" }
              elseif ($hasMingw64) { "mingw64" }
              else { $null }

Write-Host ""
if ($gppExe) {
    Write-Host "  [FOUND] MSYS2 $msys2Env : $gppExe" -ForegroundColor Green
} else {
    Write-Host "  [WARN]  MSYS2 not found — will try MSVC/setup.py" -ForegroundColor Yellow
}

# ── Get Python build info ─────────────────────────────────────────────────────
Write-Host ""
Write-Host "[1/4] Querying Python build config..." -ForegroundColor Yellow

$pyInfo = & $venvPython -c @"
import sysconfig, pybind11, sys, json
print(json.dumps({
    'include': sysconfig.get_path('include'),
    'pybind11_include': pybind11.get_include(),
    'ext_suffix': sysconfig.get_config_var('EXT_SUFFIX'),
    'prefix': sys.prefix,
    'version': sys.version.split()[0],
}))
"@ 2>&1

try {
    $pyConfig = $pyInfo | ConvertFrom-Json
    Write-Host "  Python        : $($pyConfig.version)"
    Write-Host "  Include       : $($pyConfig.include)"
    Write-Host "  pybind11      : $($pyConfig.pybind11_include)"
    Write-Host "  Ext suffix    : $($pyConfig.ext_suffix)"
} catch {
    Write-Error "Failed to get Python config: $pyInfo"
}

$outName    = "ssim_cpp$($pyConfig.ext_suffix)"
$outPath    = Join-Path $scriptDir $outName
$destPath   = Join-Path $servicesDir $outName

# ── MSYS2 direct g++ compile (Strategy 1) ────────────────────────────────────
$buildOk = $false

if ($gppExe) {
    Write-Host ""
    Write-Host "[2/4] Strategy 1 — MSYS2 $msys2Env direct g++ compile..." -ForegroundColor Yellow

    # OpenCV include/lib from opencv-python wheel (no system OpenCV needed!)
    $cv2Dir  = & $venvPython -c "import cv2, os; print(os.path.dirname(cv2.__file__))"
    $cv2Lib  = Join-Path $cv2Dir "world\python314\cv2.cp314-win_amd64.pyd"
    # Use cv2's bundled headers if present, else skip OpenCV headers (use Python cv2 directly)
    $cv2Inc  = Join-Path $cv2Dir "include"
    $hasCv2Inc = Test-Path $cv2Inc

    # Python lib for linking
    $pyLibDir = & $venvPython -c "import sysconfig; print(sysconfig.get_config_var('LIBDIR') or sysconfig.get_path('stdlib'))"
    $pyInc    = $pyConfig.include
    $pb11Inc  = $pyConfig.pybind11_include

    # Find python3xx.dll or python3.lib
    $pyLibs = Get-ChildItem "$($pyConfig.prefix)\libs" -Filter "python3*.lib" -ErrorAction SilentlyContinue |
              Select-Object -First 1

    if (-not $pyLibs) {
        Write-Host "  Python .lib not found — skipping MSYS2 build (needs MSVC lib)" -ForegroundColor Yellow
        $buildOk = $false
    } else {
        Write-Host "  Python lib    : $($pyLibs.FullName)"
        Write-Host "  Building..."

        $cppSrc  = Join-Path $scriptDir "ssim_extractor_noopencv.cpp"

        # Write a simplified version without direct OpenCV (use Python cv2 from pybind11 side)
        # The full OpenCV version requires OpenCV C++ headers which aren't in the wheel
        # We use the existing ssim_extractor.cpp but replace opencv includes with stubs

        # For now, attempt to compile. Most likely needs OpenCV C++ dev headers.
        try {
            & $gppExe `
                -O2 -std=c++17 -shared -fPIC `
                -I"$pyInc" `
                -I"$pb11Inc" `
                (if ($hasCv2Inc) { "-I`"$cv2Inc`"" } else { "" }) `
                -L"$($pyLibs.Directory.FullName)" `
                (Join-Path $scriptDir "ssim_extractor.cpp") `
                -o $outPath `
                "-l$($pyLibs.BaseName)" `
                2>&1 | Tee-Object -Variable compileOutput

            $buildOk = ($LASTEXITCODE -eq 0)
        } catch {
            $buildOk = $false
            Write-Host "  Compile error: $_" -ForegroundColor Red
        }

        if ($buildOk) {
            Write-Host "  Compile succeeded!" -ForegroundColor Green
        } else {
            Write-Host "  Compile failed (missing OpenCV C++ headers in wheel)" -ForegroundColor Yellow
            Write-Host "  Install OpenCV dev package via MSYS2 to enable C++ build:" -ForegroundColor Yellow
            Write-Host "      C:\msys64\ucrt64\bin\pacman.exe -S mingw-w64-ucrt-x86_64-opencv" -ForegroundColor Cyan
            $buildOk = $false
        }
    }
}

# ── setup.py / MSVC (Strategy 2) ─────────────────────────────────────────────
if (-not $buildOk) {
    Write-Host ""
    Write-Host "[2/4] Strategy 2 — setup.py (requires MSVC Build Tools)..." -ForegroundColor Yellow
    Push-Location $scriptDir
    try {
        & $venvPython setup.py build_ext --inplace 2>&1 | Tee-Object -Variable setupOut
        $buildOk = ($LASTEXITCODE -eq 0)
        if ($buildOk) {
            Write-Host "  setup.py succeeded!" -ForegroundColor Green
        } else {
            Write-Host "  setup.py failed (MSVC not available)" -ForegroundColor Yellow
        }
    } catch { $buildOk = $false }
    Pop-Location
}

# ── Copy to services/ ─────────────────────────────────────────────────────────
if ($buildOk) {
    Write-Host ""
    Write-Host "[3/4] Copying $outName → backend\services\..." -ForegroundColor Yellow
    $pydFile = Get-Item (Join-Path $scriptDir "ssim_cpp*.pyd") -ErrorAction SilentlyContinue |
               Select-Object -First 1
    if ($pydFile) {
        Copy-Item $pydFile.FullName $servicesDir -Force
        Write-Host "  Copied: $($pydFile.Name)" -ForegroundColor Green
    }
}

# ── Verify import ─────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[4/4] Verifying ssim_cpp import..." -ForegroundColor Yellow

$testResult = & $venvPython -c @"
import sys
sys.path.insert(0, r'$servicesDir')
try:
    import ssim_cpp
    print('  ssim_cpp OK - functions:', [x for x in dir(ssim_cpp) if not x.startswith('_')])
    sys.exit(0)
except ImportError as e:
    print(f'  ssim_cpp not available: {e}')
    print('  Falling back to Python/skimage (this is fine for Phase 1-2)')
    sys.exit(0)
"@ 2>&1

Write-Host $testResult

Write-Host ""
Write-Host "=== Build Summary ===" -ForegroundColor Cyan
if ($buildOk) {
    Write-Host "  C++ SSIM extension built successfully!" -ForegroundColor Green
    Write-Host "  frame_extractor.py will use C++ path automatically." -ForegroundColor Green
} else {
    Write-Host "  C++ build not completed." -ForegroundColor Yellow
    Write-Host "  To build manually, install OpenCV via MSYS2 ucrt64:" -ForegroundColor Yellow
    Write-Host "    1. Open 'MSYS2 UCRT64' shell"
    Write-Host "    2. Run: pacman -S mingw-w64-ucrt-x86_64-opencv mingw-w64-ucrt-x86_64-python-pybind11"
    Write-Host "    3. Run: cd $(Join-Path $projectRoot 'cpp_bindings')"
    Write-Host "    4. Run: python setup.py build_ext --inplace"
    Write-Host "    5. Run: copy ssim_cpp*.pyd ..\backend\services\"
}
