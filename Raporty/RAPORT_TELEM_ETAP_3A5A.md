# TeleM — ETAP 3A.5A — naprawa cache JSON GPMF

Data: 2026-08-18  
Zakres: wyłącznie cache GPMF JSON. SmartSync, FIT, mapy i parser GPS9 nie były zmieniane.

## A. Old cache behavior

Dotychczas istniejący `GX020079.json` był ładowany bez sprawdzania wersji parsera, fingerprintu MP4 ani `mtime`. Stary cache zawierał syntetyczne czasy `04:28:04.000–04:28:41.700`.

## B. New validity contract

Cache jest ważny wyłącznie, gdy sidecar zawiera:

```text
version = 2
source_size
source_mtime_ns
generator
```

oraz rozmiar i `mtime_ns` źródłowego MP4 są zgodne. Brak sidecaru lub brak wymaganego pola oznacza `CACHE INVALID`.

## C. Metadata format

Metadata jest przechowywane osobno, aby nie było traktowane jako telemetryczny rekord:

```text
GX020079.json.meta.json
```

Przykład:

```json
{
  "_telem_cache": {
    "version": 2,
    "source_file": "C:\\_DEV\\TeleM\\Video\\GX020079.mp4",
    "source_size": 228675046,
    "source_mtime_ns": 0,
    "generator": "gpmf"
  }
}
```

JSON i sidecar są zapisywane przez plik tymczasowy, `flush`, `fsync` i atomowy `os.replace`.

## D. GX020079 migration

```text
old cache status = INVALID
reason = legacy_cache_no_version
regenerated = yes
new first GPS = 2026:08:05 04:55:50.800
new last GPS  = 2026:08:05 04:56:28.500
GPS count     = 378
```

## E. Second load

```text
first load  = MISS → fresh GPMF extraction → atomic write
second load = HIT
fresh extraction on second load = no
```

## F. Files changed

```text
src/gui/qt/_mixins/project_mixin.py
  - GPMF_CACHE_VERSION
  - _gpmf_cache_metadata_path
  - _load_valid_gpmf_cache
  - _write_gpmf_cache
  - _atomic_write_json
  - cache HIT/MISS/REGENERATED integration in both generation paths

tests/test_gpmf_cache.py
  - legacy cache migration and reopen HIT
  - source size and mtime invalidation
  - cache version mismatch
  - corrupted JSON
```

## G. Tests

Nowe testy cache:

```text
3 passed
```

Testy powiązane po migracji realnego cache:

```text
39 passed, 17 skipped, 1 failed
```

Jedyny failure związany z tym obszarem to istniejący test SmartSync oczujący offsetu około `-1 s`; niezmieniony SmartSync zwraca `+1665.8 s`.

Pełna suite:

```text
296 passed, 5 failed, 17 skipped
```

Pozostałe cztery failure’y są niezwiązane: AMD ABI, AMD FIT layout, QP analyzer i kolejność encoderów.

## H. Compatibility

```text
GPMF values unchanged = yes
GPS9 timing retained = yes
ISOE retained = yes
SHUT retained = yes
FIT untouched = yes
SmartSync untouched = yes
map untouched = yes
```

Sidecar nie jest dodawany do głównego JSON, więc nie zmienia `telemetry_extract.py`, `TelemetryDataManager` ani dynamic discovery pól.

Stary/external JSON bez metadata jest celowo unieważniany jednokrotnie, ponieważ nie ma dowodu zgodności z aktualną semantyką GPS9.

## I. Remaining root cause

Pozostaje osobny problem synchronizacji temporalnej/GPS w:

```text
src/gui/telemetry_manager.py
_compute_smart_time_offset()
_align_offset_by_track()
```

Nie był częścią ETAPU 3A.5A.

## J. Recommended next step

Osobny etap dotyczący wyłącznie SmartSync: wybór offsetu na podstawie właściwego nakładania punktów GPS, bez przesuwania FIT względem pierwszego rekordu aktywności.
