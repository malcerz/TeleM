# TeleM — LOADING ETAP 2: GPMF records + warm cache

## 1. Root cause 27.8 s

Pomiar użytkownika dla `GX010099.MP4` wskazuje na `gpmf_records_extract = 27.78973 s` i `gps_extract = 2.91582 s` przy raw cache hit.

Aktualny kod potwierdza dwa problemy:

1. `TelemetryDataManager.load_gpmf_records()` uruchamia wiele niezależnych ekstraktorów. Każdy z nich przechodzi przez `flatten_record()` i skanuje ten sam duży płaski słownik.
2. `load_gpmf_records()` wyciąga GPS tylko po to, aby wyliczyć heading, a następnie `load_gps_track()` wykonywał pełny GPS traversal ponownie i ponownie wyliczał heading.

Raw JSON read/parse nie jest bottleneckiem. Historyczne pomiary użytkownika: read 148.42 ms, parse 693.36 ms, a oba ekstraktory razem około 30.7 s.

## 2. Podetapy `gpmf_records_extract`

Dodano profilowanie w `TelemetryDataManager.load_gpmf_records()` i `load_gps_track()`. Logowane są:

```text
[LoadProfile:GPMF] stage=<name> elapsed_ms=... input_count=... output_count=... thread=...
```

Podetapy obejmują speed, altitude, track, ISO, exposure, temperature, accelerometer, gyroscope, GPS anchor, smoothing, GPS track, heading i slope.

W lokalnym repozytorium nie ma `GX010099`, więc nie generuję fikcyjnej tabeli czasów dla tego materiału. Konkretne czasy 27.78973 s / 2.91582 s są pomiarami użytkownika i pozostają historycznym baseline.

## 3. Co oznaczało `records=1`

`ensure_records_list()` celowo opakowuje top-level `dict` w jednoelementową listę:

```python
dict -> [dict]
```

Nie oznacza to jednego próbka telemetrycznego. Jeden element zawiera dużą strukturę ExifTool/GPMF z wieloma kluczami i seriami próbek. Dlatego poprzedni log `records=1` był mylący.

Nowe profile rozróżniają `input_count` od `output_count` dla każdego ekstraktora. Nie raportują już liczby opakowań jako liczby próbek.

Dokładne liczby GPS/ACCL/GYRO dla `GX010099` nie są lokalnie dostępne, ponieważ plik nie znajduje się w repozytorium.

## 4. Pełne traversal i złożoność

Przed zmianą każdy aktywny extractor wywoływał własny skan records i własne `flatten_record()`. W aktualnym kontrakcie było co najmniej:

```text
track
ISO
exposure
temperature
accelerometer
gyroscope
GPS dla heading
GPS dla load_gps_track
```

To jest wiele przejść O(N * K), gdzie N oznacza rozmiar dużej struktury, a K liczbę aktywnych extractorów. Nie znaleziono `list.index()` ani sortowania wewnątrz głównej pętli jako osobnego O(N²); koszt wynikał głównie z powtarzanych pełnych traversalów i flattenowania.

## 5. `gps_extract = 2.9 s`

Przed zmianą GPS było wyciągane w `load_gpmf_records()` do heading, a następnie ponownie w `load_gps_track()`. Po zmianie pierwszy wynik jest zapisywany w `self.gps_track`; `load_gps_track()` wykorzystuje istniejący track i nie wykonuje drugiego pełnego ekstraktora. Heading jest również wyliczany ponownie tylko wtedy, gdy nie istnieje.

## 6. Processed telemetry cache

Dodano `src/telemetry_processed_cache.py`.

Format:

```text
<video-stem>.telemetry.json.gz
```

Jest to gzipowany JSON, więc odczyt nie wykonuje niezaufanego kodu. Cache zawiera wyłącznie dane neutralne i deterministyczne:

- speed/altitude/track,
- ISO/exposure/temperature,
- slope,
- accelerometer/gyroscope,
- GPS track,
- heading,
- `start_dt_utc`.

Nie zawiera FIT, GPX, layoutu, mapy, GUI ani render state.

Kontrakt zawiera:

```text
version = 1
source_size
source_mtime_ns
```

Raw cache i processed cache pozostają rozdzielone.

## 7. Cold load

Przy braku processed cache cold path wykonuje dotychczasową ekstrakcję, dodatkowo loguje podetapy i zapisuje processed cache po `load_gps_track()`.

## 8. Warm load

Przy raw cache hit i poprawnym processed cache:

```text
raw JSON read/parse
-> processed cache read/decode
-> apply_processed_cache()
-> pominięcie load_gpmf_records()
-> pominięcie load_gps_track()
```

Logowane są osobno:

```text
[Telemetry Cache] RAW/HIT
[Telemetry Cache] PROCESSED HIT
```

Warm load nie wykonuje ponownie kosztownych traversalów GPMF.

## 9. Benchmark GX010099

`GX010099.MP4` i `GX010099.json` nie są dostępne lokalnie. Nie wykonano więc nowego pomiaru cold/warm dla tego pliku.

| stage | cold | warm |
|---|---:|---:|
| JSON read | brak lokalnego pomiaru | historycznie 148.42 ms |
| JSON parse | brak lokalnego pomiaru | historycznie 693.36 ms |
| records extract | historycznie 27,789.73 ms | pomijany przy processed HIT |
| GPS extract | historycznie 2,915.82 ms | pomijany przy processed HIT |
| processed cache read/decode | nowy etap | do zmierzenia na GX010099 |

Lokalny pomiar dostępnego `GX020079.json` (125,936 bytes): read 0.38 ms, parse 0.89 ms.

## 10. Parity

Dodano `tests/test_telemetry_processed_cache.py`, który sprawdza round-trip i parity timestampów, próbek skalarnych, GPS oraz IMU. Test sprawdza też invalidację po zmianie źródła i wersji kontraktu.

## 11. Progress/status

Processed cache hit pokazuje:

```text
Wczytywanie cache telemetrycznego...
```

Nie pokazuje przez kilkadziesiąt sekund `Analiza GPMF...`. Processed miss zachowuje status analizy i zapisuje cache po ekstrakcji.

## 12. `QObject::startTimer`

Źródło zostało zlokalizowane w `ProjectMixin::_on_files_selected()`:

```text
bg_load worker
-> QTimer.singleShot(1500, self._check_mpv_hwdec)
```

`QTimer.singleShot()` był wywoływany z wątku `bg_load`, który nie ma właściwego Qt event dispatcher. Naprawa:

```text
bg_load
-> sig_schedule_mpv_hwdec_check
-> controller GUI thread
-> _schedule_mpv_hwdec_check()
-> QTimer.singleShot(...)
```

Nie wyciszano warningu i nie wyłączano diagnostyki MPV.

## 13. GUI responsiveness

GPMF extraction nadal działa w istniejącym `bg_load` workerze. Nie wdrażano multiprocessing ani zmian architektury z powodu GIL; brak dowodu, że GIL jest główną przyczyną. Fizyczny test QTimer/repaint/przesuwania okna nie został wykonany:

`PHYSICAL GUI RESPONSIVENESS TEST: NOT EXECUTED`.

## 14. Intel/vendor neutrality

Problem i poprawka są backend-neutralne. Nie zmieniono Intel/QSV, AMD/AMF, NVIDIA/NVENC, CUDA, D3D11, MPV hwdec ani encoderów.

## 15. Testy

Uruchomiono:

```text
python -m pytest -q tests/test_gpmf_cache.py tests/test_telemetry_processed_cache.py tests/test_telemetry_manager.py tests/test_gpmf_timing.py tests/test_map_deflayout_lifecycle.py tests/test_map_overview_first.py tests/test_map_preload_etap1.py tests/test_map_sync.py tests/test_controller_properties.py tests/test_render_tab.py
121 passed
```

`py_compile` zmienionych modułów również przechodzi.

## 16. Zmienione pliki

- `src/telemetry_processed_cache.py`
- `src/gui/telemetry_manager.py`
- `src/gui/qt/_mixins/project_mixin.py`
- `src/gui/qt/controller.py`
- `src/gui/qt/signals.py`
- `src/telemetry_extract.py` — callback profilowania JSON
- `tests/test_telemetry_processed_cache.py`
- `tests/test_gpmf_cache.py`

