# RAPORT MULTIFILE — ETAP 3: PER-CLIP ABSOLUTE TIMESTAMP / GPMF

**Data:** 2026-08-23
**Poprzednie etapy:** `RAPORT_MULTIFILE_ETAP_1_AUDYT.md`, `RAPORT_MULTIFILE_ETAP_2_TIMELINE.md`
**Zakres:** wiarygodny `absolute_start_dt`/`absolute_end_dt` dla KAŻDEGO klipu wideo, oparty na rzeczywistym czasie zapisanym w pliku (GPMF/GPS), z jawnym oznaczeniem źródła i fallbacków.

---

## 1. Stan początkowy (przed ETAPEM 3)

Po ETAPIE 2 `src/multifile.py` dostarczał `VideoTimeline` z mapowaniem `global → clip → local → absolute`, ale czas absolutny klipów pochodził z:
- **klip 0** — re-anchor do `telemetry.start_dt_utc` (anchor GPS GPMF 1. klipu),
- **klipy 1..N** — `creation_time` kontenera (`resolve_clip_absolute_start`),
- **brak `creation_time`** — fallback ciągły `base_dt + global_start_s` (niewiarygodny).

Problem: dla „kilku osobnych nagrań jednej aktywności FIT" `creation_time` bywa nieprecyzyjny lub nieobecny, a fallback ciągły błędnie zakłada brak przerw. ETAP 3 miał wprowadzić jeden resolver oparty przede wszystkim na GPS/GPMF.

---

## 2. Audyt istniejącego GPMF — dostępne dane czasu

Przeanalizowano `src/telemetry_gpmf_new.py`, `src/telemetry_extract.py`, `src/gui/telemetry_manager.py`, `src/gui/qt/_mixins/project_mixin.py`.

| Źródło | Klucze | Co daje | Użyte w ETAP 3 |
|---|---|---|---|
| **GPS9** | `GPS9` payload `'lllllllSS'`: `days`, `secs` (per próbka) | **Rzeczywisty absolutny czas GPS** każdej próbki: `GPS_EPOCH(2000-01-01) + days + secs` (`_gps9_datetime`) | ✅ główne |
| **GPSU** | `GPSU` `(Y,M,D,h,m,s,ms)` | Absolutny czas startu bloku GPS | ✅ drugorzędne |
| **STMP** | `STMP` (int64) | Czas próbki w µs; w GoPro jest **względem sesji nagrywania** (nie zawsze lokalny dla pliku!) | ✅ do korekty local offset |
| **TSMP** | `TSMP` (uint32) | Dodatkowy licznik czasu próbki | ✅ fallback dla STMP |
| **GPS5** | `GPS5` | GPS bez czasu absolutnego (używa `current_block_start_dt` + `idx*0.1`) | — (bez czasu absolutnego) |
| **SCAL/TYPE** | `SCAL`, `TYPE` | Skalowanie/dekodowanie GPS9 (kontekst per-STRM) | ✅ |
| **creation_time** | ffprobe `format_tags.creation_time` | Start nagrywania wg zegara kamery (może być startem sesji, bywa nieobecny) | ✅ fallback |
| **STMP/TSMP przy ACCL/GYRO/SHUT/ISOE** | — | Czas próbek sensorów (nie dotyczy GPS) | — |

### Kluczowe odkrycie (realne pliki)

Na `GX010115.MP4` (592 s) pierwszy blok GPS9: `STMP=749730` µs (=0.75 s, **lokalny**), `GPS9 first abs = 2026-08-14 11:18:03.000` → `clip_start ≈ 11:18:02.250`.

Na `GX020079.mp4` (37.7 s) pierwszy blok GPS9: `STMP=1665779072` µs (=1665.78 s) — **więcej niż długość pliku**. STMP jest tu **względem sesji nagrywania** (klip to chapter/sesja trwająca 27.8 min). `GPS9 first abs = 04:55:50.800`; `creation_time = 04:28:04` (start sesji, nie klipu).

Wniosek: STMP jest spójnym zegarem względnym (deltas STMP ≈ deltas GPS-absolut w obrębie pliku — zweryfikowano), ale jego wartość BEZWZGLĘDNA jest lokalna dla pliku **tylko gdy** `STMP ≤ duration + tolerancja`. Dla chapterów/later-session `STMP` jest sesyjne i nie można z niego wyliczyć local-offsetu samego pliku.

---

## 3. Nowy resolver per-clip

Jedna warstwa logiczna w `src/multifile.py`:

```
path
  → resolve_clip_timestamp(path, ffmpeg_exe, ffprobe_exe, use_cache, duration_s)
      ├─ 1. _resolve_from_gpmf(path, ...)   (extract_gpmf + parse_gpmf)
      │       → _first_absolute_time_from_parsed(parsed, duration_s)
      │           • pierwsza poprawna próbka GPS9:
      │               local = STMP/1e6 (+ idx*0.1)
      │               jeśli local ≤ duration+1.0  → clip_start = abs − local   (STMP file-local)
      │               jeśli local > duration       → clip_start = abs           (STMP sesyjny; użyj czasu GPS)
      │           • brak GPS9 → GPSU (start bloku, source=gpmf_gpsu)
      │           • brak obu → no_gps_time
      ├─ 2. jeżeli GPMF bez czasu → creation_time  (source=container_creation_time)
      └─ 3. jeżeli nic → unknown  → timeline oznacza continuous_fallback
```

### Korekta local sample offset (wymaganie zadania)
```
clip_start = sample_absolute_time − sample_local_time
```
`sample_local_time` = `STMP/1e6 (+ idx*0.1)` — **tylko gdy STMP jest file-local** (≤ duration). Gdy STMP jest sesyjny, local offset jest nieznany → używamy czasu próbki GPS jako startu klipu (błąd sub-sekundowy, wciąż bardziej wiarygodny niż `creation_time`).

---

## 4. Priorytet źródeł (rzeczywista kolejność)

1. `gpmf_gps9` — GPS9 embedded `days+secs` (realny czas GPS) + korekta STMP gdy lokalny,
2. `gpmf_gpsu` — GPSU block datetime,
3. `container_creation_time` — ffprobe `creation_time`,
4. `continuous_fallback` — `base_dt + global_start_s` (jawnie oznaczony, `reliable=False`),
5. `unknown` / `gpmf_failed` — brak źródła.

Klip 0 w projekcie z telemetrią używa szybkiej ścieżki `project_start_anchor` (re-anchor do `telemetry.start_dt_utc`, który sam pochodzi z GPMF klipu 0) — **bez ponownej ekstrakcji GPMF wielogigabajtowego pliku**.

---

## 5. Zmodyfikowane pliki

| Plik | Zmiana |
|---|---|
| `src/multifile.py` | + stałe źródeł czasu, `ClipTimestampResolution`, `resolve_clip_timestamp` (jeden resolver), `_resolve_from_gpmf`, `_first_absolute_time_from_parsed` (korekta STMP + walidacja file-local), cache w pamięci + dysk (sidecar `<video>.telem_time.json` + `.meta.json` z fingerprintem), `VideoClip` + `timestamp_source/reliable/detail`, `_rebuild` (re-anchor clip0 + oznaczenie `continuous_fallback`), `build_timeline_from_paths` (fast-path clip0, przekazanie `duration_s`, `ffmpeg_exe`), `format_timeline_diagnostics` (per-clip + GAP). |
| `src/gui/qt/_mixins/project_mixin.py` | przekazanie `ffmpeg_exe` do `build_timeline_from_paths`; pełna diagnostyka `[MultiFile]` per klip + ostrzeżenie o `continuous_fallback`. |
| `tests/test_multifile_etap3_clip_time.py` (NOWY) | 19 testów (TEST 1–9 + resolver). |
| `tests/test_multifile_timeline.py` | aktualizacja mocków do `resolve_clip_timestamp`. |

---

## 6. Cache (koszt ponownego parsowania GPMF)

- **W pamięci**: `_TIME_RESOLUTION_CACHE` kluczowana `(resolved_path, duration_s)` — STMP file-local zależy od długości klipu, więc duration wchodzi do klucza.
- **Na dysku**: sidecar `<video>.telem_time.json` + `<video>.telem_time.json.meta.json` (wzorzec jak istniejący `<video>.json` GPMF), z kontraktem `{version, source_size, source_mtime_ns, duration_s}` — zapis atomowy, tylko gdy wynik ma znane źródło i znane `duration_s`.
- **Fast-path klip 0** przy znanym `base_dt` — pomija drugą ekstrakcję GPMF pierwszego (dużego) pliku.
- Cache jest best-effort (try/except) — nigdy nie blokuje wczytania projektu.

---

## 7. Testy

### Nowe — `tests/test_multifile_etap3_clip_time.py` (19)
- **TEST 1** jeden plik: `project_duration=60 s`, `global_to_absolute(30)=10:00:30`.
- **TEST 2** dwa ciągłe chaptery: global 15:00 → `10:15:00`.
- **TEST 3** dwa nagrania z przerwą: global 15:00 → clip2 local 5:00 → `10:35:00`.
- **TEST 4** jedna aktywność FIT, trzy nagrania: `project_duration=35 min`; mapowania `0→10:05, 5→10:10, 10→10:35, 20→10:45, 25→11:20, 30→11:25`.
- **TEST 5** pierwsza próbka GPS po starcie: STMP=0.8 s, abs=10:35:00.800 → `clip_start=10:35:00.000` (NIE 10:35:00.800).
- **TEST 5b** STMP sesyjny (>duration) → używa czasu GPS (z diagnostyką `not_file_local`).
- **TEST 5c** brak STMP → używa czasu GPS.
- **TEST 5d** pierwsza próbka bloku niepoprawna (0,0) → pomijana, poprawny offset kolejnej.
- **TEST 6** creation_time vs GPMF → preferuje GPMF (`gpmf_gps9`), źródło zapisane.
- **TEST 7** brak GPMF, jest creation_time → `container_creation_time`, reliable.
- **TEST 8** brak GPMF i creation_time → brak crasha, `unknown`; w timeline → `continuous_fallback` + `reliable=False` + mapowanie przez jawny fallback.
- **TEST 9** kolejność użytkownika zachowana (B,A,C), absolutne czasy z własnych danych.
- + cache: duration w kluczu; fast-path klip 0 (resolver nie wołany, source=`project_start_anchor`); przekazanie duration do resolvera.

**Wynik:** `19 passed`.

### Regresja (istniejące)
`test_multifile_timeline` (28), `test_gpmf_timing`, `test_gpmf_cache`, `test_telemetry_manager`, `test_video_helpers`, `test_export_lifecycle`, `test_render_tab`, `test_cut_feature`, `test_chart_seek_history`, `test_chart_axis_cache`:
**171 passed / 0 failed.**

---

## 8. Smoke test (realne pliki)

| Klip | absolute_start | source | detail | creation_time | delta |
|---|---|---|---|---|---|
| `GX010115.MP4` | `2026-08-14 11:18:02.250` | `gpmf_gps9` | STMP=0.74973 s file-local | `11:18:01` | `+1.250 s` |
| `GX020079.mp4` | `2026-08-05 04:55:50.800` | `gpmf_gps9` | STMP=1665.78 s **nie file-local** (37.7 s plik) → czas GPS | `04:28:04` | `+1666.8 s` |
| `GX030120.MP4` | `2026-08-18 04:46:25.700` | `gpmf_gps9` | STMP=1006.09 s nie file-local → czas GPS | `N/A` (brak) | — |

Timeline 3 klipów: `project_duration=810.5 s`; `[MultiFile] GAP removed from final timeline` między klipami — przerwy realne usunięte z osi globalnej, czas absolutny zachowany.

Diagnostyka przykładowa (end-to-end z `base_dt`):
```
[MultiFile] Timeline: 2 clips, project_duration=630.3s
[MultiFile] Clip 1/2
  path=GX010115.MP4
  global=0.000-592.597
  absolute=2026-08-14T11:18:03.000-2026-08-14T11:27:55.597
  source=project_start_anchor reliable=True
[MultiFile] Clip 2/2
  path=GX020079.mp4
  absolute=2026-08-05T04:55:50.800-2026-08-05T04:56:28.537
  source=gpmf_gps9 reliable=True
  detail=gps9_first_abs=... stmp=1665779072.0 ... reason=stmp_not_file_local(1665.779s > duration 37.738s) (using GPS sample time as clip start)
```

---

## 9. Fallbacki — dokładnie kiedy

| Fallback | Kiedy | Oznaczenie |
|---|---|---|
| `container_creation_time` | GPMF bez GPS9/GPSU (`gpmf_failed`, `gpmf_unavailable`, `no_gps_time`) i jest `creation_time` | `source=container_creation_time`, `reliable=True` |
| `continuous_fallback` | klip bez absolutnego startu (brak GPMF i `creation_time`) | `source=continuous_fallback`, `reliable=False`; log: `[MultiFile] WARNING: no reliable absolute start ...` |
| `project_start_anchor` | klip 0 przy znanym `base_dt` (telemetria) | `source=project_start_anchor`, `reliable=True` |
| „using GPS sample time" | STMP sesyjny (nie file-local) lub brak STMP | `source=gpmf_gps9`, `reliable=True`, w `detail` jawny powód |

---

## 10. Ryzyka

- **Timezone**: wszystkie czasy normalizowane do naive-UTC (`_as_naive_utc`); GPS9/GPSU są UTC, `creation_time` parsowane z offsetem i konwertowane. Brak mieszania stref.
- **Precyzja timestampu**: korekta STMP daje dokładność ~ms dla klipów, gdzie GPS startuje tuż po starcie pliku; dla chapterów/later-session start klipu = czas pierwszej próbki GPS (błąd sub-sekundowy, jawnie oznaczony).
- **Brak GPS / GPMF bez fix**: brak GPS9/GPSU → `creation_time` → `continuous_fallback`; nie crashuje.
- **Chaptery GoPro**: STMP sesyjny wykrywany przez porównanie z `duration` — nie dodawano logiki nazw plików; każdy klip weryfikowany z własnych danych.
- **Osobne nagrania**: absolutne starty z własnych GPS9 (10:05 / 10:35 / 11:20) zachowane mimo sklejenia na osi globalnej — pokryte TEST 4.
- **SmartSync**: niezmieniony; resolver ustawia *absolutną oś klipu*, a SmartSync pozostaje offsetem synchronizacyjnym na tej osi (rozdzielone pojęcia).
- **Single-file regression**: klip 0 re-anchor do `start_dt_utc`; `global_to_absolute(t) == start_dt_utc + t`; 171 testów zielonych.
- **GPMF bez GPS (syntetyczne testy)**: pokryte.

---

## 11. Gotowość do ETAPU 4

**Ocena: TAK — warunkowo.**

`video_timeline.global_to_absolute()` jest **wiarygodne** dla:
- każdego klipu z GPS9/GPSU (source `gpmf_gps9`/`gpmf_gpsu`, `reliable=True`),
- klipu 0 (re-anchor do `start_dt_utc`),
- klipów z `creation_time`.

**Pozostaje jawny warunek**: klipy z `source=continuous_fallback` lub „using GPS sample time" mają czas przybliżony (sub-sekundowo lub wprost oznaczony). Przed podpięciem pod preview/render należy:
1. **ETAP 4A (preview)**: `target_dt = timeline.global_to_absolute(current_ts)` w `preview_mixin` + przełączanie dekodera na granicach (QMediaPlayer/MPV) + CPU fallback z listy.
2. **ETAP 4B (render)**: przekazanie `video_timeline` do `frame_renderer`/`worker_cache`/`telemetry_precompute`; `target_dt` per klatka przez timeline.
3. **AMD native** (osobny etap GPU): iteracja po wszystkich klipach (obecnie tylko `input_files[0]`).
4. **Walidacja wykresów HR/Cadence** (oś względna `[-60,0]` względem absolutnego `target_dt`) oraz **SmartSync** na realnym materiale multi-file.

Kontrakt ETAPU 3 spełniony: każdy klip ma `global_start_s/global_end_s/absolute_start_dt/absolute_end_dt` + znane źródło czasu; oś globalna usuwa przerwy, absolutny czas zachowuje rzeczywiste odstępy.

---

## Podsumowanie

- Jeden resolver (`resolve_clip_timestamp`) ustala czas każdego klipu: GPMF GPS9 → GPSU → `creation_time` → `continuous_fallback`.
- Wykryto i obsłużono kluczową pułapkę: STMP w GoPro jest **względem sesji**, nie pliku — korekta local-offset tylko gdy `STMP ≤ duration`.
- Cache w pamięci + dysk (sidecar z fingerprintem) ogranicza ponowne parsowanie dużych plików; fast-path dla klipu 0.
- Pełna diagnostyka `[MultiFile]` (per-klip + GAP removed) i jawne oznaczenie fallbacków.
- 46 testów multifile + 171 łączna regresja — zielone.
