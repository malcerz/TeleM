# TeleM — ETAP 3: wizualny baseline `cycling_dashboard_v1`

Data: 2026-08-21  
Rozdzielczość: 3840×2160  
Preset: `presets/cycling_dashboard_v1.json`  
Materiał: `Video/GX030120.MP4` + `Video/Popoludniowa_jazda_na_rowerze_solar_battery.fit` + `Video/GX030120.json`

## Zakres i wynik

Wykonano wyłącznie baseline wizualny istniejącego presetu. Nie zmieniano presetu, compositorów, rendererów, resolvera telemetrycznego, synchronizacji ani żadnego pipeline’u AMD/NVIDIA/CPU.

Artefakty:

- [INDICATORS_ETAP_3_BASELINE_FRAME.png](INDICATORS_ETAP_3_BASELINE_FRAME.png) — pełna klatka CPU reference: wideo + HUD.
- [INDICATORS_ETAP_3_BASELINE_OVERLAY.png](INDICATORS_ETAP_3_BASELINE_OVERLAY.png) — sam transparentny HUD RGBA.
- [INDICATORS_ETAP_3_AMD_FRAME.png](INDICATORS_ETAP_3_AMD_FRAME.png) — klatka z krótkiego renderu `AMD_NATIVE_D3D11`.

## Wybrana klatka i dane

Wybrano reprezentatywny punkt 60,0 s od początku materiału, po wymaganych kilkudziesięciu sekundach. W tym punkcie są dostępne prędkość, kadencja, HR, pozycja GPS, wysokość i dystans.

| Pole | Wartość |
|---|---:|
| video_time | 60,0 s |
| activity_time | 60,0 s |
| frame_number | 1799 (1-based; 1798 0-based) |
| FPS | 29,97 |
| target timestamp | `2026-08-18 04:47:25.700 UTC` |
| enhanced_speed | 17,6 km/h |
| cadence | 59 rpm |
| heart_rate | 102 BPM |
| battery_pct | 77% |
| curVpower | 122 W |
| GPMF ISO / shutter / temperature | 152 / 1/2399 / 30,7°C |

FIT zawiera `solar_pct`, ale nie zawiera pola `solar`; dlatego `fit_solar_text` pozostał w layoucie aktywny, lecz nie został wyrenderowany i nie ma bboxa. Nie zastępowano Solar Power przez Solar Percentage.

## Czas generowania i diagnostyka

| Operacja | Wynik |
|---|---:|
| przygotowanie danych jednej klatki | 6,1 ms |
| CPU pełna klatka | 444,3 ms |
| CPU transparentny HUD | 35,1 ms |
| rozmiar pełnej klatki | 3840×2160 |
| rozmiar overlayu | 3840×2160, RGBA |

CPU użył wspólnego `prepare_overlay_frame_data()` + `render_preview()` / `compose_overlay()` z istniejącą ścieżką CPU reference. Oba PNG zostały obejrzane wizualnie.

## Geometria aktywnych elementów

Bbox zapisano jako `(x, y, width, height)` w pikselach dla 3840×2160. Z-order zachowuje specjalny pierwszy render `time_display`, a następnie kolejność wpisów presetu.

| Z | id | form | x / y / size / rot. | effective bbox px | Ocena wizualna | Klasa |
|---:|---|---|---|---|---|---|
| 1 | `time_display` | time_display | 2 / 2 / 0,1 / 0° | 77, 43, 392, 215 | Czytelne cztery linie i dobra hierarchia koloru; label/value są jednak bardzo zwarte i mocno obrysowane. | P |
| 2 | `dist_visual` | bar/ruler | 50 / 95 / 34 / 0° | 1256, 1973, 1328, 159 | Ruler ma cienką linię, 5 głównych podziałów, zakres 0–1 km i marker około 0,2 km; wartość i label są małe względem 4K. | P |
| 3 | `fit_battery_pct_text` | bar/segments | 87 / 6,5 / 15 / 0° | 3049, 65, 584, 151 | 20 segmentów i `77 %` są widoczne; bar jest funkcjonalny, ale podpis jest optycznie odłączony od segmentów. | P |
| 4 | `fit_solar_text` | bar/segments | 87 / 18 / 15 / 0° | brak — brak pola `solar` | Element nie pojawia się zgodnie z bindingiem danych; to nie jest błąd geometrii. | D |
| 5 | `track_map` | map | 86 / 38 / 22 / 0° | 2880, 399, 845, 845 | Kwadratowa mapa north-up z trasą i markerem; CPU baseline ma ciemny/niepełny obszar kafli, AMD pokazuje pełny jasny kafel. | R; P dla rozmiaru/opacity |
| 6 | `iso_text` | text | 23 / 7,5 / 10 / 0° | 883, 162, 162, 40 | Tekst `ISO: 152` jest czytelny, bez osobnej ikony i z dużym outline. | P; N dla ikon |
| 7 | `exposure_text` | text | 32 / 7,5 / 10 / 0° | 1229, 162, 336, 40 | `SHUTTER: 1/2399` jest czytelny, ale długi i blisko sąsiedniego pola. | P; N dla ikon |
| 8 | `temp_text` | text | 41 / 7,5 / 10 / 0° | 1574, 162, 262, 40 | Temperatura i jednostka są czytelne; odstępy górnego pasa są równomierne, lecz pas jest ciężki od outline. | P |
| 9 | `alt_visual` | bar/ruler | 6 / 52 / 18 / 90° | 153, 767, 154, 713 | Pionowa orientacja działa, są ticki, zakresy i marker; label `ALTITUDE | M` jest obrócony i zajmuje dużo miejsca. | P |
| 10 | `fit_curVpower_text` | text | 55 / 7,5 / 10 / 0° | 2112, 162, 471, 40 | `VIRTUAL POWER: 122 W` jest dobrym placeholderem tekstowym, ale nie ma poziomej skali. | P; N dla nowej skali |
| 11 | `fit_cadence_text` | chart | 20 / 84 / 24 / 0° | 303, 1606, 930, 416 | Wykres jest niski, ma grid, zakres 0–200, linię/fill i historię activity; oś X pokazuje procenty, nie czas. | P; R dla `window_s` |
| 12 | `fit_enhanced_speed_text` | gauge | 50 / 60 / 24 / 0° | 1299, 675, 1243, 1243 | Okrąg 360°, ticki/subticki, etykiety, marker, needle i `17,6 km/h` działają; środek i dolna część konkurują wizualnie z wykresami. | P |
| 13 | `fit_heart_rate_text` | chart | 50 / 84 / 24 / 0° | 1455, 1606, 930, 416 | Wykres ma fill, linię, grid, zakres 40–220 i average; również używa pełnej historii activity i procentowej osi X. | P; R dla `window_s` |

## Klasyfikacja różnic i wymagane przyszłe zmiany

Legenda: `P` — preset/layout only; `R` — renderer/backend; `D` — data/binding; `N` — nowa funkcja.

| Element / różnica | Klasa | Co byłoby potrzebne | Plik / obszar do osobnego zadania |
|---|---|---|---|
| Rozmiar, font, outline, odstępy, gęstość top pasa i pozycje | P | Dostrajać wyłącznie konfigurację presetu po zatwierdzeniu kierunku wizualnego. | `presets/cycling_dashboard_v1.json` |
| Mapa CPU vs AMD: CPU ma ciemny/niepełny obraz kafli, AMD jasny pełny kafel | R | Osobna analiza parity mapy CPU/GPU; nie zmieniano guardów ani uploadu w ETAPIE 3. | `src/indicators/moving_map.py`, `src/indicators/static_map.py`, AMD ordered-map path |
| Solar Power | D | Dostarczyć rzeczywiste pole `solar` w źródle/resolverze albo zatwierdzić inne znaczenie. `solar_pct` nie jest zamiennikiem mocy. | FIT/data binding; bez zmian w tym etapie |
| Historia chartów jest pełną aktywnością, bez arbitralnego okna sekundowego | R | Dodać jawny `window_s`, zachowując `activity`/`video` jako kompatybilne tryby. | `src/indicators/chart_builder.py`, `src/indicators/chart.py` |
| Brak ikon ISO/Shutter/Temp | N | Dodać assety lub renderer ikon oraz test parity CPU/preview/final. | lokalne rozszerzenie `src/indicators/` |
| Power ma tylko tekst, brak poziomego ruler/bar | P / N | Najpierw ustalić, czy wystarczy konfiguracja istniejącego `bar`, czy wymagany jest nowy wariant skali. | preset; ewentualnie lokalnie `src/indicators/bar.py` |
| Compass, bike/lean i slope nie są aktywne | N / D | Compass i lean wymagają geometrii/semantyki; slope i heading wymagają zatwierdzonego źródła danych. | osobne zadania gauge/data binding/indicator |
| Track-up / orientacja mapy | N / R | Dodać semantykę track-up dopiero z poprawnym headingiem i testem z-order. | `src/indicators/moving_map.py` + resolver, osobne zadanie |

Najważniejsze pięć obserwacji wizualnych:

1. Układ ma już pełną, czytelną strukturę dashboardu: top telemetry, bateria, mapa, pionowa wysokość, centralny gauge oraz dwa wykresy.
2. CPU i AMD nie są jeszcze pixel-parity dla mapy: CPU baseline ma niepełny/ciemny obszar kafli, podczas gdy AMD pokazuje jasną mapę z trasą i markerem.
3. Wykresy są obecne i mają dane, ale są niskie w stosunku do 4K, używają pełnej historii activity i pokazują procentową oś X zamiast jawnego okna czasu.
4. Centralny speedometer jest funkcjonalny jako 360° gauge, lecz duży pusty środek i bliskość dolnych wykresów ograniczają hierarchię wizualną.
5. Solar Power jest jedynym wymaganym aktywnym elementem niewidocznym z powodu braku pola `solar`; nie należy maskować tego przez użycie `solar_pct`.

## AMD short render

Wykonano 30 klatek z 1-sekundowego segmentu wyciętego z tego samego materiału w punkcie 60 s, w `AMD_NATIVE_D3D11`, 3840×2160. Zapisano [INDICATORS_ETAP_3_AMD_FRAME.png](INDICATORS_ETAP_3_AMD_FRAME.png) i obejrzano ją wizualnie.

Wybrane logi:

```text
AMD_MAP_PATH: GPU
AMD_CHART_PATH: GPU_SPLIT
AMD_GAUGE_PATH: GPU
AMD_TELEMETRY_MODE: PRECOMPUTED
AMD_MAP_ORDER: CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
GPU charts fallback -> CPU_REFERENCE (no active chart widgets)
GPU gauge fallback -> CPU_REFERENCE bbox=None (gauge not rendered)
```

Eksport zakończył się sukcesem: 30 klatek, audio obecne, ścieżka dekodowania `GPU_HUD_D3D11VA`, encoder AMF HEVC. Render AMD ma zgodną geometrię, z-order i wartości bieżące, ale segment 1 s zaczyna licznik `Activity` od zera; dlatego tę różnicę traktuję jako ograniczenie krótkiego probe’a, nie jako zmianę layoutu. Runtime AMD zostało wykonane; NVIDIA nie było dostępne.

## Testy

Uruchomiono 109 testów obejmujących compositor, gauge, bar/segments, chart, map sync, AMD ordered-map/dirty bbox, runtime layout/parity, multi-region above oraz NVIDIA map bounds:

```text
109 passed in 3.36s
```

W tym etapie nie modyfikowano kodu aplikacji, więc nie wykonywano pełnej regresji wszystkich 170 testów z ETAPU 2. JSON presetu został odczytany i użyty bez zmian.

## Zachowane ścieżki i ograniczenia walidacji

- CPU_REFERENCE i wspólny compositor pozostały bez zmian.
- AMD `AMD_NATIVE_D3D11`, AMF, D3D11VA, guardy map/chart/gauge i diagnostyka pozostały bez zmian.
- Ścieżka NVIDIA nie była modyfikowana ani uruchamiana runtime.
- Nie zmieniano decoder/encoder selection, FFmpeg, NVENC/CUDA, pixel formats, SmartSync, resolvera ani źródeł FIT/GPMF/GPX.

**NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.**

Ryzyko pozostałe po baseline: różnica CPU/GPU w mapie i istniejące CPU fallbacki chart/gauge wymagają osobnego zadania parity/backend, jeśli celem ma być identyczny obraz na każdej ścieżce. ETAP 3 nie zmieniał tych obszarów.
