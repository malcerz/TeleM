"""P1.0: alternate HEAD (before) and working-tree (after) renderer files in short
canonical CPU harness runs. Source files are always restored in `finally`.

Usage: ab_perf.py OUT_DIR
"""
import pathlib, subprocess, sys
root = pathlib.Path(r'C:\_DEV\SportCamHUD')
out = sys.argv[1]
files = ['src/indicators/lean.py', 'src/indicators/gauge.py', 'src/indicators/effects.py']
after = {f: (root / f).read_bytes() for f in files}
before = {f: subprocess.check_output(['git', 'show', f'HEAD:{f}'], cwd=root) for f in files}
runs = []
for rep in (1, 2):  # HUD only (diagnostic null sink, no encoder), 2 workers
    runs += [(f'hud_w2_{v}{rep}', v, 300, ['TELEM_CPU_WORKERS=2', 'TELEM_CPU_DIAG_NULL_SINK=1']) for v in ('before', 'after')]
runs += [(f'hud_w4_{v}1', v, 300, ['TELEM_CPU_WORKERS=4', 'TELEM_CPU_DIAG_NULL_SINK=1']) for v in ('before', 'after')]
for rep in (1, 2):  # full export, 2 workers
    runs += [(f'exp_w2_{v}{rep}', v, 150, ['TELEM_CPU_WORKERS=2']) for v in ('before', 'after')]
try:
    for tag, ver, frames, env in runs:
        for f in files:
            (root / f).write_bytes((before if ver == 'before' else after)[f])
        cmd = ['python', 'Raporty/CPU_P07_LOOKAHEAD/run_harness_p07.py', '--out-dir', out, '--tag', tag,
               '--frames', str(frames), '--start-frame', '900', '--extra', '--profile fast --bitrate 16M']
        for e in env:
            cmd += ['--env', e]
        r = subprocess.run(cmd, cwd=root, stdout=subprocess.DEVNULL)
        print(tag, 'exit', r.returncode, flush=True)
finally:
    for f in files:
        (root / f).write_bytes(after[f])
    print('sources restored', flush=True)
