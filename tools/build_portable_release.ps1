<#
.SYNOPSIS
    BikeRideHUD Canonical Production Portable Release Packager (PowerShell Wrapper).
.DESCRIPTION
    Invokes tools/build_portable_release.py to create C:\_DEV\BikeRideHUD-portable-clean
    using the strict allowlist, denylist safety gate, and manifest generator.
#>

param(
    [string]$Source = "C:\_DEV\BikeRideHUD-portable",
    [string]$Target = "C:\_DEV\BikeRideHUD-portable-clean"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonScript = Join-Path $scriptDir "build_portable_release.py"

Write-Host "Running BikeRideHUD Clean Portable Release Packager..." -ForegroundColor Cyan
Write-Host "Source: $Source"
Write-Host "Target: $Target"

python $pythonScript --source $Source --target $Target

if ($LASTEXITCODE -ne 0) {
    Write-Error "Portable packaging failed with exit code $LASTEXITCODE."
    exit $LASTEXITCODE
}

Write-Host "Portable package created and validated successfully." -ForegroundColor Green
