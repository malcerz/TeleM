param(
    [Parameter(Mandatory=$true)][int]$RootPid,
    [Parameter(Mandatory=$true)][string]$OutputPrefix
)
$ErrorActionPreference = 'SilentlyContinue'
$gpuPath = "${OutputPrefix}_gpu.csv"
$systemPath = "${OutputPrefix}_system.csv"
$gpuRows = [System.Collections.Generic.List[object]]::new()
$systemRows = [System.Collections.Generic.List[object]]::new()
$cpuBaseline = $null
$logicalProcessors = [Math]::Max(1, [int](Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors)

function Get-RunProcesses([int]$pidRoot) {
    $all = @(Get-CimInstance Win32_Process)
    if (-not ($all | Where-Object { [int]$_.ProcessId -eq $pidRoot })) { return @() }
    $ids = [System.Collections.Generic.HashSet[int]]::new()
    [void]$ids.Add($pidRoot)
    do {
        $changed = $false
        foreach ($proc in $all) {
            if ($ids.Contains([int]$proc.ParentProcessId) -and $ids.Add([int]$proc.ProcessId)) { $changed = $true }
        }
    } while ($changed)
    return @($all | Where-Object { $ids.Contains([int]$_.ProcessId) })
}

function Get-GpuIdentity([string]$instanceName) {
    if ($instanceName -match '^pid_(?<pid>\d+)_luid_(?<luid>.+?)_phys_(?<phys>\d+)_eng_(?<engine>\d+)_engtype_(?<type>.+)$') {
        return @{pid=[int]$Matches.pid; luid=$Matches.luid; phys=[int]$Matches.phys; engine=[int]$Matches.engine; type=$Matches.type}
    }
    return $null
}

$started = [DateTime]::UtcNow
while ($true) {
    $now = [DateTime]::UtcNow
    $procs = @(Get-RunProcesses $RootPid)
    if ($procs.Count -eq 0) { break }
    $ids = @($procs | ForEach-Object { [int]$_.ProcessId })
    $names = @{}
    foreach ($p in $procs) { $names[[int]$p.ProcessId] = [string]$p.Name }
    $procStats = @(Get-Process -Id $ids -ErrorAction SilentlyContinue)
    $cpuTotal = 0.0
    $wsTotal = 0L
    foreach ($p in $procStats) { $cpuTotal += $p.CPU; $wsTotal += $p.WorkingSet64 }
    $cpuPct = $null
    if ($null -ne $cpuBaseline) {
        $delta = $cpuTotal - $cpuBaseline.cpu
        $seconds = ($now - $cpuBaseline.time).TotalSeconds
        if ($seconds -gt 0) { $cpuPct = [Math]::Max(0, $delta / ($seconds * $logicalProcessors) * 100.0) }
    }
    $cpuBaseline = @{cpu=$cpuTotal;time=$now}
    $sysCpu = $null
    $availableMb = $null
    try { $sysCpu = [double](Get-CimInstance -Namespace root/cimv2 -ClassName Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'").PercentProcessorTime } catch {}
    try { $availableMb = [double](Get-CimInstance -Namespace root/cimv2 -ClassName Win32_PerfFormattedData_PerfOS_Memory).AvailableMBytes } catch {}
    $systemRows.Add([pscustomobject]@{
        timestamp_utc=$now.ToString('o'); run_elapsed_s=[Math]::Round(($now-$started).TotalSeconds,3)
        process_tree_pid_list=($ids -join ';'); process_tree_cpu_pct=$cpuPct
        process_tree_working_set_bytes=$wsTotal; system_cpu_pct=$sysCpu; memory_available_mb=$availableMb
    })
    try {
        # Filter the formatted GPU engine provider by the current render process
        # tree. Querying every process' wildcard counter takes several seconds
        # here and would perturb the benchmark.
        $pidClauses = @($ids | ForEach-Object { "Name LIKE 'pid_$($_)_%'" })
        $gpu = @(Get-CimInstance -Namespace root/cimv2 -ClassName Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine -Filter ($pidClauses -join ' OR '))
        foreach ($sample in $gpu) {
            $identity = Get-GpuIdentity ([string]$sample.Name)
            if ($null -eq $identity -or $identity.pid -notin $ids) { continue }
            $gpuRows.Add([pscustomobject]@{
                timestamp_utc=$now.ToString('o'); process_id=$identity.pid; process_name=$names[$identity.pid]
                adapter_luid=$identity.luid; physical_adapter=$identity.phys; engine_id=$identity.engine
                engine_type=$identity.type; utilization_pct=[Math]::Round([double]$sample.UtilizationPercentage,3)
                running_time=$sample.RunningTime
            })
        }
    } catch {}
    Start-Sleep -Seconds 2
}
if ($systemRows.Count -gt 0) { $systemRows | Export-Csv -LiteralPath $systemPath -NoTypeInformation -Encoding UTF8 }
if ($gpuRows.Count -gt 0) { $gpuRows | Export-Csv -LiteralPath $gpuPath -NoTypeInformation -Encoding UTF8 }
"samples=$($systemRows.Count) gpu_rows=$($gpuRows.Count) root_pid=$RootPid" | Set-Content -LiteralPath "${OutputPrefix}_monitor_summary.txt" -Encoding UTF8
