# RAPORT: ETAP 10L — Current Production Profile

**Data wykonania:** 2026-08-22  
**Autor:** Antigravity  
**Stan:** **PROFIL ZAKOŃCZONY (AUDIT ONLY)**

---

## 1. Konfiguracja benchmarku

Pomiary wykonano na pełnym przebiegu produkcyjnym z zachowaniem wszystkich kontraktów repozytorium:
- **Środowisko:** Windows, AMD GPU (D3D11 / AMF Native Pipeline)
- **Preset:** `presets/cycling_dashboard_v10.json` (pełny v10 HUD, wszystkie wskaźniki włączone)
- **Materiały testowe:**
  - Wideo: `Video/GX010115.MP4` (3840×2160, HEVC Main 10, 59.94 fps, obrót 180°)
  - Metadane: `Video/GX010115.json`
  - Telemetria: `Video/Jazda_na_rowerze_w_porze_lunchu.fit` (4299 rekordów)
- **Parametry renderu:**
  - Rozdzielczość wyjściowa: 1280×720
  - Długość: 120 klatek (2.0 sekundy @ 60 FPS)
  - Ścieżki: `AMD_MAP_PATH=GPU`, `AMD_CHART_PATH=CPU_REFERENCE`, `AMD_GAUGE_PATH=GPU`
  - Tryb telemetrii: `AMD_TELEMETRY_MODE=PRECOMPUTED`
  - Tryb dekodowania: `AMD_NATIVE_DECODE_MODE=GPU_HUD_D3D11VA`
  - Tryb HUD: `AMD_NATIVE_HUD_MODE=GPU_HUD` (DIRTY region upload)

---

## 2. Pomiary CPU_BELOW_MAP

Wszystkie pomiary per-widget rozdzielone na koszt renderera (`render`), wklejania/kompozycji (`paste/blend`) oraz koszt sumaryczny (`total`) dla stanu ustalonego (klatki 11–120):

| Widget | Renderer ms | Placement/Blend ms | Total ms | Udział w Below |
|---|---:|---:|---:|---:|
| **`time_display`** | 1.737 | 0.487 | **2.224** | 40.2% |
| **`dist_visual`** | 0.827 | 1.051 | **1.879** | 33.9% |
| **`fit_battery_pct_text`** | 0.041 | 0.335 | **0.376** | 6.8% |
| **`fit_solar_pct_text`** | 0.029 | 0.323 | **0.352** | 6.4% |

### Bilans CPU_BELOW:
- **SUM(Wszystkie widgety Below):** `4.831 ms`
- **CPU_BELOW `compose_overlay` total mean:** `5.536 ms` (mediana: `4.196 ms`, p95: `16.421 ms`)
- **CPU_BELOW RESIDUAL:** `0.705 ms`

### Rozbicie CPU_BELOW Residual:
- Regional canvas clear / reset: `0.180 ms`
- Dispatch & parameter extraction: `0.095 ms`
- Bounding box tracking & metadata: `0.062 ms`
- Buffer protocol & HUD update prep: `0.368 ms`

---

## 3. Warm-up vs Steady State

Porównanie fazy rozgrzewki (klatki 1–10, pierwsze ładowanie fontów, cache osi, alokacja tekstur) z fazą ustaloną (klatki 11–120):

| Zakres | Mean ms | Median ms | P90 ms | P95 ms | Min ms | Max ms |
|---|---:|---:|---:|---:|---:|---:|
| **CPU_BELOW Warm-up (1–10)** | 7.072 | 4.887 | 17.481 | 17.481 | 3.518 | 17.481 |
| **CPU_BELOW Steady (11–120)** | **5.536** | **4.196** | 7.502 | 16.421 | 3.125 | 17.210 |
| **CPU_ABOVE Warm-up (1–10)** | 19.851 | 13.567 | 50.515 | 50.515 | 11.230 | 50.515 |
| **CPU_ABOVE Steady (11–120)** | **16.658** | **13.706** | 27.783 | 35.434 | 9.470 | 51.453 |

---

## 4. Pomiary CPU_ABOVE_MAP

Świeże pomiary stanu ustalonego dla wszystkich widgetów warstwy `CPU_ABOVE_MAP`:

| Widget | Renderer ms | Placement/Blend ms | Total ms | Udział w Above |
|---|---:|---:|---:|---:|
| **Heart Rate Chart** (`fit_heart_rate_text`) | 4.266 | 0.226 | **4.492** | 27.0% |
| **Cadence Chart** (`fit_cadence_text`) | 3.894 | 0.265 | **4.159** | 25.0% |
| **Slope** (`slope_text`) | 0.998 | 0.930 | **1.928** | 11.6% |
| **Altitude** (`alt_visual`) | 0.689 | 0.572 | **1.261** | 7.6% |
| **Compass** (`compass`) | 0.400 | 0.782 | **1.183** | 7.1% |
| **Virtual Power** (`fit_curVpower_text`) | 0.045 | 0.615 | **0.660** | 4.0% |
| **Shutter** (`exposure_text`) | 0.369 | 0.105 | **0.475** | 2.8% |
| **ISO** (`iso_text`) | 0.239 | 0.135 | **0.374** | 2.2% |
| **Temperature** (`temp_text`) | 0.035 | 0.103 | **0.138** | 0.8% |
| **Speed Gauge** (`speed_visual`) | 0.000 | 0.000 | **0.000** | 0.0% *(GPU)* |

### Bilans CPU_ABOVE:
- **SUM(Wszystkie widgety Above):** `14.669 ms`
- **CPU_ABOVE `above_compose` mean:** `16.658 ms` (mediana: `13.706 ms`, p95: `35.434 ms`)
- **CPU_ABOVE RESIDUAL:** `1.989 ms`

### Rozbicie CPU_ABOVE Residual:
- Inicjalizacja płótna / regional clear: `0.250 ms`
- Extra annotations (range labels, dynamic text draw): `0.485 ms`
- BBox tracking & spatial clustering: `0.071 ms`
- Candidate crop & local alpha scan: `1.183 ms`

---

## 5. Stan wykresów HR i Cadence po ETAPIE 10E4

Po wdrożeniu pełnej osi aktywności (`time_scope = "activity"`) w ETAPIE 10E4:
- Tło wykresu z siatką i przebiegiem aktywności jest w 100% zbuforowane (`_FINAL_STATIC_CHART_CACHE` hit rate: **100% po klatce 1**).
- W każdej klatce renderer wykonuje:
  1. `final_static.copy()` (kopiowanie bufora RGBA o wymiarach widgetu),
  2. Wyszukiwanie pozycji kursora (`bisect_right` w 4299 próbkach),
  3. Rysowanie linii kursora i markera kropki (`_draw_post_paste_cursor`),
  4. Rysowanie dynamicznego tekstu aktualnej wartości (`draw.bitmap`).
- **Aktualny koszt:**
  - Cadence Chart: `4.159 ms/frame`
  - Heart Rate Chart: `4.492 ms/frame`
  - **Łącznie oba wykresy:** **`8.651 ms/frame`** (ponad 52% całego `above_compose`!).

---

## 6. Pomiary pipeline poza compositorami

| Etap pipeline | Średnia ms/frame | Mediana ms | P95 ms | Kategoria |
|---|---:|---:|---:|---|
| **Map CPU preparation / upload** | 2.607 | 1.230 | 3.640 | `MAP` |
| **MF ReadSample / D3D11VA Decode availability** | 2.846 | 0.693 | 2.104 | `DECODER` |
| **Above dirty-region crop (`above_bbox_crop`)** | 1.906 | 1.787 | 2.800 | `MEMORY/COPY` |
| **Above region RGBA to bytes** | 1.078 | 1.000 | 1.558 | `MEMORY/COPY` |
| **Above region texture upload** | 0.367 | 0.238 | 0.483 | `MEMORY/COPY` |
| **HUD dirty update (below)** | 0.354 | 0.287 | 0.683 | `MEMORY/COPY` |
| **VideoProcessor CPU submit** | 0.323 | 0.220 | 0.466 | `GPU SYNC` |
| **AMF submit / backpressure** | 0.621 | 0.484 | 1.087 | `ENCODER` |
| **AMF QueryOutput** | 0.141 | 0.118 | 0.260 | `ENCODER` |
| **Packet write / mux** | 0.159 | 0.130 | 0.340 | `ENCODER` |
| **GPU Wait / Sync** | 0.000 | 0.000 | 0.000 | `GPU SYNC` |

---

## 7. Frame Accounting & FPS

- **Decoded frames:** 120
- **Submitted frames:** 120
- **Encoded frames:** 120
- **Muxed frames:** 120
- **Bilans klatek:** `120 / 120 / 120 / 120` (**PASS — 100% integralności**)
- **RENDER FPS (szybkość renderera klatek wideo):** **`29.19 FPS`**
- **TRUE FPS (uwzględniający muxing audio/kontenera):** **`12.63 FPS`**

---

## 8. TOP 12 Bottlenecków (Stan produkcyjny ETAP 10L)

| Ranga | Komponent / Etap | ms/frame | Kategoria | Opis |
|---:|---|---:|---|---|
| **1** | **Heart Rate Chart** (`fit_heart_rate_text`) | **4.492** | `RENDERER` | Rysowanie dynamicznego kursora i tekstu na wykresie HR |
| **2** | **Cadence Chart** (`fit_cadence_text`) | **4.159** | `RENDERER` | Rysowanie dynamicznego kursora i tekstu na wykresie Cadence |
| **3** | **MF ReadSample / Decode Availability** | **2.846** | `DECODER` | Pobieranie i synchronizacja próbek dekodera sprzętowego |
| **4** | **Map CPU upload / prep** | **2.607** | `MAP` | Render kafelków mapy i przygotowanie bufora RGBA |
| **5** | **Time Display** (`time_display`) | **2.224** | `RENDERER` | Multi-line text block czasu/daty/aktywności |
| **6** | **Slope** (`slope_text`) | **1.928** | `RENDERER` | Wskaźnik nachylenia terenu (linijka/tekst) |
| **7** | **Above BBox Extraction & Crop** | **1.906** | `MEMORY/COPY` | Kadrowanie i skanowanie kanału alfa regionów Above |
| **8** | **Distance** (`dist_visual`) | **1.879** | `RENDERER` | Linijka postępu dystansu |
| **9** | **Altitude** (`alt_visual`) | **1.261** | `RENDERER` | Pasek / linijka wysokości |
| **10** | **Compass** (`compass`) | **1.183** | `RENDERER` | Render i obrót tarczy kompasu |
| **11** | **Above Region RGBA to bytes** | **1.078** | `MEMORY/COPY` | Konwersja bufora PIL RGBA do bajtów dla GPU upload |
| **12** | **Virtual Power** (`fit_curVpower_text`) | **0.660** | `RENDERER` | Cyfrowy blok mocy wirtualnej |

---

## 9. Analiza wspólnych rendererów (Shared Renderers)

1. **Wykresy (`src/indicators/chart.py`):**
   - Obsługują `Heart Rate Chart` (4.492 ms) oraz `Cadence Chart` (4.159 ms).
   - **Łączny koszt: `8.651 ms/frame`**.
   - Optymalizacja dynamicznej warstwy wykresów (uniknięcie pełnego kopiowania obrazu w każdej klatce lub kafelkowa aktualizacja kursora) przyspieszy oba widgety jednocześnie, przynosząc redukcję rzędu **~6–7 ms/frame**.
2. **Paski i Linijki (`src/indicators/bar.py`):**
   - Obsługują `Slope` (1.928 ms), `Distance` (1.879 ms), `Altitude` (1.261 ms), `Battery` (0.376 ms), `Solar` (0.352 ms).
   - W ETAPACH 10I i 10J Battery i Solar zostały obniżone do <0.38 ms. Zastosowanie podobnego buforowania statycznego w `Slope` i `Altitude` to potencjał na kolejne ~2.5 ms zysku.
3. **Teksty proste (`src/indicators/text.py`):**
   - `ISO` (0.374 ms), `Shutter` (0.475 ms), `Temperature` (0.138 ms) — pracują optymalnie i nie stanowią wąskiego gardła.

---

## 10. Wskazanie głównego bottlenecku i kolejnego targetu

### CURRENT BOTTLENECK:
**Wykresy historii aktywności (`src/indicators/chart.py`)** — `Heart Rate Chart` + `Cadence Chart` kosztują łącznie **`8.651 ms/frame`**, co stanowi **52.2%** całego czasu kompozycji `CPU_ABOVE_MAP` i jest największym pojedynczym obciążeniem CPU w całym potoku TeleM.

### NEXT TARGET:
```text
NEXT TARGET: chart.py (Cadence & Heart Rate Chart dynamic layer optimization)
```
- **Uzasadnienie:**
  1. **Najwyższy aktualny koszt:** 8.651 ms/frame w dwóch widgetach.
  2. **Lokalny zasięg:** Całość zmian zamknie się wyłącznie w `src/indicators/chart.py` i ewentualnych helperach wykresów.
  3. **Wysoki ROI:** Potencjalne obniżenie kosztu z ~8.65 ms do <2.0 ms (~6.5 ms zysku na klatkę).
  4. **Zerowe ryzyko architektoniczne:** Nie wymaga modyfikacji pipeline GPU, dekodera ani presetu `v10`.
