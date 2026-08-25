# RAPORT MULTIFILE — ETAP 4B: FINALNY RENDERING + TELEMETRY TIMELINE

**Data:** 2026-08-23
**Poprzednie etapy:** `RAPORT_MULTIFILE_ETAP_1_AUDYT.md` … `RAPORT_MULTIFILE_ETAP_4A_PREVIEW.md`
**Zakres:** podłączenie `VideoTimeline` do FINALNEGO renderingu (ten sam kontrakt czasu co preview), poprawa precompute/wykresów, zabezpieczenie AMD native dla multi-file, realny test integracyjny na `GX010114+115+116` + `Jazda_na_rowerze_w_porze_lunchu.fit`.

---

## 1. Stan przed ETAPEM 4B (miejsca liniowego `start_dt_utc + global_time`)

Audyt znalazł:
- `src/ffmpeg/frame_renderer.py` — `sample_t = index/fps`; `current_dt_utc = t0 + sample_t` (liniowo, bez mapowania klipów),
- `src/ffmpeg/worker_cache.py` — `end_dt_utc = start_dt_utc + duration_s` (błędne przy dużych lukach absolutnych),
- `src/telemetry_precompute.py` — `target_dts = [base_dt + i/fps ...]` (grid liniowy, precomputowałby przerwy),
- `src/ffmpeg/streaming.py` — `end_dt_utc` dla wykresów, `init_worker`/pool bez timeline, brak diagnostyki multi-file, brak guarda AMD native,
- `src/gui/qt/_mixins/render_mixin.py` — `stream_overlay_to_ffmpeg(start_dt_utc=...)` bez `video_timeline`.

Wszystkie te miejsca zakładały: `absolute = project_start_dt + global_time`.

---

## 2. Nowy przepływ czasu (wspólny kontrakt)

```
frame_index
  → global_time = frame_index * update_rate_step / target_fps
  → VideoTimeline.global_to_absolute(global_time)      (global → clip → local → absolute)
  → target_dt  (FIT/GPMF/GPX / wykresy / mapa)
```

Jedno wspólne API (używane przez preview i final render):
- `VideoTimeline.global_to_absolute(global_time, base_dt=...)`,
- `VideoTimeline.frame_to_absolute(index, fps, update_rate_step)`,
- `src.multifile.resolve_render_target_dt(timeline, start_dt_utc, global_time, t0)` — **pojedynczy resolver** z legacy fallbackiem (`start_dt_utc + global`) gdy brak timeline,
- `timeline_absolute_ranges(timeline)` / `timeline_absolute_end(timeline)` — realne absolutne zakresy klipów.

Single-file: `timeline.global_to_absolute(t) == start_dt_utc + t` (identycznie jak legacy).

---

## 3. Frame renderer

`src/ffmpeg/frame_renderer.py`:
```python
current_dt_utc = resolve_render_target_dt(
    WORKER_CACHE.get("video_timeline"), start_dt_utc, sample_t, t0)
```
- `sample_t` = GLOBAL czas projektu (bez zmian),
- z timeline → `global_to_absolute` (multi-file: realne absolutne czasy),
- bez timeline → `start_dt_utc + sample_t` (single-file identycznie).

---

## 4. Worker cache

`src/ffmpeg/worker_cache.py`:
- nowy parametr `video_timeline` (pickle-friendly — przekazywany do workerów procesu przez `init_worker`),
- `WORKER_CACHE["video_timeline"]`,
- **`end_dt_utc` dla wykresów**: zamiast `start_dt_utc + project_duration` → `timeline_absolute_end(timeline)` (realny koniec ostatniego klipu), z legacy fallbackiem.

---

## 5. Telemetry precompute

`src/telemetry_precompute.py` — `build_telemetry_cache(...)`:
- nowe parametry `video_timeline=None`, `update_rate_step=1`,
- grid:
  ```python
  target_dts = [video_timeline.frame_to_absolute(i, target_fps, update_rate_step)
                for i in range(total_frames)]
  ```
  z bezpiecznym fallbackiem `base_dt + i/target_fps` dla klatek bez absolutnego startu (klip fallback).
- **Nie generuje wpisów dla przerw absolutnych** (np. `10:15–10:35`), bo grid pokrywa tylko klatki finalnego filmu (skompresowana oś). Test: 4 klatki → `10:05:00, 10:05:01, 10:35:00, 10:35:01` (bez gapu).

---

## 6. Wykresy

- `streaming.py` i `worker_cache.py`: `end_dt_utc` liczony z realnych absolutnych zakresów klipów (max `absolute_end`), nie `start + project_duration`.
- `preview_mixin._render_preview`: ta sama poprawka (parity preview ↔ final).
- Semantyka wykresów (window `[-60,0]` względem absolutnego `target_dt`) zachowana; historia pierwszej klatki clip2 liczona względem prawdziwego `target_dt` (np. `10:34–10:35`), nie ograniczona do zakresów nagrań.

---

## 7. Mapy

Mapa konsumuje absolutny `target_dt` (teraz z timeline w renderze). Na granicy `clip1→clip2` pozycja mapy przeskakuje do prawdziwego czasu (bez interpolacji globalnej). Pokryte TEST 7.

---

## 8. Cut / trim przez granicę

`cut_regions` są w sekundach GLOBALNYCH; `frame_renderer` sprawdza cut na `current_t` (globalny), ffmpeg `between(t, cs, ce)` działa na osi globalnej concat. Test TEST 8: okno `global 550–700` → `clip1 local 550–600` + `clip2 local 0–100` z poprawnymi absolutnymi timestampami.

---

## 9. FFmpeg concat

Bez zmian — nadal:
```
N source MP4 → concat demuxer (-f concat) → JEDEN decode → overlay (pipe) → JEDEN encoder → JEDEN output MP4
```
Bez pośrednich temp MP4 w architekturze. Testowany realnie (patrz §15).

---

## 10. Audio

- Architektura audio bez zmian (concat audio back-to-back, bez pustych przerw).
- Realny render testowy użył segmentów bez ścieżki audio (`-an`), więc walidacja AV-sync na realnym materiale była ograniczona (opisane w §14). Mechanizm `aselect`/concat audio w standardowym pipeline zachowany.

---

## 11. Progress

Globalny: `done_frames / total_overlay_frames`, `total = ceil(project_duration * generation_fps)` (suma długości klipów). Bez resetu na granicach. Pokryte TEST 9.

---

## 12. Backend GPU

| Backend | Status |
|---|---|
| **NVIDIA (NVENC)** | Bez przebudowy; korzysta ze wspólnego concat + timeline. Na tej maszynie brak `nvcuda.dll` → nie testowany runtime (NVIDIA path preserved statycznie). |
| **AMD standard (AMF)** | Działa ze wspólnym concat + timeline (`d3d11va` decode + `hevc_amf` encode). Zweryfikowany realnie. |
| **AMD native (AMD_NATIVE_D3D11)** | **Guard multi-file**: gdy projekt ma >1 clip, `AMD_NATIVE_D3D11` NIE jest użyty (używa tylko `input_files[0]`) → log `[MultiFile] AMD_NATIVE_D3D11 multi-file not yet supported -> falling back to standard AMD/AMF pipeline` → standardowy AMF. Single-file AMD native bez zmian. |
| **Intel (QSV)** | Bez zmian (wspólny concat; `INTEL_FORCE` niezależny od liczby plików). |
| **CPU** | Bez zmian; `resolve_render_target_dt` z timeline. |

**Uwaga (pre-existing, poza zakresem ETAP 4B)**: standardowa ścieżka AMD z **wieloma workerami procesowymi** (process pool) ma rozbieżność SHM dla małych HUD-regionów/atlasu — worker renderuje pełną klatkę zamiast regionu (`cannot reshape array ...`). Zweryfikowano, że `init_worker` poprawnie przechowuje `hud_bbox/hud_regions/video_timeline` (test) — błąd leży w pre-existing kodzie AMD-region/SHM, NIE w zmianach ETAP 4B. Ścieżka `workers=1` (in-process) działa poprawnie i została użyta do realnego renderu.

---

## 13. GPMF — ograniczenie per-klip

- Wskaźniki FIT/GPX pokrywają całą aktywność (działają w multi-file przez absolutny `target_dt`).
- **Pełny per-clip GPMF dataset NIE jest jeszcze połączony** — wskaźniki GPMF używają danych głównego (pierwszego) klipu. Absolutny czas każdego klipu pochodzi z jego własnego GPMF (ETAP 3), ale strumienie telemetryczne GPMF klipów 2..N nie są scalane. Pełny per-clip GPMF to osobny etap (opisany jako ograniczenie; nie ukrywane).

---

## 14. Testy

### Nowe — `tests/test_multifile_etap4b_render.py` (13)
- **TEST 1** frame→absolute single-file: `frame 50 @10fps → global 5.0 → start+5.0`.
- **TEST 2/3** granica: `global 599.9 → 10:14:59.9`; `global 600 → 10:35:00` (NIE 10:15).
- **TEST 4** trzy nagrania jednej aktywności: target dla `global 0/300/600/900/1500/1800/2099`.
- **TEST 5** precompute: grid bez wpisów w przerwie `10:05:02–10:35:00`.
- **TEST 6** history chart: pierwsza klatka clip2 → target `10:35`, okno 60 s → `10:34–10:35`.
- **TEST 7** mapa: na granicy pozycja przeskakuje (brak interpolacji globalnej).
- **TEST 8** cut przez granicę: `global 550–700` → `clip1 local 550–600` + `clip2 local 0–100`.
- **TEST 9** progress globalny względem `2100 s`.
- **TEST 10** fallback timestamp: renderuje przez `resolve_render_target_dt`, brak crasha.
- **TEST 11** single-file parity: `timeline == start + global` dla wielu klatek.
- **TEST 12** brak timeline: legacy `start + global` działa.

**Wynik:** `13 passed` (multifile łącznie: **77 passed**).

### Regresja
- Szeroka: `export_lifecycle, intel_backend, etap5f, etap8o, etap8p_b, render_tab, cut_feature, chart_seek_history, chart_axis, etap10m_chart_dynamic, video_helpers, gpmf_timing/cache, telemetry_manager, controller_properties, nvidia_etap5b4, amd_above_dirty_mode, etap8e, etap8m4, etap6_chart_window, nvidia_regression_chart_preview, integration_real_data, map_sync, track_up_map` — **341 passed / 17 skipped / 0 failed**.
- Znany pre-existing fail: `test_etap8t_b_async_pipeline::test_async_visible_none_visible` (solar `compose_overlay`, niezwiązany z ETAP 4B — potwierdzony w repo-memory jako istniejący).

---

## 15. Realny test: GX010114 + GX010115 + GX010116 + Jazda_na_rowerze_w_porze_lunchu.fit

### Audyt materiału (timeline na realnych plikach)
| Klip | duration | creation_time | GPMF absolute_start | source | quality |
|---|---|---|---|---|---|
| GX010114.MP4 | 1956.955 s | 13:18:58 (błędny!) | **09:40:11.704** | gpmf_gps9 | exact |
| GX010115.MP4 | 592.597 s | 11:18:01 | **11:18:02.250** | gpmf_gps9 | exact |
| GX010116.MP4 | 1743.742 s | 13:29:32 (błędny!) | **11:32:09.735** | gpmf_gps9 | exact |

- **FIT `Jazda_na_rowerze_w_porze_lunchu.fit`: 09:40:10 … 12:01:13** (4299 rekordów, GPS 09:40:22–12:01:13).
- **Potwierdzenie tej samej aktywności**: wszystkie trzy klipy leżą wewnątrz zakresu FIT (09:40→12:01); koniec GX010116 = 12:01:13 ≈ koniec FIT.
- **Ważne**: `creation_time` dla GX010114 (13:18:58) i GX010116 (13:29:32) jest **błędny** (poza nagraniem) — potwierdza, że GPMF GPS9 (ETAP 3) jest właściwym źródłem czasu, nie `creation_time`.

### Granice
```
GX010114 → GX010115: global 1956.955 == 1956.955; abs gap (usunięty) 3913.6 s (65m14s)
  global 1956.455 → clip0 local 1956.455 → abs 10:12:48.159
  global 1956.955 → clip1 local 0.000     → abs 11:18:02.250   ✓ (prawdziwy T2)
GX010115 → GX010116: global 2549.552 == 2549.552; abs gap (usunięty) 254.9 s
  global 2549.552 → clip2 local 0.000     → abs 11:32:09.735   ✓
```
`project_duration = 4293.294 s` (Σ długości klipów; NIE `last_abs − first_abs`).

### FIT na granicach (przez absolutny target_dt)
```
clip0 start 09:40:11 → FIT speed N/A (pierwszy rekord GPS 09:40:22)
clip0 mid   09:56:30 → 26.10 km/h
clip0 end   10:12:48 → 0.00 km/h
clip1 start 11:18:02 → 4.54 km/h   (po 65-min przerwie — właściwe miejsce FIT)
clip1 mid   11:22:58 → 21.87 km/h
clip1 end   11:27:54 → 2.45 km/h
clip2 start 11:32:09 → 0.00 km/h
clip2 mid   11:46:41 → 21.10 km/h
clip2 end   12:01:13 → 9.37 km/h   (≈ koniec aktywności FIT)
```

### Krótki realny render przez granicę (GX010114 → GX010115)
Realny eksport 16 s (8 s końcówki GX010114 + 8 s początku GX010115), z prawdziwymi absolutnymi startami z audytu GPMF, przez rzeczywisty pipeline TeleM:
- timeline: clip1 `10:12:39.704–10:12:47.704`, clip2 `11:18:02.250–11:18:10.250`, gap usunięty (65m14s), boundary global 8.0 → `11:18:02.250`.
- FFmpeg: `d3d11va` decode + concat + overlay + `hevc_amf` encode, 480 klatek, ~325 fps, `scratch/etap4b_segment_boundary.mp4` (9.97 MB).
- **ffprobe**: video HEVC 960×540 29.97 fps, **duration 15.98 s ≈ 16 s** (oba klipy, bez przerwy).
- **Klatki przed/po granicy** (global 7.4 s vs 8.6 s): różnica pikseli ~94–96% — obraz przechodzi z końca GX010114 do początku GX010115, a **HUD time-display przeskakuje** (potwierdzone różnicą ~96% w regionie zegara; dokładne wartości czasu potwierdzone testami timeline: `7.9→10:12:47.6`, `8.0→11:18:02.25`).
- Pipeline przetworzył timeline z `[MultiFile Render]` diagnostyką i fallbackiem AMD native.

Ścieżka renderu: segmenty realnego materiału (960×540, 8 s) → timeline z realnymi absolutnymi startami → `stream_overlay_to_ffmpeg`. Wycinek z 13.5 GB/4 GB użyty zamiast pełnego dekodowania 30 GB (cut w pipeline dekoduje całość — nieefektywne dla pełnego projektu; ograniczenie opisane).

---

## 16. Regresje / ograniczenia

- **GPMF kolejnych klipów**: pełny per-clip GPMF dataset nie połączony (opisane §13).
- **AMD process-pool + mały HUD region**: pre-existing reshape bug (opisane §12); ścieżka `workers=1` działa.
- **AMD native multi-file**: guard fallback (nie renderuje tylko 1. pliku).
- **creation_time niewiarygodne** dla części GoPro (GX010114/116) — GPMF GPS9 preferowane (ETAP 3).
- **Realny render testowy**: użył segmentów bez audio (`-an`), więc walidacja AV-sync ograniczona.
- Single-file: bez regresji (341 testów zielonych).

---

## 17. Gotowość do kolejnego etapu

| Obszar | Ocena |
|---|---|
| **multi-file FIT/GPX final render** | ✅ GOTOWE — wspólny kontrakt timeline w rendererze; realnie zweryfikowane. |
| **multi-file GPMF final render** | ⚠️ częściowo — czas per-klip OK; scalenie strumieni GPMF klipów 2..N to osobny etap. |
| **AMD native multi-file** | ⏳ osoba etap — guard fallback na razie; pełna iteracja po klipach w `amd_native_exporter`. |
| **GUI/persistence multi-file** | ⏳ osobny etap — lista klipów w GUI + zapis projektu (`video_clips`). |
| **Wykresy full-activity przy dużych lukach** | ✅ poprawione (realne absolutne `end_dt_utc`); pełna walidacja przy scalonym GPMF. |

---

## Kryteria zakończenia ETAPU 4B — status

1. final renderer obsługuje listę klipów ✅
2. wejściowe MP4 składane bez przerw ✅ (concat, realnie: 15.98 s = 8+8)
3. jeden finalny pipeline / encoder ✅
4. frame index → global time ✅
5. global → VideoTimeline ✅
6. FIT/GPX dostają prawdziwy absolutny czas ✅ (audyt + render)
7. granica nie używa liniowego `start + global` ✅
8. precompute nie generuje przerw wielogodzinnych ✅ (TEST 5)
9. wykresy używają prawidłowego absolutnego `target_dt` ✅
10. cut przez granicę ✅ (TEST 8)
11. progress globalny ✅ (TEST 9)
12. single-file bez regresji ✅
13. AMD native nie renderuje po cichu 1. pliku ✅ (guard)
14. raport w `Raporty/` ✅

**Najważniejszy invariant zachowany: `GLOBAL PROJECT TIME != ABSOLUTE ACTIVITY TIME`; final renderer używa dokładnie tego samego kontraktu co preview (`global_time → VideoTimeline → clip/local → absolute target_dt → telemetry → overlay`).**
