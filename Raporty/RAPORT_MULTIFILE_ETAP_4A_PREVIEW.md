# RAPORT MULTIFILE — ETAP 4A: GLOBALNE PREVIEW WIELU KLIPÓW

**Data:** 2026-08-23
**Poprzednie etapy:** `RAPORT_MULTIFILE_ETAP_1_AUDYT.md`, `RAPORT_MULTIFILE_ETAP_2_TIMELINE.md`, `RAPORT_MULTIFILE_ETAP_3_PER_CLIP_TIME.md`
**Zakres:** podłączenie `VideoTimeline` do preview/playbacku (seek bar, dekoder, telemetria) + mała korekta jakości timestampów (`exact/estimated/fallback`). Finalny renderer BEZ zmian.

---

## 1. Stan przed zmianą

Preview zakładało jeden plik:
- `target_dt = telemetry.start_dt_utc + timedelta(seconds=current_ts)` (`preview_mixin._render_preview`),
- `media_player.setPosition(seek_seconds * 1000)` / `mpv.time_pos = seek_seconds` — pozycja traktowana jako **globalna i lokalna jednocześnie**,
- CPU fallback: `extract_frame(self.video_path, seek_seconds, ...)` — **pojedynczy plik**,
- `_on_video_frame` / `_on_mpv_playback_tick` zwracały lokalną pozycję playera jako pozycję osi czasu,
- `_on_media_end` nie istniało; brak przełączania źródła.

Dla jednego pliku to było poprawne (global == local). Dla wielu klipów dawało złe `target_dt` (np. start drugiego klipu = `10:15` zamiast prawdziwego `10:35`) i brak przełączania dekodera.

---

## 2. Timestamp quality (mała korekta kontraktu)

ETAP 3 miał przypadek „GPS sample time used directly as clip start", który nie był oznaczony jako przybliżony. Wprowadzono prosty model bez dużego systemu confidence:

```
timestamp_quality = exact | estimated | fallback
```

| Źródło | quality | reliable |
|---|---|---|
| GPS9 + file-local STMP (`local = STMP/1e6 ≤ duration`) | **exact** | True |
| GPS9 + sesyjny STMP / brak local offset (start = czas próbki GPS) | **estimated** | True |
| GPSU (bez local offset) | **estimated** | True |
| `creation_time` | **estimated** | True |
| `continuous_fallback` / brak źródła | **fallback** | False |
| klip 0 re-anchor do `start_dt_utc` (telemetria GPMF anchor) | **exact** | True |

Pole dodane do `ClipTimestampResolution` i `VideoClip`; diagnostyka `[MultiFile] ... quality=...`. `timestamp_reliable` zachowane dla kompatybilności (ETAP 3) — nie zmienia swojej semantyki: True = realne źródło czasu, False = fallback.

---

## 3. Global / local / absolute — kontrakt

W każdej chwili preview istnieją trzy różne czasy, nigdy nie utożsamiane:

```
GLOBAL TIME     — pozycja na skompresowanej osi projektu (seek bar)
LOCAL CLIP TIME — czas wewnątrz aktywnego MP4 (decoder QMediaPlayer/MPV)
ABSOLUTE TIME   — prawdziwy timestamp telemetrii (FIT/GPMF/GPX)
```

Przepływ:

```
global_time
  → video_timeline.global_to_clip(global_time)
  → (clip_index, local_time)
  → video_timeline.global_to_absolute(global_time) = absolute_dt
```

`_resolve_preview_time(global_time)` zwraca `{global_time, clip_index, clip, local_time, absolute_dt}`. Bez timeline (single-file / brak) → legacy: `local == global`, `absolute = start_dt_utc + global`.

Przykład:
```
global = 720 s
clip2.global_start = 600 s
local = 120 s
clip2.absolute_start = 10:35:00
absolute = 10:37:00
```

---

## 4. MPV

- `_on_seek_changed`: `global → _resolve_preview_time → _preview_ensure_active_clip` (tylko przy zmianie clipu: `mpv.play(clip.path)`, `pause=True`) → `mpv.time_pos = local_time` → `_render_preview(global)`.
- `_on_mpv_playback_tick`: `mpv.time_pos` jest **lokalne** → `_local_to_global(local)` → `sig_seek_position(global)` → `_render_preview(global)`.
- Koniec clipu: `local ≥ clip.duration` i jest następny → `_preview_ensure_active_clip(next, 0.0)` + `mpv.time_pos = 0.0` + `sig_seek_position(next.global_start)` (oś globalna ciągła). Koniec ostatniego clipu → stop + seek 0.
- `reinit_mpv` zachowuje AKTYWNY clip (nie zawsze clip 0) i przelicza `local → global` dla `_render_preview`.

---

## 5. QMediaPlayer

- `_preview_ensure_active_clip`: przy zmianie clipu ustawia `_pending_seek_ms = local*1000` i `setSource(clip.path)` — **seek odroczony**.
- Nowy handler `_on_media_status_changed`: gdy `LoadedMedia`/`BufferedMedia` → `setPosition(_pending_seek_ms)` + `play()` (jeśli nie gra); gdy `EndOfMedia` → `_on_media_end`.
- `_render_preview`: przy seeku w tym samym clipie — `setPosition(local*1000)` bezpośrednio; przy zmianie clipu — odroczony przez status.
- `_on_video_frame`: `media_player.position()/1000` jest **lokalne** → `_local_to_global` → `_render_preview_from_pil(pil, global)`.
- `_on_media_end`: koniec clipu z następnym → `_preview_ensure_active_clip(next, 0.0)`, `_pending_seek_ms=0`, `play()`, `sig_seek_position(next.global_start)`; koniec ostatniego → stop. Tylko podczas `_playing`.

Brak race condition `setSource + setPosition` — seek czeka na załadowanie źródła.

---

## 6. CPU fallback

- `extract_frame(self.video_paths, global_time, ...)` — helper jest już multi-clip świadomy (mapuje global → clip/local wewnętrznie). Zmieniono z `self.video_path` (singiel) na `self.video_paths or [self.video_path]` z czasem **globalnym**.
- `target_dt` dla telemetrii zawsze z `_resolve_preview_time` (timeline), nie z wewnętrznego `start + global` — kontrakt zachowany.

---

## 7. Global seek bar

- `sig_seek_position` emitowany zawsze z **globalną** pozycją.
- Lokalna pozycja playera → globalna przez `_local_to_global(local) = active_clip.global_start_s + local`.
- `current_position = global_time / video_duration_s` (wykresy/kursor).
- Przykład: `clip2.global_start = 600`, `player.local = 123` → seek bar = `723` (TEST 3).

---

## 8. Granice klipów

- Semantyka z ETAPU 2: `global_to_clip(boundary)` wybiera **następny** clip, `local=0`.
- `global_end clip1 == global_start clip2`.
- `_resolve_preview_time(599.999)` → clip1 (ostatnia klatka); `_resolve_preview_time(600.0)` → clip2 local 0 (pierwsza klatka). Żadnej duplikacji ani pustej przerwy (TEST 2, 5).

---

## 9. Playback ciągły

- MPV: `_on_mpv_playback_tick` wykrywa koniec clipu → automatyczne przejście do następnego (local=0), globalna oś dalej rośnie.
- QMedia: `EndOfMedia` → `_on_media_end` → przełączenie na następny clip (local=0) i kontynuacja.
- Koniec ostatniego clipu = koniec projektu (stop).
- Brak preloadingu następnego pliku (świadomie — najpierw poprawność).

---

## 10. Telemetria

- `target_dt = video_timeline.global_to_absolute(global_time)` (lub legacy `start_dt_utc + global` gdy brak timeline).
- Wszystko poniżej (TelemetryDataManager / `prepare_overlay_frame_data` / `render_preview` / `compose_overlay`) bez zmian — przyjmują absolutny `target_dt`.
- Render tab preview (`render_tab._build_preview_qimage`) również używa timeline dla `target_dt` (parity preview ↔ render), reszta renderera nietknięta.

---

## 11. FIT / wykresy / mapa

- FIT/pauzy: bez zmian w logice. Na pierwszej klatce clip2 resolver FIT dostaje prawdziwy `10:35` (nie `10:15`).
- Wykresy HR/Cadence: względne `[-60,0]` liczone względem absolutnego `target_dt`; na granicy `10:15→10:35` historia pierwszej klatki clip2 to `10:34–10:35` (dane FIT z fragmentu spoza filmu są poprawne).
- Mapa: konsumuje absolutny `target_dt` i `gps_track` — przy zmianie clipu natychmiast pokazuje właściwą pozycję (bez resetu śladu).

---

## 12. Testy

### Nowe — `tests/test_multifile_etap4a_preview.py` (13)
- **TEST 1** resolve preview time: global 100 → clip1 local 100 → abs 10:06:40; global 700 → clip2 local 100 → abs 10:36:40.
- **TEST 2** granica: 599.999 → clip1 (10:14:59.999); 600.0 → clip2 local 0 (10:35:00).
- **TEST 3** global z lokalnej pozycji: clip2.local 123 → global 723; single-file identity.
- **TEST 4** single-file: global == local, absolute == start+global, brak switcha źródła.
- **TEST 5** gap absolutny: koniec clip1 ≈ 10:15, start clip2 = 10:35, globalnie bez 20-min przerwy.
- **TEST 6** source switch: seek 100/200/300 w clip1 → brak `setSource`; seek 700 → dokładnie jedno `setSource`; `_pending_seek_ms` ustawione (120000 ms).
- **TEST 7** lokalny seek: global 720 → local 120 (nie 720).

### Uzupełnienie jakości — `tests/test_multifile_etap3_clip_time.py` (+4)
- TEST 8 (ETAP 4A): GPS9+file-local STMP → `exact`; GPS9+session STMP → `estimated`; GPSU → `estimated`; `creation_time` → `estimated`; `continuous_fallback` → `fallback`.

### Wyniki
- Multifile (3 pliki testowe): **46 + 13 + (4 nowe w etap3) = 63 passed**.
- Szeroka regresja (render_tab, cut_feature, chart_seek_history, chart_axis, export_lifecycle, video_helpers, gpmf_timing/cache, telemetry_manager, mp4_inspector, controller_properties, etap10m_chart_dynamic): **218 passed / 0 failed**.

---

## 13. Smoke test (realne pliki)

```
GX010115.MP4 (592.6 s, abs 11:18:03) + GX020079.mp4 (37.7 s, abs 04:55:50.8)
project_duration_s = 630.335

global    0.00 -> clip0 local   0.000 abs 2026-08-14 11:18:03
global  300.00 -> clip0 local 300.000 abs 2026-08-14 11:23:03
global  590.00 -> clip0 local 590.000 abs 2026-08-14 11:27:53
global  592.60 -> clip1 local   0.003 abs 2026-08-05 04:55:50.8   (granica → prawdziwy T2)
global  620.00 -> clip1 local  27.403 abs 2026-08-05 04:56:18.2
local_to_global(clip1 local 100) = 100.0
local_to_global(clip2 local 100) = 692.597
```
Potwierdzone: obraz na granicy przeskakuje do prawdziwego absolutnego czasu drugiego nagrania; oś globalna ciągła; `local_to_global` poprawny dla aktywnego clipu.

Pełna ręczna walidacja FIT na granicy wymaga kompletnego materiału multi-file z jednym FIT — dostarczono mechanizm diagnostyczny `[MultiFile Preview] Switch clip ...`.

---

## 14. Regresje / ograniczenia

- **GPMF kolejnych klipów**: preview nadal korzysta z telemetrii (GPMF) głównie pierwszego klipu; FIT/GPX pokrywają całą aktywność. Pełny per-clip GPMF dataset to osobny etap (opisane jako ograniczenie).
- **Timestamp estimated**: klipy z `quality=estimated` mają start przybliżony (sub-sekundowo) — jawnie oznaczone w diagnostyce; nie wpływają na single-file (clip 0 `exact`/`project_start_anchor`).
- **MPV / QMediaPlayer**: zmiany zachowują istniejący lifecycle; QMedia seek odroczony do załadowania źródła (brak race).
- **CPU preview**: `extract_frame(self.video_paths, global)` — bez duplikowania mapowania clipów.
- **Wykresy (chart)**: oś `end_dt_utc = start + project_duration` może być zbyt krótka przy dużych lukach absolutnych — do pełnej walidacji w ETAP 4B (nie zmieniano semantyki wykresów).
- Finalny renderer: **bez zmian**.

---

## 15. Gotowość do ETAPU 4B

**Ocena: TAK.** Ten sam kontrakt `video_timeline.global_to_absolute(global_time)` może zostać użyty w finalnym rendererze:
- `frame_renderer.render_overlay_frame`: `current_dt_utc = timeline.frame_to_absolute(index, fps)` zamiast `t0 + index/fps`,
- `worker_cache.init_worker`: przekazanie `video_timeline` (per-clip oś wykresów),
- `telemetry_precompute`: grid `target_dts` przez timeline,
- `streaming`/`command_builder`: globalna oś concat już poprawna (back-to-back); cuty na osi globalnej.

Warunek: klipy z `quality=estimated`/`continuous_fallback` muszą być traktowane z jawnym oznaczeniem; konwersja `frame_index → global_time` przez `timeline.frame_to_absolute` (już istnieje) + diagnostyka.

---

## Podsumowanie

- Korekta jakości: `timestamp_quality = exact | estimated | fallback` z precyzyjną semantyką (bez dużego systemu confidence).
- Preview: jeden resolver `_resolve_preview_time` (global → clip/local/absolute); seek bar globalny; dekoder (MPV/QMediaPlayer/CPU) dostaje **lokalny** czas; telemetria dostaje **absolutny** timestamp.
- Przełączanie źródła tylko przy zmianie clipu (`_active_preview_clip_index`); QMedia seek odroczony przez `mediaStatusChanged`; automatyczne przejście clip→clip (MPV tick / EndOfMedia).
- Single-file: identyczne zachowanie (legacy fallback + timeline z 1 clipem daje `start_dt_utc + t`).
- 63 testy multifile + 218 szerokiej regresji — zielone; finalny renderer nietknięty.
