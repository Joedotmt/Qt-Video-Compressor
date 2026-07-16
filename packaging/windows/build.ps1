[CmdletBinding()]
param(
    [string] $PythonPath = "",
    [string] $IsccPath = "",
    [switch] $SkipInstaller
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$specPath = Join-Path $PSScriptRoot "video-compressor.spec"
$installerScript = Join-Path $PSScriptRoot "video-compressor.iss"
$distRoot = Join-Path $repoRoot "dist\windows"
$workRoot = Join-Path $repoRoot "build\windows"
$appDir = Join-Path $distRoot "VideoCompressor"
$installerDir = Join-Path $distRoot "installer"

function Find-UcrtPython {
    $candidates = [System.Collections.Generic.List[string]]::new()

    if ($PythonPath) {
        $candidates.Add($PythonPath)
    }

    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -ne $pythonCommand) {
        $candidates.Add($pythonCommand.Source)
    }

    $defaultMsysPython = "C:\msys64\ucrt64\bin\python.exe"
    if (Test-Path -LiteralPath $defaultMsysPython) {
        $candidates.Add($defaultMsysPython)
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (-not (Test-Path -LiteralPath $candidate)) {
            continue
        }

        $prefix = & $candidate -c "import sys; print(sys.prefix)"
        if ($LASTEXITCODE -ne 0) {
            continue
        }

        $normalizedPrefix = ($prefix | Select-Object -Last 1).Trim().Replace("\", "/").TrimEnd("/")
        if ($normalizedPrefix.EndsWith("/ucrt64", [System.StringComparison]::OrdinalIgnoreCase)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "MSYS2 UCRT64 Python was not found. Run this from an MSYS2 UCRT64 shell or pass -PythonPath."
}

function Find-Iscc {
    if ($IsccPath) {
        if (-not (Test-Path -LiteralPath $IsccPath)) {
            throw "ISCC.exe was not found at '$IsccPath'."
        }
        return (Resolve-Path -LiteralPath $IsccPath).Path
    }

    $isccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($null -ne $isccCommand) {
        return $isccCommand.Source
    }

    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "Inno Setup 6 was not found. Install it or pass -IsccPath."
}

$python = Find-UcrtPython
$originalPath = $env:PATH
$env:PATH = "$(Split-Path -Parent $python);$env:PATH"
$versionText = Get-Content -LiteralPath (Join-Path $repoRoot "main.py") -Raw
$versionMatch = [regex]::Match(
    $versionText,
    '(?m)^VERSION\s*=\s*["''](?<version>\d+\.\d+\.\d+(?:\.\d+)?)["'']\s*$'
)
if (-not $versionMatch.Success) {
    throw "Could not read a numeric VERSION from main.py."
}
$appVersion = $versionMatch.Groups["version"].Value

Push-Location $repoRoot
try {
    & $python -c "import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1'); from gi.repository import Adw, Gtk; import PyInstaller"
    if ($LASTEXITCODE -ne 0) {
        throw "The MSYS2 Python GTK/libadwaita/PyInstaller packages are incomplete."
    }

    & $python -m PyInstaller $specPath --noconfirm --distpath $distRoot --workpath $workRoot
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }

    $appExecutable = Join-Path $appDir "VideoCompressor.exe"
    if (-not (Test-Path -LiteralPath $appExecutable)) {
        throw "PyInstaller did not create '$appExecutable'."
    }

    $bundledFfmpeg = Get-ChildItem -LiteralPath $appDir -Recurse -File | Where-Object {
        $_.Name -in @("ffmpeg.exe", "ffprobe.exe")
    }
    if ($bundledFfmpeg) {
        throw "FFmpeg must remain an external dependency; it was found in the application bundle."
    }

    if ($SkipInstaller) {
        Write-Host "Application bundle: $appDir"
        return
    }

    $iscc = Find-Iscc
    & $iscc "/DAppVersion=$appVersion" $installerScript
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup failed with exit code $LASTEXITCODE."
    }

    $installerPath = Join-Path $installerDir "VideoCompressor-$appVersion-windows-x64.exe"
    if (-not (Test-Path -LiteralPath $installerPath)) {
        throw "Inno Setup did not create '$installerPath'."
    }

    $hash = Get-FileHash -LiteralPath $installerPath -Algorithm SHA256
    $checksumPath = "$installerPath.sha256"
    "$($hash.Hash.ToLowerInvariant())  $(Split-Path $installerPath -Leaf)" |
        Set-Content -LiteralPath $checksumPath -Encoding ascii

    Write-Host "Application bundle: $appDir"
    Write-Host "Installer: $installerPath"
    Write-Host "SHA-256: $checksumPath"
}
finally {
    $env:PATH = $originalPath
    Pop-Location
}
