# TeleM AMD Render Path Audit - continuous system resource sampler.
# Samples CPU% (CIM), GPU engine utilization (Get-Counter), RAM (CIM) and
# VRAM (Get-Counter) into one master CSV until killed.  The harness writes the
# active case name into <CsvDir>\current_case.txt before each export; each
# sample row is tagged with that name ("idle" between cases).  The GPU Engine
# performance counter is slow (~2.5-3 s/query on this machine), so the sample
# period is a few seconds - adequate for avg/max per case on long exports.
# AMD APU engine mapping: 3d -> gpu_3d, "video decode" -> gpu_decode,
# "video codec" -> gpu_encode (VCN encoder), copy -> gpu_copy.
param(
    [Parameter(Mandatory=$true)][string]$Csv
)
$ErrorActionPreference = "SilentlyContinue"
$tagFile = Join-Path (Split-Path $Csv -Parent) "current_case.txt"
if (-not (Test-Path $Csv)) { "tag,t,cpu_total,cpu_py_raw,cpu_py_norm,gpu_3d,gpu_decode,gpu_encode,gpu_copy,ram_used_mb,ram_avail_mb,vram_ded_mb,vram_shared_mb" | Set-Content -Path $Csv -Encoding UTF8 }
$os = Get-CimInstance Win32_OperatingSystem
$totalMb = [math]::Round($os.TotalVisibleMemorySize / 1024, 0)
while ($true) {
    $tag = "idle"
    if (Test-Path $tagFile) {
        try { $t = (Get-Content $tagFile -Raw -ErrorAction Stop).Trim(); if ($t) { $tag = $t } } catch {}
    }
    $cpuTotal = $null; $g3d = 0.0; $gdec = 0.0; $genc = 0.0; $gcopy = 0.0
    try { $cpuTotal = (Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'").PercentProcessorTime } catch {}
    try {
        $samps = (Get-Counter "\GPU Engine(*)\Utilization Percentage" -MaxSamples 1 -ErrorAction Stop).CounterSamples
        foreach ($s in $samps) {
            if ($s.InstanceName -notmatch "engtype_(.+)$") { continue }
            $et = $Matches[1].Trim()
            if ($et -match "^3d") { $g3d += $s.CookedValue }
            elseif ($et -match "^video decode") { $gdec += $s.CookedValue }
            elseif ($et -match "^video codec") { $genc += $s.CookedValue }
            elseif ($et -match "^copy") { $gcopy += $s.CookedValue }
        }
    } catch {}
    $freeMb = $null
    try { $freeMb = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024, 0) } catch {}
    $usedMb = if ($totalMb -and $freeMb) { $totalMb - $freeMb } else { $null }
    $vramDed = $null; $vramShared = $null
    try {
        $s2 = (Get-Counter "\GPU Adapter Memory(*)\Dedicated Usage" -MaxSamples 1 -ErrorAction Stop).CounterSamples
        $s2s = ($s2 | Measure-Object -Property CookedValue -Sum).Sum
        if ($s2s) { $vramDed = [math]::Round($s2s / 1MB, 0) }
    } catch {}
    try {
        $s3 = (Get-Counter "\GPU Adapter Memory(*)\Shared Usage" -MaxSamples 1 -ErrorAction Stop).CounterSamples
        $s3s = ($s3 | Measure-Object -Property CookedValue -Sum).Sum
        if ($s3s) { $vramShared = [math]::Round($s3s / 1MB, 0) }
    } catch {}
    $cpuTotalR = if ($null -ne $cpuTotal) { [math]::Round([double]$cpuTotal, 1) } else { "" }
    $g3dR = [math]::Round($g3d, 1); $gdecR = [math]::Round($gdec, 1)
    $gencR = [math]::Round($genc, 1); $gcopyR = [math]::Round($gcopy, 1)
    $ts = Get-Date -Format "HH:mm:ss.fff"
    $line = "$tag,$ts,$cpuTotalR,,,$g3dR,$gdecR,$gencR,$gcopyR,$usedMb,$freeMb,$vramDed,$vramShared"
    Add-Content -Path $Csv -Value $line -Encoding UTF8
    Start-Sleep -Milliseconds 200
}
