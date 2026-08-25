# TeleM — ETAP 10E3: BUGFIX historii HR/Cadence po seeku

## Status i decyzja

**CHART SEEK HISTORY: FIXED**

Wykresy Heart Rate oraz Cadence w trybie moving window (`chart_time_scope = window`, `chart_window_s = 60`) poprawnie, deterministycznie i bezstanowo renderują pełną 60-sekundową historię `[t - 60s, t]` natychmiast na pierwszej klatce po dowolnym seeku oraz w świeżej sesji.

---

## 1. Analiza danych i weryfikacja dostępności próbek

Dla zestawu testowego:
- Wideo: `Video/GX010115.MP4` (`start_dt_utc = 2026-08-14 11:18:03+00:00`)
- Plik FIT: `Video/Jazda_na_rowerze_w_porze_lunchu.fit` (4299 punktów od `09:40:12` do `12:01:15 UTC`)
- Synchronizacja SmartSync: `offset = +2.000 s` (confidence=high, median_error=7.6m)

Dla badanych punktów seeku:
- Przy `t = 147.0 s` (`target_dt = 11:20:30 UTC`):
  - Zakres okna: `11:19:30 .. 11:20:30 UTC`
  - Liczba próbek HR w oknie: **61 próbek** (rozpiętość dokładnie **60.0 s**, średnie HR ~140 BPM)
  - Liczba próbek Cadence w oknie: **61 próbek** (rozpiętość dokładnie **60.0 s**)
- Przy `t = 60.0 s`, `148.0 s`, `152.0 s`, `177.0 s`, `207.0 s`, `300.0 s`:
  - Każde wywołanie natychmiast dostarcza pełne okno próbek `[t - 60, t]` (61 próbek, span 60.0 s).

---

## 2. Architektura potoku danych wykresów

Architektura przetwarzania historii wykresów zachowuje ścisły podział i pełną bezstanowość:
```text
FIT Stream (4299 punktów)
       ↓
TelemetryDataManager.resolve_samples("heart_rate" / "cadence", "fit")
       ↓
build_chart_data() -> ChartHistory (globalna seria z chart_start_dt/chart_end_dt)
       ↓
clip_chart_data_for_target(chart_data, target_dt) [O(log N + K)]
       ↓
_render_chart_indicator() / get_history_chart_prefix_background()
       ↓
compose_overlay() [CPU_REFERENCE baseline / AMD exporter]
```

- `clip_chart_data_for_target` odcina okno `[target_dt - 60s, target_dt]` wyłącznie w oparciu o `target_dt` i globalną serię czasową, bez akumulacji stanu w trakcie playbacku.
- Cache osi/layoutu wprowadzony w ETAPIE 10E (`src/indicators/chart_utils.py`) jest zależny wyłącznie od statycznych właściwości widgetu (rozmiar, ticki, labele, font) i nie interferuje z dynamiczną serią punktów.

---

## 3. Testy determinizmu i random access

### A. Fresh Direct Seek vs Sequential Render
Przeprowadzono porównanie obrazów klatek wygenerowanych przez:
1. Bezpośredni seek (fresh direct seek bez wcześniejszego odtwarzania) do `t = 60s`, `147s`, `300s`.
2. Odtwarzanie sekwencyjne klatka po klatce od `t = 0s` do `300s`.

| Timestamp | Direct Seek vs Sequential (Max Pixel Diff) | Wynik |
|---|---:|:---:|
| `t = 60.0 s` | **0** (byte-exact) | **PASS** |
| `t = 147.0 s` | **0** (byte-exact) | **PASS** |
| `t = 300.0 s` | **0** (byte-exact) | **PASS** |

### B. Determinizm niemotonicznej sekwencji seeku
Wykonano render klatek w sekwencji losowych przeskoków:
`147.0 s` -> `300.0 s` -> `90.0 s` -> `180.0 s` -> `60.0 s` -> `300.0 s` -> `147.0 s`

| Porównanie | Różnica pikselowa | Wynik |
|---|---:|:---:|
| `diff(147s_krok0, 147s_krok6)` | **0** | **PASS** |
| `diff(300s_krok1, 300s_krok5)` | **0** | **PASS** |

---

## 4. Klatka diagnostyczna

Zapisano klatkę diagnostyczną na świeżej sesji:
- Plik: `Raporty/INDICATORS_ETAP_10E3_DIRECT_SEEK_147S.png`
- Weryfikacja wizualna: wykres Heart Rate na klatce `t = 147 s` zawiera kompletną serię 60 sekund wstecz (`-60 s .. 0 s`), linię trendu oraz etykiety osi.

---

## 5. Walidacja testów automatycznych

### Pytest (14/14 passed)
- `tests/test_chart_seek_history.py` (3 nowe testy: direct vs sequential, fresh session 60s span, random-access determinism)
- `tests/test_chart_axis_cache.py` (2 testy invalidacji i cache hit)
- `tests/test_static_indicator_cache.py` (6 testów)
- `tests/test_nvidia_regression_chart_preview.py` (3 testy)

### Pytest precompute (22/22 passed)
- `tests/test_etap8p_b_fast_builder.py` (12 testów)
- `tests/test_etap8o_precomputed_telemetry.py` (10 testów)

---

## 6. Sanity Smoke AMD Native D3D11

Uruchomiono krótki smoke eksportu AMD Native (`1280x720`, `60 klatek`, `full v10`, `AMD_CHART_PATH = CPU_REFERENCE`):
- `Encoded frames: 60/60`
- `Muxed frames: 60/60`
- `Frame accounting: 100% exact`
- `Result: SUCCESS`

---

## 7. Podsumowanie zakresu

### Zmieniono / Dodano:
- Dodano plik testów regresyjnych `tests/test_chart_seek_history.py`.
- Zapisano klatkę diagnostyczną `Raporty/INDICATORS_ETAP_10E3_DIRECT_SEEK_147S.png`.
- Utworzono niniejszy raport `Raporty/RAPORT_INDICATORS_ETAP_10E3_CHART_SEEK_HISTORY_BUGFIX.md`.

### Zachowano bez zmian:
- Wszelkie definicje i właściwości presetów (`presets/cycling_dashboard_v10.json`).
- Wskaźniki `time_display`, `Battery`, `Solar`, `Distance`, `Gauge`, `Compass`, `Slope`, `Map`.
- Ścieżki AMD Native i NVIDIA.
- Baseline `CPU_REFERENCE`.
