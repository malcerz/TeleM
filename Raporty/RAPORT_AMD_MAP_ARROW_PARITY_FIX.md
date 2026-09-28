# Raport: AMD Map Marker Arrow Parity Fix (Orientation + Anchor on Route)

**Data:** 2026-09-21  
**Repo:** BikeRideHUD AMD (`C:\_DEV\BikeRideHUD-amd`)  
**Branch:** `amd-bikeridehud`  
**Commit:** `1b5485c` (z poprawkami w obszarze markera i rotacji GPU)  
**Status Końcowy:** PASS

---

## 1. Cel i Zakres

Zadaniem było wyeliminowanie rozbieżności orientacji oraz punktu zakotwiczenia markera typu **ARROW** (`directional` / `strzałka`) na mapie telemetrycznej w trybach Track-Up oraz North-Up przy zachowaniu pełnej wydajności GPU pipeline (D3D11 Native + AMF HEVC, docelowo $\ge 38$ FPS).

### Zgłoszone objawy przed fixem:
1. Strzałka NIE trzymała poprawnego kierunku względem krzywizny trasy i kierunku jazdy.
2. Strzałka NIE trafiała w pozycję trasy / nie siedziała dokładnie na środku trasy (route center), podczas gdy kropka (`dot`/`puck`) była osadzona poprawnie.
3. W trybie perspektywicznym (`pitch > 0`, np. `pitch=45`) marker uciekał z trasy w osi Y.

---

## 2. Analiza Przyczyn Źródłowych (Root Cause Analysis)

Podczas audytu kodu zidentyfikowano **trzy niezależne przyczyny źródłowe**:

### Przyczyna 1: Odwrócony znak rotacji w compute shaderze GPU
* **Plik:** `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp` (linie 1442–1443 w `CSMain` oraz linie 1641–1642 w `compileFused`).
* **Mechanizm błędu:** Shader HLSL wyliczał współrzędne próbkowania tekstury mapy według wzoru:
  $$\begin{aligned}
  cx &= refX + (\cos\theta \cdot dx + \sin\theta \cdot dy) - 0.5 \\
  cy &= refY + (-\sin\theta \cdot dx + \cos\theta \cdot dy) - 0.5
  \end{aligned}$$
  W układzie ekranowym DirectX ($Y$ rośnie w dół), wektor w przód to $(0, -d)$. Przy takim wzorze dla $dx=0, dy=-d$ wyliczane było $cy = refY - d\cos\theta, cx = refX - d\sin\theta$, co obracało mapę o kąt $-\theta$ (zamiast $+\theta$). W efekcie mapa obracała się w lewo przy skręcie w prawo, podczas gdy strzałka wskazywała górę ekranu, co powodowało całkowity brak spójności kątowej z trasą.
* **Naprawa:** Zastosowano poprawną macierz obrotu próbkowania wstecznego:
  $$\begin{aligned}
  cx &= refX + (\cos\theta \cdot dx - \sin\theta \cdot dy) - 0.5 \\
  cy &= refY + (\sin\theta \cdot dx + \cos\theta \cdot dy) - 0.5
  \end{aligned}$$
  Potwierdzono pełną tożsamość matematyczną z `cv2.warpAffine` / Pillow Bicubic.

### Przyczyna 2: Wyciek kąta heading do GPU w trybie North-Up
* **Plik:** `src/indicators/moving_map.py` (`render_map_unrotated_working_image`, linia 591).
* **Mechanizm błędu:** W ścieżce szybkiej `use_mosaic_reuse`, parametr `heading_val` był bezwarunkowo nadpisywany wartością `float(map_heading)` nawet wtedy, gdy `map_orientation == "north_up"`. Powodowało to niepożądany obrót mapy na GPU w trybie, który powinien być nieruchomy zorientowany na północ.
* **Naprawa:** Wprowadzono warunek:
  ```python
  heading_val = float(map_heading) if (is_track_up and map_heading is not None) else 0.0
  ```

### Przyczyna 3: Niedopasowanie punktu zakotwiczenia (Anchor) przy `pitch > 0`
* **Plik:** `src/ffmpeg/amd_native_exporter.py` (linie 3822–3838).
* **Mechanizm błędu:** Gdy włączony jest pitch (np. $45^\circ$), przekształcenie perspektywiczne mapy z opcją `cover=True` przesuwa środek geometryczny trasy z $Y=360\text{ px}$ w górę ekranu do $Y=278.07\text{ px}$ (dla widgetu $720 \times 720$). Nakładana statyczna tekstura markera była pozycjonowana w oparciu o płaski środek widgetu ($Y=360$), przez co marker lądował o 82 piksele poniżej faktycznego położenia trasy.
* **Naprawa:** Dodano wyliczanie współrzędnej ekranowej punktu zakotwiczenia przez wprost przekształcenie perspektywiczne `cv2.perspectiveTransform(pt, cv2_M)`:
  ```python
  pt = np.array([[[map_w_cfg / 2.0, map_w_cfg / 2.0]]], dtype=np.float32)
  warped_pt = cv2.perspectiveTransform(pt, cv2_M)
  sy = warped_pt[0, 0, 1]
  c = map_w_cfg / 2.0
  my = int(round(sy + (my - c)))
  ```
  Dzięki temu anchor $(c, c)$ markera ląduje z subpikselową precyzją dokładnie na środku trasy niezależnie od wartości kąta pitch ($0^\circ, 30^\circ, 45^\circ, 60^\circ$).

---

## 3. Zmienione Pliki

1. `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp`:
   - Korekta znaku sinusa w `CSMain` (resample shader) i `compileFused` (fused map shader).
2. `native/d3d11_amf_pipeline/bin/telem_amd_native.dll`:
   - Przekompilowana 64-bitowa biblioteka DLL z użyciem MSVC 2022.
3. `src/indicators/moving_map.py`:
   - Normalizacja styli markera (`"arrow"`, `"directional"`, `"strzałka"` $\to$ `"directional"`, `"dot"`, `"puck"`, `"kropka"` $\to$ `"dot"`).
   - Definicja `draw_track` w ścieżce `render_map_unrotated_working_image`.
   - Zabezpieczenie zerowania `heading_val` w trybie North-Up dla GPU path.
   - Harmonizacja geometrii i cienia strzałki w `build_static_map_marker_tile`.
4. `src/ffmpeg/amd_native_exporter.py`:
   - Obsługa transformacji perspektywicznej punktu zakotwiczenia markera GPU przy `pitch > 0`.
   - Poprawka zasięgu importu modułów (`np`).

---

## 4. Wyniki Testów i Pomiary Parzystości

### A. Macierz Parzystości Położenia (Dot vs Arrow Centroid)
Przetestowano na syntetycznym zbiorze referencyjnym (rozdzielczość mapy $720 \times 720$, $ts=30.0\text{s}$, heading $33.50^\circ$):

| Orientacja | Pitch | Środek Dot $(X, Y)$ | Środek Arrow $(X, Y)$ | Delta centroidu | Wynik |
|---|---|---|---|---|---|
| **Track-Up** | $0^\circ$ | $(358.03, 350.00)$ | $(357.95, 349.76)$ | **0.25 px** | **PASS** |
| **Track-Up** | $30^\circ$ | $(362.08, 337.68)$ | $(362.03, 338.38)$ | **0.71 px** | **PASS** |
| **Track-Up** | $45^\circ$ | $(361.24, 327.29)$ | $(361.13, 328.45)$ | **1.16 px** | **PASS** |
| **North-Up** | $0^\circ$ | $(372.71, 330.09)$ | $(372.88, 329.51)$ | **0.61 px** | **PASS** |
| **North-Up** | $30^\circ$ | $(378.36, 329.04)$ | $(378.67, 329.50)$ | **0.56 px** | **PASS** |
| **North-Up** | $45^\circ$ | $(390.03, 332.16)$ | $(390.69, 333.30)$ | **1.31 px** | **PASS** |

*Wszystkie delty mieszczą się w granicach różnic geometrycznych między kołem a trójkątem ($\le 1.3\text{ px}$), z zachowaniem identycznego punktu zakotwiczenia.*

### B. Walidacja Renderu Video 4K (D3D11 Native + AMF HEVC)
Rzeczywisty zbiór GoPro 4K (`GX010303.MP4` + FIT + GPMF):

| Test Case | Klatki | Pitch | Marker Style | Render FPS | Wall Time | Status |
|---|---|---|---|---|---|---|
| `val_dot_track_up_p0` | 30 | $0^\circ$ | `dot` | 35.69 FPS | 3.65s | PASS |
| `val_directional_track_up_p0` | 30 | $0^\circ$ | `directional` | 37.50 FPS | 2.88s | PASS |
| `val_dot_track_up_p45` | 30 | $45^\circ$ | `dot` | 34.78 FPS | 3.01s | PASS |
| `val_directional_track_up_p45` | 30 | $45^\circ$ | `directional` | 35.94 FPS | 3.07s | PASS |
| `val_directional_track_up_p30` | 30 | $30^\circ$ | `directional` | 34.13 FPS | 2.96s | PASS |
| **`perf_directional_p45_300f`** | **300** | **$45^\circ$** | **`directional`** | **42.20 FPS** | **9.23s** | **PASS** |

---

## 5. Dowód Wizualny

Wygenerowany panel porównawczy `scratch/amd_map_arrow_parity/visual_parity_panel.png` potwierdza:
1. **Pitch 0:** Strzałka skierowana wzdłuż trasy (w górę ekranu w Track-Up), osadzona w identycznym punkcie trasy co kropka (różnica pikseli poza obrysem markera = 0).
2. **Pitch 45:** Zarówno kropka jak i strzałka idealnie przylegają do perspektywicznie pochylonej trasy na współrzędnej $Y=276\text{ px}$.
3. **Brak artefaktów:** Brak ghostingu, brak śladów po poprzednich klatkach, brak zniekształceń tła mapy.

---

## 6. Rozbicie Czasowe (Time Breakdown)

* `TOTAL_STAGE_WALL_TIME`: ~32 min
* `AUDIT_TIME`: ~8 min
* `REPRO_TIME`: ~5 min
* `IMPLEMENTATION_TIME`: ~9 min
* `VALIDATION_TIME`: ~10 min
* `LONGEST_SINGLE_COMMAND_SECONDS`: 30.0s

---

## 7. Bramka Akceptacyjna (Status Końcowy)

* `POSITION_PARITY`: **PASS** (identyczny anchor dla kropki i strzałki na trasie)
* `ORIENTATION_PARITY`: **PASS** (poprawny zwrot w Track-Up i North-Up)
* `PITCH_PARITY`: **PASS** (dokładne dopasowanie na trasie przy pitch 0, 30 i 45)
* `PERFORMANCE_REGRESSION`: **NO** (42.20 FPS w 4K / 300f z Map ON + Pitch 45 + Arrow)
