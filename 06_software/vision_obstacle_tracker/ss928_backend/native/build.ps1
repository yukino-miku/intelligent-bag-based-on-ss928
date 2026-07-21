param(
    [Parameter(Mandatory = $true)]
    [string]$SdkRoot,
    [Parameter(Mandatory = $true)]
    [string]$ToolchainFile,
    [string]$BuildDirectory = "build",
    [string]$CMake = "cmake",
    [string]$Generator = "Ninja"
)

$ErrorActionPreference = "Stop"
$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$include = Join-Path $SdkRoot "include/hisilicon/npu"
$library = Join-Path $SdkRoot "lib/linux/hisilicon/npu/libascendcl.so"

if (-not (Test-Path -LiteralPath (Join-Path $include "acl.h") -PathType Leaf)) {
    throw "SS928 ACL header not found below $include"
}
if (-not (Test-Path -LiteralPath $library -PathType Leaf)) {
    throw "SS928 ACL library not found: $library"
}

& $CMake -S $source -B $BuildDirectory -G $Generator `
    "-DCMAKE_BUILD_TYPE=Release" `
    "-DCMAKE_TOOLCHAIN_FILE=$ToolchainFile" `
    "-DSS928_NPU_INCLUDE_DIR=$include" `
    "-DSS928_NPU_LIBRARY=$library"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $CMake --build $BuildDirectory --config Release
exit $LASTEXITCODE
