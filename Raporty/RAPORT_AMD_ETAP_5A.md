# TeleM — AMD ETAP 5A — profil `compose_overlay()`

Data: 2026-08-14  
Wynik: **PASS**

ETAP 5A dodał wyłącznie opt-in instrumentację CPU. Nie zmieniono renderera, semantyki telemetrii ani natywnego pipeline'u GPU. Profilowanie włącza `AMD_OVERLAY_PROFILE=ON`; domyślnie jest wyłączone. Natywne `AMD_NATIVE_PROFILING` i diagnostyka pozostały OFF, więc pomiar nie dodawał blokującego oczekiwania GPU.

## Przebieg referencyjny

| Pole | Wynik |
|---|---:|
| Materiał | `Video/GX020079.mp4` |
| Wywołanie | produkcyjny `stream_overlay_to_ffmpeg()` z parametrami GUI |
| Klatki | 1131 / 1131 |
| Wall-clock przebiegu profilowanego | 69.430 s |
| TRUE FPS przebiegu profilowanego | 16.290 |
| TRUE production baseline ETAP 4 | **16.695 FPS** |
| `compose_overlay` | AVG 34.727, Median 32.381, P95 46.675, P99 62.318 ms |
| Telemetry/frame_data | AVG 9.281, Median 5.810, P95 17.176, P99 18.930 ms |

FPS przebiegu profilowanego nie jest nowym baseline'em wydajności. Profil zawiera wiele przeźroczystych wrapperów i liczników wywołań Pillow.

Pipeline GPU pozostał identyczny: MF/D3D11VA P010 → direct VideoProcessor → NV12 → regionalny HUD RGBA → direct planar NV12 compute → AMF. Rawvideo pipe, CPU base, CPU→GPU base, GPU→CPU base, dodatkowa kopia decoder surface oraz blocking GPU wait: **0**. DLL ABI 4, SHA-256 `CE640BB8047B3354ADE3518B90FB4B89DAD932A4E22A4CEEFE890A4B6C0348BD`, identyczny jak w ETAPIE 4.

## Wskaźniki

Czasy `total` są rozłączne pomiędzy wskaźnikami. `render` i `paste` są ich podetapami.

| Indicator | AVG | Median | P95 | P99 | render | paste/composite | Class |
|---|---:|---:|---:|---:|---:|---:|---|
| `fit_cadence_text` | 9.177 | 8.451 | 15.188 | 21.710 | 5.215 | 3.796 | DYNAMIC EVERY FRAME |
| `track_map` | 8.807 | 8.198 | 10.166 | 21.080 | 4.244 | 4.436 | DYNAMIC EVERY FRAME |
| `fit_heart_rate_text` | 7.819 | 7.320 | 9.901 | 19.541 | 4.227 | 3.440 | DYNAMIC EVERY FRAME |
| `fit_enhanced_speed_text` | 3.627 | 3.334 | 4.456 | 11.544 | 1.793 | 1.682 | DYNAMIC EVERY FRAME |
| `iso_text` | 1.278 | 1.493 | 1.912 | 4.106 | 1.025 | 0.177 | DYNAMIC (740 nowych wartości/renderów) |
| `time_block` | 0.730 | 0.472 | 0.987 | 5.166 | 0.254 | 0.396 | SEMI-DYNAMIC (38 renderów, około 1/s) |
| `exposure_text` | 0.434 | 0.182 | 1.150 | 1.682 | 0.259 | 0.124 | SEMI-DYNAMIC (291 nowych renderów) |
| `fit_gopro_battery_text` | 0.428 | 0.400 | 0.544 | 1.042 | 0.139 | 0.220 | SEMI-DYNAMIC; w klipie stały |
| `temp_text` | 0.213 | 0.193 | 0.273 | 0.627 | 0.019 | 0.144 | SEMI-DYNAMIC; w klipie stały |

Klasyfikacja części składowych:

- statyczne: tła gauge'a, podziałka, tick marks, osie, grid, historyczne polilinie wykresów, nagłówki wykresów i tło/route mapy;
- semi-dynamic: time/date, exposure, temperatura i bateria; cache kluczowany jest finalnym tekstem;
- dynamiczne co klatkę: igła i wartość prędkości, kursory i wartości wykresów, pozycja/marker mapy oraz finalne złożenie każdego widgetu z canvasem.

## Pillow — operacje zbiorcze

| Operation | AVG | Median | P95 | P99 | Calls/frame |
|---|---:|---:|---:|---:|---:|
| `alpha_composite` | 23.131 | 21.618 | 30.474 | 49.385 | 18.00 |
| `paste` | 7.913 | 7.353 | 11.167 | 17.608 | 20.03 |
| `copy` | 5.801 | 5.574 | 7.264 | 10.354 | 6.04 |
| text drawing | 3.234 | 2.945 | 5.659 | 12.654 | 4.03 |
| `crop` | 3.221 | 3.077 | 3.978 | 5.674 | 10.95 |
| `textbbox/getbbox` | 0.611 | 0.568 | 0.868 | 1.483 | 6.13 |
| `ImageDraw` creation | 0.237 | 0.205 | 0.318 | 0.432 | 14.95 |
| primitives (line/polygon/ellipse/rectangle/arc) | 0.147 | 0.131 | 0.212 | 0.383 | 7.22 |
| `Image.new` | 0.103 | 0.080 | 0.136 | 0.587 | 0.95 |
| font cache lookup | 0.022 | 0.019 | 0.027 | 0.042 | 18.10 |
| `ImageFont.truetype` real load | 0.002 | 0 | 0 | 0 | 7 wywołań/cały run |
| resize | 0 | 0 | 0 | 0 | 0 |
| rotate/transpose | 0 | 0 | 0 | 0 | 0 |
| transform | 0 | 0 | 0 | 0 | 0 |
| GaussianBlur/filters | 0 | 0 | 0 | 0 | 0 |
| konwersje NumPy w aktywnym `compose_overlay` | 0 | 0 | 0 | 0 | 0 |

Metryki API Pillow są **inkluzywne**: np. `alpha_composite` wewnętrznie wykonuje operacje crop/paste. Nie wolno ich sumować. Czas `indicator.*.total` i `compose.total` jest właściwym czasem ściennym.

Fonty są cache'owane poprawnie. Było 20 474 lookupów cache (18.10/frame), ale tylko 7 rzeczywistych wywołań `ImageFont.truetype` w całym eksporcie. Nie wykryto ładowania fontu per-frame.

## Supersampling, bitmapy tymczasowe i dirty bbox

Wszystkie aktywne wskaźniki mają efektywny supersampling **1×**. Żaden aktywny widget nie wykonał resize/rotate/transform. Canvas ma 8 294 400 pikseli.

| Indicator | Output bitmap | Output px | Największy `Image.new` px/call | Liczba `Image.new` | Dirty px AVG | Dirty % HUD |
|---|---:|---:|---:|---:|---:|---:|
| `time_block` | 225×131 | 29 475 | 311 040 | 38 | 64 355 | 0.776% |
| `fit_cadence_text` | 1160×511 | 592 760 | 561 340 | 2 | 732 840 | 8.835% |
| `fit_enhanced_speed_text` | 648×648 | 419 904 | 419 904 | 2 | 413 504 | 4.985% |
| `fit_gopro_battery_text` | 267×54 | 14 418 | 31 696 | 1 | 46 498 | 0.561% |
| `fit_heart_rate_text` | 1160×511 | 592 760 | 561 340 | 2 | 732 840 | 8.835% |
| `iso_text` | około 282×51 | 14 394 AVG | 32 692 | 740 | 47 459 | 0.572% |
| `exposure_text` | około 238×51 | 12 157 AVG | 28 309 | 291 | 41 772 | 0.504% |
| `temp_text` | 316×51 | 16 116 | 35 748 | 1 | 51 876 | 0.625% |
| `track_map` | 691×691 | 477 481 | 3 211 264 | 1 | 594 441 | 7.167% |

Największa nieproporcjonalna bitmapa tymczasowa to cache mapy 1792×1792 (3.21 Mpx) dla finalnego widgetu 691×691. Jest tworzona raz, ale kopiowana co klatkę przed markerem/cropem. Time block tworzy 960×324 tylko przy zmianie sekundy; pozostałe statyczne bitmapy są tworzone raz lub na zmianę tekstu.

## Full-canvas operations

| Operation | AVG amortyzowane | Wywołania | Faktyczny koszt/call | Konieczność |
|---|---:|---:|---:|---|
| inicjalne wyczyszczenie persistent canvas 3840×2160 | 0.003 ms/frame | 1 | 3.261 ms | tak, inicjalizacja |

Nie ma per-frame operacji Pillow, która faktycznie skanuje cały canvas 3840×2160. Kolejne czyszczenia są regionalne: AVG 2.009, P95 2.664, P99 3.983 ms. `base_img.alpha_composite(widget, dest)` działa na obiekcie będącym pełnym canvasem, ale Pillow ogranicza przetwarzanie do prostokąta widgetu; wykrywane wewnętrzne `crop` nie oznacza skanu 8.29 Mpx.

## Mapa

| Podetap | AVG | Median | P95 | P99 |
|---|---:|---:|---:|---:|
| background tiles / kopia cached grid | 2.921 | 2.682 | 3.296 | 5.009 |
| route polyline | 0.001 | 0 | 0 | 0 |
| current marker | 0.049 | 0.046 | 0.062 | 0.109 |
| position lookup/interpolation | 0.015 | 0.014 | 0.024 | 0.038 |
| crop do 691×691 | 0.534 | 0.507 | 0.655 | 0.992 |
| rotation/resize | 0 | 0 | 0 | 0 |
| composite na finalny HUD | 4.436 | — | 5.066 | — |
| **TOTAL indicator** | **8.807** | **8.198** | **10.166** | **21.080** |

Kafelki są w cache pamięci/dysku. Grid tła i route są zbudowane raz; `route_polyline` wykonał się raz. Co klatkę wykonywane są: kopia dużego cached grid, marker, crop i alpha composite. To kopia tła, a nie pobieranie/renderowanie kafelków, odpowiada za większość `background_tiles`.

## Wykresy

| Podetap | Cadence AVG/P95 | Heart rate AVG/P95 |
|---|---:|---:|
| cached history + current cursor | 0.889 / 1.124 | 0.612 / 0.756 |
| sam current cursor | 0.862 / 1.096 | 0.593 / 0.735 |
| static background/axes/grid/history build | 2 wywołania łącznie dla obu wykresów; 0.008 ms/frame amortyzowane | jw. |
| background/chart assembly | 3.304 / 4.465 | 2.649 / 3.172 |
| dynamic value label | 0.749 / 1.052 | 0.747 / 0.893 |
| render | 5.215 / 7.144 | 4.227 / 5.321 |
| paste na HUD | 3.796 / 4.843 | 3.440 / 4.093 |
| **TOTAL** | **9.177 / 15.188** | **7.819 / 9.901** |

Osie, grid i cała historyczna polilinia nie są przerysowywane co klatkę — znajdują się w `_CHART_BG_CACHE`. Co klatkę kopiowane jest cached tło, rysowany cursor, kopiowany nagłówek, wklejany chart, rysowana bieżąca wartość, a wynik jest composited na HUD.

## Telemetry/frame_data

| Podetap | AVG | Median | P95 | P99 |
|---|---:|---:|---:|---:|
| `prepare_overlay_frame_data` TOTAL | **9.281** | **5.810** | **17.176** | **18.930** |
| direct interpolation/lookups GPMF | 3.960 | 2.126 | 9.791 | 10.648 |
| dynamic FIT fields | 5.167 | 3.710 | 11.500 | 13.490 |
| `resolve_cache_value` (wewnątrz dynamic FIT) | 5.054 | 3.633 | 11.261 | 13.163 |
| date/time | 0.053 | 0.043 | 0.150 | 0.197 |
| range calculations | 0.003 | 0.003 | 0.008 | 0.010 |
| graph position/data | 0.002 | 0.001 | 0.003 | 0.005 |
| map/GPS data handoff | <0.001 | 0 | 0.001 | 0.001 |

`resolve_cache_value` wykonał **18 wywołań/frame**. Kod rozwiązuje wszystkie odkryte FIT fields, również te nieaktywne w layoutcie; jest to realny kandydat do następnego etapu, ale nie został zmieniony. `dynamic FIT fields` zawiera `resolve_cache_value`, więc tych wierszy nie należy sumować.

## TOP 15 CPU bottlenecks

Denominator „CPU frame” to wall-clock profiled run: 61.388 ms/encoded frame. Ranking jest inkluzywny i świadomie pokazuje zarówno kontenery, wskaźniki, jak i operacje wewnętrzne; pozycje nakładające się nie są sumowalne.

| Rank | Operation / indicator | AVG ms | P95 | % compose | % CPU frame |
|---:|---|---:|---:|---:|---:|
| 1 | `compose.total` | 34.727 | 46.675 | 100.0% | 56.6% |
| 2 | Pillow `alpha_composite` | 23.131 | 30.474 | 66.6% | 37.7% |
| 3 | telemetry total | 9.281 | 17.176 | 26.7% | 15.1% |
| 4 | cadence indicator total | 9.177 | 15.188 | 26.4% | 14.9% |
| 5 | map indicator total | 8.807 | 10.166 | 25.4% | 14.3% |
| 6 | Pillow `paste` | 7.913 | 11.167 | 22.8% | 12.9% |
| 7 | heart-rate indicator total | 7.819 | 9.901 | 22.5% | 12.7% |
| 8 | graph background/chart assembly | 5.953 | 8.701 | 17.1% | 9.7% |
| 9 | Pillow `copy` | 5.801 | 7.264 | 16.7% | 9.4% |
| 10 | dynamic FIT fields | 5.167 | 11.500 | 14.9% | 8.4% |
| 11 | `resolve_cache_value` | 5.054 | 11.261 | 14.6% | 8.2% |
| 12 | interpolation/lookups | 3.960 | 9.791 | 11.4% | 6.5% |
| 13 | speed gauge total | 3.627 | 4.456 | 10.4% | 5.9% |
| 14 | text drawing | 3.234 | 5.659 | 9.3% | 5.3% |
| 15 | Pillow `crop` | 3.221 | 3.978 | 9.3% | 5.2% |

## Golden i poprawność

| Kontrola | Wynik |
|---|---|
| Frame 30 MAE/MAX/P95/P99 | 0 / 0 / 0 / 0 — PASS |
| Frame 300 MAE/MAX/P95/P99 | 0 / 0 / 0 / 0 — PASS |
| Frame 900 MAE/MAX/P95/P99 | 0 / 0 / 0 / 0 — PASS |
| Final MP4 SHA-256 ETAP 5A | `6E0884960B5530BA305F5391BF45FF0BE801DE7391D0DA14A009E6B1DB25E693` |
| Final MP4 SHA-256 ETAP 4 real GUI | ten sam — byte-identical |
| AAC payload SHA-256 | `549C551024C0171D679CC8ADB6CE35E6530291F75DF485B51DFEEE7A3E72EC55` — identyczny |
| FIT / GPMF / Map / Date-time / HUD / Color / Audio | PASS |
| AMF INPUT_FULL / retries / drops | 0 / 0 / 0 |
| Testy | 166 passed, 17 skipped |

Finalny plik: `Raporty/AMD_ETAP5A/full_gui_profile_1131.mp4`. Surowe metryki: `full_gui_profile_1131.mp4.amd_profile.json`.

## Proponowane następne małe etapy

Nie zostały zaimplementowane.

1. **5B — pomijanie resolve nieaktywnych FIT fields.** Ograniczyć 18 lookupów do pól rzeczywiście konsumowanych przez aktywne wskaźniki. Oczekiwane 3–4.5 ms/frame. Risk: **LOW**. Wygląd HUD: nie powinien się zmienić; wymaga testu pól dynamicznie włączanych.
2. **5C — mapa: crop cached background przed kopią i markerem.** Uniknąć per-frame kopii 1792×1792, operować na finalnym 691×691 regionie z zachowaniem tej samej kolejności alpha. Oczekiwane 2–3 ms/frame. Risk: **MEDIUM**. Wygląd: może się zmienić przy błędzie współrzędnych/krawędzi, dlatego wymagane exact A/B.
3. **5D — wykresy: cache finalnego statycznego assembly.** Połączyć cached history/axes/grid/header raz, a per-frame dorysować wyłącznie cursor i wartość; usunąć dwie duże kopie/paste na chart. Oczekiwane 4–7 ms/frame dla obu wykresów. Risk: **MEDIUM**. Wygląd: teoretycznie bez zmian, ale kolejność alpha musi być identyczna.
4. **5E — regionalne compositing/clear Pillow.** Zmierzyć i zastąpić złożenia przez jawne operacje tylko na bbox widgetów, bez zmiany pixel math; cel to część 23.1 ms inkluzywnego alpha composite i 2.0 ms regional clear. Oczekiwane 3–6 ms/frame. Risk: **HIGH**. Wygląd może zmienić się na krawędziach alfa, więc wymagany pixel-exact fallback/A-B.

Na podstawie stosunku zysk/ryzyko kolejny etap powinien zacząć się od telemetrii (5B), mimo że największym całkowitym kosztem pozostaje HUD. Zatrzymano się po profilowaniu ETAPU 5A.
