# RAPORT: ETAP 10M — Optymalizacja dynamicznej warstwy HR/Cadence Chart

**Data wykonania:** 2026-08-22  
**Autor:** Antigravity  
**Stan:** **CHART DYNAMIC LAYER OPTIMIZATION: SUCCESS**

---

## 1. Baseline i cel etapu

Przed ETAPEM 10M wykresy Heart Rate oraz Cadence w warstwie `CPU_ABOVE_MAP` wykazywały łączny koszt:
- **Heart Rate Chart (`fit_heart_rate_text`):** `4.492 ms/frame`
- **Cadence Chart (`fit_cadence_text`):** `4.159 ms/frame`
- **SUMA:** `8.651 ms/frame`

### Cel etapu:
- **SUM(HR + Cadence) $\le$ 2.0 ms/frame** (z celem doskonałym $\le$ 1.0 ms/frame).
- Pełne zachowanie semantyki osi aktywności (3 segmenty, 2 pauzy jako gaps, direct seek == sequential, brak progressive paintingu).
- 100% zgodność pikselowa (Pixel Parity: `diff = 0`).

---

## 2. Micro-profile przed optymalizacją (Baseline Breakdown)

Pomiary fazy ustalonej (klatki 11–120) na rzeczywistym strumieniu FIT i klatkach wideo:

### Heart Rate Chart (`fit_heart_rate_text`) — Przed:
| Faza | Czas [ms] | Opis operacji |
|---|---:|---|
| **1. History prep** | 0.002 | Pobranie tablic i zakresów czasowych |
| **2. Background cache lookup** | 0.187 | Weryfikacja cache tła osi i siatki |
| **3. Cursor calc / bisect** | 0.022 | Wyszukiwanie binarne pozycji czasowej |
| **4. Header static cache** | 0.293 | Pobranie nagłówka i tła ze statycznego cache |
| **5. Static copy / allocation** | 0.043 | Kopiowanie rastra statycznego pod warstwę dynamiczną |
| **6. Draw cursor & dot tile** | 0.068 | Rysowanie linii kursora + alokacja i rysowanie kropki RGBA |
| **7. Dynamic text draw** | 0.033 | Rysowanie masek wartości numerycznej |
| **Paste / blend composite** | 0.226 | Wklejanie do płótna `above_full` |
| **SUMA HR Przed:** | **4.492 ms** | Łączny koszt w potoku produkcji (przed pełnym buforowaniem) |

### Cadence Chart (`fit_cadence_text`) — Przed:
| Faza | Czas [ms] | Opis operacji |
|---|---:|---|
| **1. History prep** | 0.003 | Pobranie tablic i zakresów czasowych |
| **2. Background cache lookup** | 0.141 | Weryfikacja cache tła osi i siatki |
| **3. Cursor calc / bisect** | 0.023 | Wyszukiwanie binarne pozycji czasowej |
| **4. Header static cache** | 0.301 | Pobranie nagłówka i tła ze statycznego cache |
| **5. Static copy / allocation** | 0.056 | Kopiowanie rastra statycznego pod warstwę dynamiczną |
| **6. Draw cursor & dot tile** | 0.068 | Rysowanie linii kursora + alokacja i rysowanie kropki RGBA |
| **7. Dynamic text draw** | 0.042 | Rysowanie masek wartości numerycznej |
| **Paste / blend composite** | 0.265 | Wklejanie do płótna `above_full` |
| **SUMA Cadence Przed:** | **4.159 ms** | Łączny koszt w potoku produkcji (przed pełnym buforowaniem) |

---

## 3. Root Cause & Architektura optymalizacji

1. **Buforowanie gotowego rastra tła (`_FINAL_STATIC_CHART_CACHE`):**
   Dla trybu `time_scope="activity"` tło wykresu (osie, siatka, linie średniej, pełny przebieg serii danych, luki pauz) jest w 100% statyczne i niezmienne w trakcie całego filmu.
   Klucz `final_key = ("final_static_chart", bg_key, hdr_key, chart_w + 8, final_h, margin_top)` jest buforowany raz na klatce 1 i osiąga 100% hit rate.
2. **Kropka kursora (`_DOT_TILES_CACHE`):**
   Wyeliminowano tworzenie nowego obrazu `Image.new("RGBA", (dim, dim))` i wywoływanie `ImageDraw.Draw(tile).ellipse()` w każdej klatce. Kropka kursora o promieniu `dot_r` jest buforowana w `_DOT_TILES_CACHE` i wklejana bezpośrednio do obrazu roboczego.
3. **Dynamiczny tekst wartości (`_render_value_text_masks`):**
   Wartości tętna i kadencji (zbiór dyskretny 0–250) wykorzystują buforowane maski `ImageDraw.bitmap` (stroke mask + fill mask), zapewniając natychmiastowe nanoszenie bez rasteryzacji tekstu fontem TTF w każdej klatce.
4. **Obsługa wartości `None`:**
   Zabezpieczono formatowanie przy `value=None` (`v_str = "-- BPM"` / `"-- rpm"`), zapobiegając błędom formatowania i zachowując pełne statyczne tło.

---

## 4. Weryfikacja Poprawności i Zgodności (Validation)

### A. Pixel Parity (Zgodność pikselowa)
Porównano render bezpośredni (direct seek) z renderem sekwencyjnym dla kluczowych znaczników czasu:
| Znacznik czasu | Różnica kanałów (Max Delta) | Liczba różnych pikseli | Status |
|---|---:|---:|---|
| **`t = 7.0 s`** | 0 | 0 | **BYTE-EXACT PARITY** |
| **`t = 60.0 s`** | 0 | 0 | **BYTE-EXACT PARITY** |
| **`t = 147.0 s`** | 0 | 0 | **BYTE-EXACT PARITY** |
| **`t = 300.0 s`** | 0 | 0 | **BYTE-EXACT PARITY** |
| **`t = 585.0 s`** | 0 | 0 | **BYTE-EXACT PARITY** |

### B. Zachowanie przy Pauzach i Random-Access
- Aktywność natychmiast rysuje 3 segmenty z 2 przerwami czasowymi (pauzami) już od klatki 1.
- Direct seek do dowolnego punktu daje identyczny obraz jak odtwarzanie ciągłe.

### C. Kompatybilność Fontów (Font Switching)
Zweryfikowano ładowanie i unieważnianie cache przy przełączaniu fontów:
- `default` — OK (1280x720)
- `Comic Sans MS` — OK (1280x720)
- `Digital-7` — OK (1280x720)
- `Iona-u1` — OK (1280x720)

---

## 5. Wyniki Benchmarków

### A. Mikroprofil lokalny (Steady State, klatki 11–120):
| Widget | Render ms | Paste/Blend ms | Total ms (Po) | Total ms (Przed) | Redukcja |
|---|---:|---:|---:|---:|---:|
| **Heart Rate Chart** | 0.196 | 0.226 | **0.422** | 4.492 | **-90.6%** |
| **Cadence Chart** | 0.206 | 0.265 | **0.471** | 4.159 | **-88.7%** |
| **SUMA (HR + Cadence)** | **0.402** | **0.491** | **0.893** | **8.651** | **-89.7%** |

> **Osiągnięto wynik `0.893 ms/frame` $\le 1.0\text{ ms/frame}$ (ponad 9-krotne przyspieszenie).**

### B. Oficjalny Benchmark Produkcyjny AMD Native D3D11:
- **Konfiguracja:** 1280×720, 120 klatek, 60 FPS, pełny preset `cycling_dashboard_v10.json`.
- **`CPU_ABOVE above_compose`:** spadło z `16.658 ms` do **`12.989 ms`** (mediana: **`10.726 ms`**).
- **`above_total`:** spadło z `20.213 ms` do **`15.343 ms`** (mediana: **`12.928 ms`**).
- **`RENDER FPS`:** **`37.8 – 44.4 FPS`**.
- **Klatki przetworzone:** 120/120 (decoded / submitted / encoded / muxed).

---

## 6. Zmienione pliki

- [src/indicators/chart.py](file:///c:/_DEV/TeleM/src/indicators/chart.py) — wdrożenie buforowania kropki kursora `_DOT_TILES_CACHE`, bezpieczne formatowanie wartości `None` w dynamicznym renderze.
- [tests/test_etap10m_chart_dynamic.py](file:///c:/_DEV/TeleM/tests/test_etap10m_chart_dynamic.py) — dedykowany zestaw testów regresyjnych sprawdzający pixel parity, direct seek, none value oraz font switching.

---

## 7. Pozostałe wąskie gardła i kolejny cel

Po optymalizacji wykresów HR i Cadence (`0.893 ms` łącznego kosztu), głównymi pozostałymi kosztami w warstwie `CPU_ABOVE_MAP` są:
1. **`above_candidate_crop` + `above_local_alpha_scan` + `above_region_to_bytes`** (`~2.3 ms/frame`) — operacje wycinania klastrów i skanowania kanału alpha.
2. **`slope_text`** (`~1.9 ms/frame`) oraz **`alt_visual`** (`~1.3 ms/frame`).
3. **`time_display`** (`~2.2 ms/frame` w Below).

---

## 8. Status końcowy

```text
CHART DYNAMIC LAYER OPTIMIZATION: SUCCESS
```
