# RAPORT MULTIFILE — ETAP 1: AUDYT ARCHITEKTURY

**Data:** 2026-08-23
**Zakres:** audyt read-only aktualnego kodu TeleM pod kątem założeń single-file oraz propozycja architektury multi-file.
**Wynik audytu:** architektura jest wystarczająco jasna — przechodzimy do pierwszego bezpiecznego etapu implementacji (model `VideoClip` + globalna timeline + mapowanie global→clip→absolute).

---

## 1. Obecna architektura — przepływ danych

```
load_tab (QFileDialog.getOpenFileNames — WIELO-WYBÓR już aktywny)
  → sig_files_selected(video_paths: list, gpx, fit)
  → ProjectMixin._on_files_selected
      ├─ self.video_paths = [...]          (lista — zapisana)
      ├─ self.video_path = video_paths[0]  (SINGULAR — pierwszy clip)
      ├─ QMediaPlayer / MPV -> source = video_path   (pierwszy clip)
      ├─ ffprobe_stream_info(paths[0])     (rozdzielczość/FPS z 1. klipu)
      ├─ video_duration_s = Σ duration     (suma — już multi-świadoma, ale bez mapy granic)
      ├─ _load_or_generate_telemetry()     (GPMF/ExifTool tylko z paths[0])
      ├─ load_gpx / load_fit               (align do start_dt_utc — 1. klipu)
      └─ first_frame = extract_frame(self.video_paths, 0)   (JEDYNY w pełni clip-świadomy konsument)

Preview (seek_bar → sig_seek_changed):
  mpv:     mpv_player.time_pos = s
  QMedia:  media_player.setPosition(ms) → _on_video_frame
  CPU:     extract_frame(video_path, s)   ← SINGULAR (preview_mixin L254)
  → target_dt = telemetry.start_dt_utc + timedelta(seconds=current_ts)   ← JEDEN start absolutny
  → prepare_overlay_frame_data(target_dt, start_dt_utc, ...)
  → compose_overlay / render_preview(target_dt, ...)
  → QImage → GUI

Rendering finalny (render_tab → RenderMixin._render_pipeline):
  → stream_overlay_to_ffmpeg(input_files=self.video_paths, duration_s=video_duration_s,
                             start_dt_utc=telemetry.start_dt_utc, ...)
      ├─ total_overlay_frames = ceil(duration_s * generation_fps)
      ├─ >1 plik → concat demuxer (render_concat_list.txt) dla video I audio   ← back-to-back, bez offsetów
      ├─ 1 plik  → -i <file>
      ├─ JEDNO polecenie ffmpeg (filter_complex: overlay na pipe:0 rawvideo)
      ├─ worker per klatka: render_overlay_frame(index, ...)
      │     sample_t = index / generation_fps
      │     target_dt = start_dt_utc + sample_t        ← LINIOWY grid czasu
      └─ progress = done / total_overlay_frames (globalny — już multi-świadomy)
```

Kluczowy wniosek: **warstwy wskaźników i kompozytora są clip-agnostyczne**. Otrzymują tylko absolutny `target_dt` oraz `start_dt_utc`. Całe założenie single-file siedzi wyżej — w sposobie wyliczania `target_dt` z jednego `start_dt_utc` i liniowego czasu globalnego.

---

## 2. Założenia single-file — inwentarz

| Lokalizacja | Założenie |
|---|---|
| `controller.py:119-132` | `video_path` singular (primary = 1. clip), `video_duration_s` jeden skalar, `meta_path` jeden JSON |
| `project_mixin.py L157` | `self.video_path = self.video_paths[0]` |
| `project_mixin.py L178/L183` | QMediaPlayer / MPV dekodują **tylko pierwszy clip** (preview) |
| `project_mixin.py L188-195` | `ffprobe_stream_info(paths[0])` — w/h/fps z 1. klipu |
| `project_mixin.py L357/L378/L460` | GPMF / ExifTool **tylko z paths[0]** |
| `project_mixin.py L388` | `meta = video_path.with_suffix(".json")` — 1. sidecar |
| `project_mixin.py L415-422` | fallback `start_dt_utc` z `creation_time` 1. klipu |
| `preview_mixin.py L254` | CPU fallback `extract_frame(self.video_path, ...)` — singular |
| `preview_mixin.py L277-281` | `target_dt = start_dt_utc + current_ts` — jeden start |
| `playback_mixin.py L91/L173/L227/L285` | granice odtwarzania względem `video_duration_s` |
| `render_mixin.py L73/L87/L90/L128` | guard `video_path`, JSON, ffprobe, rotacja z 1. klipu |
| `telemetry_manager.py L403` | jeden `start_dt_utc` (absolutny start projektu) |
| `telemetry_manager.py L509/L549-555` | `start_dt_utc` = anchor GPS 1. klipu / 1. próbka |
| `telemetry_manager.py L675/L770` | GPX/FIT align do pojedynczego `start_dt` |
| `telemetry_gpmf_new.py L789` | `gpmf_to_exiftool_json(video_path)` — 1. strumień GPMF |
| `ffmpeg/streaming.py L429-430` | `total_overlay_frames` z jednej `duration_s` |
| `ffmpeg/streaming.py L530-547` | concat back-to-back — bez per-clip offsetu, bez per-clip telemetrii |
| `ffmpeg/frame_renderer.py L88/L116` | `sample_t = index/fps`; `target_dt = t0 + sample_t` — liniowy grid |
| `ffmpeg/worker_cache.py L100` | `end_dt_utc = start_dt_utc + duration_s` — jedna oś |
| `ffmpeg/telemetry_precompute.py L359/L671` | `target_dts = [base_dt + i/fps ...]` — jeden `base_dt` |
| `ffmpeg/amd_native_exporter.py L1197` | `input_files[0]` — AMD native używa **tylko 1. klipu** |
| `ffmpeg/command_builder.py L620+` | jeden filter graph; cuty po liniowym czasie |
| `ffmpeg/second_pass.py L29` | jobs `(i,...)` index-based, liniowa oś |
| `telemetry_extract.py L1226-1244` | `get_container_rotation` koercja listy→1. plik |
| `load_tab.py L372/L408` | inspekcja / QP analiza 1. klipu |

---

## 3. Proponowana architektura multi-file

Model docelowy — rozszerzamy istniejące klasy, bez nowego frameworka:

```
controller / ProjectMixin
  ├─ video_paths: list[Path]               (istnieje)
  ├─ video_clips: list[VideoClip]          (NOWE)
  ├─ video_timeline: VideoTimeline         (NOWE — globalna oś)
  ├─ video_duration_s = timeline.project_duration_s
  └─ telemetry.start_dt_utc                (pozostaje — start absolutny projektu = 1. klipu)
```

### Nowe elementy (do zaimplementowania)

1. **`src/multifile.py`** — nowy moduł (czysta logika, bez zależności GUI/ffmpeg):
   - `VideoClip` — dataclass: `path, duration_s, fps, width, height, absolute_start_dt, absolute_end_dt, global_start_s, global_end_s`.
   - `VideoTimeline` — klasa mapująca:
     - `project_duration_s` (Σ czasów trwania clipów, NIE różnica absolutna),
     - `global_to_clip(global_time) -> (clip_index, local_time)`,
     - `global_to_absolute(global_time) -> datetime` (kluczowy resolver),
     - `absolute_to_global(absolute_dt) -> float` (rewers — dla precompute/SmartSync/wykresów),
     - `frame_to_absolute(index, target_fps, update_rate_step)`,
     - `build_from_paths(paths, ffprobe_exe, base_dt, ...)` — budowa z ffprobe + per-clip absolutny start.

2. **Resolver per-clip absolutnego startu** — dla każdego klipu:
   - priorytet 1: własny anchor GPS/GPMF klipu (następny etap — pełne per-clip GPMF),
   - priorytet 2: `creation_time` kontenera klipu (ffprobe — tanie, implementowane teraz),
   - klip 0: `base_dt` = `telemetry.start_dt_utc` (zachowanie obecne bit-for-bit).

### Elementy do rozszerzenia (późniejsze etapy)

| Element | Zmiana |
|---|---|
| `preview_mixin._render_preview` | `target_dt = video_timeline.global_to_absolute(current_ts)` zamiast `start_dt_utc + ts`; CPU fallback z `video_paths` |
| `playback_mixin` | przełączanie źródła dekodera na granicy clipów (QMediaPlayer/MPV) |
| `render_mixin._render_pipeline` | przekazanie `video_timeline` do pipeline'u |
| `frame_renderer.render_overlay_frame` | `current_dt_utc = timeline.global_to_absolute(sample_t)` |
| `worker_cache.init_worker` | przyjęcie `video_timeline` (per-clip oś wykresów) |
| `telemetry_precompute` | grid `target_dts` przez timeline |
| `amd_native_exporter` | iteracja po wszystkich klipach (obecnie tylko `[0]`) |
| `command_builder` | per-clip cuty / konwersja na oś globalną |
| `project_mixin` | per-clip GPMF (anchor + dane) |
| `streaming` | audio: concat bez pustych przerw (już OK — concat back-to-back), ale timestamps per-clip |

### Elementy do pozostawienia BEZ zmian

- `overlay_renderer.prepare_overlay_frame_data` / `compose_overlay` — clip-agnostyczne,
- `indicators/*` — tylko konsumują `target_dt`,
- `telemetry_manager.resolve_value` / `resolve_samples` — interpolacja po absolutnym czasie (działa poprawnie, bo dane FIT/GPX/GPMF mają absolutne timestampy),
- logika pauz FIT — **bez zmian** (multi-file korzysta z tej samej logiki),
- SmartSync (`_compute_smart_time_offset`) — bez zmian; działa na absolutnych timestampach,
- wybór backendu (NVIDIA/AMD/Intel/CPU) — bez zmian.

---

## 4. Global timeline → clip timeline → absolute timestamp

```
global_time (oś skompresowanego filmu)
   ↓ VideoTimeline.find_clip
(active_clip_index, local_time = global_time - clip.global_start_s)
   ↓
absolute_timestamp = clip.absolute_start_dt + timedelta(seconds=local_time)
   ↓
TelemetryDataManager.resolve_value(field, absolute_timestamp, source)
   ↓
FIT / GPMF / GPX
```

Przykład z przerwą:

```
clip0 abs 10:00-10:10  → global 0-10
clip1 abs 10:30-10:40  → global 10-20

global 15:00 → clip1, local 5:00 → absolute 10:35:00 → telemetry z 10:35:00
```

**Invariant:** `GLOBAL VIDEO TIME != ABSOLUTE TELEMETRY TIME`.

`video_duration_s = Σ clip.duration_s` — NIGDY `last_abs - first_abs`.

---

## 5. Preview — przełączanie dekodera podczas seek

Docelowy mechanizm (etap preview):
1. `seek_seconds` (globalny) → `VideoTimeline.global_to_clip` → `(clip_index, local_time)`.
2. Jeżeli `clip_index != active_clip_index` → przełącz źródło QMediaPlayer/MPV na `clips[clip_index].path`.
3. `media_player.setPosition(local_time * 1000)` / `mpv.time_pos = local_time`.
4. `target_dt = timeline.global_to_absolute(seek_seconds)` → `_render_preview`.
5. CPU fallback: `extract_frame(self.video_paths, seek_seconds, ...)` — już clip-świadomy (istnieje).

Wykresy (HR/Cadence 60 s): oś musi pozostać **względna** `[-60, 0]` względem `target_dt` — naturalnie wynika z absolutnego `target_dt`, więc per-clip nie zmienia semantyki (kolejny etap walidacji).

---

## 6. Rendering — jeden ciągły eksport bez pośrednich MP4

Preferowana architektura (zgodna z obecną):

```
decoder clip 1 ─┐
decoder clip 2 ─┼→ concat demuxer (-f concat)  → jeden ffmpeg
decoder clip 3 ─┘        ↓
                   decoded frames (global time)
                          ↓ overlay (pipe:0 rawvideo, per-frame target_dt przez timeline)
                          ↓ JEDEN encoder → JEDEN finalny MP4
```

- Obecny concat demuxer już daje back-to-back oś globalną bez pustych przerw — **zachowujemy**.
- Zmiana: `target_dt` per klatka liczony przez `timeline.global_to_absolute(sample_t)` zamiast `start_dt_utc + sample_t`.
- `total_overlay_frames` i progress pozostają globalne (już poprawne).
- **AMD native**: obecnie używa `input_files[0]` — wymaga iteracji po wszystkich klipach (dedykowany etap GPU).

---

## 7. Audio

- Obecnie: concat demuxer dostaje ten sam `render_concat_list.txt` dla audio → audio jest back-to-back **bez** rzeczywistych przerw między nagraniami. To dokładnie pożądane zachowanie (przerwy usuwane).
- Ryzyko: AV desync na granicach — concat demuxer zachowuje względne PTS wewnątrz każdego pliku, więc timbase i PTS są spójne przy jednorodnych parametrach.
- Warunek: ta sama rozdzielczość/FPS/pixel format/kodek wśród clipów. Różnice → ostrzeżenie lub kontrolowany błąd (etap walidacji parametrów).
- Brak potrzeby przebudowy audio na tym etapie; opisujemy jako świadomą decyzję.

---

## 8. GPU — ryzyka dla NVIDIA / AMD / Intel

| Backend | Ryzyko | Plan |
|---|---|---|
| **Wspólny** | Zmiana `target_dt` nie dotyka GPU — overlay liczony w Pythonie, potem upload. Zero transferów GPU→CPU→GPU na granicach (conat w ffmpeg). | Zachować obecny model: dekoder→(concat)→overlay→encoder. |
| **NVIDIA (NVENC/NVDEC)** | Obecna ścieżka ustawia `hwaccel=cuda`, `-hwaccel_output_format cuda`, atlas/bbox HUD. Concat z `-hwaccel` musi być zweryfikowany (może wymagać `-hwaccel_output_format cuda` per input). | Zachować obecne wywołanie; concat już działa w produkcji dla N plików (testy `test_export_lifecycle`). Weryfikacja przy zmianie timestampów. |
| **AMD (AMF/D3D11/AMD_NATIVE_D3D11)** | `export_amd_native_d3d11` używa **tylko** `input_files[0]` — klipy 2..N pomijane. To realny bug multi-file. | Dedykowany etap GPU: iteracja po klipach w native exporterze. Na razie nie dotykamy (poza raportem). |
| **Intel (QSV)** | Ten sam concat co CPU/NVENC; `INTEL_FORCE` nie zależy od liczby plików. | Zachować. |
| **CPU fallback** | `extract_frame` już clip-świadomy; timeline jest czystą logiką. | Rozszerzyć `_render_preview` CPU o listę. |

**Zasada AGENTS.md #20:** bez zbędnych transferów `GPU→CPU→GPU` na granicach plików; concat demuxer w ffmpeg przełącza dekoder bez udziału Pythona.

---

## 9. GPMF / FIT / GPX — zachowanie resolvera i czasu absolutnego

- **FIT/GPX**: jeden plik pokrywa całą aktywność; filmy to wybrane fragmenty. Dane pozostają absolutne (`timestamp` UTC). `sync_gpx_to_video` / `sync_fit_to_video` **zachowują absolutne timestampy** — `video_start_dt` służy tylko jako T=0. Multi-file nie wymaga zmian w tych funkcjach.
- **GPMF**: obecnie parsujemy GPMF **tylko 1. klipu** (projekt_mixin L357). W multi-file każdy klip może mieć własny GPMF. Plan: per-clip anchor GPS (`absolute_start_dt` klipu) w pierwszej kolejności z jego własnego GPMF; na ten etap fallback = `creation_time` kontenera klipu (tanie, przez ffprobe).
- **`start_dt_utc` projektu** pozostaje pojedynczym absolutnym startem (z 1. klipu). Timeline używa go jako `base_dt` dla klipu 0 — **gwarantuje tożsamość single-file**.
- **Nie wracamy** do sztucznego `creation_time + sample_index * 0.1` — obecny kod ma dokładniejsze źródła czasu (GPS9/GPSU/TSMP/STMP); per-clip GPMF w kolejnym etapie.

---

## 10. Ryzyka regresji

1. **SmartSync** — bez zmian w `_compute_smart_time_offset`; timeline to nowa warstwa powyżej. Rewers `absolute_to_global` przyda się do walidacji. Ryzyko niskie.
2. **Pauzy FIT** — bez zmian w logice; multi-file NIE utożsamia czasu filmu z czasem aktywności. Ryzyko niskie.
3. **Mapy / Track-Up** — mapa konsumuje absolutny `target_dt` i `gps_track`; per-clip nie zmienia. Ryzyko niskie.
4. **Wykresy (HR/Cadence)** — oś względna `[-60,0]` względem absolutnego `target_dt`; przy przerwach między klipami okno może zawierać próbki spoza klipu — do weryfikacji w etapie telemetry timestamp mapping. Ryzyko średnie.
5. **Preview/final parity** — oba muszą używać tego samego `timeline.global_to_absolute`; każda zmiana walidowana na obu ścieżkach (AGENTS.md #9).
6. **GPU (AMD native)** — `input_files[0]` to istniejący, realny problem; wymaga dedykowanego etapu. Ryzyko wysokie, ale **poza zakresem ETAP 1**.
7. **Audio** — concat bez przerw; AV desync tylko przy niejednorodnych parametrach clipów → walidacja parametrów w etapie render.
8. **Single-file regresja** — timeline z jednym clipem + `base_dt` musi dawać `global_to_absolute(t) == start_dt_utc + t`; pokryte testami.

---

## 11. Plan implementacji (podział na małe etapy)

```
ETAP 1 (ten raport + pierwsza bezpieczna implementacja):
  1. model VideoClip / lista clipów           ✅ (implementowane teraz)
  2. globalna timeline (VideoTimeline)        ✅
  3. mapowanie global → clip → absolute       ✅
  4. kompatybilność jednego pliku             ✅
  5. testy obowiązkowe (single/dual/gap/FIT)  ✅

ETAP 2 — TIMELINE:
  6. preview: target_dt przez timeline + przełączanie dekodera na granicach
  7. telemetry timestamp mapping (per-clip target_dt w preview i render)
  8. render CPU/reference: frame_renderer/worker_cache/precompute przez timeline

ETAP 3 — RENDER:
  9. rendering GPU: AMD native (iteracja po klipach), weryfikacja concat NVENC/QSV
 10. audio: walidacja AV sync na granicach + parametry clipów

ETAP 4 — GUI / PERSYSTENCJA:
 11. GUI multi-file (lista clipów w projekcie, etykiety "Plik 2 z 3")
 12. zapis/odczyt projektu (video_clips w pliku projektu)
 13. pełne testy regresyjne
```

Kolejność zgodna z wymaganiami zadania; ETAP 1 celowo nie dotyka preview/render/GPU — minimalizuje ryzyko regresji i zachowuje wszystkie istniejące ścieżki (NVIDIA/AMD/Intel/CPU).

---

## Podsumowanie

- GUI już pozwala wybrać wiele plików; `video_paths`, `extract_frame` (list) i concat demuxer już istnieją.
- Jedyna realna blokada multi-file to **jeden liniowy `start_dt_utc + t`** w preview/render/precompute/AMD-native oraz **per-clip GPMF/absolute start**.
- ETAP 1 wprowadza czysty, przetestowany model timeline bez dotykania istniejących ścieżek renderowania.
