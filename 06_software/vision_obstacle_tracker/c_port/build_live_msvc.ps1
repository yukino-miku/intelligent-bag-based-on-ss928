$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VcVars = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
$BuildDir = Join-Path $ScriptDir "build"
$OrtDir = Join-Path $ScriptDir "third_party\onnxruntime\onnxruntime-win-x64-1.26.0"
$OpenCvDir = Join-Path $ScriptDir "third_party\opencv"
$ObjDir = "$BuildDir\\"

New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

$cmd = "call `"$VcVars`" && cl /nologo /EHsc /std:c++17 /utf-8 /W4 /WX /wd4127 /I`"$ScriptDir\include`" /I`"$OrtDir\include`" /I`"$OpenCvDir\build\include`" `"$ScriptDir\src\vision_obstacle_tracker_live.cpp`" `"$ScriptDir\src\vot_backend.cpp`" `"$ScriptDir\src\vot.c`" /Fo`"$ObjDir`" /Fe:`"$BuildDir\vision_obstacle_tracker_live.exe`" /link /LIBPATH:`"$OrtDir\lib`" /LIBPATH:`"$OpenCvDir\build\x64\vc16\lib`" onnxruntime.lib opencv_world4130.lib"

cmd.exe /c $cmd
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Copy-Item -LiteralPath (Join-Path $OrtDir "lib\onnxruntime.dll") -Destination $BuildDir -Force
Copy-Item -LiteralPath (Join-Path $OpenCvDir "build\x64\vc16\bin\opencv_world4130.dll") -Destination $BuildDir -Force

Write-Host "Built $BuildDir\vision_obstacle_tracker_live.exe"
