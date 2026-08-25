# TeleM — ETAP 2: pierwsza wersja docelowego presetu dashboardu

Data: 2026-08-21  
Zakres: wyłącznie konfiguracja osobnego presetu i walidacja istniejących ścieżek.  
Renderery, telemetry resolver, synchronizacja, AMD/NVIDIA pipeline i `def_layout.json`: bez zmian.

## 1. Utworzony preset

Plik:

`presets/cycling_dashboard_v1.json`

Preset jest layoutem JSON dla rozdzielczości referencyjnej `3840×2160`. Nie zastępuje `def_layout.json` i nie jest automatycznie aktywowany przy starcie. Można go wczytać przez istniejące GUI „Wczytaj preset” albo wskazać jako preset startowy w istniejącym mechanizmie ustawień.

Każdy element pozostaje konfigurowalny przez istniejący layout: ma `enabled`, `x`, `y`, `size`, `rotation`, `form` oraz pola stylu właściwe dla danego renderera.

## 2. Elementy wykorzystane w presecie

| Element | Klucz | Forma | Źródło / dane |
|---|---|---|---|
| Time block | `time_display` | `time_display` | data i czas z istniejącego GPMF; elapsed i average speed z `frame_data.py` |
| Distance Progress | `dist_visual` | `bar`, `bar_style=ruler` | GPMF `track_samples`, dystans bieżący i dynamiczny max z istniejącego compositora |
| Garmin Edge Battery | `fit_battery_pct_text` | `bar`, `bar_style=segments` | FIT `battery_pct`, zakres 0–100, wartość tekstowa w segmencie |
| Garmin Solar Power | `fit_solar_text` | `bar`, `bar_style=segments` | FIT `solar` w W; nie używa `solar_pct` |
| Dynamic Map | `track_map` | `map` | FIT GPS track z aktualnym markerem; north-up |
| ISO | `iso_text` | `text` | GPMF `iso` |
| Shutter | `exposure_text` | `text` | GPMF `exposure`, formatowanie istniejące `1/{value}` |
| Temperature | `temp_text` | `text` | GPMF `temperature`, °C |
| Altitude | `alt_visual` | `bar`, `bar_style=ruler`, rotation 90° | GPMF `altitude`, dynamiczny min/max |
| Power / Virtual Power | `fit_curVpower_text` | `text` | FIT `curVpower`, W; bez obliczania w rendererze |
| Cadence Chart | `fit_cadence_text` | `chart` | FIT `cadence`, `chart_time_scope=activity` |
| Speedometer | `fit_enhanced_speed_text` | `gauge` | FIT `enhanced_speed`, `sweep_angle=360` |
| Heart Rate Chart | `fit_heart_rate_text` | `chart` | FIT `heart_rate`, `chart_time_scope=activity` |

Celowo nie dodano `compass`, `bike/lean`, `slope` ani track-up mapy.

## 3. Rozmieszczenie

- `time_display` znajduje się w lewym górnym rogu.
- ISO, shutter, temperatura i virtual power tworzą górny pas informacyjny.
- Battery i Solar są w prawym górnym obszarze.
- Mapa north-up znajduje się po prawej stronie, odseparowana od wykresów i gauge.
- Altitude jest pionowym rulerem po lewej stronie.
- Speedometer jest centralnym, pełnym 360° gauge.
- Cadence i Heart Rate są rozdzielonymi wykresami w dolnej połowie.
- Distance Progress jest na dole, centralnie.

Pozycje są zapisane procentowo w JSON, nie wewnątrz rendererów.

## 4. Odwzorowane elementy i różnice względem referencji

### Działające w pierwszej wersji

- wieloliniowy blok czasu z datą, czasem, activity time i average speed;
- distance ruler z bieżącą wartością, skalą i zakresem;
- segmentowy battery bar z `battery_pct` i tekstem procentowym;
- north-up dynamic map z trasą i markerem;
- ISO, shutter i temperatura;
- pionowy altitude ruler;
- virtual power z FIT `curVpower`;
- cadence i heart-rate charts z istniejącym zakresem `activity`;
- pełny okrągły wariant istniejącego gauge prędkości.

### Różnice pozostawione celowo

- Nie ma compass, bike/lean ani slope.
- Mapa pozostaje north-up; nie dodawano track-up.
- W istniejących plikach FIT występuje `solar_pct`, ale nie znaleziono pola `solar` oznaczającego moc. Preset nie podmienia Solar Power na Solar Percentage. W rezultacie `fit_solar_text` jest ukryty, gdy źródło nie dostarcza `solar`.
- Wykresy używają pełnej historii `activity`, bez nowego `window_s`.
- Wygląd jest przybliżeniem referencji z istniejących rendererów; nie zmieniano ich dla pixel-perfect podobieństwa.

## 5. Preview

### GUI preview

Uruchomiono kontroler GUI w trybie offscreen z:

- `Video/GX030120.MP4`,
- `Video/Popoludniowa_jazda_na_rowerze_solar_battery.fit`,
- `presets/cycling_dashboard_v1.json` jako `_startup_preset` tylko w pamięci testu.

Wynik:

- preset został załadowany;
- GUI zgłosiło `gui_preview_ready`;
- aktywnych było 13 wpisów presetu;
- `last_src_pil=True`, czyli ścieżka preview wykonała render obrazu.

Klatka preview została również wyrenderowana bezpośrednio przez wspólną funkcję `render_preview()` w 3840×2160. Widoczne były: battery segments, mapa, altitude, gauge, oba wykresy, distance, time display oraz teksty kamery. Solar Power pozostał niewidoczny, zgodnie z brakiem pola FIT `solar`.

## 6. CPU reference

CPU reference została sprawdzona przez `render_preview()` na danych FIT/GPMF. Obraz zawierał poprawne elementy i zachował kolejność:

```text
time_display
→ elementy poniżej mapy
→ track_map
→ elementy powyżej mapy
```

Nie zmieniano `compose_overlay()`, `rotated_paste()` ani żadnej semantyki CPU.

## 7. Final AMD

Uruchomiono krótki, 1-sekundowy probe finalnego eksportu na rzeczywistym materiale:

- wejście: `Video/GX020079.mp4`;
- dane: `Video/Morning_Ride.fit` i istniejące `GX020079.json`;
- format: 3840×2160, 30 klatek;
- ścieżka: `AMD_NATIVE_D3D11`;
- wynik: eksport zakończony sukcesem, 30 klatek i obecne audio.

Log wybrał:

```text
AMD_MAP_PATH: GPU
AMD_CHART_PATH: GPU_SPLIT
AMD_GAUGE_PATH: GPU
AMD_TELEMETRY_MODE: PRECOMPUTED
AMD_MAP_ORDER: CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
```

Podczas renderowania guardy zachowały poprawność obrazu:

```text
GPU charts fallback -> CPU_REFERENCE (no active chart widgets)
GPU gauge fallback -> CPU_REFERENCE bbox=None (gauge not rendered)
```

To nie jest błąd do naprawiania w ETAPIE 2. Guardów nie usuwano ani nie wymuszano GPU. Mapa użyła ścieżki GPU, a chart/gauge zachowały CPU fallback, gdy capture bbox nie był bezpiecznie dostępny. Klatka końcowa została sprawdzona wizualnie.

## 8. NVIDIA

Ścieżka NVIDIA nie była modyfikowana. Wykonano tylko kontrolę statyczną oraz testy jednostkowe związane z regionami mapy. Runtime NVIDIA nie był wykonywany, ponieważ aktualna maszyna ma AMD.

Sformułowanie walidacyjne: ścieżka NVIDIA zachowana statycznie; runtime validation nie był możliwy na tej maszynie.

## 9. Z-order i ryzyka

- `track_map` jest pojedynczym kanonicznym wpisem, więc AMD może użyć istniejącego podziału below/map/above.
- Wpisy po `track_map` są traktowane jako elementy powyżej mapy; ich bboxy nie nachodzą celowo na mapę.
- Gauge i chart są rozdzielone przestrzennie. Nie zmieniano guardów overlap/rotation.
- Altitude ma rotation 90°, ale jest poza mapą i nie wymaga zmiany renderera.
- Solar pozostawiono jako `fit_solar_text`, a nie `fit_solar_pct_text`, aby nie zmieniać znaczenia danych.
- Docelowy preset jest konfigurowalny; przesunięcie elementów przez GUI może zmienić decyzję AMD GPU/CPU zgodnie z istniejącymi guardami.

## 10. Testy

Walidacja JSON:

```text
preset_json=OK
reference_resolution=[3840, 2160]
```

Pierwszy zestaw testów rendererów i layoutu:

```text
108 passed in 4.48s
```

Drugi zestaw obejmujący runtime layout, AMD z-order, mapę, chart i gauge:

```text
62 passed in 8.37s
```

Łącznie wykonano 170 test executions bez niepowodzeń, w tym:

- `test_layout_manager.py`,
- `test_compositing_etap5e.py`,
- `test_gauge_rendering.py`,
- `test_bar_integration.py`,
- `test_chart_rendering.py`,
- `test_map_sync.py`,
- testy AMD ordered map/dirty bbox,
- testy runtime layout/parity,
- testy AMD ETAP 5B,
- testy map region bounds NVIDIA,
- testy chart time scope/clipping i gauge parity.

## 11. Elementy odłożone

Odłożone bez zmian w kodzie:

- Compass — brak headingu i dedykowanej semantyki gauge.
- Bike/Lean Indicator — brak assetu/geometrii i źródła kąta.
- Track-up mapy — obecna mapa pozostaje north-up.
- Slope — brak zatwierdzonego data binding.
- Konfigurowalne `window_s` dla wykresów.
- Solar Power — brak pola FIT `solar` w dostępnych danych; obecne `solar_pct` nie zostało użyte jako zamiennik.

## 12. Zmienione pliki

Utworzone:

- `presets/cycling_dashboard_v1.json`
- `Raporty/RAPORT_INDICATORS_ETAP_2_PRESET.md`

`def_layout.json` oraz kod aplikacji nie zostały zmienione. Tymczasowe skrypty walidacyjne w `scratch/` zostały usunięte po użyciu. Zastane, wcześniejsze modyfikacje repozytorium pozostały nietknięte.

## 13. Stan backendów

### Zachowane

- CPU_REFERENCE i wspólny compositor;
- AMD `AMD_NATIVE_D3D11`, map/chart/gauge guardy i diagnostyka;
- NVIDIA CUDA/NVENC/region/atlas code;
- FFmpeg, AMF/NVENC, decoder selection i backend selection;
- telemetry resolver, FIT/GPMF/GPX synchronization oraz SmartSync.

### Ryzyko pozostałe

Najważniejsze ryzyko funkcjonalne to brak pola Solar Power w dostępnych danych FIT. Najważniejsze ryzyko wydajnościowe pozostaje istniejące: duża mapa, dwa wykresy i CPU fallback przy niebezpiecznych bboxach. Nie wprowadzono nowego transferu GPU→CPU→GPU ani żadnej zmiany pipeline’u.
