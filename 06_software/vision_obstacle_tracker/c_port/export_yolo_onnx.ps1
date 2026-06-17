param(
    [int[]]$ImageSizes = @(512, 1024)
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$ModelDir = Join-Path $ScriptDir "models"
$OriginalOnnx = Join-Path $ProjectDir "yolo11n.onnx"

New-Item -ItemType Directory -Force -Path $ModelDir | Out-Null

foreach ($size in $ImageSizes) {
    Write-Host "Exporting yolo11n.pt to ONNX imgsz=$size"
    Push-Location $ProjectDir
    try {
        py -c "from ultralytics import YOLO; YOLO('yolo11n.pt').export(format='onnx', imgsz=$size, opset=12, simplify=False)"
    } finally {
        Pop-Location
    }

    if (-not (Test-Path -LiteralPath $OriginalOnnx)) {
        throw "Expected export output missing: $OriginalOnnx"
    }

    $dest = Join-Path $ModelDir "yolo11n_imgsz$size.onnx"
    Copy-Item -LiteralPath $OriginalOnnx -Destination $dest -Force
    Write-Host "Wrote $dest"
}

Write-Host "ONNX model exports are ready under $ModelDir"
