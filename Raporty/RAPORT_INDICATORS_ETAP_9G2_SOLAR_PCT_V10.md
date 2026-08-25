# TeleM — ETAP 9G2: integracja `solar_pct` — v10

## 1. Confirmed field

`EXACT SOLAR FIELD NAME: solar_pct`.

FIT metadata: developer data index `2`, record field `0`, `uint8`, units `%`, scale `1`, offset `0`, range `0..100`, `2340` samples. Pole `solar` pozostaje odrębne i nietknięte.

## 2. Integration path

Generic path działa bez specjalnego kodu Solar:

```text
FIT parser → FitDataset.available_fit_fields / field_catalog
           → fit_data["solar_pct"]
           → generic fit_{field}_text key
           → resolver(source="fit")
           → frame_data / precompute
           → istniejący segment bar + icon="solar"
```

## 3. Parser changes

Brak zmian w `telemetry_fit.py`. Parser zachowuje nazwę developer field `solar_pct`.

## 4. Resolver changes

Brak zmian w resolverze. Lookup `solar_pct` działa przez istniejącą ścieżkę dokładnej nazwy FIT, bez aliasowania do `solar`.

## 5. Sampling cadence

`solar_pct` ma `2340` próbek. Mediana odstępu wynosi `1.0 s`; występuje również pojedyncza większa luka `254 s`.

## 6. STEP/hold semantics

Użyto istniejącej semantyki `interpolate_value`: STEP / hold-last. Nie ma interpolacji liniowej procentu.

## 7. Zero vs missing

`0%` pozostaje wartością `0.0`. Pusty stream albo brak próbki zwraca `None`; test ochronny potwierdza rozróżnienie.

## 8. Values 60/180/300 s

Zastosowano znany sync `+2.000 s`: video start odpowiada FIT `11:18:01 + 2 s = 11:18:03`.

| video time | FIT raw time | raw `solar_pct` | resolved | displayed |
|---:|---|---:|---:|---:|
| 60 s | 2026-08-14 11:19:01 | 100 | 100 | 100% |
| 180 s | 2026-08-14 11:21:01 | 100 | 100 | 100% |
| 300 s | 2026-08-14 11:23:01 | 100 | 100 | 100% |

Nie wykonywano ponownie SmartSync.

## 9. `solar_pct` vs `solar`

W punkcie kontrolnym wartości są rozdzielone przez resolver; test wymusza timestamp, dla którego `solar_pct != solar`. Pola mają różne developer indexes i różną liczbę próbek (`2340` vs `4299`), więc nie są aliasami.

## 10. CPU/frame_data/precompute parity

Dla kontrolnego timestampu `frame_data`, bezpośredni resolver i `build_telemetry_cache().lookup()` zwracają identycznie `100.0`, z tą samą regułą STEP.

## 11. v9 → v10

Utworzono `presets/cycling_dashboard_v10.json` bezpośrednio z v9. W v10:

- widget zmieniono na `fit_solar_pct_text`;
- dodano jawne `field: "solar_pct"`;
- `source: "fit"`;
- `unit: "%"`;
- `min_val: 0`, `max_val: 100`;
- `icon: "solar"` zachowane;
- segment bar i pozycja zachowane.

v9 nie został zmieniony.

## 12. Real render

CPU reference 3840×2160, około 300 s, zapisano jako [INDICATORS_ETAP_9G2_SOLAR_PCT_V10.png](INDICATORS_ETAP_9G2_SOLAR_PCT_V10.png). Klatka pokazuje `100 %` w istniejącym Solar segment barze z ikoną Solar.

## 13. Tests

Nowe `tests/test_solar_pct.py`: `6 passed`.

Targetowane testy łącznie: `32 passed`, obejmując Solar, katalog FIT, precompute, segment bar i ikony. Pełnego suite nie uruchamiano. Osobna próba legacy `tests/test_fit_registration.py` zatrzymała się podczas collection z powodu brakującego `src.gui.hud_tuner_app`; nie jest to regresja ETAPU 9G2.

## 14. Performance

- FIT parse + extraction: `1669.640 ms` dla całego pliku;
- resolver lookup `solar_pct`: `0.173 ms` średnio / 1000 lookupów;
- precompute build dla jednego frame: `3.921 ms`;
- precomputed value: `100.0`.

## 15. Changed files

- `presets/cycling_dashboard_v10.json`;
- `tests/test_solar_pct.py`;
- niniejszy raport;
- `Raporty/INDICATORS_ETAP_9G2_SOLAR_PCT_V10.png`.

## 16. Preserved paths

Nie zmieniano parsera FIT, resolvera, precompute production logic, `src/indicators/*`, rendererów, AMD/NVIDIA/CUDA/NVENC/AMF/D3D11, Track-Up, mapy, ikon, fontów ani presetów v1–v9. Lean pozostaje `DEFERRED — IMU NOT RELIABLE`. Font pozostaje `POSTPONED`. Nie wykonywano AMD smoke ani SmartSync.

## 17. Final decision

```text
SOLAR_PCT: INTEGRATED
```
