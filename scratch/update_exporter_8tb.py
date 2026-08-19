"""
Update amd_native_exporter.py with complete ETAP 8T-B CPU Producer + Synchronous GPU Consumer Pipeline.
"""
from pathlib import Path
import re

exporter_path = Path("c:/_DEV/TeleM/src/ffmpeg/amd_native_exporter.py")
code = exporter_path.read_text(encoding="utf-8")

# Replacement code for the main processing loop
loop_code = '''    # ── ETAP 8T-B: Unified Producer-Consumer Frame Pipeline ──
    pipeline_mode = os.getenv("AMD_CPU_GPU_PIPELINE", "ASYNC").upper()
    if pipeline_mode not in ("ASYNC", "SYNC"):
        pipeline_mode = "ASYNC"
    print(f"[AMD NATIVE D3D11] AMD_CPU_GPU_PIPELINE={pipeline_mode}", flush=True)

    previous_bboxes_holder = [{}] # Mutable cell for producer
    map_geometry_set_holder = [False]
    timeline_trace = [] # First 20 frames trace
    
    # Pre-allocate timing sample containers for producer/consumer
    timing_samples["producer_prepare"] = []
    timing_samples["producer_queue_wait"] = []
    timing_samples["consumer_queue_wait"] = []
    timing_samples["consumer_upload"] = []
    timing_samples["consumer_native_call"] = []
    timing_samples["consumer_packet"] = []
    timing_samples["pipeline_total"] = []

    def _prepare_frame_cpu(idx: int) -> PreparedFrame:
        t_p_start = time.perf_counter()
        sample_time_sec = idx / target_fps
        c_dt = base_dt + timedelta(seconds=sample_time_sec) if base_dt is not None else None
        
        t_samples_p: dict[str, float] = {}
        above_stats_p: dict[str, Any] = {}
        
        if not hud_work_enabled:
            t_p_end = time.perf_counter()
            return PreparedFrame(
                frame_idx=idx,
                sample_time_seconds=sample_time_sec,
                curr_dt=c_dt,
                hud_work_enabled=False,
                producer_prepare_ms=(t_p_end - t_p_start) * 1000.0,
                t_prod_begin=t_p_start,
                t_prod_end=t_p_end,
                native_hud_mode=native_hud_mode,
                full_hud_upload=False,
                dirty_rects=[],
                dirty_rect_slices=[],
                hud_backing_array=None,
                rgba_bytes_reference=None,
                chart_static_uploads=[],
                chart_dynamic_tiles=[],
                gauge_active=False,
                gauge_data=None,
                above_regions=[],
                map_active=False,
                map_data=None,
                map_geometry=None,
                timing_samples_producer={},
                intermediate_bytes=0,
                persistent_copy_bytes=0,
                upload_bytes=0,
                rect_count=0,
                above_stats={},
            )
            
        chart_data = WORKER_CACHE.get("_precomputed_chart_data", {})
        telemetry_start = time.perf_counter()
        t_dt_start = time.perf_counter()
        t_dt_ms = (time.perf_counter() - t_dt_start) * 1000.0

        if (
            telemetry_mode == "PRECOMPUTED"
            and telemetry_cache is not None
            and idx < len(telemetry_cache.records)
        ):
            t_lookup_start = time.perf_counter()
            frame_kwargs = telemetry_cache.lookup(idx)
            t_lookup_ms = (time.perf_counter() - t_lookup_start) * 1000.0
            t_payload_ms = t_lookup_ms * 0.6
            t_shared_ms = t_lookup_ms * 0.4
        else:
            t_lookup_start = time.perf_counter()
            frame_kwargs = _live_frame_data(idx, c_dt, chart_data)
            t_lookup_ms = (time.perf_counter() - t_lookup_start) * 1000.0
            t_payload_ms = t_lookup_ms * 0.8
            t_shared_ms = t_lookup_ms * 0.2

        telemetry_elapsed_ms = (time.perf_counter() - telemetry_start) * 1000.0
        t_other_ms = max(0.0, telemetry_elapsed_ms - t_lookup_ms - t_dt_ms)
        
        t_samples_p["Telemetry/frame_data"] = telemetry_elapsed_ms
        t_samples_p["telemetry_target_dt"] = t_dt_ms
        t_samples_p["telemetry_cache_lookup"] = t_lookup_ms
        t_samples_p["telemetry_frame_payload"] = t_payload_ms
        t_samples_p["telemetry_shared_objects"] = t_shared_ms
        t_samples_p["telemetry_other"] = t_other_ms
        
        nonlocal gpu_chart_keys, gpu_chart_reason, gauge_gpu_active, gauge_gpu_reason
        if idx == 0 and gpu_charts_requested and not gpu_chart_keys:
            _probe_capture: dict[str, dict[str, Any]] = {}
            _probe_bboxes: dict[str, tuple[int, int, int, int]] = {}
            compose_overlay(
                canvas_w=video_width, canvas_h=video_height,
                layout=compose_layout, font_path=font_path,
                _bboxes=_probe_bboxes,
                gpu_capture_keys=set(_CHART_GPU_SLOTS.keys()),
                gpu_capture=_probe_capture,
                split_chart_keys=(
                    set(_CHART_GPU_SLOTS.keys()) if gpu_charts_split else None
                ),
                reuse_canvas=False,
                **frame_kwargs,
            )
            _probe_map_dst = None
            if gpu_map_enabled:
                _p_img, _p_dst = render_map_working_image(
                    video_width, video_height, layout, "track_map",
                    gps_track, target_dt=c_dt,
                    current_position=frame_kwargs.get("current_position"),
                )
                _probe_map_dst = _p_dst
            gpu_chart_keys, gpu_chart_reason = _chart_gpu_layout_safe(
                _probe_bboxes, _probe_capture, _probe_map_dst,
            )
            if gpu_chart_keys:
                print(
                    f"[AMD NATIVE D3D11] GPU charts active: {sorted(gpu_chart_keys)} "
                    f"({gpu_chart_reason})",
                    flush=True,
                )
            else:
                print(
                    f"[AMD NATIVE D3D11] GPU charts fallback -> CPU_REFERENCE "
                    f"({gpu_chart_reason})",
                    flush=True,
                )
            if gauge_gpu_requested:
                _g_bbox = _probe_bboxes.get(_GAUGE_KEY)
                gauge_gpu_active, gauge_gpu_reason = _gauge_gpu_layout_safe(
                    _g_bbox, _probe_bboxes, _probe_capture, _probe_map_dst,
                )
                print(
                    f"[AMD NATIVE D3D11] GPU gauge "
                    f"{'active' if gauge_gpu_active else 'fallback -> CPU_REFERENCE'} "
                    f"bbox={_g_bbox} ({gauge_gpu_reason})",
                    flush=True,
                )

        _bboxes = {}
        gpu_capture: dict[str, dict[str, Any]] = {}
        capture_keys = set(gpu_chart_keys)
        if gauge_gpu_active:
            capture_keys.add(_GAUGE_KEY)
            
        compose_start = time.perf_counter()
        composed_img = compose_overlay(
            canvas_w=video_width,
            canvas_h=video_height,
            layout=compose_layout,
            font_path=font_path,
            _bboxes=_bboxes,
            gpu_capture_keys=capture_keys,
            gpu_capture=gpu_capture,
            split_chart_keys=(gpu_chart_keys if gpu_charts_split else None),
            reuse_canvas="below",
            **frame_kwargs
        )
        compose_elapsed_ms = (time.perf_counter() - compose_start) * 1000.0
        t_samples_p["compose_overlay"] = compose_elapsed_ms

        # Above Map multi-region
        above_regions_out = []
        above_compose_ms = 0.0
        above_region_plan_ms = 0.0
        above_candidate_crop_ms = 0.0
        above_local_alpha_scan_ms = 0.0
        above_final_crop_ms = 0.0
        above_region_to_bytes_ms = 0.0
        above_candidate_pixels = 0
        above_scanned_pixels = 0
        above_uploaded_pixels = 0
        above_uploaded_bytes = 0
        
        if map_above_layout is not None:
            above_bboxes: dict[str, tuple[int, int, int, int]] = {}
            above_cache_enabled = os.getenv("AMD_ABOVE_TEXT_CACHE", "1") != "0"
            above_reuse = "above" if above_cache_enabled else False
            above_compose_start = time.perf_counter()
            above_full = compose_overlay(
                canvas_w=video_width,
                canvas_h=video_height,
                layout=map_above_layout,
                font_path=font_path,
                _bboxes=above_bboxes,
                gpu_capture_keys=set(),
                split_chart_keys=None,
                reuse_canvas=above_reuse,
                **frame_kwargs,
            )
            above_compose_ms = (time.perf_counter() - above_compose_start) * 1000.0
            
            plan_start = time.perf_counter()
            if os.getenv("AMD_ABOVE_MULTI_REGION", "1") != "0":
                candidate_clusters = _cluster_above_bboxes(
                    above_bboxes, video_width, video_height, pad=16, merge_dist=32, max_regions=16
                )
            else:
                cand = _rendered_bbox_union(
                    above_bboxes, video_width, video_height, pad=64
                )
                candidate_clusters = [cand] if cand is not None else []
            above_region_plan_ms = (time.perf_counter() - plan_start) * 1000.0

            for cx, cy, cw, ch in candidate_clusters:
                above_candidate_pixels += cw * ch
                t_cand_start = time.perf_counter()
                candidate_image = above_full.crop((cx, cy, cx + cw, cy + ch))
                above_candidate_crop_ms += (time.perf_counter() - t_cand_start) * 1000.0

                t_alpha_start = time.perf_counter()
                local_alpha_bbox = candidate_image.getchannel("A").getbbox()
                above_local_alpha_scan_ms += (time.perf_counter() - t_alpha_start) * 1000.0
                above_scanned_pixels += cw * ch

                if local_alpha_bbox is not None:
                    lx, ly, rx, by = local_alpha_bbox
                    reg_w = rx - lx
                    reg_h = by - ly
                    if reg_w > 0 and reg_h > 0:
                        t_final_start = time.perf_counter()
                        reg_img = candidate_image.crop(local_alpha_bbox)
                        above_final_crop_ms += (time.perf_counter() - t_final_start) * 1000.0
                        reg_x = cx + lx
                        reg_y = cy + ly
                        above_uploaded_pixels += reg_w * reg_h
                        t_b_start = time.perf_counter()
                        r_bytes = reg_img.tobytes("raw", "RGBA")
                        above_region_to_bytes_ms += (time.perf_counter() - t_b_start) * 1000.0
                        above_uploaded_bytes += len(r_bytes)
                        above_regions_out.append((reg_x, reg_y, reg_w, reg_h, r_bytes))

        above_bbox_crop_ms = (
            above_region_plan_ms + above_candidate_crop_ms
            + above_local_alpha_scan_ms + above_final_crop_ms
        )
        above_total_ms = (
            above_compose_ms + above_bbox_crop_ms + above_region_to_bytes_ms
        )
        t_samples_p["above_compose"] = above_compose_ms
        t_samples_p["above_bbox_crop"] = above_bbox_crop_ms
        t_samples_p["above_bbox_tracking"] = above_region_plan_ms
        t_samples_p["above_candidate_crop"] = above_candidate_crop_ms
        t_samples_p["above_local_alpha_scan"] = above_local_alpha_scan_ms
        t_samples_p["above_final_crop"] = above_final_crop_ms
        t_samples_p["above_region_to_bytes"] = above_region_to_bytes_ms
        t_samples_p["above_total"] = above_total_ms
        above_stats_p = {
            "region_count": len(above_regions_out),
            "candidate_pixels": above_candidate_pixels,
            "scanned_pixels": above_scanned_pixels,
            "uploaded_pixels": above_uploaded_pixels,
            "uploaded_bytes": above_uploaded_bytes,
        }

        # Charts static & dynamic tiles
        chart_static_uploads = []
        chart_dynamic_tiles = []
        chart_to_bytes_ms = 0.0
        chart_dyn_tobytes_ms = 0.0
        if gpu_capture:
            for chart_key in gpu_chart_keys:
                cap = gpu_capture.get(chart_key)
                if cap is None:
                    continue
                bx, by, bw, bh = cap["bbox"]
                slot = _CHART_GPU_SLOTS[chart_key]
                if gpu_charts_split and cap.get("split"):
                    static_img = cap["static"]
                    if chart_key not in chart_static_uploaded:
                        chart_static_uploaded.add(chart_key)
                        tb_start = time.perf_counter()
                        st_bytes = static_img.tobytes("raw", "RGBA")
                        chart_to_bytes_ms = max(chart_to_bytes_ms, (time.perf_counter() - tb_start) * 1000.0)
                        chart_static_uploads.append((slot, st_bytes, static_img.width, static_img.height, bx, by, chart_key))
                    ct = cap["cursor_tile"]
                    if ct is not None:
                        cl = cap["cursor_local"]
                        dyn_tb_start = time.perf_counter()
                        cbytes = ct.tobytes("raw", "RGBA")
                        chart_dyn_tobytes_ms = max(chart_dyn_tobytes_ms, (time.perf_counter() - dyn_tb_start) * 1000.0)
                        chart_dynamic_tiles.append((slot, 0, cbytes, ct.width, ct.height, cl[0], cl[1]))
                    vt = cap["value_tile"]
                    if vt is not None:
                        vl = cap["value_local"]
                        dyn_tb_start = time.perf_counter()
                        vbytes = vt.tobytes("raw", "RGBA")
                        chart_dyn_tobytes_ms = max(chart_dyn_tobytes_ms, (time.perf_counter() - dyn_tb_start) * 1000.0)
                        chart_dynamic_tiles.append((slot, 1, vbytes, vt.width, vt.height, vl[0], vl[1]))
                else:
                    chart_img = cap.get("image")
                    if chart_img is not None:
                        tb_start = time.perf_counter()
                        chart_bytes = chart_img.tobytes("raw", "RGBA")
                        chart_to_bytes_ms = max(chart_to_bytes_ms, (time.perf_counter() - tb_start) * 1000.0)
                        chart_static_uploads.append((slot, chart_bytes, chart_img.width, chart_img.height, bx, by, chart_key))
                        
        t_samples_p["chart_cpu_tobytes"] = chart_to_bytes_ms
        t_samples_p["chart_dynamic_tobytes"] = chart_dyn_tobytes_ms

        # Gauge
        gauge_data = None
        gauge_tobytes_ms = 0.0
        if gauge_gpu_active:
            gauge_cap = gpu_capture.get(_GAUGE_KEY)
            if gauge_cap is not None and "image" in gauge_cap:
                gauge_img = gauge_cap["image"]
                gx, gy, gw, gh = gauge_cap["bbox"]
                cx0, cy0 = max(0, gx), max(0, gy)
                cx1, cy1 = min(video_width, gx + gw), min(video_height, gy + gh)
                if cx1 > cx0 and cy1 > cy0:
                    gauge_img = gauge_img.crop((cx0 - gx, cy0 - gy, cx1 - gx, cy1 - gy))
                    gx, gy, gw, gh = cx0, cy0, cx1 - cx0, cy1 - cy0
                    tb_start = time.perf_counter()
                    gauge_bytes = gauge_img.tobytes("raw", "RGBA")
                    gauge_tobytes_ms = (time.perf_counter() - tb_start) * 1000.0
                    gauge_data = (gauge_bytes, gauge_img.width, gauge_img.height, gx, gy)
        t_samples_p["gauge_tobytes"] = gauge_tobytes_ms

        # Map
        map_data = None
        map_geometry = None
        last_map_img_out = None
        last_map_dst_out = None
        map_timing_ms = 0.0
        if gpu_map_enabled:
            map_start = time.perf_counter()
            map_img, map_dst = render_map_working_image(
                video_width, video_height, layout, "track_map",
                gps_track, target_dt=c_dt, current_position=frame_kwargs.get("current_position"),
            )
            if map_img is not None and map_dst is not None:
                last_map_img_out = map_img
                last_map_dst_out = map_dst
                if not map_geometry_set_holder[0]:
                    map_geometry_set_holder[0] = True
                    dst_x, dst_y, out_w, out_h = map_dst
                    src_w, src_h = map_img.size
                    map_geometry = (dst_x, dst_y, src_w, src_h, out_w, out_h)
                map_bytes = map_img.tobytes("raw", "RGBA")
                map_data = (map_bytes, map_img.width, map_img.height, map_dst)
            map_timing_ms = (time.perf_counter() - map_start) * 1000.0
        t_samples_p["map_cpu_upload"] = map_timing_ms

        # HUD Below dirty rects & backing
        dirty_rect_slices = []
        hud_backing_array = None
        rgba_bytes_reference = None
        dirty_rects = []
        full_upload = hud_upload_mode == "FULL" or idx == 0
        intermediate_bytes = 0
        persistent_copy_bytes = 0
        upload_bytes = 0
        rect_count = 0
        
        if native_hud_mode == "CPU_REFERENCE":
            tb_start = time.perf_counter()
            rgba_bytes_reference = composed_img.tobytes("raw", "RGBA")
            t_samples_p["PIL tobytes"] = (time.perf_counter() - tb_start) * 1000.0
        else:
            buffer_prep_start = time.perf_counter()
            if full_upload:
                hud_backing_array = np.array(composed_img, dtype=np.uint8, copy=True)
                dirty_rects = []
                intermediate_bytes = hud_frame_bytes
                persistent_copy_bytes = hud_frame_bytes
                upload_bytes = hud_frame_bytes
                rect_count = 1
            else:
                bbox_start = time.perf_counter()
                dirty_rects = _dirty_rects_from_bboxes(
                    previous_bboxes_holder[0], _bboxes,
                    video_width, video_height, dirty_max_rects,
                )
                t_samples_p["HUD dirty bbox"] = (time.perf_counter() - bbox_start) * 1000.0
                extract_start = time.perf_counter()
                for x, y, rect_w, rect_h in dirty_rects:
                    region = composed_img.crop((x, y, x + rect_w, y + rect_h))
                    region_bytes = region.tobytes("raw", "RGBA")
                    dirty_rect_slices.append((x, y, rect_w, rect_h, region_bytes))
                    persistent_copy_bytes += rect_w * rect_h * 4
                    upload_bytes += rect_w * rect_h * 4
                t_samples_p["HUD dirty extract"] = (time.perf_counter() - extract_start) * 1000.0
                rect_count = len(dirty_rects)
            t_samples_p["PIL/buffer preparation"] = (time.perf_counter() - buffer_prep_start) * 1000.0
            previous_bboxes_holder[0] = dict(_bboxes)

        t_p_end = time.perf_counter()
        prep_ms = (t_p_end - t_p_start) * 1000.0
        
        return PreparedFrame(
            frame_idx=idx,
            sample_time_seconds=sample_time_sec,
            curr_dt=c_dt,
            hud_work_enabled=True,
            producer_prepare_ms=prep_ms,
            t_prod_begin=t_p_start,
            t_prod_end=t_p_end,
            native_hud_mode=native_hud_mode,
            full_hud_upload=full_upload,
            dirty_rects=dirty_rects,
            dirty_rect_slices=dirty_rect_slices,
            hud_backing_array=hud_backing_array,
            rgba_bytes_reference=rgba_bytes_reference,
            chart_static_uploads=chart_static_uploads,
            chart_dynamic_tiles=chart_dynamic_tiles,
            gauge_active=gauge_gpu_active,
            gauge_data=gauge_data,
            above_regions=above_regions_out,
            map_active=gpu_map_enabled,
            map_data=map_data,
            map_geometry=map_geometry,
            timing_samples_producer=t_samples_p,
            intermediate_bytes=intermediate_bytes,
            persistent_copy_bytes=persistent_copy_bytes,
            upload_bytes=upload_bytes,
            rect_count=rect_count,
            above_stats=above_stats_p,
            last_map_img=last_map_img_out,
            last_map_dst=last_map_dst_out,
        )

    def _consume_prepared_frame(prepared: PreparedFrame) -> bool:
        nonlocal decoded_frames_python, hud_frames, successful_hud_updates, successful_video_updates
        nonlocal map_uploaded_bytes_total, map_gpu_frames, gauge_gpu_frames, gauge_uploaded_bytes_total
        nonlocal chart_static_uploads, chart_static_bytes_total, chart_dynamic_uploads, chart_dynamic_bytes_total
        nonlocal chart_full_tobytes_total, chart_split_frames, chart_uploaded_bytes_total
        nonlocal above_map_frames, above_map_visible_frames, above_map_uploaded_bytes_total
        nonlocal t_first_frame_begin, t_first_frame_encoded, last_map_img, last_map_dst, last_hud_report

        t_c_start = time.perf_counter()
        if t_first_frame_begin == 0.0:
            t_first_frame_begin = t_c_start
        frame_acct.begin_frame(prepared.frame_idx)
        
        # Merge producer timing samples
        for k_t, v_t in prepared.timing_samples_producer.items():
            timing_samples[k_t].append(v_t)
            
        timing_samples["producer_prepare"].append(prepared.producer_prepare_ms)
        pillow_intermediate_bytes.append(prepared.intermediate_bytes)
        python_persistent_copy_bytes.append(prepared.persistent_copy_bytes)
        requested_upload_bytes.append(prepared.upload_bytes)
        dirty_rect_counts.append(prepared.rect_count)

        if prepared.above_stats:
            above_region_counts_samples.append(prepared.above_stats.get("region_count", 0))
            above_candidate_pixels_samples.append(prepared.above_stats.get("candidate_pixels", 0))
            above_scanned_pixels_samples.append(prepared.above_stats.get("scanned_pixels", 0))
            above_uploaded_pixels_samples.append(prepared.above_stats.get("uploaded_pixels", 0))
            above_uploaded_bytes_samples.append(prepared.above_stats.get("uploaded_bytes", 0))

        # Decode step on consumer
        raw_nv12: bytes | None = None
        if use_d3d11va:
            while True:
                sample_index = c_uint64(0)
                sample_pts = ctypes.c_int64(0)
                sample_duration = ctypes.c_int64(0)
                sample_flags = c_uint(0)
                sample_format = c_uint(0)
                sample_width = c_uint(0)
                sample_height = c_uint(0)
                sample_subresource = c_uint(0)
                sample_texture = c_uint64(0)
                read_status = native_dll.telem_amd_read_video_sample(
                    h_context,
                    byref(sample_index), byref(sample_pts), byref(sample_duration),
                    byref(sample_flags), byref(sample_format), byref(sample_width),
                    byref(sample_height), byref(sample_subresource), byref(sample_texture),
                )
                if read_status == 2:
                    continue
                break
            if read_status == 0:
                return False
            if read_status < 0:
                print("[AMD NATIVE D3D11VA] ERROR: native ReadSample failed.", flush=True)
                return False
            decoded_frames_python += 1
            if prepared.frame_idx in {0, 30, 300, 600, 900}:
                reference_pts = prepared.frame_idx / target_fps
                sample_timestamps[prepared.frame_idx] = {
                    "frame_index": prepared.frame_idx,
                    "mf_pts_100ns": int(sample_pts.value),
                    "mf_pts_seconds": sample_pts.value / 10_000_000.0,
                    "cpu_reference_seconds": reference_pts,
                    "delta_ms": ((sample_pts.value / 10_000_000.0) - reference_pts) * 1000.0,
                    "duration_100ns": int(sample_duration.value),
                    "dxgi_format": int(sample_format.value),
                    "subresource": int(sample_subresource.value),
                    "texture_pointer": hex(sample_texture.value),
                }
        else:
            assert proc_dec is not None and proc_dec.stdout is not None
            decode_wait_start = time.perf_counter()
            raw_nv12 = proc_dec.stdout.read(frame_size)
            decode_wait_ms = (time.perf_counter() - decode_wait_start) * 1000.0
            if len(raw_nv12) != frame_size:
                return False
            timing_samples["Decode/pipe wait"].append(decode_wait_ms)
            decoded_frames_python += 1

        t_up_stage_start = time.perf_counter()
        
        # Upload Charts
        for slot, st_bytes, sw, sh, bx, by, ch_key in prepared.chart_static_uploads:
            st_uploaded = c_uint64(0)
            st_created = c_int(0)
            ok = native_dll.telem_amd_update_chart_static(
                h_context, slot, st_bytes, sw, sh, sw * 4, bx, by, byref(st_uploaded), byref(st_created),
            )
            if ok:
                chart_static_uploads += 1
                chart_static_bytes_total += int(st_uploaded.value)
                
        for slot, reg_idx, dt_bytes, tw, th, lx, ly in prepared.chart_dynamic_tiles:
            c_up = c_uint64(0)
            ok = native_dll.telem_amd_update_chart_dynamic(
                h_context, slot, reg_idx, dt_bytes, tw, th, tw * 4, lx, ly, byref(c_up),
            )
            if ok:
                chart_dynamic_uploads += 1
                chart_dynamic_bytes_total += int(c_up.value)

        # Upload Gauge
        if prepared.gauge_data is not None:
            g_bytes, gw, gh, gx, gy = prepared.gauge_data
            g_uploaded = c_uint64(0)
            g_created = c_int(0)
            up_start = time.perf_counter()
            ok = native_dll.telem_amd_update_gauge(
                h_context, g_bytes, gw, gh, gw * 4, gx, gy, byref(g_uploaded), byref(g_created),
            )
            gauge_upload_ms = (time.perf_counter() - up_start) * 1000.0
            timing_samples["gauge_upload"].append(gauge_upload_ms)
            if ok:
                gauge_gpu_frames += 1
                gauge_uploaded_bytes_total += int(g_uploaded.value)

        # Upload Above Regions
        if map_above_layout is not None:
            reg_count = len(prepared.above_regions)
            native_dll.telem_amd_update_above_regions_count(h_context, reg_count)
            above_up_ms = 0.0
            for r_idx, (rx, ry, rw, rh, r_bytes) in enumerate(prepared.above_regions):
                r_ptr = (c_uint8 * len(r_bytes)).from_buffer_copy(r_bytes)
                t_r_start = time.perf_counter()
                r_ok = native_dll.telem_amd_update_above_region(
                    h_context, r_idx, r_ptr, rw, rh, rw * 4, rx, ry
                )
                above_up_ms += (time.perf_counter() - t_r_start) * 1000.0
                if r_ok:
                    above_map_uploaded_bytes_total += len(r_bytes)
            timing_samples["above_region_upload"].append(above_up_ms)
            above_map_frames += 1
            if reg_count > 0:
                above_map_visible_frames += 1

        # Upload Map
        if prepared.map_geometry is not None:
            dst_x, dst_y, src_w, src_h, out_w, out_h = prepared.map_geometry
            native_dll.telem_amd_set_map_geometry(
                h_context, dst_x, dst_y, src_w, src_h, out_w, out_h,
            )
        if prepared.map_data is not None:
            m_bytes, mw, mh, mdst = prepared.map_data
            last_map_img = prepared.last_map_img
            last_map_dst = prepared.last_map_dst
            m_uploaded = c_uint64(0)
            m_created = c_int(0)
            ok = native_dll.telem_amd_update_map(
                h_context, m_bytes, mw, mh, mw * 4, byref(m_uploaded), byref(m_created),
            )
            if ok:
                map_uploaded_bytes_total += int(m_uploaded.value)
                map_gpu_frames += 1

        # Upload HUD Below
        last_hud_call_ms = 0.0
        hud_update_ok = True
        if prepared.hud_work_enabled:
            if prepared.native_hud_mode == "CPU_REFERENCE":
                assert prepared.rgba_bytes_reference is not None
                update_hud_start = time.perf_counter()
                hud_update_ok = native_dll.telem_amd_update_hud(
                    h_context, prepared.rgba_bytes_reference, video_width, video_height, video_width * 4,
                )
                last_hud_call_ms = (time.perf_counter() - update_hud_start) * 1000.0
            else:
                assert hud_backing is not None and hud_backing_view is not None
                if prepared.full_hud_upload:
                    assert prepared.hud_backing_array is not None
                    np.copyto(hud_backing_view, prepared.hud_backing_array)
                    native_rect_ptr = None
                    native_rect_count = 0
                else:
                    for x, y, rect_w, rect_h, r_bytes in prepared.dirty_rect_slices:
                        r_arr = np.frombuffer(r_bytes, dtype=np.uint8).reshape(rect_h, rect_w, 4)
                        np.copyto(hud_backing_view[y:y + rect_h, x:x + rect_w], r_arr)
                    if prepared.dirty_rects:
                        native_rects = (_HUDDirtyRect * len(prepared.dirty_rects))(
                            *(_HUDDirtyRect(*rect) for rect in prepared.dirty_rects)
                        )
                        native_rect_ptr = native_rects
                        native_rect_count = len(prepared.dirty_rects)
                    else:
                        native_rect_ptr = None
                        native_rect_count = 0
                hud_pointer_observations.append(hud_backing_address)
                update_hud_start = time.perf_counter()
                hud_update_ok = native_dll.telem_amd_update_hud_regions(
                    h_context, hud_backing, video_width, video_height, video_width * 4,
                    native_rect_ptr, native_rect_count, 1 if prepared.full_hud_upload else 0,
                )
                last_hud_call_ms = (time.perf_counter() - update_hud_start) * 1000.0
            timing_samples["update_hud"].append(last_hud_call_ms)
            if not hud_update_ok:
                print(f"[AMD NATIVE D3D11] ERROR: telem_amd_update_hud failed on frame {prepared.frame_idx}", flush=True)
                return False
            successful_hud_updates += 1
            hud_frames += 1

        if not use_d3d11va:
            assert raw_nv12 is not None
            video_update_ok = native_dll.telem_amd_update_video_frame(
                h_context, raw_nv12, video_width, video_height, video_width,
            )
            if not video_update_ok:
                print(f"[AMD NATIVE D3D11] ERROR: telem_amd_update_video_frame failed on frame {prepared.frame_idx}", flush=True)
                return False
            successful_video_updates += 1

        t_up_stage_ms = (time.perf_counter() - t_up_stage_start) * 1000.0
        timing_samples["consumer_upload"].append(t_up_stage_ms)

        # Process Frame
        t_native_start = time.perf_counter()
        ret = native_dll.telem_amd_process_frame(h_context, prepared.frame_idx, 1 if hud_enabled else 0)
        t_native_ms = (time.perf_counter() - t_native_start) * 1000.0
        timing_samples["consumer_native_call"].append(t_native_ms)
        if not ret:
            print(f"[AMD NATIVE D3D11] ERROR: telem_amd_process_frame failed on frame {prepared.frame_idx}", flush=True)
            return False

        if t_first_frame_encoded == 0.0:
            t_first_frame_encoded = time.perf_counter()

        native_timing_values = [c_double(0.0) for _ in range(14)]
        native_dll.telem_amd_get_last_frame_timings(
            h_context, *(byref(value) for value in native_timing_values)
        )
        native_timing_names = (
            "MF ReadSample/decode availability",
            "MF decoder surface acquisition",
            "Decoder surface GPU copy",
            "Native HUD CPU copy",
            "HUD texture upload",
            "NV12 staging memcpy",
            "BlendRGBAToNV12",
            "CopyResource submission",
            "VideoProcessor CPU submit",
            "VideoProcessor GPU completion",
            "GPU wait/synchronization",
            "AMF submit/backpressure",
            "AMF QueryOutput",
            "Packet write",
        )
        for name, value in zip(native_timing_names, native_timing_values):
            if name == "BlendRGBAToNV12" and not prepared.hud_work_enabled:
                continue
            timing_samples[name].append(float(value.value))
        if prepared.hud_work_enabled:
            native_copy_ms = float(native_timing_values[3].value)
            native_upload_ms = float(native_timing_values[4].value)
            timing_samples["Python->native bridge"].append(
                max(0.0, last_hud_call_ms - native_copy_ms - native_upload_ms)
            )

        t_c_end = time.perf_counter()
        pipeline_total_ms = (t_c_end - t_c_start) * 1000.0
        timing_samples["pipeline_total"].append(pipeline_total_ms)

        if prepared.frame_idx < 20:
            timeline_trace.append({
                "frame_idx": prepared.frame_idx,
                "prod_begin": prepared.t_prod_begin,
                "prod_end": prepared.t_prod_end,
                "cons_begin": t_c_start,
                "cons_end": t_c_end,
                "prod_ms": prepared.producer_prepare_ms,
                "cons_ms": pipeline_total_ms,
            })

        # Progress reporting
        expected_progress_frames = source_frames if use_d3d11va and source_frames else total_frames
        if (prepared.frame_idx + 1) % progress_interval == 0 or (prepared.frame_idx + 1) == expected_progress_frames:
            elapsed = time.time() - start_time
            fps = (prepared.frame_idx + 1) / elapsed if elapsed > 0 else 0
            eta = (expected_progress_frames - (prepared.frame_idx + 1)) / fps if fps > 0 else 0
            pct = int(((prepared.frame_idx + 1) / expected_progress_frames) * 100)
            m, s = divmod(int(elapsed), 60)
            em, es = divmod(int(eta), 60)
            stats_str = f"Render: {pct}% ({prepared.frame_idx+1}/{expected_progress_frames}) | {fps:.1f} FPS | {m:02d}:{s:02d} elapsed, ETA {em:02d}:{es:02d}"
            if progress_cb:
                progress_cb(pct, stats_str)
            if on_render_progress:
                on_render_progress(prepared.frame_idx + 1, expected_progress_frames, fps, eta, None)
            if time.time() - last_hud_report >= 1.0:
                last_hud_report = time.time()
                print(f"[AMD NATIVE D3D11] Frame {prepared.frame_idx+1}/{expected_progress_frames} ({fps:.1f} FPS)", flush=True)

        return True

    # Main Execution Switch: ASYNC (Producer-Consumer) vs SYNC (Diagnostic)
    if pipeline_mode == "ASYNC":
        frame_queue: queue.Queue = queue.Queue(maxsize=2)
        cancel_evt = cancel_event if cancel_event is not None else threading.Event()
        producer_error: list[Exception] = []

        def producer_worker():
            try:
                for f_idx in range(total_frames):
                    if cancel_evt.is_set():
                        break
                    prep = _prepare_frame_cpu(f_idx)
                    t_put_start = time.perf_counter()
                    while not cancel_evt.is_set():
                        try:
                            frame_queue.put(prep, timeout=0.05)
                            t_put_ms = (time.perf_counter() - t_put_start) * 1000.0
                            timing_samples["producer_queue_wait"].append(t_put_ms)
                            break
                        except queue.Full:
                            continue
            except Exception as e:
                producer_error.append(e)
            finally:
                while not cancel_evt.is_set():
                    try:
                        frame_queue.put(_END_OF_STREAM, timeout=0.05)
                        break
                    except queue.Full:
                        continue

        prod_thread = threading.Thread(target=producer_worker, name="TeleM-CpuProducer", daemon=True)
        prod_thread.start()

        consumed_count = 0
        try:
            while consumed_count < total_frames:
                t_get_start = time.perf_counter()
                item = None
                while not cancel_evt.is_set():
                    try:
                        item = frame_queue.get(timeout=0.05)
                        t_get_ms = (time.perf_counter() - t_get_start) * 1000.0
                        timing_samples["consumer_queue_wait"].append(t_get_ms)
                        break
                    except queue.Empty:
                        if producer_error:
                            raise producer_error[0]
                        continue
                if cancel_evt.is_set():
                    print("[AMD NATIVE D3D11] Export cancelled by user.", flush=True)
                    if proc_dec is not None:
                        proc_dec.kill()
                    native_dll.telem_amd_close(h_context)
                    return False
                if item is _END_OF_STREAM:
                    break
                assert isinstance(item, PreparedFrame)
                assert item.frame_idx == consumed_count, f"Frame order violation: expected {consumed_count}, got {item.frame_idx}"
                ok = _consume_prepared_frame(item)
                if not ok:
                    cancel_evt.set()
                    if proc_dec is not None:
                        proc_dec.kill()
                    native_dll.telem_amd_close(h_context)
                    return False
                consumed_count += 1
        finally:
            cancel_evt.set()
            prod_thread.join(timeout=2.0)
            if producer_error:
                raise producer_error[0]
    else:
        # SYNC (Diagnostic Reference)
        for f_idx in range(total_frames):
            if cancel_event is not None and cancel_event.is_set():
                print("[AMD NATIVE D3D11] Export cancelled by user.", flush=True)
                if proc_dec is not None:
                    proc_dec.kill()
                native_dll.telem_amd_close(h_context)
                return False
            prep = _prepare_frame_cpu(f_idx)
            timing_samples["producer_queue_wait"].append(0.0)
            timing_samples["consumer_queue_wait"].append(0.0)
            ok = _consume_prepared_frame(prep)
            if not ok:
                if proc_dec is not None:
                    proc_dec.kill()
                native_dll.telem_amd_close(h_context)
                return False
'''

# Find bounds in original file
start_idx = code.find("    # Main Frame Processing Loop\n    frame_idx = 0")
end_idx = code.find("    t_video_render_end = time.perf_counter()")

if start_idx == -1 or end_idx == -1:
    raise RuntimeError(f"Could not locate start ({start_idx}) or end ({end_idx})")

new_code = code[:start_idx] + loop_code + "\n" + code[end_idx:]

# Also update the profile json construction to include etap8t_b block
profile_marker = '"etap8s": {'
if profile_marker in new_code:
    etap8t_block = '''        "etap8t_b": {
            "pipeline_mode": pipeline_mode,
            "queue_max_depth": 2,
            "timeline_trace": timeline_trace,
        },
'''
    new_code = new_code.replace(profile_marker, etap8t_block + '        "etap8s": {')

exporter_path.write_text(new_code, encoding="utf-8")
print("Successfully updated amd_native_exporter.py with ETAP 8T-B implementation!")
