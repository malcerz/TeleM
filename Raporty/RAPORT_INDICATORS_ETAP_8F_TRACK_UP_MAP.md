# TeleM — ETAP 8F: Track-Up Map z canonical `heading`

Data: 2026-08-22.

## Zakres

Dodano opcjonalną orientację `track_up` dla istniejącego `MovingMapRenderer`.
Domyślne `north_up` pozostało bez zmian i zachowuje dotychczasową szybką
ścieżkę renderowania.

Track-Up działa w jednym lokalnym rastrze:

```text
tiles + track + marker
        ↓
rotate around center
        ↓
crop do finalnego rozmiaru
```

Nie powstał osobny renderer mapy, system kafelków ani nowy algorytm headingu.
Heading nie wchodzi do klucza cache kafelków i nie zmienia zoomu.

## Geometria i semantyka

Przed obrotem używany jest kwadratowy overscan:

```text
working_size = ceil(output_size × sqrt(2))
```

Przykładowo dla mapy 768×768 raster roboczy ma 1087×1087 px. Po obrocie
wynik jest ponownie przycinany do 768×768 px. Marker jest rysowany w północnym
rastrze przed obrotem, dlatego pozostaje w centrum finalnego obrazu.

Konwencja obrotu jest geograficzna: `heading=0°` oznacza north-up,
`90°` east, `180°` south, `270°` west. `heading=None` ma wizualny fallback do
`north_up`; nie jest traktowany jako nowa wartość telemetryczna.

## Binding danych

`track_map` korzysta z istniejącego kanonicznego `heading` i z tego samego
`source`, co mapa:

- `source=gpmf` → GPMF-derived heading;
- `source=fit` → FIT GPS track / FIT-derived heading;
- `source=gpx` → GPX source, jeżeli jest dostępny.

Renderer mapy nie wykonuje bearingu, filtracji ani interpolacji. Wartość jest
przygotowywana w `frame_data` albo w precomputed telemetry cache i przekazywana
przez CPU reference, preview oraz AMD map upload.

## Konfiguracja

Dodano pole GUI/schema:

```json
"map_orientation": "north_up" | "track_up"
```

Brak pola w starszym layoucie oznacza `north_up`. Utworzono
`presets/cycling_dashboard_v6.json` jako kopię v5 z jedyną zmianą funkcjonalną:
`indicators.track_map.map_orientation = "track_up"`. Preset v5 i wcześniejsze
nie zostały zmienione.

## Testy CPU i parity

Dodano `tests/test_track_up_map.py`. Obejmuje on:

- kardynalne kąty `0/90/180/270` oraz kąt pośredni `45°`;
- dokładny finalny rozmiar obrazu i brak clippingu rogów;
- byte-identical fallback `heading=None` i `heading=0°` względem north-up;
- brak headingu w cache key oraz zachowanie zoomu;
- source isolation FIT vs GPMF w reference i precompute;
- schema GUI oraz różnicę v6 względem v5.

Uruchomione bramki:

```text
python -m pytest -q tests/test_track_up_map.py tests/test_map_first_render_parity.py \
  tests/test_amd_chart_map_split.py tests/test_compass_rendering.py \
  tests/test_slope_rendering.py tests/test_telemetry_heading.py \
  tests/test_telemetry_slope.py
52 passed

python -m pytest -q tests/test_etap8o_precomputed_telemetry.py \
  tests/test_etap8p_b_fast_builder.py tests/test_etap8m3_runtime_layout_and_parity.py \
  tests/test_etap8m4_chart_time_scope.py
35 passed
```

`py_compile` zmienionych modułów oraz `git diff --check` zakończyły się
poprawnie. Nie uruchamiano pełnej kolekcji 600+ testów.

## Rzeczywisty materiał i artefakt CPU

Wygenerowano:

```text
Raporty/INDICATORS_ETAP_8F_TRACK_UP_CPU_FRAME.png
```

Klatka pochodzi z `Video/GX030120.MP4`, z dopasowanym FIT-em
`Video/Poranna_jazda_na_rowerze.fit`, około 60 s osi czasu. Dla mapy użyto
FIT source, a przygotowany `map_heading` wyniósł `24.6812067°`. Na klatce
widoczna jest mapa Track-Up z trasą obróconą razem z podkładem.

## AMD smoke

Wykonano krótki eksport Native AMD 1280×720, 60 klatek (~2 s), z presetem v6:

```text
AMD_MAP_PATH: GPU
AMD_MAP_ORDER: CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
AMD_TELEMETRY_MODE: PRECOMPUTED
map_gpu: 60 frames
decoded/submitted/muxed: 60 frames
output video: 1280×720, 2.002 s
true FPS: 7.785
```

W klatce AMD mapa zachowuje Track-Up; jej lokalny track jest obrócony zgodnie
z bieżącym headingiem. Istniejący guard chartów przełączył HR/Cadence do
`CPU_REFERENCE` z powodu unsafe layoutu; nie był to fallback wywołany przez
Track-Up. Zmiana w `src/ffmpeg/amd_native_exporter.py` ogranicza się do
przekazania `map_heading` do istniejącego map uploadu — bez zmiany pipeline'u
GPU, synchronizacji, encodera lub z-orderu.

## Zachowane ścieżki i ryzyka

- CPU reference pozostaje baseline’em semantycznym.
- AMD map path, z-order `CPU_BELOW_MAP → GPU_MAP → CPU_ABOVE_MAP` i diagnostyka
  pozostały aktywne.
- NVIDIA code path, importy i konfiguracja nie były przebudowywane.
- Nie zmieniano `src/telemetry_heading.py`, bearingu, smoothingu, GYRO, ACCEL,
  Lean ani synchronizacji telemetrycznej.
- Track-Up dodaje koszt obrotu lokalnego rastra; krótki smoke nie zastępuje
  pełnego benchmarku produkcyjnego.

**NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.**
