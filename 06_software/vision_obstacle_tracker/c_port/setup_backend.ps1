param(
    [switch]$Force,
    [switch]$InstallBuildTools
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ThirdPartyDir = Join-Path $ScriptDir "third_party"
$DownloadDir = Join-Path $ThirdPartyDir "downloads"

$OnnxVersion = "1.26.0"
$OnnxZipName = "onnxruntime-win-x64-$OnnxVersion.zip"
$OnnxUrl = "https://github.com/microsoft/onnxruntime/releases/download/v$OnnxVersion/$OnnxZipName"
$OnnxSize = 75675381

$OpenCvVersion = "4.13.0"
$OpenCvExeName = "opencv-$OpenCvVersion-windows.exe"
$OpenCvUrl = "https://github.com/opencv/opencv/releases/download/$OpenCvVersion/$OpenCvExeName"
$OpenCvSize = 194496264

function Ensure-Dir($Path) {
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Assert-Under($Root, $Path) {
    $rootFull = [System.IO.Path]::GetFullPath($Root)
    $pathFull = [System.IO.Path]::GetFullPath($Path)
    if (-not $pathFull.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside root: $pathFull"
    }
}

function Download-File($Url, $Output, $ExpectedSize) {
    if ((Test-Path -LiteralPath $Output) -and -not $Force) {
        $actual = (Get-Item -LiteralPath $Output).Length
        if ($actual -eq $ExpectedSize) {
            Write-Host "Using existing $(Split-Path -Leaf $Output) ($actual bytes)"
            return
        }
    }

    Write-Host "Downloading $Url"
    curl.exe -L --fail --retry 5 -o $Output $Url
    $actualSize = (Get-Item -LiteralPath $Output).Length
    if ($actualSize -ne $ExpectedSize) {
        throw "Unexpected size for $Output`: expected $ExpectedSize, got $actualSize"
    }
}

function Install-OnnxRuntime {
    $zip = Join-Path $DownloadDir $OnnxZipName
    $dest = Join-Path $ThirdPartyDir "onnxruntime"
    $header = Join-Path $dest "onnxruntime-win-x64-$OnnxVersion\include\onnxruntime_c_api.h"

    if ((Test-Path -LiteralPath $header) -and -not $Force) {
        Write-Host "ONNX Runtime already extracted"
        return
    }

    Ensure-Dir $dest
    Expand-Archive -LiteralPath $zip -DestinationPath $dest -Force
}

function Install-OpenCv {
    $exe = Join-Path $DownloadDir $OpenCvExeName
    $dest = Join-Path $ThirdPartyDir "opencv"
    $dll = Join-Path $dest "build\x64\vc16\bin\opencv_world4130.dll"
    $header = Join-Path $dest "build\include\opencv2\opencv.hpp"
    $lib = Join-Path $dest "build\x64\vc16\lib\opencv_world4130.lib"

    if ((Test-Path -LiteralPath $dll) -and (Test-Path -LiteralPath $header) -and (Test-Path -LiteralPath $lib) -and -not $Force) {
        Write-Host "OpenCV already extracted"
        return
    }

    $tmp = Join-Path $ThirdPartyDir "opencv_sfx"
    Assert-Under $ThirdPartyDir $tmp
    Assert-Under $ThirdPartyDir $dest
    if (Test-Path -LiteralPath $tmp) {
        Remove-Item -LiteralPath $tmp -Recurse -Force
    }
    if (Test-Path -LiteralPath $dest) {
        Remove-Item -LiteralPath $dest -Recurse -Force
    }
    Ensure-Dir $tmp

    Write-Host "Extracting OpenCV self-extracting archive"
    $process = Start-Process -FilePath $exe -ArgumentList @("-y", "-o$tmp") -PassThru -WindowStyle Hidden
    $finished = Wait-Process -Id $process.Id -Timeout 900 -ErrorAction SilentlyContinue
    $extracted = Join-Path $tmp "opencv"
    $extractedDll = Join-Path $extracted "build\x64\vc16\bin\opencv_world4130.dll"
    $extractedHeader = Join-Path $extracted "build\include\opencv2\opencv.hpp"
    $extractedLib = Join-Path $extracted "build\x64\vc16\lib\opencv_world4130.lib"

    if ($null -eq $finished -and (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)) {
        if ((Test-Path -LiteralPath $extractedDll) -and (Test-Path -LiteralPath $extractedHeader) -and (Test-Path -LiteralPath $extractedLib)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        } else {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            throw "OpenCV extraction did not complete within timeout"
        }
    }

    if (-not ((Test-Path -LiteralPath $extractedDll) -and (Test-Path -LiteralPath $extractedHeader) -and (Test-Path -LiteralPath $extractedLib))) {
        throw "OpenCV extraction did not produce the required header, DLL, and import library"
    }

    Move-Item -LiteralPath $extracted -Destination $dest
    if ((Test-Path -LiteralPath $tmp) -and -not (Get-ChildItem -LiteralPath $tmp -Force)) {
        Remove-Item -LiteralPath $tmp
    }
}

function Install-MsvcBuildTools {
    Write-Host "Installing Visual Studio Build Tools 2022 with VC tools"
    winget install --id Microsoft.VisualStudio.2022.BuildTools --source winget --silent --disable-interactivity --accept-package-agreements --accept-source-agreements --override "--wait --quiet --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
}

Ensure-Dir $ThirdPartyDir
Ensure-Dir $DownloadDir

Download-File $OnnxUrl (Join-Path $DownloadDir $OnnxZipName) $OnnxSize
Download-File $OpenCvUrl (Join-Path $DownloadDir $OpenCvExeName) $OpenCvSize
Install-OnnxRuntime
Install-OpenCv

if ($InstallBuildTools) {
    Install-MsvcBuildTools
}

Write-Host "Backend dependencies are installed under $ThirdPartyDir"
