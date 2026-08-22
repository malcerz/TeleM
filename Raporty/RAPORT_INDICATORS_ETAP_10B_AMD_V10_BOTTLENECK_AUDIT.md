# TeleM — ETAP 10B: audyt wydajności AMD v10

Data audytu: 2026-08-22  
Preset: `presets/cycling_dashboard_v10.json`  
Ścieżka: AMD Native D3D11 + MediaFoundation D3D11VA + AMF HEVC  
Test: 1280×720, 2 s, target 60 FPS, 120 klatek, materiał `Video/GX010115.MP4`, FIT z offsetem +2 s, bez SmartSync.

## 1. Wynik główny

Wariant pełnego v10 nie spełnia budżetu 16,67 ms/klatkę. Głównym kosztem jest `CPU_ABOVE_MAP`, zwłaszcza gdy aktywne są chart’y i speed gauge. Wyłączenie chartów zwiększyło TRUE FPS z 8,89 do 12,98, a wyłączenie chartów i gauge do 13,65 FPS, nadal poniżej 60 FPS.

## 2. CPU_ABOVE_MAP

Kolejność z istniejącego compositora:

```text
compass
slope_text
iso_text
exposure_text
temp_text
alt_visual
fit_curVpower_text
fit_cadence_text
fit_enhanced_speed_text
fit_heart_rate_text
```

`AMD_MAP_ORDER` pozostał: `CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP`.

## 3. Fallback chartów

Żądana ścieżka: `AMD_CHART_PATH: GPU_SPLIT`. Efektywna ścieżka po guardzie: `CPU_REFERENCE` dla obu chartów.

Powód:

```text
GPU_CHART_UNSAFE_LAYOUT
fit_cadence_text overlaps widget bbox=(451,503,378,61)
fit_heart_rate_text overlaps widget bbox=(451,503,378,61)
```

Kolizja bbox dotyczy `dist_visual`.

## 4. Fallback gauge

Żądana ścieżka: `AMD_GAUGE_PATH: GPU`. Efektywna ścieżka: `CPU_REFERENCE` dla `fit_enhanced_speed_text`.

Powód:

```text
bbox=(481,223,319,319)
gauge overlaps widget bbox=(451,503,378,61)
```

Guard jest konserwatywny, ale zachowuje poprawny z-order.

## 5. Bbox kontra rzeczywista alfa

Pomiar wykonano na rzeczywistej klatce HUD 1280×720, przy czasie aktywności około 1 s, renderując widgety osobno i przecinając maski alfa.

| Para | Przecięcie bbox | Pole bbox | Przecięcie alfa |
|---|---:|---:|---:|
| `dist_visual` – `fit_cadence_text` | 33×54 | 1782 px | 0 px |
| `dist_visual` – `fit_heart_rate_text` | 251×54 | 13554 px | 251 px |
| `dist_visual` – `fit_enhanced_speed_text` | 319×39 | 12441 px | 0 px |
| `fit_cadence_text` – `fit_heart_rate_text` | 0×160 | 0 px | 0 px |

Wniosek: fallback chartów nie jest w całości fałszywy — HR ma realne piksele alfa w strefie `dist_visual`. Dla cadence i speed gauge obserwowane przecięcie alfa było zerowe, ale bbox guard pozostaje bezpiecznym testem dla zmiennych danych/klatek.

## 6. Benchmark wariantów

Wartości są wynikami pojedynczych pełnych eksportów z 120 klatkami. `above_compose` i `above_total` to średnie ms/klatkę z tabeli eksportera.

| Wariant | Wyłączone | TRUE FPS | RENDER FPS | `above_compose` | `above_total` | pipeline total | precompute |
|---|---|---:|---:|---:|---:|---:|---:|
| A | nic, pełny v10 | 8.893 | 14.376 | 33.236 ms | 35.571 ms | 4.646 ms | 55.1 ms |
| B | cadence + HR | 12.977 | 28.978 | 11.812 ms | 13.193 ms | 4.330 ms | 74.2 ms |
| C | speed gauge | 10.531 | 18.584 | 28.936 ms | 31.240 ms | 4.668 ms | 44.0 ms |
| D | cadence + HR + speed gauge | 13.650 | 31.362 | 11.100 ms | 11.607 ms | 3.866 ms | 40.7 ms |

Każdy wariant zakończył się poprawnie: decoded/received 120, submitted 120, encoded 120, muxed 120. Różnice precompute są jednorazowym kosztem inicjalizacji i nie są głównym bottleneckiem.

## 7. Budżet klatki

Budżet dla 60 FPS: `16,67 ms/klatkę`.

- A: sam `CPU_ABOVE_MAP` średnio 35,57 ms, bez pozostałej kompozycji.
- A: `compose_overlay` średnio 28,35 ms; razem te dwie fazy dominują profil.
- D: `compose_overlay` + `above_total` to około 27,56 ms, nadal ponad budżetem.
- Dekoder/submit/AMF/pakietowanie pozostają niskie względem CPU compositing: odpowiednio około 0,35/0,49/0,11/0,10 ms w A.
- `Audio mux` jest kosztem jednorazowym eksportu, nie kosztem każdej klatki.

## 8. Dekodowanie, encode i transfery

Źródło: HEVC, 3840×2160, `yuv420p10le`, 30000/1001 FPS. Log AMD potwierdził MediaFoundation D3D11VA i GPU surface 3840×2160.

Wyjście z checkpointu AMD: HEVC 1280×720, `yuv420p`, AMF hardware encoder. Profil nie wykazał pełnego `GPU → CPU → GPU` dla klatki wideo. Występują zamierzone małe transfery HUD/regionów (`map_cpu_upload` około 0,23 ms; GPU map upload 0 ms w trybie persistent/native).

## 9. Microtest 4K

Pominięty. Profil 720p jednoznacznie wskazuje CPU compositor jako bottleneck, więc 4K nie zmieniłby decyzji i nie był potrzebny do bezpiecznego audytu.

## 10. Ranking bottlenecków

1. `CPU_ABOVE_MAP` — chart’y i speed gauge na `CPU_REFERENCE`.
2. `compose_overlay` / rasteryzacja aktywnych wskaźników przed i po mapie.
3. Jednorazowy `precompute_build` — mały względem czasu eksportu.
4. Decode/encode/submit/packet — brak sygnału, że ograniczają ten test.

## 11. Bezpieczne opcje optymalizacji

- Najpierw zoptymalizować `CPU_ABOVE_MAP` bez zmiany z-orderu i bez usuwania CPU_REFERENCE.
- Osobno przeanalizować guard chart/gauge: obecnie można rozważyć bardziej precyzyjną maskę alfa tylko jako kontrolowany eksperyment z parity testem; nie należy wyłączać guardu na podstawie samego bbox.
- Nie zmieniać dekodera, AMF, formatu klatek ani ścieżki NVIDIA w ramach tego audytu.

## 12. Zmiany i walidacja

### Changed

Nie zmieniono kodu produkcyjnego, presetów ani testów. Utworzono wyłącznie ten raport w `Raporty`.

### Preserved

CPU_REFERENCE, AMD GPU map/chart/gauge paths, NVIDIA path, backend selection, telemetry resolver i z-order pozostawiono bez zmian.

### Tested

- Cztery kontrolowane eksporty AMD Native D3D11, 1280×720, 2 s, 60 FPS.
- Pomiar bbox i rzeczywistej maski alfa widgetów.
- `ffprobe` wejścia i istniejącego wyjścia AMD.
- `git diff --check`.

### Not tested

Nie wykonano pełnego suite 10A ani testu runtime NVIDIA. NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.

### Risks

Wyniki TRUE FPS są eksportami krótkimi i zależą od obciążenia systemu. Guard bbox jest konserwatywny, co ogranicza GPU fast-path, ale chroni parity i z-order.

## Final decision

`NEXT: OPTIMIZE CPU_ABOVE_MAP`

Nie wykonywano jeszcze żadnego fixa ani tuningu produkcyjnego.
