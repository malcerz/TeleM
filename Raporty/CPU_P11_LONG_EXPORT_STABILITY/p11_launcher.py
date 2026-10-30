"""P1.1 launcher: run the canonical CPU harness unchanged, plus count completed
HUD render jobs (frame index, worker pid) in the parent into P11_PROGRESS (JSON, 1 s).
Read-only: it only adds a done-callback to futures returned by _RenderExecutor.submit.
"""
if __name__ == '__main__':
    import atexit, json, os, runpy, sys, threading, time
    REPO = r'C:\_DEV\SportCamHUD'
    sys.path.insert(0, REPO)
    import src.ffmpeg.streaming as st

    out = os.environ['P11_PROGRESS']
    lock = threading.Lock()
    jobs = []  # one dict per executor (= one export job)
    orig_init, orig_submit = st._RenderExecutor.__init__, st._RenderExecutor.submit

    def init(self, *a, **k):
        orig_init(self, *a, **k)
        with lock:
            self._p11 = {'t_start': time.time(), 'done': 0, 'idx': {}, 'pids': {}, 'errors': [], 't_first': None, 't_last': None}
            jobs.append(self._p11)

    def submit(self, *a, **k):
        fut = orig_submit(self, *a, **k)
        st_ = self._p11

        def cb(f):
            try:
                r = f.result()
            except Exception as exc:  # noqa: BLE001
                with lock:
                    st_['errors'].append(repr(exc))
                return
            now = time.time()
            with lock:
                st_['done'] += 1
                st_['idx'][r[0]] = st_['idx'].get(r[0], 0) + 1
                if len(r) >= 10:
                    st_['pids'][r[2]] = st_['pids'].get(r[2], 0) + 1
                st_['t_first'] = st_['t_first'] or now
                st_['t_last'] = now
        fut.add_done_callback(cb)
        return fut

    st._RenderExecutor.__init__, st._RenderExecutor.submit = init, submit

    def dump():
        with lock:
            rows = []
            for j in jobs:
                idx = j['idx']
                rows.append({'t_start': j['t_start'], 't_first': j['t_first'], 't_last': j['t_last'], 'done': j['done'],
                             'distinct': len(idx), 'duplicates': sum(v - 1 for v in idx.values() if v > 1),
                             'min_idx': min(idx) if idx else None, 'max_idx': max(idx) if idx else None,
                             'per_worker_pid': {str(p): n for p, n in j['pids'].items()}, 'errors': j['errors'][:5]})
        tmp = out + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({'t': time.time(), 'jobs': rows}, f)
        for _ in range(20):  # Windows refuses the rename while the monitor has the file open
            try:
                os.replace(tmp, out)
                return
            except PermissionError:
                time.sleep(0.05)

    def loop():
        while True:
            dump()
            time.sleep(1)
    threading.Thread(target=loop, daemon=True, name='p11-progress').start()
    atexit.register(dump)
    sys.argv[0] = REPO + r'\SportCamHUD.py'
    runpy.run_path(sys.argv[0], run_name='__main__')
