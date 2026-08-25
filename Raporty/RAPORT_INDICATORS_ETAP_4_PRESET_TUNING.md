# TeleM — ETAP 4: preset-only visual tuning `cycling_dashboard_v1`

Data: 2026-08-21  
Preset referencyjny: `presets/cycling_dashboard_v1.json`  
Preset wynikowy: `presets/cycling_dashboard_v2.json`

## Zakres i reguły

Wykonano wyłącznie tuning presetu. `cycling_dashboard_v1.json` nie został zmodyfikowany; SHA-256 przed i po pracy:

`099A36CE356E9EE0F5B5667D7504A246BAEE5AA4F59DD7CA7B81E3054DC09002`

Nie zmieniano rendererów, compositora, layout managera, telemetry/data flow, backend selection, AMD/NVIDIA ani encoderów. Kolejność wskaźników pozostała taka sama jak w v1.

Materiał kontrolny: `Video/GX030120.MP4`, `Video/Popoludniowa_jazda_na_rowerze_solar_battery.fit`, `Video/GX030120.json`; `video_time=60.0 s`, `activity_time=60.0 s`, frame 1799 (1-based), 3840×2160.

## Zmiany v1 → v2

| Wskaźnik | v1 | v2 | Cel korekty |
|---|---|---|---|
| `time_display` | x2/y2, font 2.0 | x2/y2, font 1.8 | bardziej kompaktowy blok w lewym górnym rogu |
| `dist_visual` | x50/y95, size34, label on | x50/y96.5, size30, label off | usunięcie kolizji etykiety i spokojniejszy dół kadru |
| battery | x87/y6.5, size15 | x88/y6.5, size12 | mniejszy, czytelny segmentowy wskaźnik |
| solar | x87/y18, size15 | x88/y17, size12 | zachowany jako opcjonalny widget; brak danych `solar` w FIT |
| `track_map` | x86/y38, size22 | x86/y38, size20 | więcej marginesu przy prawej krawędzi |
| ISO / shutter / temp | x23/32/41, size10, font1.8 | x22/30/38, size9, font1.4 | jeden równy, lżejszy rząd metadanych |
| `alt_visual` | x6/y52, size18, label on | x5.5/y52, size16, label off | wąski pionowy ruler bez dublowania opisu |
| virtual power | tekst x55/y7.5 | bar/ruler x56/y12, size18 | wykorzystanie istniejącego prymitywu bar/ruler, bez nowego renderera |
| cadence chart | x20/y84, size24, font1.4 | x24/y85, size27, font1.2 | szeroki dolny panel z większym odstępem od środka |
| speed gauge | x50/y60, size24 | x50/y53, size17.3 | centralny gauge dopasowany do układu v2 |
| heart-rate chart | x50/y84, size24, font1.4 | x59/y85, size27, font1.2 | para dolnych wykresów bez nachodzenia na gauge |

Wspólne strojenie: lżejsze fonty i ticki, globalny outline tekstu `1`, mniejsza bateria i mapa, zachowane granice zakresów oraz kolory statusowe.

## CPU reference — bbox i wartości

Poniżej bboxes z transparentnego overlayu, format `[x, y, width, height]`.

| Wskaźnik | v1 bbox | v2 bbox |
|---|---:|---:|
| `time_display` | `[77,43,392,215]` | `[77,43,314,171]` |
| `dist_visual` | `[1256,1973,1328,159]` | `[1335,2041,1170,86]` |
| battery | `[3049,65,584,151]` | `[3145,82,469,116]` |
| solar | brak bbox / brak danych | brak bbox / brak danych |
| `track_map` | `[2880,399,845,845]` | `[2918,437,768,768]` |
| ISO | `[883,162,162,40]` | `[845,162,119,26]` |
| shutter | `[1229,162,336,40]` | `[1152,162,253,26]` |
| temp | `[1574,162,262,40]` | `[1459,162,195,26]` |
| `alt_visual` | `[153,767,154,713]` | `[165,805,92,636]` |
| virtual power | `[2112,162,471,40]` | `[1794,210,713,99]` |
| cadence chart | `[303,1606,930,416]` | `[400,1609,1045,454]` |
| speed gauge | `[1299,675,1243,1243]` | `[1472,697,897,897]` |
| heart-rate chart | `[1455,1606,930,416]` | `[1744,1609,1045,454]` |

Wartości CPU w frame 1799: enhanced speed `17.60796`, cadence `59`, heart rate `102`, battery `77%`, virtual power `122 W`, solar `None`, ISO `152`, shutter `1/2399`, temperatura `30.7°C`.

Kontrola wizualna potwierdziła: brak clippingu głównych widgetów, brak nachodzenia chartów na centralny gauge, zachowane ticki/range labels oraz czytelność wartości na jasnym i ciemnym tle.

Artefakty:

- [CPU final frame](INDICATORS_ETAP_4_V2_FRAME.png)
- [CPU transparent overlay](INDICATORS_ETAP_4_V2_OVERLAY.png)

## AMD short probe

Uruchomiono krótki, 1-sekundowy eksport z segmentu `60.0 s` na tej samej rozdzielczości i z presetem v2. Artefakt:

- [AMD final frame](INDICATORS_ETAP_4_V2_AMD_FRAME.png)

Zarejestrowane ścieżki:

```text
AMD_MAP_PATH: GPU
AMD_MAP_ORDER: CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
AMD_CHART_PATH: GPU_SPLIT
AMD_GAUGE_PATH: GPU
AMD_TELEMETRY_MODE: PRECOMPUTED
GPU charts fallback -> CPU_REFERENCE (no active chart widgets)
GPU gauge fallback -> CPU_REFERENCE bbox=None (gauge not rendered)
```

Na obrazie AMD zachowana jest geometria v2, z-order i clipping głównych elementów. Różnice wartości chwilowych względem CPU (`125 W` vs `122 W`, `58 rpm` vs `59 rpm`, `17.5` vs `17.60796`) wynikają z krótkiego segmentu i innej chwili próbkowania; zegar aktywności w takim probe zaczyna od `00:00`. Nie zmieniano tego w ETAP4, ponieważ wymagałoby to ingerencji poza presetem.

`solar` nadal nie ma danych wejściowych w FIT (`solar_pct` jest innym polem); widget pozostawiono w v2 jako konfigurowalny, lecz nie wymuszano nowego mapowania źródła.

NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.

## Testy

Uruchomiono:

```text
python -m pytest -q tests/test_layout_manager.py tests/test_compositing_etap5e.py tests/test_gauge_rendering.py tests/test_bar_integration.py tests/test_chart_rendering.py tests/test_map_sync.py tests/test_amd_native_ordered_map.py tests/test_amd_native_ordered_map_clear.py tests/test_amd_native_above_dirty_bbox.py tests/test_amd_native_etap4.py tests/test_etap8m3_runtime_layout_and_parity.py tests/test_etap8n_multi_region_above.py
128 passed in 3.39s
```

Rewalidacja bieżącego stanu repozytorium 2026-08-21:

```text
129 passed in 4.02s
```

Sprawdzono również poprawność JSON v1/v2 oraz niezmienność SHA-256 v1. CPU render, overlay i AMD probe zakończyły się poprawnie.

## Ograniczenia i rekomendacja

Preset nie może samodzielnie naprawić różnicy parity mapy CPU/AMD, zmienić okna historii chartów, dodać prawdziwego źródła solar, ani zapewnić dedykowanej semantyki power bez zmian w kodzie. Wirtual power w v2 jest celowo zrealizowany istniejącym `bar/ruler`.

Największą wartość następnego pojedynczego etapu da **ETAP 5A — parity mapy CPU/AMD**: mapa zajmuje duży, ważny obszar dashboardu, a znana różnica wizualna nie może być rozwiązana samym presetem. Ten temat powinien pozostać osobnym zadaniem backend/rendering i nie należy go dopisywać do tuningu v2.
