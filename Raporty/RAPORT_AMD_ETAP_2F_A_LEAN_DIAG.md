# RAPORT AMD ETAP 2F-A — LEAN INDICATOR CPU ROTATION DIAGNOSTICS

Data: 2026-08-26
Zakres: Diagnostyka i pomiar kosztów renderingu CPU dla widgetu `lean_indicator` (`Przechył`) w pipeline AMD / def_layout.

---

## 1. Cel i kontekst

W teście integracyjnym ETAP 2E (GX030120, 3840x2160, `def_layout.json`):
- `lean_indicator` ON: `above_compose` ≈ 53.9 ms, RENDER FPS ≈ 14.7–16.0
- `lean_indicator` OFF: `above_compose` ≈ 15.0 ms, RENDER FPS ≈ 33.7

Koszt CPU samego wskaźnika przechyłu wynosił ~37 ms na klatkę (prawie 70% całego czasu `above_compose`).

Celem ETAP 2F-A jest:
1. Zlokalizowanie renderera i struktury wywołań.
2. Zmierzenie składowych kosztów (`base_cache`, `pad_build`, `rotate`, `composite`, `text`).
3. Zbadanie geometrii: wymiary source sprite, canvas rotacji, visible bbox, pivot.
4. Sprawdzenie stanu wdrożenia optymalizacji (cache, tight rotation, tight composite).

---

## 2. Stan repozytorium i pliki źródłowe

- **Renderer**: `_render_lean_indicator(...)` w [`src/indicators/lean.py`](file:///c:/_DEV/TeleM/src/indicators/lean.py).
- **Wywołanie**: [`src/indicators/dispatcher.py`](file:///c:/_DEV/TeleM/src/indicators/dispatcher.py) -> `render_value_indicator` -> [`src/indicators/compositor.py`](file:///c:/_DEV/TeleM/src/indicators/compositor.py).
- **Stan git `src/indicators/lean.py`**: Czysty (brak zmian w working tree). Poprzedni agent przygotował skrypt pomiarowy [`scratch/etap2f_lean_breakdown.py`](file:///c:/_DEV/TeleM/scratch/etap2f_lean_breakdown.py).

---

## 3. Pomiary faz (300 klatek, realne kąty GX030120, 3840x2160)

Kąty telemetryczne: `n=300`, unikalnych wartości `300`, zakres `[-14.35°, +23.65°]`.

| Faza pomiaru | Średni czas [ms] | Mediana [ms] | P95 [ms] | Udział w koszcie |
|---|---|---|---|---|
| **`rotate`** (`pad_img.rotate(angle, BICUBIC)`) | **33.675 ms** | **29.463 ms** | **57.248 ms** | **91.0%** |
| **`compose`** (`img.alpha_composite(rotated, ...)`) | **1.341 ms** | **1.218 ms** | **1.845 ms** | **3.6%** |
| **`pad_build`** (`Image.new` + composite ikony) | **0.737 ms** | **0.615 ms** | **1.114 ms** | **2.0%** |
| **`text_metrics`** (bbox tytułu i wartości) | **0.174 ms** | **0.152 ms** | **0.243 ms** | **0.5%** |
| **`value_draw`** (draw text tile cached) | **0.097 ms** | **0.081 ms** | **0.141 ms** | **0.3%** |
| **`full_call`** (cały `_render_lean_indicator`) | **37.015 ms** | **31.863 ms** | **62.699 ms** | **100.0%** |

---

## 4. Analiza geometrii

- **Source sprite (`graphic`)**: `258 x 307` px (dla `size_px = 307`, skalowana ikona `wzor/rower_ico.png` z zachowaniem aspect ratio).
- **Obecny canvas rotacji (`pad`)**: `618 x 618` px (`2 * max(gw, gh) + 4 = 2 * 307 + 4 = 618`).
- **Powierzchnia padu**: `381 924` px².
- **Rzeczywisty zrotowany visible bbox**: Mediana obszaru to `80 860` px² (**zaledwie 21.2% powierzchni padu**). Union bbox dla kątów `[-14.35°, +23.65°]` to `[68, 0, 509, 314]`.
- **Pivot**: Bottom-centre `(pivot_x=0.5, pivot_y=1.0)` -> w pikselach sprite'a: `(129.0, 307.0)`.
- **Widget raster**: `323 x 430` px.

---

## 5. Status istniejących mechanizmów optymalizacji

| Mechanizm | Status | Opis |
|---|---|---|
| **Static graphic cache** | **OBECNY** | `_LEAN_GRAPHIC_CACHE` cache'uje wczytany i przeskalowany `rower_ico.png`. |
| **Static base cache** | **OBECNY** | `_LEAN_BASE_CACHE` cache'uje tło, tytuł, referencję i podziałki (300 trafień, 1 miss na klatce 0). |
| **Text tile cache** | **OBECNY** | `_TEXT_TILE_CACHE` cache'uje wyrenderowane kafelki tekstu. |
| **Padded sprite pre-assembly** | **BRAK** | `pad_img` jest alokowany i składany od nowa w każdej klatce (`0.74 ms`). |
| **Tight rotation** | **BRAK** | Rotowany jest pełny kwadrat `618x618` zamiast minimalnego prostokąta otaczającego (`33.68 ms`). |
| **Tight crop / composite** | **BRAK** | Do `img` kompozytowany jest cały bufor `618x618` (`1.34 ms`). |
| **Quantized angle / pre-rotated cache** | **BRAK** | Każdy ułamek stopnia wywołuje pełną rotację BICUBIC. |

---

## 6. Wnioski do ETAP 2F-B (Plan optymalizacji)

Głównym wąskim gardłem jest rotacja niepotrzebnie dużego bufora `618x618` (91% czasu).
Kierunki optymalizacji CPU dla ETAP 2F-B:
1. **Pre-assembled padded sprite**: Jednorazowe złożenie padu w `_LEAN_GRAPHIC_CACHE` (oszczędność `0.74 ms`).
2. **Tight rotation around pivot**: Wyznaczenie bounding boxa zrotowanego sprite'a lub rotacja na mniejszym buforze dopasowanym do promienia od pivotu.
3. **Tight composite**: Kompozycja tylko wycinka zawierającego nieprzezroczyste piksele (oszczędność `~0.8 ms`).
4. **Kwantyzacja / Cache zrotowanych klatek (opcjonalnie)**: Rozdzielczość kątowa np. 0.5° lub 0.2° w cache ograniczy rotacje BICUBIC niemal do zera po kilkudziesięciu klatkach.
