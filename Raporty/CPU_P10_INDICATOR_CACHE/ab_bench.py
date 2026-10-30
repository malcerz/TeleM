"""P1.0: interleaved A/B of lean/compass renderers, HEAD (A) vs working tree (B).

Both versions live in one process (A is loaded from `git show HEAD:...`), so CPU
frequency drift hits them equally. Frames alternate A/B (order flipped each frame).
Usage: ab_bench.py ANGLES_JSON OUT_JSON [passes]
"""
import gc, hashlib, importlib.util, json, statistics, subprocess, sys, time, types
REPO = r'C:\_DEV\SportCamHUD'
sys.path.insert(0, REPO)
import psutil
from src.indicators import dispatcher, effects as eff_b, gauge as gauge_b, lean as lean_b
from src.indicators.helpers import resolve_indicator_font_path


def load_head(rel, name):
    src = subprocess.check_output(['git', 'show', f'HEAD:{rel}'], cwd=REPO).decode('utf-8')
    mod = types.ModuleType(name); mod.__file__ = REPO + '/' + rel
    exec(compile(src, mod.__file__, 'exec'), mod.__dict__)
    return mod


eff_a = load_head('src/indicators/effects.py', 'effects_head')
gauge_a = load_head('src/indicators/gauge.py', 'gauge_head')
lean_a = load_head('src/indicators/lean.py', 'lean_head')
VERS = {'A': (eff_a, gauge_a, lean_a), 'B': (eff_b, gauge_b, lean_b)}

W, H = 3840, 2160
layout = json.load(open(REPO + r'\def_layout.json', encoding='utf-8'))
font = resolve_indicator_font_path(layout['global'].get('font'), 'arial.ttf')
angles = json.load(open(sys.argv[1]))
passes = int(sys.argv[3]) if len(sys.argv) > 3 else 5


def render(ver, key, v):
    eff, gauge, lean = VERS[ver]
    dispatcher._render_lean_indicator = lean._render_lean_indicator
    dispatcher._render_gauge_indicator = gauge._render_gauge_indicator
    sys.modules['src.indicators.effects'] = eff  # dispatcher imports effects lazily
    cfg = layout['indicators'][key]
    fv = None if key != 'compass' else ('--' if v is None else f'{v:.0f}')
    t0 = time.perf_counter_ns()
    img, x, y, _ = dispatcher.render_value_indicator(W, H, layout, font, key, v, '°', cfg.get('label', ''),
                                                    cfg_override=cfg, formatted_val=fv, supersample=1)
    dt = (time.perf_counter_ns() - t0) / 1e6
    return dt, hashlib.sha256(img.tobytes() + repr((img.size, x, y)).encode()).hexdigest()


def cache_bytes(cache):
    from PIL import Image
    def nb(v):
        if isinstance(v, Image.Image): return v.width * v.height * len(v.getbands())
        if isinstance(v, (tuple, list)): return sum(nb(x) for x in v)
        return 0
    return sum(nb(v) for v in cache.values())


out = {}
for frag, d in angles.items():
    for key, seq in (('lean_indicator', d['lean']), ('compass', d['compass'])):
        times = {'A': [], 'B': []}; mism = 0
        for p in range(passes):
            for ver in 'AB':
                e, g, l = VERS[ver]; l.clear_lean_caches(); g.clear_compass_cache(); e.clear_effects_cache()
            for i, v in enumerate(seq):
                order = 'AB' if (i + p) % 2 == 0 else 'BA'
                res = {ver: render(ver, key, v) for ver in order}
                times['A'].append(res['A'][0]); times['B'].append(res['B'][0])
                mism += res['A'][1] != res['B'][1]
        row = {ver: {'mean_ms': statistics.fmean(t), 'median_ms': statistics.median(t)} for ver, t in times.items()}
        row['B_vs_A_mean_pct'] = 100 * (row['B']['mean_ms'] / row['A']['mean_ms'] - 1)
        row['B_vs_A_median_pct'] = 100 * (row['B']['median_ms'] / row['A']['median_ms'] - 1)
        row['rgba_mismatches'] = mism; row['renders_per_version'] = len(times['A'])
        row['cache_after_last_pass'] = {
            ver: {'lean_patch': {**VERS[ver][2]._LEAN_ROTATED_PATCH_CACHE.stats(), 'bytes': cache_bytes(VERS[ver][2]._LEAN_ROTATED_PATCH_CACHE)},
                  'compass': {**VERS[ver][1]._COMPASS_INDICATOR_CACHE.stats(), 'bytes': cache_bytes(VERS[ver][1]._COMPASS_INDICATOR_CACHE)},
                  'effects': {**VERS[ver][0]._EFFECT_CACHE.stats(), 'bytes': VERS[ver][0]._CACHED_BYTES}} for ver in 'AB'}
        out[f'{frag}.{key}'] = row
        print(frag, key, json.dumps({k: row[k] for k in ('A', 'B', 'B_vs_A_mean_pct', 'B_vs_A_median_pct', 'rgba_mismatches')}), flush=True)
sys.modules['src.indicators.effects'] = eff_b
json.dump(out, open(sys.argv[2], 'w'), indent=1)
