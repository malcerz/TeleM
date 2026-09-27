param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $TeleMArguments
)

# Developer-only launcher. It selects proof output and starts the normal GUI;
# it does not select media and does not start an automatic render.
$env:TELEM_INTEL_PROOF = "1"
$entrypoint = Join-Path $PSScriptRoot "TeleMGP.py"
& python $entrypoint @TeleMArguments
exit $LASTEXITCODE
