if __name__ == '__main__':
    import os, sys, json, dataclasses, runpy
    sys.path.insert(0, r'C:\_DEV\SportCamHUD')
    import src.ffmpeg.streaming as st
    import builtins, hashlib
    os.environ['TELEM_CPU_DIAG_DUMP_FRAMES'] = ','.join(map(str, range(150)))
    class HashSink:
        def __init__(self, path): self.path = path
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def write(self, data):
            with builtins.open(os.path.join(os.environ['P07A_DIAG_DIR'], 'hud_hashes.jsonl'), 'a') as f:
                f.write(json.dumps({'frame':os.path.basename(self.path),'sha256':hashlib.sha256(data).hexdigest()})+'\n')

            if os.path.basename(self.path) == 'export_hud_f' + os.environ.get('P09_CAPTURE_FRAME','-1') + '.rgba':
                with builtins.open(self.path, 'wb') as capture: capture.write(data)
            return len(data)
    def diagnostic_open(path, mode='r', *args, **kwargs):
        if mode == 'wb' and os.path.basename(str(path)).startswith('export_hud_f'): return HashSink(path)
        return builtins.open(path, mode, *args, **kwargs)
    st.open = diagnostic_open
    from src.render_telemetry_cache import RenderTelemetryCache
    from src.telemetry_precompute import TelemetryFrameCache
    out = os.environ['P07A_DIAG_DIR']
    os.makedirs(out, exist_ok=True)
    if os.environ.get('TELEM_CPU_WORKERS') == '1':
        original_frame_job = st.render_frame_bytes_job
        def capture_frame(job):
            idx, data = original_frame_job(job)
            with builtins.open(os.path.join(out, 'hud_hashes.jsonl'), 'a') as f:
                f.write(json.dumps({'frame': 'export_hud_f%d.rgba' % (idx - int(os.environ.get('P09_START','900'))), 'sha256': hashlib.sha256(data).hexdigest()}) + '\n')
            if idx - int(os.environ.get('P09_START','900')) == int(os.environ.get('P09_CAPTURE_FRAME','-1')):
                with builtins.open(os.path.join(out, 'export_hud_f%d.rgba' % (idx - int(os.environ.get('P09_START','900')))), 'wb') as f: f.write(data)
            return idx, data
        st.render_frame_bytes_job = capture_frame
    for cls in (RenderTelemetryCache, TelemetryFrameCache):
        original = cls.record
        def make_record(orig):
            def record(self, idx):
                value = orig(self, idx)
                with open(os.path.join(out, 'records.jsonl'), 'a', encoding='utf8') as f:
                    f.write(json.dumps({'frame':idx,'value':dataclasses.asdict(value)}, sort_keys=True, default=str, allow_nan=True)+'\n')
                return value
            return record
        cls.record = make_record(original)
    sys.argv[0] = r'C:\_DEV\SportCamHUD\SportCamHUD.py'
    runpy.run_path(sys.argv[0],run_name='__main__')
