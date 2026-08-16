# ETAP 5M — profiling run + non-invasive CPU/GPU utilization sampling.
# Measurement only. Does not modify production code.
#
# Runs ONE full profiling export (AMD_NATIVE_PROFILING=1, AMD_OVERLAY_PROFILE=1)
# while a background sampler records, every 0.5 s:
#   - overall CPU %
#   - python process CPU % (normalized to logical cores)
#   - GPU engine utilization by engine type (3D / Video Decode / Video Encode / Copy)
# Writes samples to Raporty/AMD_ETAP5G/etap5m_util_samples.csv and prints a summary.

$ErrorActionPreference = "Continue"
$ROOT = "C:\_DEV\TeleM"
$PY = "c:/_DEV/TeleM/.venv-1/Scripts/python.exe"
$SAMPLES = "$ROOT\Raporty\AMD_ETAP5G\etap5m_util_samples.csv"

$Logicals = (Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors
if (-not $Logicals) { $Logicals = [Environment]::ProcessorCount }

# ── sampler background job ─────────────────────────────────────────────
$sampler = {
    param($csv, $logicals)
    $rows = @()
    $deadline = (Get-Date).AddSeconds(150)
    while ((Get-Date) -lt $deadline) {
        $cpuTotal = $null; $cpuPy = $null; $gpu = @{}
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
                $et = if ($m.Success) { $m.Groups[1].Value } else { "other" }
                if ($gpu.ContainsKey($et)) { $gpu[$et] += $s.CookedValue }
                else { $gpu[$et] = $s.CookedValue }
            }
        } catch {}
        $rows += [pscustomobject]@{
            t = (Get-Date).ToString("HH:mm:ss.fff")
            cpu_total = [math]::Round($cpuTotal, 1)
            cpu_py_raw = [math]::Round($cpuPy, 1)
            cpu_py_norm = if ($null -ne $cpuPy) { [math]::Round($cpuPy / $logicals, 1) } else { $null }
            gpu_3d = if ($gpu.ContainsKey("3D")) { [math]::Round($gpu["3D"], 1) } else { 0 }
            gpu_decode = if ($gpu.ContainsKey("Video Decode")) { [math]::Round($gpu["Video Decode"], 1) } else { 0 }
            gpu_encode = if ($gpu.ContainsKey("Video Encode")) { [math]::Round($gpu["Video Encode"], 1) } else { 0 }
            gpu_copy = if ($gpu.ContainsKey("Copy")) { [math]::Round($gpu["Copy"], 1) } else { 0 }
        }
        Start-Sleep -Milliseconds 500
    }
    $rows | Export-Csv -Path $csv -NoTypeInformation -Encoding UTF8
}

if (Test-Path $SAMPLES) { Remove-Item $SAMPLES -Force }
$job = Start-Job -ScriptBlock $sampler -ArgumentList $SAMPLES, $Logicals

# ── run the profiling export ───────────────────────────────────────────
$env:AMD_NATIVE_PROFILING = "1"
$env:AMD_OVERLAY_PROFILE = "1"
$env:AMD_MAP_PATH = "GPU"
$env:AMD_MAP_FILTER = "LANCZOS"
foreach ($f in @("AMD_GAUGE_AB_READBACK","AMD_MAP_AB_READBACK","AMD_CHART_AB_READBACK",
                 "AMD_CHART_STATIC_READBACK","AMD_NATIVE_DIAGNOSTICS","AMD_MAP_STATS")) {
    Remove-Item "Env:$f" -ErrorAction SilentlyContinue
}

& $PY "$ROOT\scratch\run_etap5g_export.py" --frames 1131 --chart-path GPU_SPLIT `
    --gauge-path GPU --output "$ROOT\Raporty\AMD_ETAP5G\5m_profile.mp4"

# ── aggregate utilization ──────────────────────────────────────────────
Stop-Job $job -ErrorAction SilentlyContinue
Remove-Job $job -Force -ErrorAction SilentlyContinue
if (Test-Path $SAMPLES) {
    $rows = Import-Csv $SAMPLES
    Write-Output ""
    Write-Output "==== CPU/GPU UTILIZATION (sampled every 0.5 s) ===="
    Write-Output ("logical cores: {0}  samples: {1}" -f $Logicals, $rows.Count)
    foreach ($col in @("cpu_total","cpu_py_raw","cpu_py_norm","gpu_3d","gpu_decode","gpu_encode","gpu_copy")) {
        $vals = @($rows | ForEach-Object { if ($_.$col -ne "") { [double]$_.$col } } | Where-Object { $_ -ne $null })
        if ($vals.Count -gt 0) {
            $avg = ($vals | Measure-Object -Average).Average
            $mx  = ($vals | Measure-Object -Maximum).Maximum
            $sorted = @($vals | Sort-Object)
            $idx = [math]::Min($sorted.Count - 1, [int]($sorted.Count * 0.99))
            $p99 = $sorted[$idx]
            Write-Output ("{0,-14} avg={1,6.1f}  max={2,6.1f}  p99={3,6.1f}" -f $col, $avg, $mx, $p99)
        }
    }
} else {
    Write-Output "no utilization samples"
}
