# TeleM — ETAP 9E: pixel-style Gauge / Ruler / Slope + cycling_dashboard_v8

## 1. Scope

Dodano opcjonalny lokalny profil `tick_profile: "pixel"` w istniejących rendererach Gauge i bar/ruler. Zmieniono wyłącznie lokalny raster ticków, linii i markerów oraz preset v8.

## 2. Nowy materiał testowy

Użyto `Video/GX010115.MP4`, `Video/GX010115.json` i `Video/Jazda_na_rowerze_w_porze_lunchu.fit`. Timestamp renderu: **300 s** (`11:23:03` UTC video timeline).

## 3. Dwie referencje TO

`wzor/00000.png` wykorzystano jako referencję czystej geometrii ticków, linii i markerów. `wzor/Zrzut ekranu 2026-08-22 092614.png` wykorzystano jako referencję kontrastu i czytelności na filmie. To ten sam layout, nie dwa konkurencyjne wzorce.

## 4. Gauge default vs pixel

Brak `tick_profile` oraz jawne `"default"` przechodzą identyczną ścieżką jak wcześniej. `"pixel"` ma ostrzejsze, radialne ticki z wyraźniejszą hierarchią major/minor, bez globalnego blur ani zmiany antialiasingu.

## 5. Speed Gauge

W v8 Speed Gauge używa `tick_profile: "pixel"`.

- major tick length: `0.12 × radius`;
- minor tick length: `0.035 × radius`;
- major width: około `1.15 ×` lokalna grubość ticka;
- minor width: około `0.42 ×` lokalna grubość ticka;
- needle: dotychczasowe mapowanie kąta i długość, lokalnie cięższy profil (`1.8 × needle_width`), bez zmiany center/range/value semantics.

W 4K dla v8 odpowiada to w przybliżeniu 48 px major i 14 px minor przy promieniu około 400 px. Wymiary są liczone z lokalnego radiusu, więc skaluje się to również w 1280×720.

## 6. Compass

Compass korzysta z tego samego `gauge.py`; nie dodano osobnego renderera. W v8 ma `tick_profile: "pixel"`, `compass_tick_degrees: 5` i major co `45°`. Zachowano cardinals, heading, ring i needle semantics.

## 7. Bar/ruler default vs pixel

Ruler bez profilu zachowuje dotychczasową rasteryzację. Pixel ruler używa major length około `4%` lokalnej szerokości, minor length około `1.8%`, większej grubości major i krótszych/cieńszych minor ticków z twardym profilem.

## 8. Slope

Slope w v8 zachowuje zakres `-20..+20`, major `5%`, minor `1%`, źródło i format wartości. Pixel profile wzmacnia zero line, różnicę major/minor, zwiększa marker width i zamienia okrągły marker na prostokątny hard-edged marker z zachowaniem koloru/borderu.

## 9. Distance

Distance zachowuje pozycję, zakres i dane. W v8 otrzymał pixel profile, ostrzejsze ticki, jaśniejszy tick/marker oraz `marker_border_color` i `tick_width` jako istniejące właściwości presetowe.

## 10. Altitude

Altitude zachowuje pozycję, zakres i dane. W v8 otrzymał pixel profile, jaśniejsze ticki, biały border markera i lokalną hierarchię major/minor.

## 11. Virtual Power

Virtual Power zachowuje źródło FIT i wartości. W v8 otrzymał pixel profile oraz mocniejszy kontrast track/tick/marker wyłącznie presetowo.

## 12. Charts

Rendererów chartów nie zmieniano. W v8 jedynie presetowo podniesiono `line_width` z `2` do `3`; okno `60 s`, dane, fill i semantics etykiet pozostały bez zmian.

## 13. Map

Finalny `map_style` v8: `satellite`, zgodnie z aktywną referencją mapy widoczną w `wzor/00000.png`. Track-Up i tile engine nie były zmieniane. **MAP DIRECTION MARKER — FUTURE SMALL CHANGE**.

## 14. v7 → v8 table

| Obszar | v7 | v8 |
|---|---|---|
| Speed Gauge | default tick profile | `pixel`, needle width 5 |
| Compass | 15° ticks | `pixel`, 5° ticks, major 45° |
| Distance | default ruler | `pixel`, jaśniejsze ticki/marker |
| Altitude | default ruler | `pixel`, jaśniejsze ticki/marker |
| Virtual Power | default ruler | `pixel`, jaśniejszy kontrast |
| Slope | default geometry | `pixel`, prostokątny marker, mocniejsza hierarchia |
| Charts | line width 2 | line width 3, preset-only |
| Map | `light_all` | `satellite` |
| Font | default | bez zmian, brak `font` override |

v1–v7 nie były modyfikowane.

## 15. Render comparison

Finalna klatka CPU reference 3840×2160 została porównana wizualnie z obiema referencjami. Pixel profile poprawia rozdział grubych major ticków i krótkich minor ticków na jasnym i ciemnym tle. Speed Gauge, Compass, Slope, Distance, Altitude i Virtual Power są widoczne; map pozostaje satelitarny; charts zachowują dotychczasową semantykę.

## 16. Performance

Orientacyjny średni czas lokalnego rastra, 20 powtórzeń w 1280×720:

| Raster | default | pixel |
|---|---:|---:|
| Speed Gauge | 2.399 ms | 2.221 ms |
| Compass | 3.525 ms | 3.518 ms |
| Slope | 10.232 ms | 5.076 ms |

Nie wystąpił wielokrotny wzrost kosztu.

## 17. Tests

Uruchomiono **53 testy**, wszystkie zakończone sukcesem: `test_pixel_indicator_style.py`, `test_gauge_rendering.py`, `test_compass_rendering.py`, `test_slope_rendering.py` i `test_bar_integration.py`. Pełnego suite 600+ nie uruchamiano.

## 18. Changed files

- `src/indicators/gauge.py` — opcjonalny pixel tick profile Gauge/Compass.
- `src/indicators/bar.py` — opcjonalny pixel profile ruler/Slope i prostokątny marker Slope.
- `src/gui/qt/models.py` — minimalne pole `tick_profile` w schematach Gauge/Compass/ruler/Slope.
- `presets/cycling_dashboard_v8.json` — nowy preset wyłącznie na bazie v7.
- `tests/test_pixel_indicator_style.py` — testy default/pixel, Compass, Slope, v7/v8.
- `Raporty/RAPORT_INDICATORS_ETAP_9E_PIXEL_STYLE_V8.md` — niniejszy raport.
- `Raporty/INDICATORS_ETAP_9E_V8_FRAME.png` — finalna klatka CPU reference.

## 19. Preserved paths

Nie zmieniano telemetry, SmartSync, `moving_map.py`, frame data, precompute, FFmpeg, AMD exportera, NVIDIA, Track-Up implementation ani presetów v1–v7. Font, font_size, assety i kerning pozostały bez zmian. Nie dodano ikon. NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.

## 20. Remaining differences

- font — postponed;
- icons — postponed;
- map direction marker — future small change;
- Solar — `DATA SOURCE UNRESOLVED`;
- Lean — `DEFERRED — IMU NOT RELIABLE`;
- nie wykonywano pixel-perfect image matching ani automatycznego sweepu parametrów.

### AGENTS.md — raport końcowy

**Changed:** lokalny, opcjonalny pixel profile Gauge/Compass/ruler/Slope, preset v8, minimalne schema i testy.

**Preserved:** default rendering, CPU reference semantics, telemetry/data sources, AMD/NVIDIA/FFmpeg paths, v1–v7.

**Tested:** 53 targetowane testy, compile check, `git diff --check`, CPU reference render 3840×2160 na nowym MP4+FIT, orientacyjny benchmark lokalnych rasterów.

**Not tested:** NVIDIA runtime, pełny suite, sprzętowy AMD smoke.

**Risks:** finalna ocena pixel-style pozostaje wizualna; map direction marker, font i Solar nadal są odroczone/unresolved.
