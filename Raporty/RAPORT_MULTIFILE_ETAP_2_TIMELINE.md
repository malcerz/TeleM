# RAPORT MULTIFILE — ETAP 2: MODEL `VideoClip` + GLOBALNA TIMELINE

**Data:** 2026-08-23
**Poprzedni etap:** `RAPORT_MULTIFILE_ETAP_1_AUDYT.md` (audyt architektury)
**Zakres:** pierwsza bezpieczna implementacja — model `VideoClip`, globalna timeline, mapowanie `global → clip → local → absolute`, kompatybilność jednego pliku.

---

## Co zmieniono

| Plik | Zmiana |
|---|---|
| **`src/multifile.py`** (NOWY) | Dataclass `VideoClip` + klasa `VideoTimeline` + funkcje probingowe (`probe_video_info`, `resolve_clip_absolute_start`, `build_timeline_from_paths`). Czysta logika, bez zależności GUI/ffmpeg w samym mapowaniu. |
| **`src/gui/qt/controller.py`** | Dodano stan: `self.video_clips: list` oraz `self.video_timeline` (inicjalizowane puste/None). |
| **`src/gui/qt/_mixins/project_mixin.py`** | Po wczytaniu telemetrii (GPMF/GPX/FIT) budowana jest timeline przez `build_timeline_from_paths(...)`; `video_duration_s` = `timeline.project_duration_s`; diagnostyka `[MultiFile] Timeline built ...` oraz ostrzeżenie o klipach bez absolutnego startu. |
| **`tests/test_multifile_timeline.py`** (NOWY) | 28 testów obowiązkowych (single/dual/gap/FIT/granice/order/build). |
| **`Raporty/RAPORT_MULTIFILE_ETAP_1_AUDYT.md`** (NOWY) | Raport z audytu (wymagany przez zadanie). |

---

## Decyzje architektoniczne

### 1. `VideoClip` — model pojedynczego pliku
```python
@dataclass
class VideoClip:
    path: Path
    duration_s: float
    fps: float
    width: int
    height: int
    absolute_start_dt: Optional[datetime]   # prawdziwy absolutny start klipu (naive UTC)
    absolute_end_dt: Optional[datetime]     # absolute_start_dt + duration_s
    global_start_s: float                   # start na skompresowanej osi projektu
    global_end_s: float
```
Nazwy pól zgodne z architekturą TeleM; `absolute_*` = czas rzeczywisty, `global_*` = oś finalnego filmu.

### 2. `VideoTimeline` — globalna oś
- `project_duration_s = Σ clip.duration_s` (**NIE** `last_abs − first_abs`).
- `global_to_clip(global_time) -> (clip_index, local_time)` — klamp do osi; wartość dokładnie na granicy należy do **następnego** klipu („pierwsza klatka kolejnego klipu”).
- `global_to_absolute(global_time) -> datetime` — **kluczowy resolver**:
  ```
  global_time -> clip -> local_time -> clip.absolute_start_dt + local_time
  ```
- `absolute_to_global(absolute_dt) -> float|None` — rewers (dla precompute/SmartSync/wykresów).
- `frame_to_absolute(frame_index, fps, update_rate_step)` — grid liniowy `index/fps` → `global_to_absolute`.

### 3. Start absolutny klipu (etap 1)
- **Klip 0**: zawsze re-anchorowany do `base_dt` = `telemetry.start_dt_utc` (anchor GPS GPMF 1. klipu). Dzięki temu **single-file jest bit-for-bit identyczny** z obecnym zachowaniem: `global_to_absolute(t) == start_dt_utc + t`.
- **Klipy 1..N**: `creation_time` kontenera (ffprobe — tanie). Gdy brak → fallback „ciągły” (`base_dt + clip.global_start_s`) z jawną diagnostyką. **Per-clip GPMF anchor** (dokładniejsze dla chapterów GoPro) to kolejny etap.
- `GX030120.MP4` w materiale testowym nie ma `creation_time` — co udowodnił smoke test; dlatego diagnostyka ostrzega jawnie (AGENTS.md #7).

### 4. Kolejność plików
Kolejność z `paths` jest zachowywana, **nigdy nie sortowana** po timestampie (świadomy wybór użytkownika ma pierwszeństwo).

### 5. Kompatybilność jednego pliku
`video_clips = [clip0]` → `is_single_file == True`; wszystkie mapowania redukują się do `start_dt_utc + t`. Nie stworzono osobnej ścieżki single-file vs multi-file.

### 6. Świadomie NIE zmieniano (zakres poza ETAP 2)
- preview (`target_dt` nadal `start_dt_utc + ts`),
- render (`frame_renderer` / `worker_cache` / `precompute`),
- AMD native (`input_files[0]`),
- audio,
- GUI multi-file,
- zapis projektu,
- żadna z istniejących ścieżek NVIDIA/AMD/Intel/CPU.

---

## Testy wykonane

### Nowe (28)
`tests/test_multifile_timeline.py` — pokrycie:
1. **Jeden plik**: `project_duration = 60 s`, `global_to_absolute(t) = base + t`, re-anchor klipu 0 do `base_dt`, klamp zakresu.
2. **Dwa ciągłe pliki**: 10:00-10:10 + 10:10-10:20 → global 0-10/10-20; granica 600 s → klip 2.
3. **Dwa pliki z przerwą**: 10:00-10:10 + 10:30-10:40 → global 15:00 → klip 2 local 5:00 → **abs 10:35:00** (wymagane przez zadanie); `absolute_to_global` w przerwie → None.
4. **Kilka nagrań jednej aktywności FIT**: 3 filmy → global 35 min; timestampy telemetrii na starcie/środku/końcu każdego klipu.
5. **Granice clipów**: ostatnia klatka clip1 / pierwsza klatka clip2, brak duplikacji/pominięcia w mapowaniu.
6. **build_timeline_from_paths** z zamockowanym ffprobe (kolejność zachowana, re-anchor, gap usunięty).
7. **Ordering**: kolejność użytkownika zachowana nawet przy odwróconych czasach; `set_base_dt` re-anchoruje.
8. Bezpieczne zachowanie przy błędzie ffprobe (brak wyjątku).

**Wynik:** `28 passed`.

### Smoke test na realnym materiale
`Video/GX010115.MP4` + `Video/GX020079.mp4` + `Video/GX030120.MP4` przez prawdziwy `ffprobe.exe`:
```
GX010115.MP4: dur=592.60s fps=29.970 3840x2160 start=2026-08-14 11:18:01
GX020079.mp4: dur=37.74s  fps=29.970 3840x2160 start=2026-08-05 04:28:04
GX030120.MP4: dur=180.18s fps=29.970 3840x2160 start=None   (brak creation_time)
project_duration_s = 810.52 s  (suma)
global 0 -> 11:18:01 | global 500 -> 11:26:21 | ...
```
Timeline buduje się poprawnie; `GX030120` potwierdza konieczność diagnostyki braku absolutnego startu.

### Regresja (istniejące testy)
`test_multifile_timeline`, `test_export_lifecycle_p1_fixes`, `test_render_tab`, `test_video_helpers`, `test_gpmf_cache`, `test_telemetry_manager`, `test_cut_feature`, `test_chart_seek_history`, `test_mp4_inspector`, `test_chart_axis_cache`:
**168 passed / 0 failed.**

---

## Znane ograniczenia

1. **Per-clip GPMF anchor** nie jest jeszcze zaimplementowany — klipy 1..N używają `creation_time` (lub fallbacku ciągłego). Dokładność dla chapterów GoPro poprawi się w etapie GPMF.
2. `video_duration_s` w kontrolerze pozostaje sumą (bez zmiany); timeline dostarcza mapę granic dla późniejszych etapów.
3. Timeline NIE jest jeszcze używana w preview/render — celowo, aby etap 2 był minimalny i bezpieczny.
4. `absolute_to_global` wymaga, aby klipy miały rozpoznany absolutny start (klip 0 zawsze ma, klipy 1..N po rozpoznaniu).

---

## Ryzyka

- **Brak regresji single-file**: pokryty testami (`global_to_absolute(t) == start_dt_utc + t`).
- **Nowe ryzyko**: przy braku `creation_time` w klipach 1..N fallback „ciągły” może dać błędny absolutny czas dla telemetrii — dlatego jest jawnie logowany i zastępowany w następnym etapie (per-clip GPMF).
- Nie dotykano istniejących ścieżek NVIDIA/AMD/Intel/CPU.

---

## Co dalej (ETAP 3 — PREVIEW / TELEMETRY TIMESTAMP MAPPING)

1. `preview_mixin._render_preview`: `target_dt = video_timeline.global_to_absolute(current_ts)`; CPU fallback z `video_paths`.
2. `playback_mixin`: przełączanie dekodera (QMediaPlayer/MPV) na granicy klipów (`global_to_clip` → `local_time`).
3. `render_mixin` + `frame_renderer` + `worker_cache` + `telemetry_precompute`: per-klatka `target_dt` przez timeline.
4. Walidacja wykresów HR/Cadence (oś względna `[-60,0]` względem absolutnego `target_dt`).
5. AMD native: iteracja po wszystkich klipach.
6. Testy: preview seek przez granice, render 2 klipów, AV sync.
