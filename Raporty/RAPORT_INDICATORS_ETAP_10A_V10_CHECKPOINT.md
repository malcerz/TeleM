# TeleM — ETAP 10A: release checkpoint `cycling_dashboard_v10`

## 1. Scope

Wykonano checkpoint regresyjny v10 bez nowych funkcji, tuningu layoutu, doboru fontu ani zmian produkcyjnego kodu.

## 2. v10 feature inventory

Preset zachowuje: Time/Date/Activity, Distance, Battery, `solar_pct`, ISO, Shutter, Temperature, Altitude, Virtual Power, Speed Gauge, Compass, Slope, HR/Cadence charts, Track-Up map, mapę satellite, directional marker, proceduralne ikony, pixel tick profile i infrastrukturę fontów per-widget. Lean pozostaje celowo niewdrożony.

Solar: `source=fit`, `field=solar_pct`, `unit=%`, range `0..100`; nie jest aliasowane do `solar`.

## 3. Targeted gate tests

Checkpoint gate: **55 passed**.

Uruchomiono wskazane testy Solar, ikon, markera, pixel style, Track-Up, map parity, Compass, Slope, font selection i AMD chart/map split.

## 4. Full suite result

```text
650 passed, 17 skipped in 53.26s
```

## 5. Known `test_fit_registration` status

Nie wystąpił blocker `test_fit_registration.py` / `src.gui.hud_tuner_app`. Pełny suite przeszedł bez błędu collection; nie wykonywano wariantu wyłączonego.

## 6. Any new failures

Nie znaleziono nowych failure ani regresji związanej z Gauge, Bar, Map, Compass, Slope, Charts, fontami, ikonami, Solar lub generic FIT fields.

## 7. CPU final frame

Wyrenderowano jedną klatkę CPU reference 3840×2160 dla `2026-08-14 11:23:03 UTC` / około 300 s. Artefakt: [INDICATORS_ETAP_10A_V10_CPU_FRAME.png](INDICATORS_ETAP_10A_V10_CPU_FRAME.png). Jednorazowy czas wykonania renderu z przygotowaniem danych wyniósł około `4.50 s`.

## 8. Data sanity

Na finalnej klatce wartości są finite i pochodzą z właściwych źródeł:

| field | value |
|---|---:|
| speed | 21.2 km/h |
| HR | 97 BPM |
| cadence | 64 RPM |
| altitude | 23.2 m |
| virtual power | 25 W |
| battery | 89% |
| solar_pct | 100% |
| heading | 141.2° |
| slope | -0.4% |

## 9. Solar

W v10 użyto wyłącznie `solar_pct`. Pole `solar` pozostało odrębne. `solar_pct` zachowuje STEP/hold-last oraz rozróżnienie `0%` od missing.

## 10. Charts

Cadence i HR mają `chart_time_scope=window`, `chart_window_s=60.0`, `line_width=3`. Etykiety osi pozostają w trybie czasu względnego `-60 ... 0`, nie procentowym.

## 11. Compass / heading

Compass zachowuje canonical heading, pixel tick profile i dotychczasową geometrię. Finalna wartość kontrolna: `141.2°`.

## 12. Slope

Slope zachowuje istniejący zakres, STEP/derived semantics, pixel profile i finalną wartość `-0.4%`.

## 13. Track-Up + directional marker

`map_orientation=track_up`, `map_style=satellite`, `map_marker_style=directional`. Marker na finalnej mapie jest skierowany UP; map center, zoom i crop pozostają bez zmian.

## 14. Icons

Obecne są: Clock, Camera, Temperature, Battery i Solar. Ikony pozostają proceduralne, opcjonalne i wspólne dla CPU/AMD raster path.

## 15. Font infrastructure/default behavior

V10 nie ustawia custom fontu. Default pozostaje aktualny. Testy font selection przeszły; stare layouty bez właściwości `font` nadal się ładują. Font visual matching pozostaje odroczony.

## 16. Preset v1–v10 load compatibility

Wszystkie presety `cycling_dashboard_v1.json` … `cycling_dashboard_v10.json` przeszły parse/load. Nie renderowano historycznych presetów.

## 17. CPU/precompute semantics

Dla reprezentatywnego timestampu Solar, heading, slope oraz dane HR/Cadence zachowują tę samą semantykę w CPU preview/reference preparation i AMD precomputed path. Nie wymagano byte-identical całej klatki między backendami.

## 18. AMD smoke

Wykonano v10 smoke 1280×720 przez około 2 s. Wynik: `True`. Artefakt: `Raporty/ETAP_10A_AMD_SMOKE_1280.mp4`.

## 19. AMD diagnostics

Potwierdzone logi:

```text
AMD_MAP_PATH: GPU
AMD_MAP_ORDER: CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
AMD_TELEMETRY_MODE: PRECOMPUTED
```

Chart GPU przeszedł do `CPU_REFERENCE` z istniejącego powodu `GPU_CHART_UNSAFE_LAYOUT` / overlap widgetów; nie jest to regresja Solar ani v10. Gauge miał analogiczny istniejący fallback overlap.

Frame accounting smoke: `decoded/submitted/muxed = 60/60/60`.

## 20. NVIDIA static preservation

Nie zmieniano NVIDIA/CUDA/NVENC ani wyboru backendu. NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.

## 21. Performance sanity

AMD smoke: `TRUE FPS = 5.631`, render FPS `12.575`, precompute build `50.131 ms`. CPU frame one-shot: około `4.50 s` wraz z przygotowaniem danych. Nie zauważono oczywistej regresji performance w zakresie checkpointu.

## 22. Changed files

W ETAPIE 10A zmieniono wyłącznie artefakty `Raporty/*`: niniejszy raport, finalną klatkę CPU i krótki AMD smoke. Nie zmieniano kodu produkcyjnego ani presetów.

## 23. Remaining deferred items

- Font visual matching — deferred/postponed.
- Lean controlled calibration — `DEFERRED — IMU NOT RELIABLE`.

## 24. Final checkpoint decision

```text
V10 CHECKPOINT: PASS
```
