# ETAP 5M — CPU/GPU utilization sampler (fixed: incremental CSV append).
# Runs a fresh production 1131 export while a background sampler appends
# CPU% / GPU-engine utilization every ~0.5 s to a CSV.  Measurement only.
$ErrorActionPreference = "Continue"
$ROOT = "C:\_DEV\TeleM"
$PY = "c:/_DEV/TeleM/.venv-1/Scripts/python.exe"
$CSV = "$ROOT\Raporty\AMD_ETAP5G\etap5m_util_samples.csv"
$Logicals = (Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors
if (-not $Logicals) { $Logicals = [Environment]::ProcessorCount }

if (Test-Path $CSV) { Remove-Item $CSV -Force }
"t,cpu_total,cpu_py_raw,cpu_py_norm,gpu_3d,gpu_decode,gpu_encode,gpu_copy" |
    Set-Content -Path $CSV -Encoding UTF8

$sampler = {
    param($csv, $logicals)
    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline) {
        $cpuTotal = ""; $cpuPy = ""; $g3d = 0; $gdec = 0; $genc = 0; $gcopy = 0
        try {
            $cpuTotal = (Get-Counter "\Processor Information(_Total)\% Processor Time" `
                -SampleInterval 1 -MaxSamples 1 -ErrorAction Stop).CounterSamples[0].CookedValue
        } catch {}
        try {
            $cpuPy = (Get-Counter "\Process(python*)\% Processor Time" `
                -SampleInterval 1 -MaxSamples 1 -ErrorAction Stop).CounterSamples |
                Measure-Object -Property CookedValue -Sum | Select-Object -ExpandProperty Sum
        } catch {}
        try {
            $samps = (Get-Counter "\GPU Engine(*)\Utilization Percentage" `
                -SampleInterval 1 -MaxSamples 1 -ErrorAction Stop).CounterSamples
            foreach ($s in $samps) {
                $m = [regex]::Match($s.InstanceName, "engtype_(\w+)")
                if ($m.Success) {
                    switch ($m.Groups[1].Value) {
                        "3D" { $g3d += $s.CookedValue }
                        "Video Decode" { $gdec += $s.CookedValue }
                        "Video Encode" { $genc += $s.CookedValue }
                        "Copy" { $gcopy += $s.CookedValue }
                    }
                }
            }
        } catch {}
        $cpuNorm = if ($cpuPy -ne "") { [math]::Round([double]$cpuPy / $logicals, 1) } else { "" }
        $cpuTotalR = if ($cpuTotal -ne "") { [math]::Round([double]$cpuTotal, 1) } else { "" }
        $cpuPyR = if ($cpuPy -ne "") { [math]::Round([double]$cpuPy, 1) } else { "" }
        $line = "{0},{1},{2},{3},{4},{5},{6},{7}" -f (Get-Date).ToString("HH:mm:ss.fff"),
            $cpuTotalR, $cpuPyR, $cpuNorm,
            [math]::Round($g3d, 1), [math]::Round($gdec, 1),
            [math]::Round($genc, 1), [math]::Round($gcopy, 1)
        Add-Content -Path $csv -Value $line -Encoding UTF8
        Start-Sleep -Milliseconds 500
    }
}

$job = Start-Job -ScriptBlock $sampler -ArgumentList $CSV, $Logicals

# fresh production run (profiling OFF)
$env:AMD_MAP_PATH = "GPU"
$env:AMD_MAP_FILTER = "LANCZOS"
foreach ($f in @("AMD_GAUGE_AB_READBACK","AMD_MAP_AB_READBACK","AMD_CHART_AB_READBACK",
                 "AMD_CHART_STATIC_READBACK","AMD_NATIVE_DIAGNOSTICS","AMD_NATIVE_PROFILING",
                 "AMD_OVERLAY_PROFILE","AMD_MAP_STATS")) {
    Remove-Item "Env:$f" -ErrorAction SilentlyContinue
}
& $PY "$ROOT\scratch\run_etap5g_export.py" --frames 1131 --chart-path GPU_SPLIT `
    --gauge-path GPU --output "$ROOT\Raporty\AMD_ETAP5G\5m_util_run.mp4"

# let the sampler flush a few more samples, then stop it (CSV is incremental)
Start-Sleep -Seconds 3
Stop-Job $job -ErrorAction SilentlyContinue
Remove-Job $job -Force -ErrorAction SilentlyContinue
Write-Output "SAMPLER DONE"
