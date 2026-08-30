# TeleM — LOADING ETAP 1: profilowanie i naprawa 45% „Wczytywanie JSON”

## 1. Reprodukcja

Na repozytorium dostępny jest materiał `Video/GX020079.MP4` oraz `Video/GX020079.json`.

Rozmiary:

```text
GX020079.MP4  = 228,675,046 bytes
GX020079.json = 125,936 bytes
```

Fizyczny pomiar responsywności GUI na Intel nie został wykonany: `PHYSICAL GUI RESPONSIVENESS TEST: NOT EXECUTED`.

## 2. Pełny loading pipeline

1. `ProjectMixin::_on_files_selected()` emituje `0%` i uruchamia `bg_load()` w `threading.Thread`.
2. `bg_load()` wykrywa ffprobe/ffmpeg, analizuje strumień przez `ffprobe_stream_info()`, ustala rozdzielczość/FPS/czas.
3. Layout jest ładowany przez `normalize_layout()`; MapPreload startuje równolegle przed ciężką analizą GPMF.
4. `_load_or_generate_telemetry()` sprawdza sidecar przez `_load_valid_gpmf_cache()`.
5. Cache miss: `gpmf_to_exiftool_json()` albo subprocess ExifTool, następnie zapis sidecaru, `ensure_records_list()`, `load_gpmf_from_exiftool(flat=...)`, `load_gpmf_records()` i `load_gps_track()`.
6. Cache hit: odczyt sidecaru, konwersja rekordów i ekstrakcja telemetryczna.
7. Następnie ładowane są GPX/FIT, budowany jest `VideoTimeline`, rejestrowane pola FIT i przygotowywany pierwszy preview.
8. GUI otrzymuje sygnały progresu, a `sig_map_ready` niezależnie odświeża preview mapy.

## 3. Co naprawdę oznaczało 45%

Przed zmianą etykieta `45% / Wczytywanie JSON...` obejmowała nie tylko odczyt JSON. Przy trafieniu w sidecar wykonywano:

```text
_load_valid_gpmf_cache()
ensure_records_list()
load_gpmf_from_exiftool(video_path)  <- ponowny odczyt ExifTool z MP4
load_gpmf_records()
load_gps_track()
```

Najważniejszy błąd: sidecar zawierał już słownik kompatybilny z ExifTool, ale cache-hit przekazywał do `load_gpmf_from_exiftool()` tylko ścieżkę MP4, więc ExifTool uruchamiał się ponownie.

## 4. Timingi przed zmianą

Kod przed zmianą nie rozdzielał czasów. Dostępny był tylko jeden status 45%, bez pomiaru read/parse/ExifTool/extraction. Dlatego nie przypisuję historycznych wartości liczbowych bez pomiaru.

| Etap | Przed zmianą | Wątek | Wejście |
|---|---|---|---|
| sidecar read/parse | brak osobnego pomiaru | `bg_load` worker | JSON |
| ExifTool przy cache hit | wykonywany, brak pomiaru | `bg_load` worker | MP4 |
| GPMF extraction | brak osobnego pomiaru | `bg_load` worker | rekordy |
| GPS/IMU | brak osobnego pomiaru | `bg_load` worker | rekordy |

## 5. GUI thread / worker

`_on_files_selected()` uruchamia `bg_load()` poza Qt GUI thread. Odczyt JSON, GPMF i ekstrakcja telemetryczna są wykonywane w tym workerze. Nie znaleziono w tej ścieżce `join()`, `wait()` ani synchronicznego oczekiwania GUI na worker.

## 6. GIL

Brak dowodu, że GIL był główną przyczyną. Ciężka praca jest w workerze, a obecny przypadek wskazuje konkretnie na zbędny subprocess ExifTool przy cache hit. Nie wdrażano multiprocessing ani nowego frameworka async.

## 7. Cache / cold vs warm

Cache ma fingerprint źródłowego MP4: wersję kontraktu, rozmiar i `mtime_ns`. Stary/niezweryfikowany sidecar jest odrzucany.

Pomiar istniejącego JSON:

```text
json_file_read = 0.38 ms
json_parse     = 0.89 ms
JSON size      = 125,936 bytes
```

Dla `GX020079.json` brakowało aktualnego sidecar metadata, więc nie uruchamiano ryzykownego generowania w ramach tego audytu.

## 8. Faktyczna przyczyna

Zbędne ponowne uruchomienie ExifTool na MP4 podczas warm cache load, ukryte pod etykietą „Wczytywanie JSON”. To zwiększało czas etapu i zaciemniało rzeczywisty progres.

## 9. Zmiany produkcyjne

- `load_json_with_fallback()` obsługuje opcjonalny callback profilujący osobno file read i JSON parse.
- `_load_valid_gpmf_cache()` loguje odczyt/parsowanie sidecaru.
- `_load_or_generate_telemetry()` loguje GPMF conversion, ExifTool process, records conversion, GPMF extraction i GPS extraction.
- Cache hit przekazuje `flat=data` do `load_gpmf_from_exiftool()`, więc nie uruchamia ponownie ExifTool.
- Status 45% zmieniono na `Odczyt JSON...`, a po trafieniu cache na `Analiza GPMF...`.

Nie zmieniano mapy, finalnego renderera, QSV, AMF, NVENC, CUDA ani decoder/encoder selection.

## 10. Progress przed/po

Przed:

```text
45% Wczytywanie JSON...
```

Po:

```text
45% Odczyt JSON...
50% GPMF: czytanie strumienia...
55% Analiza GPMF... / ExifTool: odczyt metadanych...
65% Parsowanie danych (...)
70% Metadane gotowe
```

Nie dodano sztucznego timerowego zwiększania procentu.

## 11. Statusy przed/po

Status odpowiada teraz faktycznej fazie: odczyt sidecaru, generowanie GPMF, ExifTool, analiza GPMF i parsowanie danych.

## 12. Timingi po zmianie

Profilowanie emituje między innymi:

```text
[LoadProfile] stage=json_file_read ...
[LoadProfile] stage=json_parse ...
[LoadProfile] stage=gpmf_exiftool_extract ...
[LoadProfile] stage=gpmf_records_extract ...
[LoadProfile] stage=gps_extract ...
```

Każdy wpis zawiera elapsed, thread id/name, rozmiar wejścia i — gdy dostępne — liczbę rekordów.

## 13. Responsywność GUI

Nie wykonano fizycznego testu przesuwania okna/repaint/QTimer na Intel. Kodowa analiza potwierdza workerową ścieżkę ładowania; wpływ GIL i konkurencji z MapPreload wymaga pomiaru runtime na maszynie użytkownika.

## 14. Intel

Problem jest backend-neutralny. Intel jedynie ujawnił objaw; poprawka dotyczy cache/telemetry loading i nie zawiera warunku vendor-specific.

## 15. Regresja

Uruchomiono:

```text
python -m pytest -q tests/test_gpmf_cache.py tests/test_map_deflayout_lifecycle.py tests/test_map_overview_first.py tests/test_map_preload_etap1.py tests/test_map_sync.py tests/test_telemetry_manager.py
88 passed
```

Dodano asercję, że warm cache przekazuje słownik `flat` do ekstrakcji zamiast ponownego odczytu z MP4.

## 16. Physical GUI

`PHYSICAL GUI RESPONSIVENESS TEST: NOT EXECUTED`.

