"""P1.0: per-indicator cost of lean/compass with the real def_layout.json config.

Usage: python indicator_profile.py ANGLES_JSON OUT_JSON [--cprofile]
ANGLES_JSON holds real per-frame lean/compass values ({frag: {lean: [...], compass: [...]}}).
Renders through the production dispatcher (render_value_indicator, incl. effects).
"""
import copy, cProfile, gc, hashlib, io, json, pstats, sys, time
sys.path.insert(0, r'C:\_DEV\SportCamHUD')
import psutil
from src.indicators import dispatcher, effects, gauge, lean
from src.indicators.helpers import resolve_indicator_font_path

W, H = 3840, 2160
layout = json.load(open(r'C:\_DEV\SportCamHUD\def_layout.json', encoding='utf-8'))
font = resolve_indicator_font_path(layout['indicators']['compass'].get('font') or None,
                                   resolve_indicator_font_path(layout['global'].get('font'), 'arial.ttf'))
angles = json.load(open(sys.argv[1]))
proc = psutil.Process()


def render(key, value, fv):
    cfg = layout['indicators'][key]
    return dispatcher.render_value_indicator(W, H, layout, font, key, value, '°', cfg.get('label', ''),
                                            cfg_override=cfg, formatted_val=fv, supersample=1)


def fv_for(key, v):
    if key == 'compass':
        return '--' if v is None else f'{v:.0f}'
    return None


def clear_all():
    lean.clear_lean_caches(); gauge.clear_compass_cache(); effects.clear_effects_cache()


def run(key, seq, reps=3):
    rows = []
    for rep in range(reps):
        clear_all(); gc.collect()
        rss0 = proc.memory_info().rss
        t = []
        hashes = []
        for v in seq:
            t0 = time.perf_counter_ns()
            img, x, y, _ = render(key, v, fv_for(key, v))
            t.append((time.perf_counter_ns() - t0) / 1e6)
            hashes.append(hashlib.sha256(img.tobytes() + repr((img.size, x, y)).encode()).hexdigest())
        t.sort()
        rows.append({'mean_ms': sum(t) / len(t), 'median_ms': t[len(t) // 2], 'p90_ms': t[int(len(t) * .9)],
                     'rss_delta_mib': (proc.memory_info().rss - rss0) / 1048576,
                     'lean_patch': lean._LEAN_ROTATED_PATCH_CACHE.stats(),
                     'compass': gauge._COMPASS_INDICATOR_CACHE.stats(),
                     'effects': effects.get_effects_cache_stats(), 'hashes': hashes})
    return rows


out = {'font': font}
for frag, d in angles.items():
    for key, seq in (('lean_indicator', d['lean']), ('compass', d['compass'])):
        rows = run(key, seq)
        best = min(rows, key=lambda r: r['mean_ms'])
        assert all(r['hashes'] == rows[0]['hashes'] for r in rows), 'non-deterministic across reps'
        out[f'{frag}.{key}'] = {k: v for k, v in best.items() if k != 'hashes'}
        out[f'{frag}.{key}']['all_mean_ms'] = [r['mean_ms'] for r in rows]
        out[f'{frag}.{key}']['frames_sha256'] = rows[0]['hashes']
        print(frag, key, round(best['mean_ms'], 3), 'ms', {k: best[k] for k in ('lean_patch', 'compass')}, flush=True)

if '--cprofile' in sys.argv:
    for key in ('lean_indicator', 'compass'):
        seq = angles['900']['lean' if key == 'lean_indicator' else 'compass']
        clear_all()
        pr = cProfile.Profile(); pr.enable()
        for v in seq:
            render(key, v, fv_for(key, v))
        pr.disable()
        s = io.StringIO(); pstats.Stats(pr, stream=s).sort_stats('tottime').print_stats(18)
        out[f'cprofile.{key}'] = s.getvalue()
        print(s.getvalue())
json.dump(out, open(sys.argv[2], 'w'), indent=1)
