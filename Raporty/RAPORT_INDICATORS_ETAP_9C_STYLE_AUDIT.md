# TeleM — ETAP 9C: audyt pixel-style typografii, linii i ikonografii

Data: 2026-08-22  
Zakres: **AUDYT ONLY**. Nie zmieniano `src/*`, `presets/*` ani `wzor/*`.

## 1. Reference / current frame

Porównano:

- wzorzec: `wzor/00000.png`;
- aktualny preset: `presets/cycling_dashboard_v7.json`;
- klatka v7: `Raporty/INDICATORS_ETAP_9C_V7_REFERENCE_FRAME.png`;
- rozdzielczość: `3840×2160`, około `60 s`.

Geometria v7 została potraktowana jako baseline. Nie wykonywano kolejnego audytu położeń mapy, chartów, Distance, Slope ani Compass poza odnotowaniem ewidentnych różnic stylistycznych.

## 2. Główna diagnoza

Największa różnica nie wynika z layoutu, lecz z typografii i ikonografii:

1. wzorzec używa spójnego kroju pixel/segmentowego z kwadratowymi zakończeniami znaków;
2. v7 używa zwykłego fontu FreeType/Arial z klasycznym wygładzaniem i outline;
3. wzorzec ma własne ikony zegara, kamery, temperatury, baterii i markerów, których v7 nie odwzorowuje jako osobnych assetów;
4. v7 ma poprawną ogólną rodzinę kolorów, ale ticki/markery są zbyt „wektorowe” i zbyt gładkie;
5. różnica stylu jest globalna dla tekstu, dlatego sama zmiana `font_size` nie osiągnie pixel-parity.

## 3. Typography audit

### Time / Date / Activity

| Cecha | v7 | Wzorzec | Ocena / decyzja |
|---|---|---|---|
| Rodzina fontu | Arial/FreeType | pixel/segment | **RENDERER/FONT ASSET CHANGE REQUIRED** |
| Cyfry | proporcjonalne, gładkie | segmentowe, kwadratowe | font asset, nie preset |
| Weight | regular | ciężki pixel | font asset |
| Spacing | klasyczny kerning | szeroki stały spacing | font asset/renderer |
| Outline | 1 px czarny | ciemna krawędź pixelowa | częściowo preset, głównie font |
| Wyrównanie | poprawne geometrycznie | bardziej zwarty blok | mała korekta font metrics |

Decyzja: **RENDERER/FONT ASSET CHANGE REQUIRED**. Istniejący `font_size` może zmienić skalę, ale nie rodzinę znaków. Nie znaleziono lokalnego pixel-font assetu do bezpiecznego użycia.

### ISO / Shutter / Temperature

Obecne `font_size=1.54` poprawia czytelność, ale v7 nadal ma gładki, proporcjonalny font i klasyczny zapis `SHUTTER: 1/2399`. Wzorzec używa krótszych pixelowych etykiet i silniejszego rytmu znaków. Odstępy można dostroić presetem, lecz identyczny wygląd wymaga wspólnego font assetu i prawdopodobnie kontrolowanego spacingu.

Decyzja: **FONT/ASSET** dla pełnej zgodności; `font_size`/pozycje są wystarczające tylko dla przybliżenia.

## 4. Top telemetry / Battery / Solar

Battery w v7 korzysta z istniejącego segment bara: 20 segmentów, gap `2`, radius `2`, gradient teal/green/yellow/orange. Wzorzec ma grubsze, bardziej pixelowe segmenty i silniejszy biały opis. Kształt segmentów jest dostępny presetowo, ale pixelowe krawędzie i ikonografia wymagają font/renderer.

Solar zachowuje status: **DATA SOURCE UNRESOLVED**. Audyt dotyczy wyłącznie wyglądu; nie rozwiązywano źródła i nie mapowano żadnego pola.

| Element | Różnica stylistyczna | Najmniejsza droga |
|---|---|---|
| Battery segments | v7 gładkie/zaokrąglone, wzorzec grubszy pixelowy | preset częściowo; renderer dla exact pixel |
| Battery label/value | Arial vs pixel | font asset |
| Solar bar | slot v7 istnieje, ale brak wiarygodnej wartości | data unresolved; style później |

## 5. Virtual Power

Ruler v7 używa szarej linii, regularnych ticków i pomarańczowego markera. Wzorzec ma jaśniejsze, bardziej kontrastowe ticki i pixelowy label/value. Istniejące properties `tick_width`, `track_color`, `tick_color`, `marker_color`, `value_font_scale` pozwalają uzyskać większość poprawy bez kodu.

Decyzja: **PRESET ONLY** dla kolorów, grubości i kontrastu; **FONT/ASSET** dla pixelowych liter.

## 6. Altitude

V7 ma cienki szary ruler i niebieski marker. Wzorzec ma grubsze białe ticki, bardziej wyraźny rytm major/minor oraz pixelowe etykiety. `tick_width`, `tick_color`, `marker_color` i `font_size` wystarczają do poprawy kontrastu, ale obecny bar nie oferuje pełnej kontroli nad pixelowym profilem ticków.

Decyzja: **PRESET ONLY** dla koloru/rozmiaru; **SMALL BAR CHANGE** dla dokładnego major/minor ratio i kwadratowych zakończeń.

## 7. Speed Gauge — szczegółowa tabela

| Element | v7 | Wzorzec | Typ różnicy | Potrzebna zmiana |
|---|---|---|---|---|
| Outer radius | `size=18.5`, duży centralny gauge | większy ciężar optyczny, pixel ring | niewielka | PRESET ONLY |
| Major ticks | 6 zakresów / istniejące major ticks | grube, jasne, segmentowe | styl linii | PRESET ONLY / gauge |
| Minor ticks | gładkie, regularne | gęstsze i bardziej kwadratowe | renderer geometry | SMALL GAUGE CHANGE |
| Tick length | z `thickness=2` | wyraźnie dłuższe major | konfiguracja | PRESET ONLY |
| Tick width | automatycznie wyliczana | bardziej stała i grubsza | renderer/style | SMALL GAUGE CHANGE |
| Value | `14.8 km/h`, Arial | duży pixelowy odczyt | font | FONT/ASSET |
| Unit | `km/h` | pixelowy, bliżej wartości | font/spacing | FONT/ASSET |
| Range labels | regularne cyfry | pixelowe, szerszy spacing | font | FONT/ASSET |
| Needle | czerwony trójkątny marker | czerwony, cięższy pixel/triangle | niewielka | PRESET ONLY; renderer dla exact |
| Needle width | `4` → wewnętrznie skalowana | optycznie grubsza | konfiguracja/render | PRESET ONLY |
| Needle length | `1.05` | podobna proporcja | brak istotnej różnicy | bez zmiany |
| Needle center | poprawny centralnie | poprawny centralnie | brak | bez zmiany |
| Colors | czerwony marker, białe ticki | czerwony marker, białe ticki | mała różnica odcienia | PRESET ONLY |
| Outline | 1 px czarny | pixel edge / mocniejszy kontrast | styl | font/gauge |

Największa różnica Speed Gauge: nie geometria, lecz **pixelowy profil ticków i font wartości**. Obecny renderer jest funkcjonalnie wystarczający, ale exact reference wymaga małej zmiany w `gauge.py` albo dedykowanego trybu pixel-style.

## 8. Compass

Compass i Speed Gauge należą do tej samej rodziny okrągłych gauge’y, ale wzorzec ma gęstsze, bardziej jednolite ticki oraz pixelowe cardinal labels. V7 ma cieńszy ring i gładkie litery. `compass_tick_degrees`, `compass_major_tick_degrees`, `compass_ring_width`, `compass_tick_width` i kolory są dostrajane presetem.

Decyzja: **PRESET ONLY** dla gęstości/grubości/koloru; **FONT/ASSET** dla pełnej zgodności cardinal labels. Nie zmieniano `heading` ani semantyki cardinals.

## 9. Slope

Wzorzec używa bardziej kontrastowego, kolorowego markera i prostych, cięższych pixelowych ticków. V7 ma jasny, chłodny track i żółty marker z białym borderem; przez to wygląda bardziej jak standardowy bar niż element wzorca.

`track_color`, `tick_color`, `zero_tick_color`, `marker_color`, `marker_border_color` i `marker_size` umożliwiają poprawę presetem. Kwadratowe zakończenia i dokładny pixel marker wymagałyby małej zmiany w `_render_slope`.

## 10. Charts

| Cecha | Cadence/HR v7 | Wzorzec | Wniosek |
|---|---|---|---|
| Grid | ciemny `#252525` | jaśniejszy, pixelowy | preset może zwiększyć kontrast |
| Border/axis | cienki i gładki | wyraźniejszy | preset częściowo, chart dla exact |
| Line width | `2` | cięższa, bardziej stała linia | preset `line_width` |
| Fill | Cadence `65`, HR `45` | płaski, kontrolowany fill | preset `fill_alpha` |
| Value font | Arial/FreeType | pixelowy | font asset |
| Label font | Arial/FreeType | pixelowy | font asset |
| X-axis labels | regularny odstęp i kerning | stały pixel spacing | chart/font |
| Cursor/marker | standardowy punkt/linia | bardziej kwadratowy marker | chart renderer |

Największa różnica chartów to styl, nie okno `60 s`. Nie zmieniano `chart_time_scope` ani `chart_window_s`.

## 11. Map style

Geometrii Track-Up nie oceniano ponownie. Wizualnie v7 używa jasnego stylu `light_all`, podczas gdy wzorzec pokazuje ciemniejszą/satelitarną mapę. Istniejący renderer obsługuje `satellite`, `dark_all` i inne style; zmiana `map_style` byłaby **PRESET ONLY**, bez zmiany tile source implementation.

Pozostałe różnice: v7 ma czerwoną trasę `#FF3C1E`, biały okrągły marker i `track_width=2`; wzorzec ma bardziej wyrazisty marker kierunkowy. Kolor i szerokość są presetowe, kształt markera nie.

## 12. Distance

V7 ma poprawioną geometrię z 9B. Stylistycznie ruler jest szary z żółtym markerem, a wzorzec używa jaśniejszych, bardziej pixelowych ticków i wyraźniejszej wartości. `tick_width=1.1`, `tick_color`, `marker_color`, `marker_size` i `value_font_scale` pozwalają na poprawę presetem.

Decyzja: **PRESET ONLY** dla stylu; font value pozostaje częścią wspólnego problemu font assetu.

## 13. Dominujące kolory

| Element | v7 | Wzorzec | Różnica |
|---|---|---|---|
| White | `#FFFFFF` | biały/prawie biały | zgodny kolor, inny raster/font |
| Gray | `#424242`, `#BDBDBD`, `#252525` | głównie biały + ciemny outline | v7 za miękki/ciemny w tickach |
| Yellow/orange | `#FFD42A`, `#FF9A2E` | żółty/lime/orange | rodzina zgodna, proporcje akcentów inne |
| Red | `#FF3C1E`, `#FF5533` | czerwony marker/chart | rodzina zgodna, v7 marker bardziej gładki |
| Outline | czarny `1 px` | ciemna pixel edge | grubość podobna, profil różny |
| Transparent fill | HR `45`, Cadence `65` | płaski, mniej miękki fill | v7 HR bliżej wzorca po 9B |

## 14. Outline

Globalne `text_outline=1`:

| Element | Ocena v7 |
|---|---|
| Mały tekst | TOO THIN dla pixel-reference; GOOD dla zwykłego fontu |
| Duża wartość Speed | GOOD, ale brakuje pixel edge |
| Chart values | TOO THIN wizualnie |
| Compass | GOOD dla ringa, TOO THIN dla cardinal labels |
| Slope | GOOD dla kontrastu, profil niepixelowy |

Nie rekomenduję globalnego zwiększania outline bez font assetu, ponieważ może pogorszyć czytelność obecnego Arial/FreeType.

## 15. Ikonografia

| Ikona / symbol | Jest w wzorcu | Jest w v7 | Potrzebny asset? |
|---|---|---|---|
| Zegar | tak, osobny pixel clock | brak osobnego assetu; tylko tekstowy time block | tak / renderer time block |
| Kamera | tak, przy camera telemetry | brak osobnej ikony | tak |
| Temperatura/symbol | tak, pixelowy symbol | głównie tekst `°C` | tak lub renderer |
| Battery glyph/segment group | tak | segment bar bez pełnego glyphu w próbce | częściowo asset/renderer; dane też niepełne |
| Solar glyph/segment group | tak | slot jest, wartość unresolved | asset opcjonalny; data unresolved |
| Compass cardinal/needle | tak | tak, ale inny raster i font | font; needle częściowo istnieje |
| Speed needle | tak | tak, inny profil | niekoniecznie; mały gauge change |
| Map direction marker | tak | okrągły marker | renderer/map marker |
| Bike Lean | przyszły asset | brak | `wzor/rower_ico.png`, ale DEFERRED |

Nie znaleziono istniejącego lokalnego zestawu pixel icons poza `wzor/rower_ico.png`, którego nie wolno używać w tym etapie.

## 16. Existing local assets

Sprawdzone lokalnie foldery projektu: `wzor/`, `assets/` i `resources/` (brak dodatkowych użytecznych pixel-font/icon assets w dostępnych folderach). Dostępne są:

- `wzor/00000.png` — referencja;
- `wzor/rower_ico.png` — przyszły asset Lean, nie używać teraz.

Nie pobierano fontów ani grafik z internetu.

## 17. Top 5 rzeczywistych zmian rendererowych

| # | Plik / funkcja | Zakres | Ryzyko | Impact |
|---:|---|---|---|---|
| 1 | `src/indicators/helpers.py` `load_font` + `src/gui/layout_manager.py` `resolve_font_path` | kontrolowany wybór lokalnego pixel-font assetu i cache fontu | MEDIUM | HIGH |
| 2 | `src/indicators/gauge.py` `_render_gauge_indicator` | opcjonalny pixel tick profile: stała długość/grubość, kwadratowe zakończenia, needle profile | LOW | HIGH |
| 3 | `src/indicators/bar.py` `_render_ruler` / `_render_slope` | pixel tick endpoints i marker profile bez zmiany semantyki | LOW | MEDIUM |
| 4 | `src/indicators/chart.py` `_render_chart_indicator` | crisp axis/cursor/line raster i pixel label spacing | LOW | MEDIUM |
| 5 | `src/indicators/time_display.py` `render_time_display` | opcjonalne ikonki clock/camera/temp oraz stały pixel spacing | MEDIUM | HIGH |

To nie są zalecenia do wykonania w 9C. Nie proponuję refaktoru pipeline’u ani zmian backendowych.

## 18. Top 5 drobnych zmian preset-only

| # | Zmiana | Impact | Code risk |
|---:|---|---|---|
| 1 | `track_map.map_style: light_all → satellite` lub `dark_all`, po potwierdzeniu oczekiwanego wariantu | HIGH | LOW |
| 2 | Compass `compass_tick_degrees: 15 → 5` i ewentualnie `compass_tick_width: 1.0 → 1.2` | MEDIUM | LOW |
| 3 | Slope: cieplejszy `marker_color`, jaśniejszy `track_color`, mniejszy `marker_border_color` | MEDIUM | LOW |
| 4 | Distance/Power/Altitude: jaśniejsze ticki i `tick_width` około `1.3–1.5` | MEDIUM | LOW |
| 5 | Charts: `grid_color` jaśniejszy, Cadence/HR `line_width` `2 → 3` tylko jeśli pixel line nie powoduje dominacji | MEDIUM | LOW |

Nie zmieniono tych wartości. Są propozycjami do przyszłego presetowego etapu.

## 19. Rekomendowany ETAP 9D

Maksymalnie trzy zmiany kodowe, w tej kolejności:

1. **Font asset plumbing** — jeden lokalny pixel font dla wszystkich text/gauge/chart paths;
2. **`src/indicators/gauge.py`** — pixel tick/needle profile jako opcjonalny styl, zachowując istniejący default;
3. **`src/indicators/bar.py`** — pixel ruler/slope marker profile, bez zmiany źródła, zakresu i geometrii layoutu.

`chart.py` i `time_display.py` pozostawić jako kolejne kroki, jeśli po wprowadzeniu wspólnego fontu różnica nadal będzie duża.

## 20. Solar i Lean

Solar: **DATA SOURCE UNRESOLVED**. Nie analizowano FIT developer fields i nie zmieniano semantyki.

Lean: **DEFERRED — IMU NOT RELIABLE**. Nie uruchamiano skryptów IMU i nie używano `wzor/rower_ico.png`.

## 21. Validation i kontrola repo

Wykonano:

- load v7;
- jedną aktualną klatkę CPU `3840×2160` przy około 60 s;
- wizualne porównanie element po elemencie z `wzor/00000.png`;
- lokalny inventory `wzor/`, `assets/`, `resources/`;
- `git diff --check`.

Nie uruchamiano pełnego pytest suite, AMD exportu, NVIDIA runtime, IMU ani SmartSync jako osobnego testu. Tymczasowy skrypt audytowy zostanie usunięty po zakończeniu raportu.

Nie zmieniono `src/*`, `presets/*` ani `wzor/*`. NVIDIA path preserved statically; runtime validation was not relevant to this audit and was not performed on this AMD machine.
