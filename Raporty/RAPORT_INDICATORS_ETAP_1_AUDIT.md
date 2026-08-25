# TeleM — ETAP 1: audyt istniejących wskaźników względem docelowego layoutu

Data audytu: 2026-08-21  
Zakres: wyłącznie audyt statyczny istniejącej implementacji.  
Zmiany w kodzie aplikacji: nie wykonano.

## Konkluzja

TeleM ma już działającą, konfigurowalną bazę dla większości elementów docelowego dashboardu. Istnieją wspólne renderery tekstu, belki, segmentów, gauge, wykresu i mapy, a GUI zapisuje layout jako JSON. Największa różnica między kodem a wymaganym layoutem nie polega obecnie na braku osobnego renderera dla każdego pola, tylko na tym, że aktywny `def_layout.json` używa głównie dynamicznych pól FIT i prostych bloków tekstowych.

Elementy wymagające rzeczywistego rozszerzenia to:

- zakres czasowy wykresów cadence/heart-rate,
- semantyka kompasu i ewentualnie orientacja mapy względem kierunku jazdy,
- źródło/wiązanie danych dla slope i heading,
- osobny mechanizm dla wskaźnika przechyłu roweru, razem z assetem lub określeniem geometrii,
- docelowa konfiguracja presetu i włączenie istniejących rendererów dla distance, altitude, power oraz baterii/solara.

Nie ma podstaw do zmiany architektury renderowania, łączenia ścieżek AMD/NVIDIA ani do wprowadzania nowej wspólnej klasy bazowej.

## 1. Obecny pipeline wskaźników

Przepływ danych i renderowania wygląda następująco:

```text
FIT / GPMF / GPX / metadata
        ↓
resolver i synchronizacja telemetryczna
        ↓
interpolacja / smoothing / konwersja jednostek / formatowanie
        ↓
prepare_overlay_frame_data()
        ↓
compose_overlay() / render_preview()
        ↓
Pillow CPU reference albo selektywny upload/compositing GPU
        ↓
preview GUI albo finalny eksport FFmpeg
```

Najważniejsze punkty implementacji:

- `src/indicators/frame_data.py:65` przygotowuje wartości per klatka, `extra_indicators`, czas aktywności i średnią prędkość.
- `src/indicators/dispatcher.py:26` wybiera renderer na podstawie `form`.
- `src/indicators/compositor.py:51` składa overlay, zachowuje kolejność layoutu i obsługuje dirty bounding-boxes.
- `src/indicators/compositor.py:152` i `:199` renderuje specjalnie `time_block` oraz `time_display` przed zwykłą pętlą wskaźników.
- `src/indicators/compositor.py:274` przechodzi po pozostałych wskaźnikach w kolejności wpisów layoutu.
- `src/indicators/compositor.py:564` udostępnia ścieżkę preview opartą o ten sam compositor.
- `src/overlay_renderer.py` re-eksportuje kompatybilnie funkcje z pakietu `src.indicators` dla starszych wywołań.

Wartości telemetryczne nie powinny być ponownie rozwiązywane w rendererach. Obecny kod zasadniczo zachowuje ten kontrakt: renderer otrzymuje wartość, historię albo track, a nie wybiera samodzielnie źródła telemetrycznego.

## 2. Inwentarz rendererów

| Typ / plik | Obecne możliwości | Ograniczenia istotne dla layoutu |
|---|---|---|
| `text.py` | Tekst, label, unit, kolor, font, outline, cache rasteru | Brak ikon i assetów obrazkowych |
| `custom_text.py` | Dowolny tekst użytkownika, rozmiar, kolor, obrót | To nadal tekst, nie renderer wskaźnika obrazkowego |
| `time_block.py` | Trzy linie: label/date/time | Nie zawiera elapsed time ani average speed |
| `time_display.py` | Date, current time, elapsed, average speed; każda linia może być włączona i stylowana | Nie jest używany w obecnym aktywnym `def_layout.json` |
| `bar.py` | Ruler z markerem, tickami i zakresem oraz `segments` z aktywnymi/nieaktywnymi segmentami | Renderer segmentów jest poziomy; pionowość wynika z obrotu compositora |
| `segment_bar.py` | Kompatybilny shim do `bar.py` | Brak osobnego silnika |
| `gauge.py` | Zakres, ticki, subticki, etykiety, needle, marker, wartość centralna, sweep/start angle | Brak semantyki kompasu, kierunku kardynalnego i obracanej tarczy |
| `chart.py` / `chart_builder.py` | Historia, linia, fill, grid, etykiety, średnia, cursor, clipping, cache i split GPU | GUI oferuje tylko zakres `activity`/`video`, bez dowolnego `window_s` |
| `moving_map.py` | Mapa z trasą, aktualną pozycją, markerem, zoomem, stylem, kolorem i kształtem | Brak track-up/orientacji według headingu; obecna mapa jest north-up |
| `static_map.py` / `map_renderer.py` | Render statyczny, cache/precache tile’i, route i marker | Nie jest to osobny renderer headingu ani kompasu |
| `rotated_paste.py` | Kompozycja z obrotem 90/180/270 stopni i ochroną przed overlapem | Nie zapewnia płynnego obrotu wskazówki lub obrazu według wartości |
| `gpu_compositor.py` | Ogólne operacje OpenCL: blend/resize/rotate/composite | Nie jest podstawowym, osobnym rendererem wskaźników dla finalnego NVIDIA/AMD |

Rejestr typów znajduje się w `src/indicators/registry.py`, a dispatch w `src/indicators/dispatcher.py:26-112`.

## 3. Obecne wskaźniki i aktywny layout

### 3.1. Layout kodowy

`src/gui/layout_manager.py:174` tworzy fallbackowy layout zawierający m.in. `time_block`, gauge prędkości, bar odległości, pionowy bar wysokości, teksty ISO/shutter/temperature/power/heart-rate/cadence/battery oraz `track_map` wyłączony domyślnie.

### 3.2. Layout faktycznie ładowany przy starcie

`src/gui/qt/controller.py:134-136` uruchamia `_load_startup_preset()`, a `:255-263` ładuje `def_layout.json`, jeśli plik istnieje. Dlatego bieżący wygląd aplikacji należy oceniać przede wszystkim na podstawie `def_layout.json`, a nie tylko `default_layout()`.

W aktywnym `def_layout.json` włączone są obecnie:

- `time_block`,
- `fit_cadence_text` jako chart,
- `fit_enhanced_speed_text` jako gauge,
- `fit_heart_rate_text` jako chart,
- `fit_temperature_text` jako text,
- `iso_text`, `exposure_text`, `temp_text`,
- `track_map` jako map,
- `fit_battery_text`, `fit_battery_pct_text`, `fit_solar_pct_text` jako text.

Wyłączone pozostają m.in. `dist_visual`, `dist_text`, `alt_visual`, `alt_text`, `power_text`, `time_display` oraz większość dynamicznych pól FIT. Oznacza to, że część targetu jest już obecna funkcjonalnie, ale nie jest jeszcze ułożona jako docelowy preset.

## 4. Porównanie 16 elementów docelowych

Legenda stanu: `GOTOWY` = istniejący renderer i wiązanie wystarczają do celu; `PRAWIE GOTOWY` = funkcja istnieje, ale wymaga konfiguracji/presetu lub ma małą lukę; `WYMAGA ROZSZERZENIA` = istnieje baza, lecz brakuje istotnej funkcji lub danych; `BRAK` = brak obecnej implementacji użytecznej dla celu.

| Docelowy element | Obecna implementacja | Stan | Brakujące funkcje | Pliki do potencjalnej zmiany | CPU | AMD | NVIDIA | Ryzyko |
|---|---|---|---|---|---|---|---|---|
| A. Time Block: timestamp/date/activity time/avg speed | `time_display.py` ma cztery linie; `frame_data.py` dostarcza elapsed i avg speed. Aktywny preset używa tylko `time_block`. | PRAWIE GOTOWY | Włączyć `time_display` w presecie i ustalić docelowe formatowanie/pozycję. | `src/indicators/time_display.py`, `src/indicators/frame_data.py`, `src/gui/qt/models.py`, `def_layout.json` | Dostępny | Render pozostaje CPU HUD; brak osobnej zmiany AMD | Renderowany jako część CPU HUD/uploadu | Pomylenie `time_block` z `time_display`; z-order specjalnie obsługiwany przed pętlą |
| B. Distance Progress | `bar.py` ruler, `dist_visual`, `dist_text`; zakres distance może być dynamicznie nadpisany. | PRAWIE GOTOWY | Ustawić źródło, max/range, label i styl w docelowym presecie. | `src/indicators/bar.py`, `src/indicators/frame_data.py`, `src/gui/layout_manager.py`, `def_layout.json` | Dostępny | Brak osobnego GPU renderera; zwykły element CPU HUD | CPU raster + upload/overlay CUDA | Wartość i jednostka muszą pozostać zgodne z resolverem; nie dublować interpolacji |
| C. Garmin Edge Battery | Dynamiczne pola FIT `fit_battery_text`/`fit_battery_pct_text`; registry potrafi dobrać segment bar, ale aktywny layout używa text. | PRAWIE GOTOWY | Skonfigurować `bar_style=segments`, zakres 0–100, segmenty, kolor i źródło. | `src/indicators/registry.py`, `src/indicators/bar.py`, `src/gui/qt/models.py`, `def_layout.json` | Dostępny | CPU HUD; bez potrzeby zmiany ścieżki GPU | CPU raster; brak dedykowanego NVIDIA renderera | Niejednoznaczność `battery` vs `battery_pct`; kontrola jednostek i skali x100 |
| D. Garmin Solar Power | `fit_solar_text`/`fit_solar_pct_text` oraz ten sam generic bar/segments. W aktywnym layoucie solar jest text. | PRAWIE GOTOWY | Wybrać właściwe pole procentowe albo moc, dobrać jednostkę i formę segmentową. | `src/indicators/registry.py`, `src/indicators/bar.py`, `src/gui/qt/models.py`, `def_layout.json` | Dostępny | CPU HUD | CPU raster + overlay CUDA | Nie mieszać solar power z solar percentage; nie zmieniać resolvera priorytetów |
| E. Compass | Brak dedykowanego heading/compass. `gauge.py` ma regulowany arc i needle. | WYMAGA ROZSZERZENIA | Heading/course, normalizacja 0–360, kierunki N/E/S/W, opcjonalna tarcza obracana lub needle. | `src/indicators/gauge.py`, `src/indicators/dispatcher.py`/konfiguracja; ewentualnie istniejące wiązanie danych | Częściowa baza | Obecny gauge GPU ma guard; nowe elementy muszą zachować fallback CPU | CPU raster + overlay CUDA | Brak headingu w obecnym audycie; nie wolno wymyślać nowej polityki źródła |
| F. Bike/Lean Indicator | Brak assetu obrazkowego, renderera image/sprite i danych lean/bike angle. `rotated_paste` obsługuje tylko stałe obroty 90/180/270. | BRAK | Źródło kąta, asset/geometria roweru, pivot, znak/invert, płynny obrót i konfiguracja. | Nowy lokalny renderer/funkcja wskaźnika, `src/indicators/dispatcher.py`, schema/model GUI; po ustaleniu danych także wiązanie | Brak | Musi mieć jawny CPU fallback; nie zmieniać pipeline AMD w ramach tego audytu | Musi pozostać zgodny z CPU rasterem; brak runtime | Największa luka funkcjonalna; ryzyko assetu, pivotu i semantyki znaku |
| G. Dynamic Map | `moving_map.py`, `static_map.py`, `map_renderer.py`: route, marker, zoom, style, shape, current position. | WYMAGA ROZSZERZENIA | Track-up/orientacja według headingu, jeśli wymaga tego target; ewentualnie tryb north-up/track-up. | `src/indicators/moving_map.py`, `src/map_renderer.py`, konfiguracja mapy | Dostępny | AMD ma osobną ścieżkę mapy i z-order guard; rozszerzenie musi zachować fallback | Statycznie zachowana ścieżka region/atlas; brak runtime | Tile/cache i z-order; orientacja może zmienić koszt renderowania i bezpieczeństwo GPU |
| H. ISO | `iso_text` + `text.py`; aktywny w `def_layout.json`. | GOTOWY | Tylko docelowa pozycja/styl/label, jeśli różnią się od aktualnych. | Zwykle `def_layout.json`; opcjonalnie schema | Dostępny | CPU HUD | CPU raster + CUDA overlay | Formatowanie i źródło muszą pozostać bez zmian semantycznych |
| I. Shutter | `exposure_text` + formatowanie `1/{int(value)}` w compositorze; aktywny. | GOTOWY | Ewentualny styl i label docelowego layoutu. | `def_layout.json`, ewentualnie `src/indicators/compositor.py` tylko jeśli wymagany jest inny format | Dostępny | CPU HUD | CPU raster + CUDA overlay | Utrata formatu ułamkowego przy nieostrożnej zmianie |
| J. Temperature | `temp_text` oraz dynamiczny `fit_temperature_text`; text renderer; aktywny. | GOTOWY | Ustalić, czy target używa temperatury kamery czy FIT; skonfigurować label/jednostkę. | `def_layout.json`, schema/layout | Dostępny | CPU HUD | CPU raster + CUDA overlay | Dwa możliwe pola temperatury; nie wprowadzać nowego resolvera |
| K. Altitude | `alt_visual` jako bar z obrotem 90°, `alt_text`, dynamiczny zakres/min/max/ticki. | PRAWIE GOTOWY | Aktywować i ustawić targetowy zakres, skalę, rotację i pozycję. | `src/indicators/bar.py`, `src/indicators/frame_data.py`, `def_layout.json` | Dostępny | CPU HUD; GPU guard tylko dla wybranych typów | CPU raster + CUDA overlay | Obroty, zakres dynamiczny i overlap z mapą mogą wymusić fallback |
| L. Virtual Power | `power_text` i dynamiczne FIT `fit_curVpower_text`; generic text/bar może pokazać skalę. Brak osobnego kalkulatora power w rendererze. | PRAWIE GOTOWY | Potwierdzić, że resolver dostarcza virtual power; wybrać text/ruler i zakres. | `src/indicators/frame_data.py`, `src/indicators/bar.py`, `def_layout.json` | Dostępny, jeśli wartość jest w danych | CPU HUD | CPU raster + CUDA overlay | Nie implementować obliczeń w rendererze; rozróżnić curVpower od innych power |
| M. Cadence History Chart | `fit_cadence_text` jako chart jest aktywny; wspólny `chart.py` obsługuje line/fill/grid/cursor. | WYMAGA ROZSZERZENIA | Konfigurowalne okno historii w sekundach zamiast tylko `activity`/`video`; docelowe zakresy i etykiety. | `src/indicators/chart_builder.py`, `src/indicators/chart.py`, `src/gui/qt/models.py`, schema | Dostępny | AMD ma `GPU_SPLIT`/fallback CPU; overlap/obrót mogą wyłączyć GPU | CPU chart raster + region/atlas overlay; statycznie zachowany | Dużo punktów i fill/grid; layout overlap może przełączyć całość na CPU_REFERENCE |
| N. Speedometer | `fit_enhanced_speed_text` jako gauge jest aktywny; `gauge.py` ma needle, ticki, zakres, wartość i konfigurowalny sweep. | PRAWIE GOTOWY | Ustawić duży okrągły wariant, zakres i styl targetowego layoutu; renderer nie wymaga nowego typu. | `def_layout.json`, `src/gui/qt/models.py`; ewentualnie `gauge.py` tylko dla kosmetyki | Dostępny | Istnieje GPU gauge z guardem i CPU fallbackiem | CPU raster + CUDA overlay | Kolizje z innymi elementami mogą wymusić fallback; nie zmieniać z-order |
| O. Heart Rate History Chart | `fit_heart_rate_text` jako chart jest aktywny; ten sam renderer co cadence. | WYMAGA ROZSZERZENIA | Takie samo okno historii, zakres i konfiguracja osi jak dla cadence. | `src/indicators/chart_builder.py`, `src/indicators/chart.py`, `src/gui/qt/models.py` | Dostępny | GPU split/fallback zależny od geometrii | CPU chart raster + region/atlas overlay | Koszt i clipping przy większej historii; wspólny kod musi zachować parity cadence/HR |
| P. Slope | Brak osobnego slope field/wiązania. `bar.py` może narysować zakres ujemny/dodatni, jeśli dostanie wartość. | WYMAGA ROZSZERZENIA | Dostęp slope/grade, zero-centered scale, znak, jednostka i konfiguracja bar/ruler. | `src/indicators/bar.py`/schema, istniejące wiązanie danych po potwierdzeniu pola; nie resolver ad hoc | Renderer częściowo dostępny | CPU HUD; nie zmieniać backendu | CPU raster + CUDA overlay | Najpierw trzeba ustalić semantykę i źródło; nie mylić slope z altitude |

## 5. Macierz CPU / AMD / NVIDIA

| Obszar | CPU reference | AMD | NVIDIA |
|---|---|---|---|
| Tekst, time block, time display | Pełny render Pillow i compositor | Pozostaje częścią CPU HUD; nie ma potrzeby zmiany ścieżki | CPU raster jest przesyłany do finalnego overlay; brak osobnego renderera NVIDIA |
| Bar/segment bar | Pełny render Pillow | Zwykle CPU HUD; nie należy dodawać transferu tylko dla zmiany stylu | CPU raster + upload/overlay CUDA |
| Gauge | Pełny render Pillow, baseline poprawności | `amd_native_exporter.py` ma opcjonalny GPU gauge, ale guard overlap/rotacji może wymusić CPU_REFERENCE | CPU raster + CUDA overlay |
| Charts | Pełny render Pillow | Możliwy GPU split, lecz unsafe layout wraca do CPU_REFERENCE | CPU chart raster; region/atlas i `overlay_cuda` |
| Map | Pełny render Pillow | Opcjonalna ścieżka GPU mapy z podziałem `CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP`; unsafe layout wraca do CPU_REFERENCE | Brak osobnej mapowej semantyki NVIDIA; wykorzystuje wspólny raster/region |
| Nowe elementy | Muszą najpierw mieć poprawny baseline CPU | AMD może zostać rozszerzony dopiero po porównaniu z CPU reference | NVIDIA powinien zachować obecny upload/overlay i nie wymagać nowego backendu wskaźników |

Istotne punkty AMD znajdują się w `src/ffmpeg/amd_native_exporter.py`, m.in. guardy layoutu około linii 145, 178 i 227 oraz diagnostyka ścieżek około 843-937. NVIDIA używa ścieżki w `src/ffmpeg/streaming.py` i `src/ffmpeg/command_builder.py`, w tym `scale_cuda`/`overlay_cuda` około 619-765.

Obowiązujące ograniczenie testowe: ścieżka NVIDIA została zachowana i sprawdzona statycznie; runtime NVIDIA nie był możliwy na tej maszynie AMD.

## 6. Preview kontra final render

Preview i finalny CPU reference korzystają z tego samego modelu danych oraz tego samego compositora:

- `src/gui/qt/_mixins/preview_mixin.py:312` przygotowuje dane overlay, a `:385` używa `render_preview()`.
- `src/ffmpeg/frame_renderer.py:125` przygotowuje dane dla finalnego renderu, a `:209`, `:240`, `:276` i `:452` wywołuje `compose_overlay()`.
- `render_preview()` w `compositor.py` jest wrapperem na ten sam mechanizm kompozycji, z `fast_preview=True`.

Wniosek: dla CPU nie ma osobnego, konkurencyjnego silnika wskaźników preview/final. Różnica powstaje dopiero wtedy, gdy finalny backend wybiera selektywny upload GPU. W AMD native wybrane mapy/charts/gauge mogą ominąć końcowy Pillow composite, ale tylko z zachowaniem guardów i CPU fallbacku. Każde nowe rozszerzenie musi najpierw zgadzać się z CPU reference, potem z preview, a dopiero na końcu z optymalizacją AMD.

## 7. Brakujące możliwości rendererów

1. Wspólny chart nie ma jawnego parametru typu `window_s`; istnieją tylko zakresy `activity` i `video` (`chart_builder.py:129`, GUI `chart_time_scope`).
2. Gauge nie ma modelu kompasu: brak kardynalnych etykiet, heading normalization i trybu dial/track direction.
3. Mapa nie ma w obecnym rendererze trybu track-up; parametry GUI typu `orient`/`rotate` nie tworzą kompletnej semantyki kierunku jazdy.
4. Brak resolverowego pola lub istniejącego wiązania dla slope/grade i heading, co należy potwierdzić przed implementacją.
5. Brak renderera obrazka/sprite’u z płynnym obrotem, pivotem i invert dla Bike/Lean.
6. GUI nie eksponuje wszystkich możliwości rendererów: np. renderer segmentów ma możliwości stylu/gradientu, których model GUI nie udostępnia w pełni.
7. Część funkcji występujących w schema mapy jest szersza niż faktycznie używany podzbiór `moving_map.py`; wymaga to rozdzielenia „pole zapisuje się w JSON” od „pole zmienia render”.

## 8. Czy potrzebny jest nowy typ wskaźnika?

Nie dla A-E, G, H-P jako osobnych rodzin:

- A: istniejący `time_display`;
- B, C, D, K, P: istniejący `bar`/`segments`;
- E: rozszerzenie `gauge`, nie nowy ogólny typ;
- G: rozszerzenie istniejącej mapy;
- H, I, J, L: `text`;
- M, O: `chart`;
- N: `gauge`.

F jest jedynym elementem bez użytecznej istniejącej rodziny. Potrzebuje lokalnego mechanizmu image/rotating indicator albo jawnie zdefiniowanej geometrii symbolu. Nie należy z tego powodu przebudowywać całego dispatcher/registry.

## 9. Ryzyka z-order i compositingu

- `compose_overlay()` renderuje `time_block` i `time_display` przed zwykłą kolejnością layoutu.
- Pozostałe wskaźniki zachowują kolejność wpisów w `layout["indicators"]`; kolejność jest częścią kontraktu wizualnego.
- `rotated_paste.py` i dirty bounding-boxes czyszczą poprzednie obszary z marginesem 40 px. Zmiana rozmiaru, rotacji lub pivotu może odsłonić artefakty, jeśli bbox nie obejmie pełnego obiektu.
- AMD dzieli mapę na części pod i nad mapą. Dodanie wskaźnika w obszarze mapy może zmienić wynik guardu i wymusić CPU_REFERENCE.
- AMD charts/gauge mają guardy dla overlapu i rotacji; targetowy layout z nakładającym się gauge/chart/map może obniżyć udział GPU, nawet jeśli obraz pozostanie poprawny.
- NVIDIA direct-region/atlas opiera się na anchorach i własności regionu. Nietypowe pozycje lub overlap mogą wrócić do legacy full-canvas path.
- Nie należy usuwać guardów ani wymuszać GPU kosztem różnicy względem CPU reference.

## 10. Ryzyka wydajnościowe

Najdroższe elementy docelowego layoutu to:

- dynamiczna mapa: tile’e, projekcja i rysowanie pełnego tracku, marker, precache oraz upload;
- dwa wykresy z historią, fill, gridem, etykietami i kursorem;
- gauge z supersamplingiem, tickami, etykietami i cieniem;
- dużo tekstów z outline/font cache przy rozdzielczości 4K/60;
- rotacje, alpha compositing, dirty-region scans i przejścia CPU↔GPU.

Szczególne ryzyko stanowi niepotrzebny transfer `GPU → CPU → GPU`. Obecna hybrydowa architektura już ma jawne CPU fallbacki i split paths; nie należy dodawać kolejnego round-trip tylko po to, aby uprościć implementację wskaźnika.

Nie wykonywano w tym etapie benchmarków. Wydajność należy mierzyć po ustaleniu finalnego presetu, bo dopiero wtedy znane są rozmiary, overlap, liczba chartów i aktywne ścieżki backendu.

## 11. Istniejące testy

Znalezione testy pokrywają znaczną część istniejącej infrastruktury:

- gauge: `tests/test_gauge_rendering.py`, `tests/test_etap8m5_gauge_parity.py`;
- bar/segments: `tests/test_bar_integration.py`;
- charts: `tests/test_chart_rendering.py`, `test_chart_label_clipping_bounds.py`, `test_chart_fixed_timeline_reveal.py`, `test_chart_static_assembly_etap5d.py`, `test_etap8m4_chart_time_scope.py`, `test_etap8m6_chart_labels.py`, `test_etap8m7_chart_frame_clipping.py` oraz testy precompute/prefix;
- mapy i z-order: `tests/test_map_sync.py`, `test_etap8m_resolution_and_map.py`, `test_etap8u_a.py`, `test_etap8u_b.py`, `test_etap8u_c.py`, `test_amd_native_ordered_map.py`, `test_amd_native_ordered_map_clear.py`, `test_amd_native_above_dirty_bbox.py`, `test_nvidia_map_region_bounds.py`;
- compositor/preview/layout: `test_compositing_etap5e.py`, `test_etap8m3_runtime_layout_and_parity.py`, `test_etap8n_multi_region_above.py`, `test_etap8s_flush_batching.py`, `test_etap8q_dirty_text_cache.py`, `test_indicator_drag.py`, `test_layout_manager.py`, `test_controller_properties.py`, `test_render_tab.py`;
- telemetry/data flow: `test_etap1_source_resolver.py`, `test_interpolation.py`, `test_gpmf_timing.py`, `test_fit_registration.py`, `test_fit_available_fields_catalog.py`, `test_etap8o_precomputed_telemetry.py`, `test_etap8p_b_fast_builder.py`;
- AMD/NVIDIA: `test_amd_native_etap1.py`–`test_amd_native_etap5b.py`, `test_nvidia_regression_chart_preview.py`, `test_nvidia_etap5b4_precise_text_bbox.py`, `test_nvidia_map_region_bounds.py`.

Nie znaleziono dedykowanych testów dla: compass, bike/lean, slope, `time_display`, arbitralnego okna historii wykresu, assetów obrazkowych i płynnego obrotu wskazówki. W tym audycie testów nie uruchamiano; wykonano analizę statyczną i kontrolę repozytorium.

## 12. Rekomendowane następne etapy

1. Zamrozić ten audyt jako baseline i przygotować osobny preset docelowego dashboardu. Najpierw użyć istniejących rendererów bez zmian w backendach.
2. Włączyć/configure’ować A, B, C, D, K, L, N oraz istniejące H, I, J w `def_layout.json`; sprawdzić pozycje, jednostki, zakresy i z-order.
3. Dodać konfigurację okna historii chartów dla M/O, zachowując obecne `activity`/`video` jako kompatybilne wartości domyślne.
4. Potwierdzić, które pola telemetryczne istnieją dla heading, slope i lean. Jeśli ich nie ma w obecnym resolverze, zaplanować osobne zadanie data-binding; nie implementować polityki źródła w rendererze.
5. Rozszerzyć gauge o minimalny tryb kompasu albo ustalić, że kompas jest osobnym lokalnym rozszerzeniem gauge. Najpierw CPU reference, potem preview i dopiero AMD guard/GPU.
6. Zaprojektować Bike/Lean: asset/geometria, pivot, znak, zakres i płynny obrót. Dodać test CPU reference i test parity przed dotykaniem GPU.
7. Dopiero po ustaleniu geometrii wykonać wizualne porównanie CPU reference vs preview vs final CPU/AMD. NVIDIA pozostawić statycznie zachowaną i zweryfikować runtime na maszynie NVIDIA.

## 13. Konkretne pliki potencjalnie do zmiany

### Preset i GUI

- `def_layout.json` — konfiguracja docelowego układu, bez zmiany architektury.
- `src/gui/layout_manager.py` — tylko jeśli preset ma dostać nowy zestaw ustawień domyślnych.
- `src/gui/qt/controller.py` — zasadniczo nie wymaga zmiany; potwierdza ładowanie `def_layout.json`.
- `src/gui/indicator_schemas.py` i `src/gui/qt/models.py` — nowe pola chart window, compass, slope lub lean.
- `src/gui/qt/_mixins/indicator_mixin.py`, `preset_mixin.py`, `video_preview.py` — tylko dla obsługi nowych pól i interakcji.

### Istniejące renderery

- `src/indicators/time_display.py` — raczej bez zmiany; wykorzystać istniejący renderer.
- `src/indicators/bar.py` — ewentualne rozszerzenie konfiguracji ruler/segments, zwłaszcza dla slope lub lepszego GUI.
- `src/indicators/gauge.py` — minimalne rozszerzenie dla compass.
- `src/indicators/chart.py` i `src/indicators/chart_builder.py` — konfigurowalne okno historii.
- `src/indicators/moving_map.py` i ewentualnie `src/map_renderer.py` — tylko jeśli target wymaga track-up/orientacji.
- `src/indicators/dispatcher.py`, `registry.py` — tylko dla nowego Bike/Lean mechanizmu lub nowego pola konfiguracji; nie refaktoryzować bez potrzeby.
- nowy lokalny moduł pod `src/indicators/` — potencjalny renderer Bike/Lean, jeśli zostanie zatwierdzona forma assetu/geometrii.

### Dane

- `src/indicators/frame_data.py` — konsumpcja już rozwiązanego heading/slope/lean, jeśli architektura danych zostanie rozszerzona osobnym zadaniem.
- `src/gui/qt/_mixins/indicator_mixin.py` — mapowanie dostępnych pól do wskaźników.

### Pliki, których nie należy zmieniać w ramach zwykłego audytu/layoutu

- `src/ffmpeg/amd_native_exporter.py`, `src/ffmpeg/streaming.py`, `src/ffmpeg/command_builder.py` — ścieżki GPU/encoderów i guardy z-order;
- konfiguracja FFmpeg, AMF, NVENC, D3D11, CUDA i formatów pikseli;
- parsery i polityka źródeł FIT/GPMF/GPX, synchronizacja oraz resolver telemetryczny.

## Stan repozytorium przed i po audycie

Repozytorium było już zmodyfikowane przed rozpoczęciem tego zadania. Zastane zmiany obejmowały m.in. `AGENTS.md`, `src/ffmpeg/amd_native_exporter.py`, `src/ffmpeg/command_builder.py`, liczne usunięcia/artefakty w `scratch/`, dodatkowe raporty, `debug/` oraz testy AMD/NVIDIA. Nie zostały cofnięte ani nadpisane.

Jedynym plikiem utworzonym przez ten audyt jest niniejszy raport. Kod aplikacji nie został zmieniony.

