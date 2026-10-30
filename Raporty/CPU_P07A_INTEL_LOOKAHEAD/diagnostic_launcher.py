if __name__ == '__main__':
    import os, sys, json, dataclasses, runpy
    sys.path.insert(0, r'C:\_DEV\SportCamHUD')
    import src.ffmpeg.streaming as st
    import builtins, hashlib
    os.environ['TELEM_CPU_DIAG_DUMP_FRAMES'] = ','.join(map(str, range(300)))
    class HashSink:
        def __init__(self, path): self.path = path
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def write(self, data):
            with builtins.open(os.path.join(os.environ['P07A_DIAG_DIR'], 'hud_hashes.jsonl'), 'a') as f:
                f.write(json.dumps({'frame':os.path.basename(self.path),'sha256':hashlib.sha256(data).hexdigest()})+'\n')
            return len(data)
    def diagnostic_open(path, mode='r', *args, **kwargs):
        if mode == 'wb' and os.path.basename(str(path)).startswith('export_hud_f'): return HashSink(path)
        return builtins.open(path, mode, *args, **kwargs)
    st.open = diagnostic_open
    from src.render_telemetry_cache import RenderTelemetryCache
    from src.telemetry_precompute import TelemetryFrameCache
    out = os.environ['P07A_DIAG_DIR']
    os.makedirs(out, exist_ok=True)
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
    orig_build = st._build_stream_ffmpeg_cmd
    def build(*args, **kwargs):
        cmd, graph = orig_build(*args, **kwargs)
        if '-filter_complex' in cmd and '[vtemp]' in graph:
            graph = graph.replace('[vtemp]', '[tap];[tap]split=2[vtemp][audit]')
            cmd[cmd.index('-filter_complex')+1] = graph
            cmd += ['-map','[audit]','-an','-c:v','rawvideo','-pix_fmt','yuv420p10le','-f','framemd5',os.path.join(out,'overlay.framemd5')]
            with open(os.path.join(out,'command.json'),'w',encoding='utf8') as f: json.dump(cmd,f,indent=2)
        return cmd, graph
    st._build_stream_ffmpeg_cmd = build
    sys.argv[0] = r'C:\_DEV\SportCamHUD\SportCamHUD.py'
    runpy.run_path(sys.argv[0],run_name='__main__')
