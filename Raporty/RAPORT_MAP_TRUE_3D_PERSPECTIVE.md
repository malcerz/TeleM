# RAPORT — Prawdziwe Pochylenie Perspektywiczne Mapy (True 3D Perspective Map)

**Data:** 2026-09-06  
**Autor:** Antigravity  
**Branch:** `integration/intel-amd`  
**Bazowy commit:** `59277b4`  
**Status:** PASS  

---

## 1. Cel zadania

Usunięcie wadliwego, 2D „pochylenia” mapy, które powodowało sztuczne obcinanie tekstury (clipping/cropping), brak skrótu perspektywicznego w osi pionowej oraz deformację trasy i markera.  
Zastąpienie go **prawdziwą projekcją perspektywiczną (3D perspective projection / homography)** traktującą całą powierzchnię mapy (kafelki + trasa + marker) jako płaski prostokątny quad w przestrzeni 3D obserwowany przez wirtualną kamerę pod zmiennym kątem pitch $\theta \in [0^\circ, 70^\circ]$.

---

## 2. Audyt poprzedniej implementacji (Dlaczego obcinała i psuła obraz)

### Poprzedni kod (`src/indicators/helpers.py`):
```python
def apply_map_pitch(img, raw_pitch: Any):
    pitch_deg = min(60.0, max(0.0, float(raw_pitch)))
    w, h = img.size
    rad = math.radians(pitch_deg)
    top_scale = math.cos(rad)
    new_top_w = w * top_scale
    inset_x = (w - new_top_w) / 2.0

    pb = [(0, 0), (w, 0), (w, h), (0, h)]
    pa = [(inset_x, 0), (w - inset_x, 0), (w, h), (0, h)]
    coeffs = _find_perspective_coeffs(pa, pb)
    return img.transform((w, h), Image.PERSPECTIVE, coeffs, Image.BILINEAR)
```

### Przyczyny błędów:
1. **Brak skrótu pionowego ($Y$-foreshortening):** Punkty górnej krawędzi miały na sztywno przypisane $Y = 0$. Przy pochyleniu kamery w 3D obiekty oddalone przesuwają się ku horyzontowi ($Y > 0$), a odległość pozorna ulega nieliniowemu skrótowi. Stary kod tego nie robił w ogóle.
2. **Odwrotne mapowanie PIL bez modelu kamery:** Przekazanie `pa` i `pb` ze sztucznym $Y=0$ tworzyło czysto 2D trapezoidalną ścinającą deformację. Piksele źródłowe w górnych narożnikach były obcinane (clip/crop), a mapa „znikała”.
3. **Brak spójności fizycznej:** Odległość kamery $d$ i FOV nie istniały — zwężenie było prostym arbitralnym $\cos(\theta)$ w poziomie bez powiązania z głębią $Z$.

---

## 3. Nowy model geometryczny i projekcja kamery (True 3D Camera Model)

### Model wirtualnej kamery:
- **Układ współrzędnych:** Płaszczyzna mapy leży w przestrzeni o wymiarach $W \times H$.
- **Kotwica dolna:** Dolna krawędź ($Y = H$, czyli $s = 0$) leży najbliżej obserwatora i zachowuje pełną szerokość $W$.
- **Odległość kamery ($d$):**
  $$d = 1.2 \cdot \max(W, H)$$
  co odpowiada naturalnemu, pozbawionemu dystorsji polu widzenia kamery $\text{FOV} \approx 45.2^\circ$ (odpowiednik obiektywu standardowego 50mm).
- **Kąt pochylenia ($\theta$):** $\theta \in [0^\circ, 70^\circ]$.
- **Dla dowolnego punktu na płaszczyźnie w odległości $s \in [0, H]$ od dolnej krawędzi:**
  - Głębokość w przestrzeni 3D:
    $$Z(s) = d + s \cdot \sin\theta$$
  - Skala powiększenia perspektywicznego:
    $$M(s) = \frac{d}{Z(s)} = \frac{d}{d + s \cdot \sin\theta}$$
  - Rzut pionowy na ekranie:
    $$\Delta Y(s) = \frac{s \cdot d \cdot \cos\theta}{d + s \cdot \sin\theta}$$
    $$Y(s) = H - \Delta Y(s)$$
  - Rzut poziomy (szerokość na wysokości $s$):
    $$W(s) = W \cdot M(s) = W \cdot \frac{d}{d + s \cdot \sin\theta}$$
    $$X_{left}(s) = \frac{W - W(s)}{2}, \quad X_{right}(s) = \frac{W + W(s)}{2}$$

### Wynikowe narożniki docelowego czworokąta (Destination Quad):
- **Górny-Lewy (TL):** $\left(\frac{W - W(H)}{2},\; H - \Delta Y(H)\right)$
- **Górny-Prawy (TR):** $\left(\frac{W + W(H)}{2},\; H - \Delta Y(H)\right)$
- **Dolny-Prawy (BR):** $(W, H)$
- **Dolny-Lewy (BL):** $(0, H)$

### Kluczowe właściwości:
- **$\theta = 0^\circ$:** $Z(H) = d \implies W(H) = W, \Delta Y(H) = H \implies Y(H) = 0$. Narożniki: $(0,0), (W,0), (W,H), (0,H)$ — **dokładna tożsamość 1:1**.
- **$\theta > 0^\circ$:**
  - $W_{top} < W$ (górna krawędź symetrycznie węższa),
  - $Y_{top} > 0$ (górna krawędź obniża się ku horyzontowi),
  - Czworokąt jest ściśle wypukły (convex quad), kąty wewnętrzne $< 180^\circ$, brak inwersji punktów,
  - Środek mapy (rowerzysta $s = H/2$) ląduje naturalnie na wysokości $Y \approx 58\%\dots70\% H$ bez sztucznych przesunięć.

---

## 4. Architektura powierzchni mapy (Canonical Offscreen Surface)

Zgodnie z wymogiem 2:
```text
Kafelki mapy (MovingMapRenderer)
+ Trasa GPS (czerwona polilinia)
+ Marker pozycji (biały ze strzałką kierunku)
↓
Kanonikowy offscreen surface (map_img: RGBA)
↓
apply_map_shape (kwadrat lub okrąg/elipsa)
↓
apply_map_opacity (kanał alpha)
↓
apply_map_pitch (homografia 3D całej powierzchni)
↓
Kompozycja do HUD
```
Wszystkie elementy (kafelki, trasa, marker) są nanoszone na powierzchnię przed rzutowaniem 3D. Dzięki temu:
- Trasa i kafelki ulegają identycznej transformacji perspektywicznej.
- Marker pozostaje dokładnie na trasie i na mapie.
- Grubość trasy naturalnie maleje wraz z odległością w głąb perspektywy.

---

## 5. Implementacja Homografii i Wydajność

1. **Akceleracja OpenCV:**
   - Wykorzystanie `cv2.getPerspectiveTransform(src_pts, dst_pts)` oraz `cv2.warpPerspective` z filtrowaniem `cv2.INTER_LINEAR` i przezroczystym tłem `(0, 0, 0, 0)`.
   - Czas rzutowania klatki mapy 4K ($692 \times 692$ px): **~3.1 ms**.
2. **Pillow Fallback:**
   - Gdyby OpenCV nie było dostępne, automatyczny fallback do `Image.transform(..., Image.PERSPECTIVE, coeffs, Image.BILINEAR)`.
3. **Cache macierzy:**
   - Macierze transformacji i współczynniki są cache'owane w `_MAP_PITCH_CACHE` pod kluczem `(w, h, round(pitch_deg, 2))`. Koszt rekalkulacji macierzy na klatkę wynosi **0.000 ms**.
4. **Bypass dla $\theta = 0^\circ$:**
   - Przy `pitch <= 0.001` natychmiastowy zwrot `return img` (**0.0003 ms**), zero narzutu na dotychczasowy rendering.

---

## 6. Pomiary numeryczne i testy geometrii

Dla canvasu mapy $W = 692, H = 692$:

| Pochylenie ($\theta$) | TL $(X, Y)$ | TR $(X, Y)$ | Szerokość góry ($W_{top}$) | Pozycja góry ($Y_{top}$) | Środek $Y$ (marker) | Wypukłość quad |
|---|---|---|---|---|---|---|
| **0°** | `(0.0, 0.0)` | `(692.0, 0.0)` | 692.0 px (100.0%) | 0.0 px (0.0%) | 346.0 px (50.0%) | Wypukły (prostokąt) |
| **20°** | `(76.7, 186.0)` | `(615.3, 186.0)` | 538.5 px (77.8%) | 186.0 px (26.9%) | 407.6 px (58.9%) | Ściśle wypukły |
| **40°** | `(120.7, 346.8)` | `(571.3, 346.8)` | 450.6 px (65.1%) | 346.8 px (50.1%) | 483.0 px (69.8%) | Ściśle wypukły |
| **60°** | `(145.0, 491.0)` | `(547.0, 491.0)` | 401.9 px (58.1%) | 491.0 px (71.0%) | 564.7 px (81.6%) | Ściśle wypukły |

---

## 7. Izolacja backendów i integracja z AMD Native D3D11

W module `src/ffmpeg/amd_native_exporter.py`:
- D3D11 posiada wbudowany shader do rotacji 2D (`AMD_GPU_MAP_ROTATE`), który obraca czworokąt wokół osi Z.
- W przypadku mapy z perspektywą 3D (`pitch > 0`), rotacja Track-Up **musi** odbywać się na płaszczyźnie gruntu przed pochyleniem kamery w 3D (inaczej obrót czworokąta z pochylonym horyzontem obracałby horyzont pionowo).
- Wprowadzono bezpieczną regułę:
  ```python
  has_pitch = float(map_cfg.get("pitch", 0.0) or 0.0) > 0.001
  gpu_map_rotate = gpu_map_enabled and gpu_map_rotate_flag and is_track_up and not has_pitch
  ```
- **Przy `pitch == 0` (domyślnym):** `gpu_map_rotate` pozostaje w 100% aktywny, dokładnie tak jak w dotychczasowym zwalidowanym profilu AMD (brak jakiejkolwiek regresji).
- **Przy `pitch > 0`:** Exporter używa `render_map_working_image` (rotacja na gruncie + pochylenie 3D), uploaduje gotową teksturę do D3D11 i kompozytuje na GPU.

---

## 8. Zrzuty ekranu z rzeczywistej trasy FIT

Wygenerowano i zarchiwizowano w `Raporty/map_screenshots/`:
- `map_real_north_tilt_0.png` — widok North-Up płaski (0°)
- `map_real_north_tilt_20.png` — widok North-Up lekka perspektywa (20°)
- `map_real_north_tilt_40.png` — widok North-Up wyraźna perspektywa (40°)
- `map_real_north_tilt_60.png` — widok North-Up mocna perspektywa (60°)
- `map_real_track_tilt_0.png` — widok Track-Up płaski (0°)
- `map_real_track_tilt_20.png` — widok Track-Up lekka perspektywa (20°)
- `map_real_track_tilt_40.png` — widok Track-Up wyraźna perspektywa (40°)
- `map_real_track_tilt_60.png` — widok Track-Up mocna perspektywa (60°)

**Weryfikacja wizualna:**
- Przy zwiększaniu kąta trasa i mapa płynnie oddalają się ku horyzontowi.
- Brak czarnych klinów — narożniki są czysto przezroczyste RGBA.
- Marker pozostaje ściśle związany ze swoją pozycją na drodze.
- Przy Track-Up zakręty obracają mapę pod kołami rowerzysty, a droga przed nim zawsze wybiega w głąb perspektywy.

---

## 9. Podsumowanie wyników testów

| Weryfikowany obszar | Wynik | Komentarz |
|---|---|---|
| **Testy geometrii narożników** | **PASS** | `tests/test_map_perspective.py` — 7 testów parametrycznych (0°, 10°, 20°, 30°, 45°, 60°, 70°) |
| **Parytet dla Tilt = 0** | **PASS** | `max_diff = 0`, tożsamy obiekt w pamięci, 0.0003 ms |
| **Zgodność Trasy i Markera** | **PASS** | Syntetyczny i rzeczywisty GPS: marker idealnie na osi rzutowanej trasy |
| **Stabilność Track-Up** | **PASS** | Obrót gruntu zachowany, perspektywa stabilna dla dowolnych kątów |
| **Parytet Preview vs Render** | **PASS** | Identyczny quad i identyczna funkcja renderująca (`max_diff = 0`) |
| **Regresje AutoFIT / Autoscale** | **PASS** | 25/25 testów dedykowanych zielonych |

---

## 10. Końcowy werdykt

```text
TRUE PERSPECTIVE MAP:            PASS
TILT 0 LEGACY PARITY:            PASS
ROUTE/MARKER PROJECTIVE PARITY:  PASS
TRACK-UP + PERSPECTIVE:          PASS
PREVIEW/RENDER PARITY:           PASS
```
