<#
.SYNOPSIS
    SportCamHUD portable release packager (PowerShell wrapper).
.DESCRIPTION
    Invokes tools/build_portable_release.py: code from a git commit, explicit
    verified runtime binaries, bundled Python runtime, manifest.
#>

param(
    [string]$Commit = "HEAD",
    [string]$Target = (Join-Path (Split-Path -Parent $PSScriptRoot) "dist\portable-stage"),
    [switch]$NoPython
)

$ErrorActionPreference = "Stop"
$pythonScript = Join-Path $PSScriptRoot "build_portable_release.py"
$extra = @()
if ($NoPython) { $extra += "--no-python" }

Write-Host "SportCamHUD portable packager: commit=$Commit target=$Target" -ForegroundColor Cyan
python $pythonScript --commit $Commit --target $Target @extra
if ($LASTEXITCODE -ne 0) {
    Write-Error "Portable packaging failed with exit code $LASTEXITCODE."
    exit $LASTEXITCODE
}
Write-Host "Portable package created and validated." -ForegroundColor Green
