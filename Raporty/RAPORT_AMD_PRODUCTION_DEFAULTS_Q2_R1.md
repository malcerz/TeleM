# Raport: Ustanowienie i Walidacja Produkcyjnych Domyślnych Wartości AMD (Q2/R1)

## Podsumowanie i Decyzja

**STATUS:** `CASE A — AMD PRODUCTION DEFAULTS Q2/R1 VALIDATED`

Po wcześniejszych testach porównawczych A/B (kolejka `AMD_QUEUE_DEPTH` 0 vs 2, pierścień `AMD_VP_PROCESSOR_RING_SIZE` 1 vs 2, oraz `AMD_ABOVE_BATCHED` 0 vs 1) ustanowiono oficjalne domyślne parametry produkcyjne potoku renderowania AMD na gałęzi `amd-bikeridehud`:
- **`AMD_QUEUE_DEPTH=2`** (tryb asynchroniczny `AMD_CPU_GPU_PIPELINE=ASYNC`)
- **`AMD_VP_PROCESSOR_RING_SIZE=1`** (optymalna głębokość pierścienia VideoProcessor)
- **`AMD_ABOVE_BATCHED=0`** (stabilny, domyślny tryb przesyłu obszarów dirty)

Wykonano kontrolny, pełny eksport GUI na referencyjnym zestawie (4K UHD, 300 klatek, HEVC AMF, `GX020079.mp4` + `GX020079.fit`) **bez żadnych zewnętrznych zmiennych środowiskowych** (`active_env_overrides = {}`), udowadniając, że produkcyjne wartości domyślne są w pełni automatycznie aktywowane bez regresji wydajnościowej ani wizualnej.

---

## Metryki Kluczowe

```text
DEFAULT_QUEUE_DEPTH=2
DEFAULT_RING_SIZE=1
DEFAULT_ABOVE_BATCHED=0

FPS=37.008
FRAMES=300/300
DROPPED=0
AMF_ERRORS=0
D3D11_ERRORS=0
```

- **Czas renderowania:** 8.106 s (300 klatek 4K @ 29.97 fps)
- **Średnia przepustowość enkodera:** 37.01 FPS (wobec 32.09 FPS w starym trybie synchronicznym SYNC/Q0)
- **Zysk względem SYNC:** **+15.3% FPS** bez jakichkolwiek modyfikacji artefaktów wizualnych
- **Zasoby:** 0 błędów AMF, 0 przepełnień buforów wejściowych (`input_full_count=0`), 0 błędów D3D11, kod wyjścia procesu potomnego: `0`.

---

## Źródło Domyślnych Wartości i Zasady Nadpisywania (Override)

Zgodnie z wymogami, modyfikacje wprowadzono w kanonicznym module zarządzania konfiguracją AMD (`src/ffmpeg/amd_config.py`) oraz w eksporterze (`src/ffmpeg/amd_native_exporter.py`), bez tworzenia drugorzędnych źródeł konfiguracji:

1. **`PRODUCTION_DEFAULTS` w `src/ffmpeg/amd_config.py`**:
   - Zaktualizowano `"pipeline": "ASYNC"`, `"queue_depth": 2`.
   - Pozostawiono `"vp_processor_ring": 1`, `"above_batched": 0`.
2. **Logika `resolve_amd_config()`**:
   - `brak env` -> `pipeline="ASYNC"`, `queue_depth=2`.
   - `AMD_QUEUE_DEPTH=0` lub `AMD_CPU_GPU_PIPELINE=SYNC` -> natychmiast wymusza tryb synchroniczny `pipeline="SYNC"`, `queue_depth=0`.
   - `AMD_QUEUE_DEPTH=2` -> wymusza `pipeline="ASYNC"`, `queue_depth=2`.
   - Dowolne `AMD_VP_PROCESSOR_RING_SIZE` i `AMD_ABOVE_BATCHED` nadal mogą być swobodnie nadpisywane przez zmienne środowiskowe.
3. **`src/ffmpeg/amd_native_exporter.py`**:
   - Pobiera konfigurację z `resolve_amd_config()`, zapewniając pojedyncze źródło prawdy (Single Source of Truth).
   - Rejestruje jawnie parametry w logu:
     ```text
     [AMD NATIVE D3D11] AMD_QUEUE_DEPTH=2
     [AMD NATIVE D3D11] AMD_CPU_GPU_PIPELINE=ASYNC
     [AMD NATIVE D3D11] AMD_VP_PROCESSOR_RING_SIZE=1
     [AMD NATIVE D3D11] AMD_ABOVE_BATCHED=0
     ```

---

## Dowód Konfiguracji (`config_proof.txt`)

Zrzut z `scratch/amd_production_defaults/config_proof.txt`:

```text
=== HARD CONFIG PROOF ===
MODE: PRODUCTION_DEFAULTS (NO ENV OVERRIDES)
AMD_QUEUE_DEPTH: 2
AMD_CPU_GPU_PIPELINE: ASYNC
AMD_VP_PROCESSOR_RING_SIZE: 1
AMD_ABOVE_BATCHED: 0
AMD_AFTER_MAP_GAUGE_GPU: GPU
AMD_AFTER_MAP_CHART_GPU: GPU_SPLIT
AMD_GPU_MAP_ROTATE: GPU
resolution: 3840x2160
codec: hevc
frame_count: 300
fps: 37.008
render_time_s: 8.106
config_fingerprint: 62db3300c3e96a0d1b26ea74687cdb0ced738091c19e31e0c322f30552554be2
dll_build_id: telem-amd-native/1.0.0+1b5485c0c7cd.src698a06a0caed
dll_abi: 9
```

Profile JSON potwierdza:
```json
"active_env_overrides": {}
```

---

## Weryfikacja Wizualna (Visual Proof)

Z wyrenderowanego pliku MP4 (`default_10s.mp4`) wyodrębniono klatki:
- Klatka 0: `scratch/amd_production_defaults/frames/frame_000.png`
- Klatka 150: `scratch/amd_production_defaults/frames/frame_150.png`
- Klatka 299: `scratch/amd_production_defaults/frames/frame_299.png`
- Stykówka (Contact Sheet): `scratch/amd_production_defaults/contact_sheet.png`

Ocena wizualna: Wszystkie komponenty nakładki (obracana mapa GPU, wykresy tętna i kadencji AFTER-MAP GPU, prędkościomierz GPU, linijka, bateria, wskaźnik pochylenia) wyrenderowane poprawnie bez defektów, migotania czy zacięć.

Status:
```text
USER VISUAL ACCEPTANCE=PENDING
```

---

## Testy Jednostkowe

Zaktualizowano zestaw testów zarządzania konfiguracją w `tests/test_amd_benchmark_governance.py`:
- Sprawdzono zachowanie domyślne (bez env).
- Sprawdzono mechanizm czyszczenia override (`clear_ambient_overrides`).
- Sprawdzono wymuszenie trybu SYNC przez `AMD_QUEUE_DEPTH=0` oraz `AMD_CPU_GPU_PIPELINE=SYNC`.
- Sprawdzono nadpisywanie `AMD_QUEUE_DEPTH=2`, `AMD_VP_PROCESSOR_RING_SIZE=2`, `AMD_ABOVE_BATCHED=1`.

Wynik: **9/9 testów PASSED** w 0.25s.

---

## Lista Zmodyfikowanych Plików

1. `src/ffmpeg/amd_config.py` — Ustawienie `pipeline: ASYNC`, `queue_depth: 2` w `PRODUCTION_DEFAULTS` oraz obsługa reguł override w `resolve_amd_config()`.
2. `src/ffmpeg/amd_native_exporter.py` — Integracja pobierania `pipeline` i `queue_depth` z `resolve_amd_config()` oraz jawne logowanie konfiguracji.
3. `tests/test_amd_benchmark_governance.py` — Aktualizacja asercji i dodanie testów reguł nadpisywania.
