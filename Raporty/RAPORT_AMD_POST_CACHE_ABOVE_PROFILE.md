# Raport: Profiling Komponentów CPU ABOVE po Wdrożeniu Visual-State Cache (AMD D3D11 Pipeline)

Data: 2026-09-16  
Środowisko: `C:\_DEV\SportCamHUD`  
Gałąź: `amd-bikeridehud`  
Oracle: `C:\_DEV\TeleM` (READ-ONLY)  

---

## 1. Wymagane Kluczowe Wskaźniki

```text
TRUE_FPS=37.753
ABOVE_TOTAL=10.109
ABOVE_COMPOSE=8.029
PRODUCER_PREPARE=17.828

TOP_1_WIDGET=speed_text
TOP_1_RENDERER=gauge
TOP_1_AVG_MS=1.397

TOP_2_WIDGET=fit_distance_text
TOP_2_RENDERER=ruler
TOP_2_AVG_MS=1.067

TOP_3_WIDGET=fit_heart_rate_text
TOP_3_RENDERER=text
TOP_3_AVG_MS=0.638

RECOMMENDED_NEXT_DIRECTION=B. istniejący renderer jest zbyt dynamiczny — GPU może być lepsze (dla typu ruler: 2.077 ms, 20.5% warstwy ABOVE)
CASE=CASE B — CPU COST NOW DISTRIBUTED ACROSS MULTIPLE RENDERERS
```

---

## 2. Konfiguracja Środowiska i Weryfikacja Braku Override

Eksport wykonano w pełnej ścieżce GUI potomnej (`SportCamHUD.py -> GUI -> RenderMixin -> AMD child -> amd_native_exporter -> DLL -> AMF`):
- **Zestaw danych**: `Video/GX020079.mp4` + `Video/GX020079.fit`
- **Rozdzielczość**: 3840x2160 (4K UHD)
- **Klatki**: 300 klatek / 10.0 s @ 29.97 fps, HEVC AMF
- **Resolved AMD Config**:
  - `AMD_QUEUE_DEPTH=2`
  - `AMD_CPU_GPU_PIPELINE=ASYNC`
  - `AMD_VP_PROCESSOR_RING_SIZE=1`
  - `AMD_ABOVE_BATCHED=0`
  - `AMD_AFTER_MAP_ALT_VISUAL_GPU=0`
  - `AMD_CPU_WIDGET_CACHE=1` (automatycznie pobrane z produkcyjnego defaultu, **brak wpisu w `active_env_overrides`**)
  - `active_env_overrides={'AMD_CPU_GPU_PIPELINE': 'ASYNC', 'AMD_QUEUE_DEPTH': '2', 'AMD_VP_PROCESSOR_RING_SIZE': '1', 'AMD_AFTER_MAP_ALT_VISUAL_GPU': '0', 'AMD_ABOVE_BATCHED': '0'}`

---

## 3. Wyniki Akceptacyjne Eksportu (Acceptance Criteria)

```text
FRAMES:          300/300 (100.0%)
DROPPED:         0
AMF ERRORS:      0
D3D11 ERRORS:    0
CHILD EXITCODE:  0
FINAL MP4 SIZE:  82,668,312 bajtów
WALL CLOCK:      7.946 s
TRUE FPS:        37.753 FPS
```

---

## 4. Efekt Wdrożenia Visual-State Cache dla `segment_bar`

Przed wdrożeniem cache wskaźniki segmentowe stanowiły niemal 3 ms narzutu na klatkę:
- `fit_garmin_battery_percent_text`: spadek z **2.086 ms** do **0.269 ms** (**-87.1%** łącznego czasu z wklejaniem; czas renderowania spadł do **0.028 ms** na trafieniach przy **99.00% hit ratio**).
- `fit_curVpower_text`: spadek z **0.729 ms** do **0.385 ms** (**-47.2%** łącznego czasu z wklejaniem; czas renderowania spadł do **0.034 ms** na trafieniach przy **95.68% hit ratio**).
- Łączny czas warstwy `above_total` ustabilizował się na poziomie **~10.1 ms** (spadek z dawnych 14.57 ms).

### Statystyki Amortyzowane Cache:
| Wskaźnik | Typ Danych | Klatki | Hits | Misses | Hit Ratio | Średni Lookup | Średni Render (Miss) | Efektywny Render |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `fit_garmin_battery_percent_text` | Wolnozmienna (bateria) | 300 | 298 | 3 | **99.00%** | 0.0278 ms | 2.6778 ms | 0.0545 ms |
| `fit_curVpower_text` | Szybkozmienna (moc) | 300 | 288 | 13 | **95.68%** | 0.0339 ms | 1.3146 ms | 0.0908 ms |
| **Łącznie `segment_bar`** | — | 600 | 586 | 16 | **97.34%** | 0.0308 ms | 1.5702 ms | 0.0727 ms |

---

## 5. Aktualny Ranking Komponentów CPU ABOVE (Malejąco wg Realnego Kosztu)

Pomiar precyzyjnymi licznikami nanosekundowymi dla każdej klatki (300 klatek produkcyjnych):

| RANK | WIDGET | TYP RENDERERA | AVG EFFECTIVE MS | P50 MS | P90 MS | P95 MS | P99 MS | MAX MS | ACTIVE FRAMES | CACHE HIT RATIO | % ABOVE_TOTAL |
|:---:|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | `speed_text` | `gauge` | **1.397** | 1.632 | 3.060 | 3.408 | 3.855 | 3.995 | 300 | — | 13.8% |
| 2 | `fit_distance_text` | `ruler` | **1.067** | 0.955 | 1.553 | 1.857 | 2.663 | 4.208 | 300 | — | 10.6% |
| 3 | `fit_heart_rate_text` | `text` | **0.638** | 0.551 | 0.790 | 0.921 | 1.502 | 15.992 | 300 | — | 6.3% |
| 4 | `alt_text` | `ruler` | **0.549** | 0.486 | 0.685 | 0.807 | 1.296 | 8.242 | 300 | — | 5.4% |
| 5 | `exposure_text` | `text` | **0.533** | 0.186 | 1.405 | 1.500 | 1.717 | 2.318 | 300 | — | 5.3% |
| 6 | `fit_solar_text` | `ruler` | **0.462** | 0.347 | 0.955 | 1.046 | 1.303 | 1.739 | 300 | — | 4.6% |
| 7 | `fit_curVpower_text` | `segment_bar` | **0.385** | 0.304 | 0.496 | 0.664 | 1.636 | 4.807 | 300 | 95.7% | 3.8% |
| 8 | `fit_cadence_text` | `text` | **0.333** | 0.294 | 0.470 | 0.565 | 0.979 | 2.643 | 300 | — | 3.3% |
| 9 | `fit_garmin_battery_percent_text` | `segment_bar` | **0.269** | 0.234 | 0.366 | 0.423 | 0.839 | 2.415 | 300 | 99.0% | 2.7% |
| 10 | `iso_text` | `text` | **0.201** | 0.105 | 0.389 | 1.032 | 1.330 | 1.772 | 300 | — | 2.0% |
| 11 | `fit_gopro_battery_text` | `text` | **0.114** | 0.105 | 0.148 | 0.172 | 0.302 | 1.121 | 300 | — | 1.1% |
| 12 | `temp_text` | `text` | **0.103** | 0.099 | 0.134 | 0.158 | 0.245 | 0.326 | 300 | — | 1.0% |
| 13 | `custom_texts` | `custom_texts` | **0.002** | 0.002 | 0.003 | 0.004 | 0.005 | 0.012 | 300 | — | 0.0% |

---

## 6. Agregacja wg Typu Renderera (Renderer Families)

Rozdzielenie źródeł danych od silników renderujących ujawnia dominujące klasy operacji:

| Typ Renderera | Łączny Czas (AVG MS) | % ABOVE_TOTAL | Liczba Widgetów | Widgety Składowe | Charakterystyka Wizualna |
|:---|:---:|:---:|:---:|:---|:---|
| **`ruler`** | **2.077 ms** | **20.5%** | 3 | `fit_distance_text`, `alt_text`, `fit_solar_text` | Ciągłe przesunięcia podziałek i etykiet na osi (bardzo wysoka dynamika klatka po klatce) |
| **`text`** | **1.921 ms** | **19.0%** | 6 | `fit_heart_rate_text`, `exposure_text`, `fit_cadence_text`, `iso_text`, `fit_gopro_battery_text`, `temp_text` | Formatowane łańcuchy znaków i ikony (zmienność dyskretna) |
| **`gauge`** | **1.397 ms** | **13.8%** | 1 | `speed_text` | Prędkościomierz (CPU raster + GPU capture/blend w AFTER-MAP) |
| **`segment_bar`** | **0.654 ms** | **6.5%** | 2 | `fit_curVpower_text`, `fit_garmin_battery_percent_text` | Segmenty objęte Visual-State Cache (zredukowane z dawnych ~2.8 ms) |
| **`custom_texts`** | **0.002 ms** | **0.0%** | 1 | `custom_texts` | Pusta kolekcja tekstów w layoucie |

---

## 7. Główne Składowe Czasowe Potoku Produkcyjnego

| Składowa | AVG MS | P50 MS | P95 MS | P99 MS |
|:---|:---:|:---:|:---:|:---:|
| `above_total` | **10.109** | 10.088 | 13.986 | 17.635 |
| `above_compose` | **8.029** | 8.090 | 11.435 | 12.896 |
| `above_region_to_bytes` | **1.990** | 1.774 | 3.259 | 4.325 |
| `above_region_upload` | **2.819** | 2.767 | 4.745 | 5.326 |
| `producer_prepare` | **17.828** | 16.698 | 22.836 | 29.290 |
| `consumer_native_call` | **17.052** | 15.539 | 35.142 | 36.559 |

---

## 8. Analiza i Rekomendacja Następnego Kierunku

### 8.1. Odpowiedź na Kluczowe Pytanie Zadania
Po usunięciu dominującego kosztu `segment_bar` (zredukowany o >76% z 2.81 ms do 0.65 ms):
1. **Wśród pojedynczych widgetów**: Największym kosztem CPU na canvasie pozostaje `fit_distance_text` (1.067 ms) oraz `alt_text` (0.549 ms) [poza `speed_text` 1.397 ms, podlegającym zasadzie GAUGE HARD STOP].
2. **Wśród typów rendererów**: Największą rodziną operacji CPU jest **`ruler`** (**2.077 ms**, 20.5% czasu ABOVE_TOTAL), a tuż za nią rodzina **`text`** (**1.921 ms**, 19.0% czasu ABOVE_TOTAL).

### 8.2. Ocena Dostępnych Kierunków:
- **Kierunek A (Visual-state cache dla kolejnego typu renderera)**:
  - Nadaje się doskonale dla rodziny `text` (`exposure_text`, `iso_text`, `temp_text`, `fit_gopro_battery_text`), gdzie sformatowany string często nie ulega zmianie przez dziesiątki klatek.
  - Słabo nadaje się dla rodziny `ruler`, ponieważ interpolowane wartości dystansu i wysokości zmieniają pozycję podziałek o ułamki piksela na niemal każdej klatce (niski hit ratio bez kwantyzacji).
- **Kierunek B (Istniejący renderer jest zbyt dynamiczny — GPU może być lepsze)** (**REKOMENDOWANY**):
  - Rodzina `ruler` (`fit_distance_text`, `alt_text`, `fit_solar_text`) generuje łącznie **2.077 ms** narzutu CPU. Rysowanie dynamicznych podziałek i linii suwaka bezpośrednio na GPU (np. via D3D11 instanced lines lub dynamiczny kafelek AFTER-MAP) całkowicie odciąża CPU Pillow z kosztownego przeliczania setek kresek.
- **Kierunek C (Optymalizacja wspólnego prymitywu renderującego/fontów)**:
  - Narzut funkcji tekstowych Pillow jest rozproszony po wielu małych wskaźnikach (~0.1-0.5 ms każdy).
- **Kierunek D (CPU ABOVE nie jest już głównym bottleneckiem)**:
  - Czas `above_total` spadł do **10.1 ms**, co zrównało go w rzędzie wielkości z czasem `consumer_native_call` (17.0 ms) i `producer_prepare` (17.8 ms). Dalsze zyski z pojedynczych widgetów będą miały charakter drobnych ułamków milisekundy.

---

## 9. Podsumowanie

```text
STATUS: COMPLETE
CASE: CASE B — CPU COST NOW DISTRIBUTED ACROSS MULTIPLE RENDERERS
RECOMMENDED_NEXT_DIRECTION: B. istniejący renderer jest zbyt dynamiczny — GPU może być lepsze
```
