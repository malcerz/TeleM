# ETAP 6C — RESULT

Data audytu: 2026-08-18  
Materiał: `Video/GX030120.MP4`  
FIT: `Video/Poranna_jazda_na_rowerze.fit`  
Tryb: wyłącznie read-only/runtime validation; brak zmian implementacyjnych w ETAPIE 6C.

## Wynik ogólny

**PARTIAL / NOT PASS**.

Wartości bieżące są zgodne między wspólnym przygotowaniem frame data, PRECOMPUTED i workerem. Potwierdzono również rzeczywisty eksport AMD Native D3D11. Nie można jednak zamknąć ETAPU 6C jako PASS, ponieważ chart history nie jest ograniczane do `target_dt`: dla punktu 14,3 s zawiera pełne 1672 próbki FIT i kończy się wartością z końca pliku. Ponadto bieżący `def_layout.json` nie zawiera aktywnych pól ACCL/GYRO; ich parity potwierdzono po aktywacji schematu w pamięci.

## A–B. Materiał i ścieżki danych

Anchor UTC GPMF: `2026-08-18 04:46:25.700000+00:00`.  
Wideo: 180,180 s, 5395 klatek, 3840×2160, 30000/1001 fps.

Liczności użyte w runtime:

| źródło | liczba |
|---|---:|
| GPMF speed | 1802 |
| GPMF ISO | 5400 |
| GPMF ACCL vectors | 35802 |
| GPMF GYRO vectors | 35802 |
| FIT heart rate | 1672 |
| FIT cadence | 1672 |

Wspólna ścieżka przygotowania jest używana przez preview i final worker: `prepare_overlay_frame_data`. PRECOMPUTED oraz worker korzystają z jawnego source resolvera.

## C–E. Źródła, wartości i czas

Dla UTC `2026-08-18 04:46:40` (14,3 s) otrzymano:

| pole | source | wartość |
|---|---|---:|
| speed | GPMF | 18.252 km/h |
| heart rate | FIT | 102 BPM |
| cadence | FIT | 63 rpm |
| temperature | GPMF | 30.419921875 °C |
| ISO | GPMF | 70 |
| exposure | GPMF | 431 |
| accel_x | GPMF | 1.2517985611510791 m/s |
| gyro_x | GPMF | 0.2364217252396166 rad/s |

ACCL/GYRO używają timestampów GPMF, a nie syntetycznego zegara GPS. Dla aktywowanych runtime pól zachowano floaty i prawdziwe zero. Magnitude jest liczona z tej samej próbki trzech osi.

Punkty PTS nominalnie wybrane dla CFR:

| video_s | frame | actual PTS s | różnica |
|---:|---:|---:|---:|
| 0 | 0 | 0.000000 | 0,0 ms |
| 14,3 | 429 | 14.314300 | +14,3 ms |
| 60 | 1798 | 59.993267 | −6,7 ms |
| 120 | 3596 | 119.986533 | −13,5 ms |
| 175 | 5245 | 175.008167 | +8,2 ms |
| end | 5395 | 180.013167 | +13,2 ms |

## F–G. Preview / CPU / PRECOMPUTED / worker

Dla punktu 14,3 s wartości `speed`, `ISO`, `exposure`, `temperature`, FIT HR/CAD oraz aktywowane ACCL/GYRO były identyczne w managerze, preview, PRECOMPUTED i workerze — różnica numeryczna 0.

Po aktywacji w pamięci pól:

```text
accel_x, accel_y, accel_z, accel_magnitude
gyro_x, gyro_y, gyro_z, gyro_magnitude
```

otrzymano parity `True` między manager → preview → PRECOMPUTED → worker. Bieżący `def_layout.json` nie ma tych ośmiu aktywnych entries, więc na konfiguracji pliku pola nie są rysowane i zwracają `None`; nie jest to silent fallback.

## H. Geometria

CPU `compose_overlay` i preview na wspólnym canvasie 960×540 zwróciły identyczne bboxy:

| element | bbox |
|---|---|
| temp_text | (16, 267, 58, 12) |
| fit_cadence_text | (43, 393, 296, 137) |
| fit_heart_rate_text | (616, 394, 296, 137) |
| fit_enhanced_speed_text | (386, 408, 163, 163) |
| track_map | (759, 34, 173, 173) |

W finalnej skali 3840×2160 AMD raportował gauge `(1544,1632,648,648)`, czyli zgodnie z przeskalowaniem bboxu 960×540. `temp_text` nie wykazuje clippingu.

## I. Chart/history — znaleziony problem

Dla `fit_cadence_text` i `fit_heart_rate_text` `chart_data` ma zawsze 1672 próbki, niezależnie od `target_dt`. Dla 14,3 s:

```text
current_position = 0.07953281423804227
chart length = 1672
chart endpoint = cadence 67.0, heart rate 107.0
```

Endpoint nie odpowiada bieżącemu `target_dt`; pochodzi z końca FIT. Jest to naruszenie wymogu ETAPU 6C, aby current value i chart history używały tej samej osi czasu i kończyły się na bieżącym punkcie. Wymaga osobnego ETAPU naprawczego; w 6C nie zmieniano kodu.

## J. Dynamic FIT i source contract

- Pole obecne w bieżącym FIT (`fit_heart_rate_text`, `fit_cadence_text`, `fit_enhanced_speed_text`) działa i nie fallbackuje do GPMF.
- Pole skonfigurowane, ale nieobecne (`fit_battery_text`) daje `(None, unit, label)`.
- `source=FIT` przy braku FIT nie przełącza się na GPMF.
- Realne `0.0` pozostaje `0.0`, a brak danych pozostaje `None`.
- Zachowanie dla brakującego źródła, realnego zera i dynamic FIT potwierdza `tests/test_etap6b_contract.py`.

## K. AMD Native / GPU

Wykonano rzeczywisty krótki eksport 6 klatek z `GX030120.MP4`:

```text
AMD_NATIVE_D3D11 = SUCCESS
GPU_HUD = active
GPU_HUD_D3D11VA = active
AMD_TELEMETRY_MODE = PRECOMPUTED
AMD_CHART_PATH = GPU_SPLIT
AMD_GAUGE_PATH = GPU
AMF HEVC encode = success
HW decode proof = YES
AMF output = 6
dropped = 0
```

Mapa została runtime’owo zdegradowana do `CPU_REFERENCE`, ponieważ przy aktualnym z-order `track_map` nie jest ostatnim wskaźnikiem. Jest to jawny fallback ochrony kolejności renderowania, nie silent fallback danych.

## L. Preview vs final render

Wspólne CPU preview/final data oraz bboxy są zgodne. AMD Native wykonał pełną ścieżkę decode → telemetry/precomputed → HUD/GPU chart/gauge → VP → AMF, ale z powodu znalezionego problemu chart endpointu oraz braku aktywnych IMU entries w realnym `def_layout.json` nie deklaruję pełnego end-to-end PASS dla wszystkich wymaganych pól.

## M. Regresja i testy

Uruchomiono:

```text
tests/test_etap6b_contract.py tests/test_telemetry_manager.py
36 passed
```

Stan pełnej suite odziedziczony po ETAPIE 6B: `316 passed, 3 failed, 17 skipped`. Trzy failure’y są wcześniejsze i niezwiązane: `test_amd_native_etap4.py`, `test_qp_analyzer.py`, `test_render_tab.py`. W ETAPIE 6C nie modyfikowano testów ani implementacji.

## N. Performance

Jednoramkowy pomiar CPU 960×540:

```text
compose_overlay: około 226 ms
preview: około 22 ms
```

AMD Native 6-klatkowy probe: wall-clock około 12,61 s, z czego audio mux był dominującym kosztem około 9,56 s. Cache PRECOMPUTED AMD: 6 klatek, około 72,2 ms, około 0,002 MiB.

## O. Status końcowy

### CONFIRMED

- current values są zgodne preview/CPU/PRECOMPUTED/worker;
- ACCL/GYRO parity działa po aktywacji pól;
- source contract, `None` i realne zero są zachowane;
- AMD Native GPU runtime działa na realnym materiale;
- CPU preview/final geometry jest zgodna.

### SUSPECTED / TO FIX IN FOLLOW-UP

- chart history nie jest przycinane do `target_dt`, więc chart endpoint nie reprezentuje bieżącej próbki;
- realny `def_layout.json` nie eksponuje aktywnych pól ACCL/GYRO, mimo że model i runtime je obsługują.

### OUT OF SCOPE

Naprawa chart history, zmiana layoutu produkcyjnego, sensor fusion, orientacja 3D, GPU optimization oraz wcześniejsze niezwiązane test failures.

**ETAP 6C zatrzymany zgodnie z zakresem.**
