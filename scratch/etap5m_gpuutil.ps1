# ETAP 5M — light GPU-engine utilization sampler (fixed engtype regex).
# Samples ONLY the GPU Engine counter every ~1.5 s (no CPU counters => low
# overhead) during a fresh production 1131 run.  Diagnostic/indicative only.
$ErrorActionPreference = "Continue"
$ROOT = "C:\_DEV\TeleM"
$PY = "c:/_DEV/TeleM/.venv-1/Scripts/python.exe"
$CSV = "$ROOT\Raporty\AMD_ETAP5G\etap5m_gpu_util.csv"

if (Test-Path $CSV) { Remove-Item $CSV -Force }
"t,gpu_3d,gpu_decode,gpu_encode,gpu_copy,gpu_other" | Set-Content -Path $CSV -Encoding UTF8

$sampler = {
    param($csv)
    $deadline = (Get-Date).AddSeconds(110)
    while ((Get-Date) -lt $deadline) {
        $b = @{ "3D"=0.0; "Video Decode"=0.0; "Video Encode"=0.0; "Copy"=0.0; "other"=0.0 }
        try {
            $samps = (Get-Counter "\GPU Engine(*)\Utilization Percentage" `
                -SampleInterval 1 -MaxSamples 1 -ErrorAction Stop).CounterSamples
            foreach ($s in $samps) {
                $m = [regex]::Match($s.InstanceName, "engtype_(.*)$")
                $et = if ($m.Success) { $m.Groups[1].Value.Trim() } else { "other" }
                if ($b.ContainsKey($et)) { $b[$et] += $s.CookedValue } else { $b["other"] += $s.CookedValue }
            }
        } catch {}
        $line = "{0},{1},{2},{3},{4},{5}" -f (Get-Date).ToString("HH:mm:ss.fff"),
            [math]::Round($b["3D"],1), [math]::Round($b["Video Decode"],1),
            [math]::Round($b["Video Encode"],1), [math]::Round($b["Copy"],1),
            [math]::Round($b["other"],1)
        Add-Content -Path $csv -Value $line -Encoding UTF8
        Start-Sleep -Milliseconds 500
    }
}

$job = Start-Job -ScriptBlock $sampler -ArgumentList $CSV

$env:AMD_MAP_PATH = "GPU"
$env:AMD_MAP_FILTER = "LANCZOS"
foreach ($f in @("AMD_GAUGE_AB_READBACK","AMD_MAP_AB_READBACK","AMD_CHART_AB_READBACK",
                 "AMD_CHART_STATIC_READBACK","AMD_NATIVE_DIAGNOSTICS","AMD_NATIVE_PROFILING",
                 "AMD_OVERLAY_PROFILE","AMD_MAP_STATS")) {
    Remove-Item "Env:$f" -ErrorAction SilentlyContinue
}
& $PY "$ROOT\scratch\run_etap5g_export.py" --frames 1131 --chart-path GPU_SPLIT `
    --gauge-path GPU --output "$ROOT\Raporty\AMD_ETAP5G\5m_gpuutil_run.mp4"

Start-Sleep -Seconds 3
Stop-Job $job -ErrorAction SilentlyContinue
Remove-Job $job -Force -ErrorAction SilentlyContinue
Write-Output "GPU SAMPLER DONE"
