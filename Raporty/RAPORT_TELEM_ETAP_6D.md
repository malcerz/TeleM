# ETAP 6D — RESULT

Data: 2026-08-18  
Materiał: `Video/GX030120.MP4` + `Video/Poranna_jazda_na_rowerze.fit`

## A. Root cause

Root cause znajdował się w `src/indicators/chart_builder.py`, funkcji `build_chart_data`: builder zwracał pełne listy wartości bez timestampów. Wspólne `prepare_overlay_frame_data`, worker i PRECOMPUTED przekazywały tę pełną serię dalej do renderera, dlatego chart dla 14,3 s zawierał całe 1672 próbki FIT.

## B. Implementation

Zmodyfikowano wyłącznie:

- `src/indicators/chart_builder.py`
- `src/indicators/frame_data.py`
- `src/telemetry_precompute.py`
- `tests/test_etap6d_chart_history.py`

`build_chart_data` zwraca list-compatible `ChartHistory`, czyli wartości z metadanymi timestampów. `clip_chart_data` używa `bisect_left`/`bisect_right` i tworzy nowy, nie-mutujący wycinek.

Clipping jest wykonywany w `prepare_overlay_frame_data` (preview/CPU/worker/AMD live) oraz w `TelemetryFrameCache.lookup` (PRECOMPUTED). Nie ma cięcia po indeksie klatki, `fps` ani `current_position`.

## C. History contract

```text
history_start = max(configured/source-visible start, first source timestamp)
history_end   = last source timestamp <= target_dt
rule          = history_start <= timestamp <= target_dt
```

Historia nie mutuje bazowej pełnej serii. Dla naive FIT i aware UTC anchor granica jest porównywana w reprezentacji timestampów serii; przechowywane timestampy pozostają bez zmian.

## D–E. Step i linear fields

HR, cadence, power, atemp, battery, ISO, SHUT, TMPC, IMU i dynamic FIT zachowują surowe próbki do `target_dt`, jeżeli mają aktywny chart indicator. Speed, altitude i distance zachowują dotychczasową interpolację current value; chart otrzymuje raw samples ograniczone czasowo i nie dodaje nowej interpolacji.

## F. Real FIT validation

Anchor: `2026-08-18 04:46:25.700000 UTC`. Surowe chart series HR/cadence: po 1672 próbki.

| video_s | current HR | HR count | HR last timestamp/value | current cadence | cadence count | cadence last timestamp/value | future |
|---:|---:|---:|---|---:|---:|---|---:|
| 0 | 103 | 0 | — | 67 | 0 | — | 0 |
| 14,3 | 102 | 15 | 04:46:40 / 102 | 63 | 15 | 04:46:40 / 62 | 0 |
| 60 | 91 | 60 | 04:47:25 / 91 | 45 | 60 | 04:47:25 / 45 | 0 |
| 120 | 109 | 120 | 04:48:25 / 109 | 74 | 120 | 04:48:25 / 74 | 0 |
| 175 | 110 | 175 | 04:49:20 / 110 | 59 | 175 | 04:49:20 / 59 | 0 |
| 180 | 108 | 180 | 04:49:25 / 108 | 61 | 180 | 04:49:25 / 61 | 0 |

Liczność jest non-decreasing: `0, 15, 60, 120, 175, 180`. Przy 14,3 s problem 1672 → 15 został usunięty. Exact timestamp jest uwzględniany (`timestamp <= target_dt`), a target przed pierwszym widocznym sample daje pustą historię.

Obecna semantyka current dla step fields trzyma poprzednią próbkę przy exact timestamp; dlatego przy 14,3 s current cadence `63` i raw chart endpoint `62` są różne. Jest to zachowana semantyka current, nie zmieniana w ETAPIE 6D. HR w tym punkcie ma zgodny endpoint `102`.

## G. Source ownership

Clipping działa po wyborze źródła przez `build_chart_data`:

| requested source | seria użyta |
|---|---|
| GPMF | GPMF only |
| FIT | FIT only |
| GPX | GPX only |

Nie dodano fallbacku. Source switching testy pozostają zielone.

## H. None / zero

Potwierdzone testami ETAP 6B i 6D: source FIT bez danych daje `current=None` i history empty; brak próbki przed targetem daje history empty; realne `0.0` pozostaje w historii; bazowa seria pozostaje niezmieniona.

## I. Preview / CPU / PRECOMPUTED / worker / AMD

Dla 14,3 s:

| path | HR count | cadence count |
|---|---:|---:|
| preview / `prepare_overlay_frame_data` | 15 | 15 |
| CPU final / wspólne frame data | 15 | 15 |
| PRECOMPUTED / `TelemetryFrameCache.lookup` | 15 | 15 |
| worker chart view | 15 | 15 |
| AMD GPU_SPLIT input | 15 | 15 |

Ponowny rzeczywisty krótki eksport AMD Native na `GX030120.MP4` zakończył się sukcesem: `AMD_TELEMETRY_MODE=PRECOMPUTED`, `AMD_CHART_PATH=GPU_SPLIT`, GPU HUD/D3D11VA active, AMF output 6, dropped 0, HW decode proof YES. Mapa zachowała wcześniejszy `CPU_REFERENCE` fallback z powodu z-order i pozostaje poza zakresem.

## J. Performance

Clipping używa binary search po timestampach: koszt znalezienia granic to `O(log N)`. Zwrócenie historii do renderera wykonuje wymagane cięcie wartości, ale nie skanuje pełnej serii w celu znalezienia endpointu i nie mutuje cache.

## K. Tests

Nowe: `tests/test_etap6d_chart_history.py` — 5 testów.

Powiązane: `39 passed` (ETAP 6D + ETAP 6B + telemetry manager) oraz `19 passed` (source resolver, GPMF timing/cache, AMD chart path).

Pełna suite: `319 passed, 3 failed, 17 skipped`. Trzy znane, wcześniejsze failure’y pozostają bez zmian: `tests/test_amd_native_etap4.py`, `tests/test_qp_analyzer.py`, `tests/test_render_tab.py`. Nie pojawiły się nowe niezwiązane failure’y.

## L. Regressions

Nie zmieniano current values, source resolvera ETAPU 6B, geometrii/bbox/size/font, `track_map`, timingów IMU, layoutu ACCL/GYRO ani implementacji GPU poza przekazaniem już przyciętej historii.

## M. Remaining issues

### CONFIRMED

- chart history nie zawiera próbek `timestamp > target_dt`;
- preview, CPU, PRECOMPUTED, worker i AMD otrzymują przyciętą historię;
- realny materiał nie ma już pełnej historii FIT przy 14,3 s;
- source ownership, `None`, zero i brak mutacji są zachowane.

### SUSPECTED

Istniejąca semantyka step current (`strict previous` przy exact timestamp) może powodować różnicę current cadence `63` vs raw endpoint `62`; nie zmieniano jej zgodnie z zakresem ETAPU 6D.

### OUT OF SCOPE

Zmiana current lookup, dodawanie ACCL/GYRO do `def_layout.json`, GPSDOP/Fix, `track_map`, sensor fusion i optymalizacja GPU.

**ETAP 6D zakończony.**
