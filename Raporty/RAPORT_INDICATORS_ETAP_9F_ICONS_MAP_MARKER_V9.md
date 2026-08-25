# TeleM — ETAP 9F: ikonografia HUD + kierunkowy marker mapy — v9

## 1. Scope

Dodano wyłącznie opcjonalną ikonografię HUD oraz opcjonalny kierunkowy marker mapy. Dane, formatowanie, układ v8, fonty i semantyka wskaźników pozostały bez zmian.

## 2. Material

Użyto `Video/GX010115.MP4`, `Video/GX010115.json` oraz `Video/Jazda_na_rowerze_w_porze_lunchu.fit`. Nie wykonywano ponownie SmartSync; wykorzystano wcześniej potwierdzony wynik: offset `+2.000 s`, confidence `high`, median error `7.6 m`, p90 `12.9 m`, coverage `1.00`.

Klatka CPU została wyrenderowana dla około 300 s, dokładnie `2026-08-14 11:23:03 UTC` (`11:23:03` na osi materiału).

## 3. References

`wzor/00000.png` służył do oceny geometrii, proporcji ikon i markera. `wzor/Zrzut ekranu 2026-08-22 092614.png` służył do oceny kontrastu, outline i czytelności na filmie. Nie użyto `wzor/rower_ico.png`.

## 4. Icon architecture

Dodano wspólny `src/indicators/icons.py`. Ikony są rysowane lokalnie z prymitywów Pillow: linia, prostokąt, polygon i koło. Są monochromatyczne, ostre, bez bitmap, gradientów, blur i zewnętrznych assetów. Domyślny kontrakt to `icon: "none"`; brak właściwości zachowuje ścieżkę legacy.

## 5. Clock

`time_display.icon = "clock"`. Ikona jest wyłącznie wizualna i nie zmienia daty, czasu, aktywności ani średniej prędkości.

## 6. Camera

`iso_text.icon = "camera"` zapewnia jedną ikonę grupy telemetryki kamery. Wartości ISO i Shutter nie zostały zmienione.

## 7. Temperature

`temp_text.icon = "temperature"`. Źródło temperatury, jednostka i format pozostały niezmienione.

## 8. Battery

`fit_battery_pct_text.icon = "battery"`. Segment count, zakres, procent i źródło pozostały bez zmian; glyph jest lokalny i skaluje się z lokalnym rozmiarem bara.

## 9. Solar visual only

`fit_solar_text.icon = "solar"` jest tylko warstwą wizualną. Status danych pozostaje `DATA SOURCE UNRESOLVED`; nie podstawiono innego pola i nie sfabrykowano wartości.

## 10. Map marker architecture

Kanoniczna właściwość markera to `map_marker_style`, z wartościami `dot` (domyślna) i `directional`. Marker jest rysowany w `MovingMapRenderer` przed przekazaniem wspólnego rastra do dalszych ścieżek. Nie dodano osobnego markera w D3D11.

## 11. North-Up marker semantics

W `north_up` marker `directional` używa istniejącego `heading`, mierzonego zgodnie z ruchem wskazówek zegara od kierunku ekranowego UP. Heading 0/90/180/270 obraca grot odpowiednio góra/prawo/dół/lewo. Środek pozostaje aktualną pozycją GPS.

## 12. Track-Up marker semantics

W `track_up` mapa pozostaje obracana istniejącą logiką Track-Up, a marker jest nanoszony w finalnej przestrzeni wyjściowej i wskazuje UP. Nie wykonuje drugiej rotacji o heading. Nie zmieniono tile selection, zoomu ani cropu.

## 13. heading=None

`directional` z `heading=None` bezpiecznie wraca do dotychczasowej kropki. Nie jest fabrykowany heading 0°.

## 14. v8 → v9

`presets/cycling_dashboard_v9.json` powstał bezpośrednio z v8. Dodano tylko właściwości ikon oraz `track_map.map_marker_style = "directional"`. Zachowano pixel profile v8, mapę satellite, Compass 5° i `charts.line_width = 3`. Presety v1–v8 nie zostały zmodyfikowane.

## 15. Render comparison

Finalny render CPU 3840×2160: [INDICATORS_ETAP_9F_V9_FRAME.png](INDICATORS_ETAP_9F_V9_FRAME.png). Ikony są czytelne na czarnym HUD, mają ciemny outline tam, gdzie jest potrzebny, a marker zastępuje kropkę pojedynczym białym grotem z outline na mapie satelitarnej.

## 16. CPU/AMD parity

Marker i ikony powstają w tym samym rastrze CPU przed przekazaniem do backendu. CPU reference i AMD otrzymują tę samą geometrię markera; nie dodano implementacji GPU o odmiennym wyglądzie.

## 17. AMD smoke

Uruchomiono v9 na 1280×720 przez około 1.5 s. Smoke zakończył się `True`. Log potwierdził:

```text
AMD_MAP_PATH: GPU
AMD_MAP_ORDER: CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
```

Artefakt smoke: `Raporty/ETAP_9F_AMD_SMOKE_1280.mp4`.

## 18. Performance

Lokalny raster 200 powtórzeń, 64 px: Clock 0.016 ms, Camera 0.015 ms, Temperature 0.020 ms, Battery 0.014 ms, Solar 0.024 ms. Marker na obrazie 768×768, 500 powtórzeń: dot 0.681 ms, directional 0.542 ms. Nie wykonano benchmarku całej aplikacji.

## 19. Tests

Uruchomiono 24 testy targetowane: ikony, marker, pixel style, Compass, Track-Up i map-first parity. Wszystkie przeszły. Dodatkowa kontrola po poprawce heading fallback: 8 testów marker/icon/Track-Up przeszło. Pełnego suite 600+ nie uruchamiano.

## 20. Changed files

- `src/indicators/icons.py` — wspólny proceduralny helper ikon.
- `src/indicators/text.py`, `src/indicators/time_display.py`, `src/indicators/bar.py` — opcjonalne osadzanie ikon w lokalnym rastrze.
- `src/indicators/moving_map.py`, `src/moving_map.py` — wybór stylu markera i wspólny raster North-Up/Track-Up.
- `src/indicators/dispatcher.py` — przekazanie canonical heading do mapy.
- `src/gui/qt/models.py` — jedno pole `icon` z dozwolonymi wartościami `none`, `clock`, `camera`, `temperature`, `battery`, `solar`.
- `presets/cycling_dashboard_v9.json` — preset v9 na bazie v8.
- `tests/test_indicator_icons.py`, `tests/test_directional_map_marker.py` — testy ikon i markera.
- niniejszy raport oraz finalna klatka w `Raporty`.

## 21. Preserved paths

Nie zmieniano telemetry/resolver/SmartSync, `src/ffmpeg/amd_native_exporter.py`, `streaming.py`, `command_builder.py`, NVIDIA/CUDA/NVENC, Track-Up tile engine, fontów, `font_size`, kerningu, spacingu, assetów ani presetów v1–v8. Bike Lean pozostaje `DEFERRED — IMU NOT RELIABLE`. NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.

## 22. Remaining differences

Font pozostaje `FONT POSTPONED`. Solar pozostaje `DATA SOURCE UNRESOLVED`. Nie wykonywano pixel-perfect image matching ani pełnego eksportu 4K/300 klatek. Zmieniono wyłącznie ikonografię i marker w ramach ETAPU 9F.
