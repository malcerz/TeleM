param(
    [string]$PythonExe = 'python',
    [string]$WorkDir = (Join-Path $PSScriptRoot '..\scratch\dji_parser_build')
)

$ErrorActionPreference = 'Stop'
$commit = 'd45ebf2afce85fa691838fd32b3da8ae2fcac773'
$repo = Join-Path $WorkDir 'telemetry-parser'
$wheelDir = Join-Path $WorkDir 'wheels'
$runtime = Join-Path $PSScriptRoot '..\runtime\telemetry_parser'

New-Item -ItemType Directory -Force $WorkDir, $wheelDir | Out-Null
if (-not (Test-Path -LiteralPath $repo)) {
    git clone https://github.com/AdrianEddy/telemetry-parser.git $repo
    if ($LASTEXITCODE -ne 0) { throw 'telemetry-parser clone failed' }
}
git -C $repo fetch origin $commit
if ($LASTEXITCODE -ne 0) { throw 'telemetry-parser fetch failed' }
git -C $repo checkout --detach $commit
if ($LASTEXITCODE -ne 0) { throw 'telemetry-parser checkout failed' }

$env:PYO3_USE_ABI3_FORWARD_COMPATIBILITY = '1'
$env:PATH = "$(Join-Path $env:USERPROFILE '.cargo\bin');$env:PATH"
& $PythonExe -m maturin build --manifest-path (Join-Path $repo 'bin\python-module\Cargo.toml') --release --interpreter $PythonExe --out $wheelDir
if ($LASTEXITCODE -ne 0) { throw 'telemetry-parser build failed' }

$wheel = Get-ChildItem -LiteralPath $wheelDir -Filter 'telemetry_parser-0.3.0-*.whl' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $wheel) { throw 'No telemetry-parser wheel was built' }
& $PythonExe -c "import pathlib,sys,zipfile; w=zipfile.ZipFile(sys.argv[1]); out=pathlib.Path(sys.argv[2]); [w.extract(n,out) for n in w.namelist() if n.startswith('telemetry_parser/')]; print(out)" $wheel.FullName $runtime
if ($LASTEXITCODE -ne 0) { throw 'Wheel extraction failed' }
Copy-Item -LiteralPath (Join-Path $repo 'LICENSE-MIT') -Destination $runtime
Copy-Item -LiteralPath (Join-Path $repo 'LICENSE-APACHE') -Destination $runtime
