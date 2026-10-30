"""P1.1: run one canonical `--test-cpu-export` (auto worker count) through
p11_launcher.py and sample resources every INTERVAL s into CSV + JSON.

Sources: psutil (system CPU/RAM, process-tree RSS/CPU, output size, disk free),
WMI perf classes via one long-lived PowerShell loop (CPU % performance and
frequency, ACPI thermal zones, passive limit/throttle reasons, disk time/bytes),
p11_launcher progress JSON (completed HUD frames) and worker cache logs.

Usage: p11_monitor.py --tag T --out-dir D --frames N --start-frame S [--extra "..."] [--interval 5]
"""
import argparse, csv, glob, json, os, shutil, subprocess, time
import psutil

REPO = r'C:\_DEV\SportCamHUD'
HERE = os.path.dirname(os.path.abspath(__file__))
VIDEO = r'C:\GoPro\GX010378.MP4'
FIT = r'C:\GoPro\2026-10-15_15-03-50.fit'
LAYOUT = REPO + r'\def_layout.json'
WMI_PS = r'''
while ($true) {
  $p = Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation -Filter "Name='_Total'"
  $z = Get-CimInstance Win32_PerfFormattedData_Counters_ThermalZoneInformation | Where-Object { $_.Temperature -gt 0 }
  $d = Get-CimInstance Win32_PerfFormattedData_PerfDisk_PhysicalDisk -Filter "Name='_Total'"
  [pscustomobject]@{
    t = [DateTimeOffset]::Now.ToUnixTimeMilliseconds() / 1000.0
    cpu_perf_pct = $p.PercentProcessorPerformance; cpu_base_mhz = $p.ProcessorFrequency
    cpu_util_pct = $p.PercentProcessorUtility
    tz_max_k = ($z | Measure-Object HighPrecisionTemperature -Maximum).Maximum
    tz_passive_min_pct = ($z | Measure-Object PercentPassiveLimit -Minimum).Minimum
    tz_throttle_reasons_max = ($z | Measure-Object ThrottleReasons -Maximum).Maximum
    disk_time_pct = $d.PercentDiskTime; disk_write_Bps = $d.DiskWriteBytesPersec; disk_read_Bps = $d.DiskReadBytesPersec
  } | ConvertTo-Json -Compress | Add-Content -Encoding utf8 -Path $env:P11_WMI
  Start-Sleep -Seconds INTERVAL
}
'''
FIELDS = ['t_s', 'frames_done', 'fps_current', 'fps_avg', 'sys_cpu_pct', 'cpu_perf_pct', 'cpu_mhz_est', 'tz_max_c',
          'tz_passive_min_pct', 'tz_throttle_reasons', 'sys_ram_used_gb', 'ffmpeg_rss_mb', 'workers_n',
          'workers_rss_mb', 'main_rss_mb', 'ffmpeg_cores', 'workers_cores', 'main_cores', 'other_cpu_pct',
          'out_mb', 'disk_free_gb', 'disk_time_pct', 'disk_write_MBps', 'worker_pids',
          'lean_patch_entries_max', 'compass_entries_max', 'effects_bytes_max_mb']


def role(p, root):
    try:
        if p.pid == root:
            return 'main'
        n = (p.name() or '').lower()
        if 'ffmpeg' in n:
            return 'ffmpeg'
        if 'python' in n:
            return 'worker' if '--multiprocessing-fork' in ' '.join(p.cmdline()) else 'python_other'
        return 'other'
    except psutil.Error:
        return 'other'


def last_json_line(path):
    try:
        lines = open(path, encoding='utf-8-sig').read().strip().splitlines()
        return json.loads(lines[-1].lstrip('\ufeff')) if lines else {}
    except (OSError, ValueError):
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tag', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--frames', type=int, required=True)
    ap.add_argument('--start-frame', type=int, default=0)
    ap.add_argument('--extra', default='')
    ap.add_argument('--interval', type=float, default=5.0)
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    base = os.path.join(a.out_dir, a.tag)
    cache_dir = base + '_worker_cache'
    os.makedirs(cache_dir, exist_ok=True)
    hook = os.path.join(a.out_dir, 'hook')
    os.makedirs(hook, exist_ok=True)
    shutil.copy(os.path.join(HERE, 'sitecustomize.py'), os.path.join(hook, 'sitecustomize.py'))
    out_mp4 = base + '.mp4'
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', TELEM_CPU_HARNESS_TRACE='1',
               P11_PROGRESS=base + '.progress.json', P11_CACHE_LOG=cache_dir, P11_WMI=base + '.wmi.jsonl',
               PYTHONPATH=os.pathsep.join(filter(None, [hook, os.environ.get('PYTHONPATH')])))
    env.pop('TELEM_CPU_WORKERS', None)  # production rule: automatic worker count
    wmi = subprocess.Popen(['powershell', '-NoProfile', '-Command', WMI_PS.replace('INTERVAL', str(int(a.interval)))],
                           env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cmd = ['python', os.path.join(HERE, 'p11_launcher.py'), '--test-cpu-export', '--mode', 'direct', '--video', VIDEO,
           '--fit', FIT, '--layout', LAYOUT, '--start-frame', str(a.start_frame), '--frames', str(a.frames),
           '--wait-prepared', '--output', out_mp4, '--result-json', base + '.result.json'] + a.extra.split()
    log = open(base + '.stdout.log', 'wb')
    t0 = time.time()
    p = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)
    root = psutil.Process(p.pid)
    rows, cpu_last = [], {}
    fcsv = open(base + '.metrics.csv', 'w', newline='')
    w = csv.DictWriter(fcsv, fieldnames=FIELDS)
    w.writeheader()
    psutil.cpu_percent(None)
    last_t, last_frames, first = time.time(), 0, None
    while p.poll() is None:
        time.sleep(a.interval)
        now = time.time()
        dt = now - last_t
        last_t = now
        agg, pids = {}, []
        try:
            procs = [root] + root.children(recursive=True)
        except psutil.Error:
            procs = []
        for pr in procs:
            try:
                r = role(pr, p.pid)
                ct = pr.cpu_times()
                c = ct.user + ct.system
                d = (c - cpu_last.get(pr.pid, c)) / dt
                cpu_last[pr.pid] = c
                g = agg.setdefault(r, {'rss': 0, 'cores': 0.0, 'n': 0})
                g['rss'] += pr.memory_info().rss
                g['cores'] += d
                g['n'] += 1
                if r == 'worker':
                    pids.append(pr.pid)
            except psutil.Error:
                pass
        try:
            jobs = json.load(open(base + '.progress.json'))['jobs']
            frames = jobs[-1]['done'] if jobs else 0
        except (OSError, ValueError, KeyError, IndexError):
            frames = last_frames
        if frames and first is None:
            first = (now, frames)
        wm = last_json_line(base + '.wmi.jsonl')
        caches = {'lean': 0, 'compass': 0, 'eff': 0}
        for f in glob.glob(os.path.join(cache_dir, 'worker_*.jsonl')):
            last = last_json_line(f)
            caches['lean'] = max(caches['lean'], last.get('lean_patch', {}).get('entries', 0))
            caches['compass'] = max(caches['compass'], last.get('compass', {}).get('entries', 0))
            caches['eff'] = max(caches['eff'], last.get('effects', {}).get('bytes', 0) or 0)
        vm = psutil.virtual_memory()
        sys_cpu = psutil.cpu_percent(None)
        tree_cores = sum(g['cores'] for g in agg.values())
        perf = wm.get('cpu_perf_pct')
        row = {
            't_s': round(now - t0, 1), 'frames_done': frames,
            'fps_current': round((frames - last_frames) / dt, 2),
            'fps_avg': round((frames - first[1]) / (now - first[0]), 2) if first and now > first[0] else 0.0,
            'sys_cpu_pct': sys_cpu, 'cpu_perf_pct': perf,
            'cpu_mhz_est': round(wm['cpu_base_mhz'] * perf / 100) if perf is not None and wm.get('cpu_base_mhz') else None,
            'tz_max_c': round(wm['tz_max_k'] / 10 - 273.15, 1) if wm.get('tz_max_k') else None,
            'tz_passive_min_pct': wm.get('tz_passive_min_pct'), 'tz_throttle_reasons': wm.get('tz_throttle_reasons_max'),
            'sys_ram_used_gb': round((vm.total - vm.available) / 2**30, 2),
            'ffmpeg_rss_mb': round(agg.get('ffmpeg', {}).get('rss', 0) / 2**20, 1),
            'workers_n': agg.get('worker', {}).get('n', 0),
            'workers_rss_mb': round(agg.get('worker', {}).get('rss', 0) / 2**20, 1),
            'main_rss_mb': round(agg.get('main', {}).get('rss', 0) / 2**20, 1),
            'ffmpeg_cores': round(agg.get('ffmpeg', {}).get('cores', 0), 2),
            'workers_cores': round(agg.get('worker', {}).get('cores', 0), 2),
            'main_cores': round(agg.get('main', {}).get('cores', 0), 2),
            'other_cpu_pct': round(max(0.0, sys_cpu - 100 * tree_cores / psutil.cpu_count()), 1),
            'out_mb': round(os.path.getsize(out_mp4) / 2**20, 1) if os.path.exists(out_mp4) else 0,
            'disk_free_gb': round(shutil.disk_usage(a.out_dir).free / 2**30, 2),
            'disk_time_pct': wm.get('disk_time_pct'),
            'disk_write_MBps': round(wm['disk_write_Bps'] / 2**20, 2) if wm.get('disk_write_Bps') is not None else None,
            'worker_pids': ' '.join(map(str, sorted(pids))),
            'lean_patch_entries_max': caches['lean'], 'compass_entries_max': caches['compass'],
            'effects_bytes_max_mb': round(caches['eff'] / 2**20, 1),
        }
        last_frames = frames
        rows.append(row)
        w.writerow(row)
        fcsv.flush()
    wall = time.time() - t0
    wmi.kill()
    fcsv.close()
    log.close()
    json.dump({'tag': a.tag, 'returncode': p.returncode, 'wall_s': round(wall, 1), 'cmd': cmd, 'samples': rows},
              open(base + '.metrics.json', 'w'), indent=1)
    print(json.dumps({'tag': a.tag, 'returncode': p.returncode, 'wall_s': round(wall, 1), 'samples': len(rows)}))


if __name__ == '__main__':
    main()
