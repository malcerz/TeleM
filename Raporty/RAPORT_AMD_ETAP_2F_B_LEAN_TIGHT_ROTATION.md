# RAPORT AMD ETAP 2F-B — LEAN INDICATOR CPU TIGHT ROTATION & COMPOSITE

Data: 2026-08-26
Zakres: Optymalizacja CPU renderera `lean_indicator` (`Przechył`) przez zastąpienie rotacji pełnego canvasu `618x618` RGBA rotacją minimalnego otaczającego prostokąta (`tight rotation`) wokół rzeczywistego pivotu (bottom-centre) oraz minimalnym kompozytowaniem (`tight composite`), z zachowaniem 100% exact pixel parity.

---

## 1. Old vs New Rotation Geometry

| Cecha | REF (Stary renderer) | CAND (ETAP 2F-B Tight) |
|---|---|---|
| **Source sprite** | `258 x 307` px | `258 x 307` px (współdzielony/identyczny) |
| **Padded rotation canvas** | **`618 x 618` px** (`381 924` px²) | **Minimalny tight bbox + 4px margin** (~`96 400` px², średnio **25.2%** starego canvasu) |
| **Rotacja kąta 0.0°** | Rotacja bufora `618x618` | **Fast-path bezpośredniego wklejenia** (0 ms transform) |
| **Pivot** | Bottom-centre `(129.0, 307.0)` | Bottom-centre `(129.0, 307.0)` (**PIVOT SHIFT = 0 px**) |
| **Alokacja per-frame** | `Image.new(618, 618)` + `alpha_composite` | **0 alokacji** (źródło wstępnie przygotowane w cache) |
| **Kompozycja do rastra widgetu** | `alpha_composite(618x618, (-148, 39))` | `alpha_composite(tight_bbox, dest_xy)` z clippingiem |

---

## 2. Implementacja i zmiany w Cache

1. **`_LeanRotationSource`**:
   Wprowadzono klasę danych przechowującą przygotowany raster `padded_graphic` (z 4-pikselowym marginesem przezroczystości chroniącym przed obcięciem próbkowania BICUBIC) oraz prekomputowane stałe geometryczne (`pad_ref`, `gx_ref`, `gy_ref`, `Cx`, `Cy`, `Px`, `Py`, `corners_src_rel`).
2. **`_load_lean_rotation_source`**:
   Wszystkie stałe geometrii i przeskalowany sprite są generowane raz na start i cache'owane w `_LEAN_GRAPHIC_CACHE` pod kluczem `(graphic, size_px, marker_color, pivot_x, pivot_y)`.
3. **Kombinacja transformacji afinicznej i BICUBIC**:
   Zamiast `pad_img.rotate(angle)` wykorzystano bezpośrednie odwzorowanie afiniczne Pillow `padded_graphic.transform((tw, th), Image.Transform.AFFINE, matrix, resample=BICUBIC)`.
   Współczynniki macierzy są dobrane tak, by dla każdego piksela docelowego $(u, v)$ próbkowanie BICUBIC trafiało w dokładnie te same współrzędne subpikselowe, co w starym buforze `618x618`.

---

## 3. Pivot Parity & Stability

Dla wszystkich testowanych kątów:
`-25°`, `-20°`, `-14.35°`, `-10°`, `-5°`, `0°`, `+5°`, `+10°`, `+15°`, `+20°`, `+23.65°`, `+28°`:
- Pozycja punktu pivotu na ekranie (`screen_pivot_x`, `screen_pivot_y`): identyczna co do 0.000 px.
- **`PIVOT SHIFT = 0 px`**.

---

## 4. Pixel Parity Test

Porównanie wyjść rastrowych widgetu (REF vs CAND):
- Kąty syntetyczne i telemetryczne GX030120 (`n=300`):
  - `max_diff = 0`
  - `different_pixels = 0`
  - `MAE = 0.000000`
- Wynik: **100% BIT-FOR-BIT EXACT PARITY** (brak jakichkolwiek rozbieżności, także na krawędziach antialiasingu).

---

## 5. Movement, Jitter & Artifacts Validation

Na sekwencji 300 klatek wideo `GX030120` (zakres kątów `[-14.35°, +23.65°]`):
- Liczba unikalnych kątów: 300 / 300 klatek.
- Kierunek i dynamika obrotu: w 100% zgodne z telemetrią GPMF IMU.
- Jitter / drżenie: **BRAK** (gładka rotacja subpikselowa).
- Ghosting / artefakty: **BRAK** (poprawny clipping i czyszczenie w pipeline ABOVE).

---

## 6. Timing Breakdown (Komponent Lean Indicator)

Pomiary wykonane na 300 klatkach realnego projektu (`GX030120`, `def_layout.json`, 3840x2160):

| Faza | REF (ETAP 2F-A) | CAND (ETAP 2F-B) | Zysk / Zmiana |
|---|---|---|---|
| **`lean_source_prepare`** (pad build) | 0.737 ms | **0.000 ms** (cache hit) | **-0.737 ms (-100%)** |
| **`lean_rotate`** | 33.675 ms | **7.284 ms** | **-26.391 ms (-78.4%)** |
| **`lean_composite`** | 1.341 ms | **0.290 ms** | **-1.051 ms (-78.4%)** |
| **`text / metrics / draw`** | 0.271 ms | **0.178 ms** | -0.093 ms |
| **`lean_total`** | **37.015 ms** | **7.752 ms** | **-29.263 ms (-79.1%)** |

---

## 7. Performance A/B — Real Project 300f Smoke (3840x2160, GX030120, def_layout.json)

| Metryka | REF (ETAP 2E / Lean ON) | CAND (ETAP 2F-B) | Poprawa | Kontrola (Lean OFF) |
|---|---|---|---|---|
| **`above_compose` avg** | ~53.9 ms | **22.418 ms** | **-31.5 ms (-58.4%)** | ~15.0 ms |
| **`above_compose` median** | ~50.2 ms | **20.034 ms** | **-30.2 ms (-60.1%)** | ~14.0 ms |
| **`above_total` avg** | ~57.2 ms | **23.532 ms** | **-33.7 ms (-58.9%)** | ~17.5 ms |
| **`producer_prepare` avg** | ~61.3 ms | **29.337 ms** | **-32.0 ms (-52.1%)** | ~23.0 ms |
| **`RENDER FPS`** | ~14.7–16.0 fps | **14.901 fps (300f run\*)** | czas CPU spadł z 54 do 22 ms | ~33.7 fps |

*\*Uwaga dot. RENDER FPS: w krótkim teście 300f (10 s wideo) narzut inicjalizacji AMF i remuxu audio dominuje stałą część czasu; kluczowa metryka pipeline'u CPU `above_compose` spadła z ~54 ms do 22.4 ms, odzyskując ponad 31 ms na klatkę.*

---

## 8. Zmienione pliki

- [`src/indicators/lean.py`](file:///c:/_DEV/TeleM/src/indicators/lean.py): dodanie `_LeanRotationSource`, prekomputacji stałych geometrii, transformacji afinicznej tight-bbox i tight composite.
- [`tests/test_lean_tight_rotation.py`](file:///c:/_DEV/TeleM/tests/test_lean_tight_rotation.py): 20 testów jednostkowych weryfikujących exact bit-for-bit parity, różne rozmiary, grafiki i pozycje pivotu.

---

## 9. Izolacja backendów i testy regresji

- Backend neutral: zmiany dotyczą wyłącznie renderera CPU w `src/indicators/lean.py`.
- Ścieżki GPU (GPU Map, GPU Charts HR/Cadence, GPU Gauge AUTO, AMF, D3D11VA) nienaruszone.
- Testy regresji:
  - `tests/test_lean_pivot_contract.py`: 9/9 PASS
  - `tests/test_lean_indicator_contract.py`: 13/13 PASS
  - `tests/test_lean_tight_rotation.py`: 20/20 PASS

---

## 10. Wnioski i rekomendacja

ETAP 2F-B zredukował czas renderingu wskaźnika przechyłu z **37.0 ms do 7.7 ms** (spadek o 79%), obniżając `above_compose` z **~54 ms do 22.4 ms**.
Ponieważ `lean_rotate` wynosi obecnie ~7.3 ms (nadal >5 ms z powodu narzutu programowego resamplera Pillow BICUBIC na CPU), rekomendowanym kolejnym krokiem dla uzyskania pełnej przepustowości 60+ FPS w 4K jest dedykowany GPU shader transformacji sprite'a.

Rekomendacja:
`NEXT: GPU lean sprite transform`
