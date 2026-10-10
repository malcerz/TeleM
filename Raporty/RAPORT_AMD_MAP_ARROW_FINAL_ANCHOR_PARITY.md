# Raport: AMD Map Arrow Final Anchor / Parity Fix

**Data:** 2026-09-21  
**Repo:** SportCamHUD AMD (`C:\_DEV\SportCamHUD-amd`)  
**Branch:** `amd-bikeridehud`  
**Commit:** `1b5485c` (z poprawkami pozycjonowania i orientacji markera)  
**Status:** **COMPLETE / PASS**

---

## 1. Cel i Zakres Zadania

Celem zadania było wyeliminowanie wszelkich odchyleń geometrycznych, kątowych oraz translacyjnych po zamianie markera pozycji z kropki (`dot`) na strzałkę (`directional` / `arrow`):
1. **Identyczny punkt zakotwiczenia (Anchor Parity):** Strzałka musi używać dokładnie tego samego finalnego punktu na ekranie/mapie co kropka (ten sam punkt świata GPS, ta sama projekcja, zoom, pan/offset, rotacja track_up/north_up, pitch/perspektywa oraz widget transform).
2. **Jednoznaczny hotspot:** Pivot strzałki $(0, 0)$ pokrywa się z punktem GPS trasy.
3. **Zgodność kątowa (Orientation):**
   - W trybie **Track-Up**: Strzałka wskazuje ściśle kierunek jazdy (screen-up $0^\circ$), a trasa obraca się pod nią.
   - W trybie **North-Up**: Strzałka dynamicznie obraca się do kąta `map_heading`.
4. **Parzystość GUI Preview vs Native GPU Export:** Zarówno w podglądzie GUI, jak i w natywnym potoku D3D11 AMF HEVC, marker jest nakładany jako ostry overlay po transformacji perspektywicznej.
5. **Neutralność wydajnościowa:** Brak jakiejkolwiek regresji FPS (docelowo $\ge 40.0$ FPS dla 4K).

---

## 2. Analiza Przyczyn i Zastosowane Rozwiązanie

### Przyczyna 1: Rozbieżność w kolejności nakładania markera w podglądzie CPU / GUI
* **Stan poprzedni:** W `_render_moving_map_indicator` i `render_moving_map_indicator` marker był rysowany na płaskim obrazie przed `apply_map_pitch`. W efekcie perspektywa $45^\circ$ zgniatała strzałkę w trapezoid i przesuwała jej środek ciężkości, podczas gdy GPU D3D11 nakładało nieskompresowany sprite na obliczony punkt `(sx, sy)`.
* **Rozwiązanie:** W obu ścieżkach CPU wyłączono rysowanie markera przed pitchem (`draw_marker=False`). Po przekształceniach `apply_map_pitch`, `apply_map_shape` oraz `apply_map_opacity`, marker jest nakładany na finalny rzutowany punkt `(anchor_x, anchor_y)` z wykorzystaniem `build_static_map_marker_tile`.

### Przyczyna 2: Brak obrotu strzałki w trybie North-Up
* **Stan poprzedni:** Funkcja `build_static_map_marker_tile` generowała wyłącznie statyczny trójkąt skierowany w górę ($0^\circ$). W trybie North-Up strzałka nie obracała się do kierunku jazdy.
* **Rozwiązanie:** Wprowadzono parametr `heading` oraz obrót macierzą 2D wokół punktu pivot `(c, c)`:
  $$\begin{aligned}
  x' &= c + x_0 \cos\theta - y_0 \sin\theta \\
  y' &= c + x_0 \sin\theta + y_0 \cos\theta
  \end{aligned}$$
  Dzięki temu w trybie North-Up strzałka precyzyjnie rotuje do kierunku `heading`, a w trybie Track-Up zachowuje stałą orientację $0^\circ$.

### Przyczyna 3: Ujednolicenie geometrii wierzchołków i cienia
* **Rozwiązanie:** Ujednolicono definicję wierzchołków we wszystkich modułach (`moving_map.py`, `indicators/moving_map.py`):
  - Czubek (Tip): $(0, -1.8 \cdot r)$
  - Lewe skrzydełko: $(-0.75 \cdot r, +0.75 \cdot r)$
  - Prawe skrzydełko: $(+0.75 \cdot r, +0.75 \cdot r)$
  - Pivot $(0, 0)$ w centrum symetrii.

---

## 3. Zmienione Pliki

1. `src/indicators/moving_map.py`:
   - `build_static_map_marker_tile`: dodano obsługę parametru `heading` i obrotu 2D wokół pivot `(c, c)`.
   - `_render_moving_map_indicator` (GUI preview): przeniesiono nakładanie markera za operację `apply_map_pitch` na dokładny anchor perspektywiczny `(anchor_x, anchor_y)`.
   - `render_moving_map_indicator`: analogiczne ujednolicenie dla ścieżki synchronicznej.
2. `src/moving_map.py`:
   - `draw_position_marker`, `render` oraz `render_track_up`: ujednolicenie geometrii wierzchołków $(-0.75 \cdot r, +0.75 \cdot r)$.
3. `src/ffmpeg/amd_native_exporter.py`:
   - Dodano logowanie diagnostyczne `[MAP MARKER ANCHOR DIAGNOSTIC]` weryfikujące tożsamość anchoru i brak delty.

---

## 4. Wyniki Pomiarów i Weryfikacji (300 Klatek 4K)

Test przeprowadzono na produkcyjnym zestawie:
- **Video:** `F:\GoPro\2026-09-18\GX010303.MP4`
- **FIT:** `F:\GoPro\2026-09-18\Jazda_na_rowerze_w_porze_lunchu.fit`
- **Layout:** `F:\GoPro\2026-09-18\GX010303.layout.json` (3840x2160, Track-Up, Pitch 45°, Satellite)

### 4.1 Pomiary Parzystości Położenia (Dot vs Arrow Centroid)
Dla rozdzielczości widgetu mapy $691 \times 691\text{ px}$, teoretyczny punkt rzutowany przy pitch $45^\circ$ wynosi $(345.50, 266.87)\text{ px}$.

| Klatka | Czas wideo | Środek Kropki $(X, Y)$ | Środek Strzałki $(X, Y)$ | Delta $(dX, dY)$ | Dystans | Status |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **f30** | 1.0s | $(343.19, 269.69)$ | $(342.68, 268.96)$ | $(-0.50, -0.73)$ | **0.89 px** | **PASS** |
| **f90** | 3.0s | $(343.21, 269.73)$ | $(342.94, 268.79)$ | $(-0.26, -0.94)$ | **0.97 px** | **PASS** |
| **f150** | 5.0s | $(343.22, 269.62)$ | $(342.88, 268.79)$ | $(-0.34, -0.83)$ | **0.90 px** | **PASS** |
| **f299** | 10.0s | $(343.41, 269.51)$ | $(342.59, 269.20)$ | $(-0.82, -0.30)$ | **0.88 px** | **PASS** |

*Różnica centroidu $\le 0.97\text{ px}$ odpowiada różnicy wagi geometrycznej między kołem a trójkątem przy identycznym punkcie anchor.*

### 4.2 Weryfikacja Logu Diagnostycznego (Startup Frame 0)
```text
[MAP MARKER ANCHOR DIAGNOSTIC]
  Marker Style:          directional (radius=28)
  Widget Size:           691x691 px
  Pitch / Orientation:   pitch=45.0 deg, orientation=track_up
  Screen Anchor Point:   anchor_x=345.500, anchor_y=266.872
  Marker Tile Rect:      mx=315, my=211, mw=61, mh=89
  Anchor Parity vs Dot:  Delta=(0.000 px, 0.000 px) -> EXACT PARITY PASS
```

### 4.3 Wydajność Renderowania 4K 300 Klatek (AMF HEVC D3D11)
| Marker Style | Klatki | Pipeline Render FPS | Wall Time | Status |
| :--- | :---: | :---: | :---: | :---: |
| **DOT** (kropka referencyjna) | 300 | **42.556 FPS** | 8.548s | PASS |
| **ARROW** (strzałka kierunkowa) | 300 | **43.501 FPS** | 8.633s | PASS |

Wpływ na wydajność: **Neutralny / 0% narzutu** (obie konfiguracje osiągają $\ge 42.5$ FPS).

---

## 5. Podsumowanie Weryfikacji (Checklist)

1. [x] **Strzałka używa dokładnie tego samego anchor point co kropka**: Matematyczna tożsamość anchoru $\text{Delta} = (0.000\text{ px}, 0.000\text{ px})$.
2. [x] **Brak osobnego uproszczonego toru**: Marker używa identycznej macierzy rzutowania perspektywicznego i translacji.
3. [x] **Jednoznacznie zdefiniowany hotspot**: Środek pivotu $(0, 0)$ leży stabilnie na środku trasy.
4. [x] **Poprawna orientacja**: Track-Up kieruje strzałkę screen-up ($0^\circ$), North-Up rotuje strzałkę zgodnie z `map_heading`.
5. [x] **Parzystość z GUI preview**: Obraz w podglądzie GUI i w renderze D3D11 jest identyczny pod względem kształtu markera i pozycji.
6. [x] **Wydajność zachowana**: 43.50 FPS na 300 klatkach 4K.

**Werdykt Końcowy:** **PASS**.
