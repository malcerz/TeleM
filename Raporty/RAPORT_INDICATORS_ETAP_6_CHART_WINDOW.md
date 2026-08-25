# TeleM — ETAP 6: konfigurowalne ruchome okno wykresów HR/Cadence

## 1. Zakres zmian

Dodano trzeci tryb historii wykresu: `chart_time_scope=window`. Implementacja korzysta z istniejących zsynchronizowanych próbek oraz istniejącego renderera `chart`; nie dodano nowej osi czasu, interpolatora ani renderera.

## 2. Nowa konfiguracja

```text
chart_time_scope=window
chart_window_s=60
```

`chart_window_s` jest normalizowane do zakresu 5–600 s. Wartość niepoprawna lub brakująca w trybie `window` daje bezpieczne 60 s.

## 3. Semantyka okna

Dla bieżącego czasu `t` renderer używa zakresu:

```text
[max(start_time, t - chart_window_s), min(end_time, t)]
```

Prawa krawędź i kursor oznaczają NOW. Próbki przyszłe nie trafiają do danych wykresu. Na początku aktywności zakres jest skracany do rzeczywistego początku, bez sztucznego powielania pierwszej próbki.

Oś X dla `window` jest względna, np. `-60 s, -45 s, -30 s, -15 s, 0 s`. Oś dla `activity` i `video` pozostała procentowa.

## 4. Kompatybilność `activity` / `video`

`activity` i `video` są zwracane bez zmiany dotychczasowej semantyki. Stare layouty bez `chart_window_s` nadal działają. Testy kompatybilności obu trybów przechodzą.

## 5. GUI

Dodano wybór:

```text
Cała aktywność
Zakres filmu
Ostatnie N sekund
```

Pole `Okno historii [s]` jest widoczne wyłącznie dla `window`, z zakresem 5–600 s i krokiem 1 s. Zmiana scope odświeża schemat właściwości i unieważnia właściwe cache renderowania.

## 6. Zmienione pliki

- `src/indicators/chart_builder.py` — normalizacja i ruchome przycinanie `ChartHistory`.
- `src/indicators/frame_data.py` — wspólne przygotowanie danych per klatka.
- `src/telemetry_precompute.py` — to samo przycinanie na ścieżce precomputed.
- `src/indicators/chart.py` — względne etykiety osi X.
- `src/gui/indicator_schemas.py`, `src/gui/qt/models.py` — schema i pola GUI.
- `src/gui/qt/_mixins/indicator_mixin.py`, `src/gui/qt/_mixins/preset_mixin.py` — odczyt/zapis i odświeżanie properties.
- `presets/cycling_dashboard_v3.json` — kopia v2 z wyłącznie dwoma wykresami przełączonymi na `window`, 60 s.
- `tests/test_etap6_chart_window.py` oraz rozszerzenie `tests/test_chart_rendering.py`.

Nie modyfikowano v1, v2 ani `def_layout.json`.

## 7. Nowe testy

Dodano testy dla:

- okna 60 s przy czasie 180 s,
- początku aktywności przy czasie 20 s,
- braku próbek przyszłych,
- zgodności `activity` i `video`,
- wartości niepoprawnych i granic 5–600 s,
- renderowania, bbox i kursora,
- wspólnej semantyki cadence/HR w przygotowaniu klatki.

## 8. Wyniki testów

Pełny zestaw testów ETAP 6 i istotnych regresji:

```text
144 passed in 7.52s
```

Obejmuje wymagane testy chart, clipping, fixed timeline, static assembly, runtime layout/parity, map parity, chart precompute/prefix, AMD oraz NVIDIA static regression.

`compileall` dla zmienionych modułów również zakończył się poprawnie.

## 9. Walidacja 20/60/180 s

Materiał: `Video/GX030120.MP4`, FIT `Popoludniowa_jazda_na_rowerze_solar_battery.fit`, JSON GPMF `Video/GX030120.json`.

| Czas filmu | Cadence | HR | Próbki | Future |
|---:|---|---|---:|---:|
| 20 s | 58 → 61 rpm | 101 → 102 BPM | 60 / 60 | 0 / 0 |
| 60 s | 64 → 59 rpm | 100 → 102 BPM | 60 / 60 | 0 / 0 |
| 180 s | 56 → 59 rpm | 102 → 103 BPM | 60 / 60 | 0 / 0 |

Dla 60 s przy czasie filmu 180 s zakres obu wykresów wynosił `04:48:25.700000`–`04:49:25.700000`, a cursor time był `04:49:25.700000`.

## 10. Cadence data window

Cadence przesuwa się razem z bieżącym czasem: 20 s → zakres ostatnich 60 s zakończony na 20 s, 60 s → zakres zakończony na 60 s, 180 s → zakres 120–180 s. Liczba próbek odpowiada długości okna, bez danych przyszłych.

## 11. HR data window

HR używa tego samego mechanizmu i tej samej osi czasu co cadence. Dla wszystkich trzech punktów kontrolnych liczba próbek i prawa krawędź są zgodne z cadence.

## 12. CPU preview

Wygenerowano i sprawdzono:

- [INDICATORS_ETAP_6_CHART_WINDOW_FRAME.png](INDICATORS_ETAP_6_CHART_WINDOW_FRAME.png)
- [INDICATORS_ETAP_6_CHART_WINDOW_OVERLAY.png](INDICATORS_ETAP_6_CHART_WINDOW_OVERLAY.png)

Artefakt finalnej klatki ma rozmiar 3840×2160. Wizualnie potwierdzono oś `-60 s ... 0 s`, wykresy cadence/HR, cursor na NOW oraz brak wyjścia poza bbox.

## 13. AMD final

Krótki probe AMD native zakończył się sukcesem: 60 klatek 1280×720, AMF i D3D11VA uruchomione. Log potwierdził:

```text
AMD_MAP_PATH: GPU
AMD_MAP_ORDER: CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
AMD_CHART_PATH: GPU_SPLIT
AMD_TELEMETRY_MODE: PRECOMPUTED
AMD_ETAP6_PROBE_OK=True
```

Probe ujawnił istniejące ograniczenie ścieżki split map: ponieważ wykresy v3 znajdują się po mapie, runtime guard raportuje `GPU charts fallback -> CPU_REFERENCE (no active chart widgets)`, a precompute eksportera otrzymuje layout części `below-map` bez tych wykresów. W rezultacie domyślny eksport AMD z GPU mapą nie potwierdza jeszcze względnych etykiet osi dla tych dwóch chartów — pozostaje przy dotychczasowej osi procentowej. Nie przebudowywano AMD backendu, zgodnie z zakresem ETAP 6 i instrukcją, aby przy konieczności specjalnej zmiany backendu zatrzymać się i opisać problem.

Wspólne CPU/precomputed przygotowanie danych oraz wartości telemetryczne są objęte testami; pełna parity wizualna AMD dla układu `GPU map + charts after map` wymaga osobnego zadania integracyjnego w eksporterze.

## 14. NVIDIA static analysis

Nie zmieniano ścieżki CUDA/NVENC ani modułów NVIDIA. Wspólne dane chart są przygotowywane przed backendem. `tests/test_nvidia_regression_chart_preview.py` przechodzi.

NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.

## 15. Performance comparison

Orientacyjny pomiar jednej klatki 3840×2160 na CPU, oba wykresy razem:

| Scope | Próbki cadence/HR | Chart data build | Frame preparation | Raster obu chartów |
|---|---:|---:|---:|---:|
| activity | 1741 / 1754 | 0.72 ms | 7.43 ms | 19.10 ms |
| window 60 s | 60 / 60 | 0.79 ms | 10.44 ms | 13.99 ms |

Pojedynczy pomiar jest orientacyjny, ale nie wykazał regresji rasteryzacji; krótsze historie zmniejszają liczbę danych z około 1.7k do 60 próbek na wykres.

## 16. Preset v3

Utworzono `presets/cycling_dashboard_v3.json` na bazie v2. Zmieniono tylko:

```text
fit_cadence_text.chart_time_scope = window
fit_cadence_text.chart_window_s = 60
fit_heart_rate_text.chart_time_scope = window
fit_heart_rate_text.chart_window_s = 60
```

Porównanie 30/60/120 s wykonano na tej samej klatce 60 s w 3840×2160. 30 s było zbyt ciasne, 120 s zbyt płaskie; 60 s wybrano jako najlepszy kompromis i zgodnie z regułą domyślną.

## 17. Pozostałe różnice względem targetu

CPU preview/final oraz wspólna ścieżka precomputed spełniają semantykę ruchomego okna. Pozostaje ograniczenie istniejącego AMD split-map layoutu opisane w sekcji 13; jego naprawa wymagałaby zmiany `src/ffmpeg/amd_native_exporter.py`, czego ETAP 6 zabrania.

W repozytorium były już niezależne, niepowiązane zmiany w plikach AMD, command builder i moving map; nie zostały cofnięte ani rozszerzone przez ETAP 6. `tests/test_map_first_render_parity.py` nadal przechodzi.
