"""P1.1 diagnostic hook (via PYTHONPATH): inside spawned export workers only, log
process RSS and lean/compass/effect cache sizes every 5 s. Read-only."""
import os
import sys

if os.environ.get('P11_CACHE_LOG') and '--multiprocessing-fork' in sys.argv:
    import json, threading, time

    def _img_bytes(cache):
        try:
            total = 0
            for v in list(cache.values()):
                for x in (v if isinstance(v, tuple) else (v,)):
                    if hasattr(x, 'getbands'):
                        total += x.width * x.height * len(x.getbands())
            return total
        except RuntimeError:  # mutated while listing; next sample
            return None

    def _loop():
        path = os.path.join(os.environ['P11_CACHE_LOG'], f'worker_{os.getpid()}.jsonl')
        while True:
            time.sleep(5)
            m = sys.modules
            row = {'t': time.time(), 'pid': os.getpid()}
            try:
                if 'src.indicators.lean' in m:
                    c = m['src.indicators.lean']._LEAN_ROTATED_PATCH_CACHE
                    row['lean_patch'] = dict(c.stats(), bytes=_img_bytes(c))
                if 'src.indicators.gauge' in m:
                    c = m['src.indicators.gauge']._COMPASS_INDICATOR_CACHE
                    row['compass'] = dict(c.stats(), bytes=_img_bytes(c))
                if 'src.indicators.effects' in m:
                    e = m['src.indicators.effects']
                    row['effects'] = dict(e._EFFECT_CACHE.stats(), bytes=e._CACHED_BYTES)
                if 'src.indicators.helpers' in m:
                    c = m['src.indicators.helpers']._STATIC_CACHE
                    row['static'] = dict(c.stats(), bytes=_img_bytes(c))
                import psutil
                row['rss'] = psutil.Process().memory_info().rss
            except Exception as exc:  # noqa: BLE001
                row['error'] = repr(exc)
            with open(path, 'a') as f:
                f.write(json.dumps(row) + '\n')

    threading.Thread(target=_loop, daemon=True, name='p11-cache-log').start()
