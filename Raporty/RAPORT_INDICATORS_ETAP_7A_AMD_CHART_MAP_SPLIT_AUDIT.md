# TeleM — ETAP 7A: audyt parity chartów AMD przy `GPU map + charts after map`

## 1. Reprodukcja

Materiał:

```text
Video/GX030120.MP4
Video/GX030120.json
Video/Popoludniowa_jazda_na_rowerze_solar_battery.fit
presets/cycling_dashboard_v3.json
```

Probe AMD: 1280×720, 2 s, `video_time` od początku materiału, tryb `GPU_HUD_D3D11VA`, `AMD_TELEMETRY_MODE=PRECOMPUTED`.

Domyślna reprodukcja zakończyła się poprawnym eksportem, ale log zawierał:

```text
AMD_MAP_PATH: GPU
AMD_MAP_ORDER: CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
AMD_CHART_PATH: GPU_SPLIT
AMD_TELEMETRY_MODE: PRECOMPUTED
GPU charts fallback -> CPU_REFERENCE (no active chart widgets)
```

## 2. Pełny layout v3

Kolejność aktywnych widgetów:

```text
0  time_display
1  dist_visual
2  fit_battery_pct_text
3  fit_solar_text
4  track_map
5  iso_text
6  exposure_text
7  temp_text
8  alt_visual
9  fit_curVpower_text
10 fit_cadence_text
11 fit_enhanced_speed_text
12 fit_heart_rate_text
13 fit_K1_text
14 fit_K2_text
15 fit_distance_text
16 fit_enhanced_altitude_text
17 fit_fractional_cadence_text
18 fit_passing_speed_text
19 fit_passing_speedabs_text
20 fit_radar_current_text
21 fit_solar_pct_text
22 fit_temperature_text
```

Istotne konfiguracje:

```text
track_map: form=map, enabled=true
fit_cadence_text: form=chart, enabled=true, chart_time_scope=window, chart_window_s=60
fit_heart_rate_text: form=chart, enabled=true, chart_time_scope=window, chart_window_s=60
fit_enhanced_speed_text: form=gauge, enabled=true
```

## 3. Ordered-map partition

`src/ffmpeg/amd_native_exporter.py:_ordered_map_layout_parts()` — linie 239–269 — zachowuje kolejność i rozdziela layout na:

```text
below:
  time_display, dist_visual, fit_battery_pct_text, fit_solar_text

map:
  track_map

above:
  iso_text, exposure_text, temp_text, alt_visual,
  fit_curVpower_text, fit_cadence_text, fit_enhanced_speed_text,
  fit_heart_rate_text, fit_K1_text, fit_K2_text, fit_distance_text,
  fit_enhanced_altitude_text, fit_fractional_cadence_text,
  fit_passing_speed_text, fit_passing_speedabs_text,
  fit_radar_current_text, fit_solar_pct_text, fit_temperature_text
```

Oba charty są jednoznacznie `after-map`.

## 4. Chart discovery

Discovery GPU chartów znajduje się w:

```text
src/ffmpeg/amd_native_exporter.py:_chart_gpu_layout_safe(), linie 177–224
src/ffmpeg/amd_native_exporter.py:runtime probe, linie 1797–1835
```

Probe wykonuje `compose_overlay(... layout=compose_layout ...)`, gdzie `compose_layout` jest już częścią `below-map` ustawioną w liniach 898–902. Ponieważ `below-map` nie zawiera `fit_cadence_text` ani `fit_heart_rate_text`, `gpu_capture` pozostaje puste, a `_chart_gpu_layout_safe()` zwraca:

```text
no active chart widgets
```

To jest utrata na etapie discovery/layout partition, przed atlasem, region capture i właściwym chart rendererem.

## 5. Telemetry/chart precompute — full vs split

Wspólny `build_chart_data()` działa poprawnie dla pełnego i `above-map` layoutu:

| Pole | Full layout | Below-map layout | Above-map layout |
|---|---|---|---|
| cadence detected | tak | nie | tak |
| HR detected | tak | nie | tak |
| cadence scope | `window` | brak | `window` |
| HR scope | `window` | brak | `window` |
| cadence window | 60 s | brak | 60 s |
| HR window | 60 s | brak | 60 s |
| cadence sample count przed clippingiem | 1741 | brak | 1741 |
| HR sample count przed clippingiem | 1754 | brak | 1754 |
| chart bbox | dostępny | dostępny przy fallback chartu | dostępny |

Kluczowy przepływ AMD:

```text
export_amd_native_d3d11()
  → init_worker(layout=compose_layout)              # amd_native_exporter.py:1262–1267
  → worker_cache.init_worker()                       # worker_cache.py:93–108
  → build_chart_data(layout, ...)
  → WORKER_CACHE["_precomputed_chart_data"]
  → build_telemetry_cache(layout=compose_layout,    # amd_native_exporter.py:1668–1688
                          chart_data=_precomputed_chart_data)
```

W v3 `compose_layout` jest `below-map`, dlatego `_precomputed_chart_data` nie zawiera żadnego chartu. `TelemetryFrameCache.lookup()` może poprawnie przycinać `window`, ale otrzymuje już pusty słownik.

## 6. Scope/window propagation

Dla pełnego layoutu i `video_time=180 s` wspólna ścieżka przygotowała:

```text
fit_cadence_text:
  scope=window
  window_s=60
  start=2026-08-18 04:48:25.700000
  end=2026-08-18 04:49:25.700000
  count=60
  first=56.0
  last=59.0
  cursor=2026-08-18 04:49:25.700000+00:00

fit_heart_rate_text:
  scope=window
  window_s=60
  start=2026-08-18 04:48:25.700000
  end=2026-08-18 04:49:25.700000
  count=60
  first=102.0
  last=103.0
  cursor=2026-08-18 04:49:25.700000+00:00
```

Dane `window=60` są więc poprawne przed wejściem do AMD compositingu, jeśli źródłem jest pełny layout. W aktualnym ordered-map flow nie są jednak zbudowane, ponieważ worker otrzymuje `below-map`.

## 7. CPU_ABOVE_MAP path

`src/ffmpeg/amd_native_exporter.py:1883–1898` wykonuje:

```text
above_full = compose_overlay(layout=map_above_layout, ..., **frame_kwargs)
```

Jest to filtrowany `above-map` layout, ale z tym samym `frame_kwargs`. Nie powstaje lokalny nowy `ChartHistory`; `CPU_ABOVE_MAP` korzysta z `frame_kwargs["chart_data"]`.

W aktualnym flow ten payload ma `chart_data={}`, więc `compositor.py:343–361` przekazuje `history_data=None` do `render_value_indicator()`.

Kontrolowany test z pełnym, przyciętym payloadem wywołał `_window_time_labels(60.0)` dla obu chartów. Ten sam test z payloadem zbudowanym z `below-map` nie wywołał `_window_time_labels` ani razu.

## 8. Chart atlas/cache analysis

Cache nie jest pierwotnym root cause. `src/indicators/chart_utils.py:_history_chart_cache_key()`, linie 209–232, uwzględnia:

```text
history identity / _chart_cache_token
length
chart_start_dt
chart_end_dt
time_scope
time_labels
geometrię i styl
```

`chart_window_s` nie występuje jako osobne pole klucza, ale przycięty `ChartHistory` dostaje nowy monotoniczny token, nowe granice czasu, długość oraz etykiety osi. Dla istniejących danych `window` występuje więc skuteczna invalidacja.

Nie znaleziono dowodu na użycie starego atlasu `activity`. Problem występuje wcześniej: do chart renderera trafia `history_data=None`.

## 9. Static/dynamic chart assembly

W `src/indicators/chart.py`:

- linie 434–446 wybierają względne etykiety dla `time_scope=window`,
- linie 447–461 wybierają fixed-timeline prefix background,
- linie 656–733 budują static chart / `ChartSplit`,
- linie 734–780 składają dynamiczny cursor i wartość.

Przy poprawnym `ChartHistory` etykiety `-60 s … 0 s` należą do static background i są widoczne zarówno w CPU rendererze, jak i w CPU fallbacku AMD. Przy pustym `history_data` renderer używa awaryjnego `[value, value]`, nie ma `time_scope=window`, nie oblicza etykiet względnych, a `chart_utils.py:640` wybiera domyślne `0%, 25%, 50%, 75%, 100%`.

## 10. Eksperyment no-map

W pamięci ustawiono `track_map.enabled=false`, bez zapisu v3.

Wynik:

```text
AMD_MAP_PATH: GPU (GPU active; reason: no active track_map)
AMD_MAP_ORDER: CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
GPU charts fallback -> CPU_REFERENCE (no active chart widgets)
ETAP7A_PROBE mode=no_map ok=True
```

Final nadal pokazał procentową oś. Powód: warunek w eksporterze sprawdza `"track_map" in layout`, a nie `track_map.enabled`; sam wyłączony widget nie wyłącza ordered split.

Dodatkowy fixture diagnostyczny usuwający klucz `track_map` całkowicie nie uruchomił map splitu. Wtedy charty zostały znalezione, a finalny CPU fallback pokazał `-60 s … 0 s`; niezależny guard GPU odrzucił ich capture z powodu overlapu bbox. To potwierdza znaczenie samej obecności klucza dla utraty precompute.

## 11. Eksperyment chart-before-map

W pamięci przeniesiono oba charty przed `track_map`, bez zmiany pliku preset.

Wynik partition:

```text
below: ... fit_cadence_text, fit_heart_rate_text
map:   track_map
above: []
```

Log AMD:

```text
AMD_CHART_PATH: GPU_SPLIT
AMD_TELEMETRY_MODE: PRECOMPUTED
GPU charts fallback -> CPU_REFERENCE
  GPU_CHART_UNSAFE_LAYOUT -> all charts CPU_REFERENCE:
  fit_cadence_text overlaps widget bbox=(439,665,402,61)
  fit_heart_rate_text overlaps widget bbox=(439,665,402,61)
ETAP7A_PROBE mode=before_map ok=True
```

Mimo fallbacku GPU final render pokazał poprawną oś `-60 s … 0 s`, ponieważ charty znalazły się w `compose_layout`, a precompute otrzymał ich historię. Jest to potwierdzenie przyczyny, nie obejście ani proponowana zmiana preset.

## 12. AMD runtime logs

Wszystkie cztery kontrolowane warianty zakończyły eksportem `ok=True`:

| Wariant | Ordered split | Discovery | Wynik osi |
|---|---|---|---|
| default v3 | tak | `no active chart widgets` | procentowa |
| `track_map.enabled=false` | nadal tak | `no active chart widgets` | procentowa |
| charts before map | tak, charty w below | aktywne, lecz unsafe overlap | `-60…0` przez CPU fallback |
| klucz mapy usunięty | nie | aktywne, lecz unsafe overlap | `-60…0` przez CPU fallback |

Wspólne parametry runtime: `GPU_HUD`, `GPU_HUD_D3D11VA`, `AMD_CHART_PATH=GPU_SPLIT`, AMF/D3D11VA uruchomione.

## 13. NVIDIA static analysis

Nie zmieniano NVIDIA ani wspólnego kodu backendowego. W audytowanym przepływie problem jest specyficzny dla AMD eksportera, który przekazuje split layout do `init_worker()`. NVIDIA nie używa tej funkcji ordered-map AMD w analizowanym miejscu.

Wspólny chart cache key zawiera `time_scope`, granice historii i etykiety osi; nie znaleziono analogicznej utraty full layoutu w testowanej ścieżce NVIDIA.

NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.

## 14. Existing tests / missing regression

Uruchomiono istniejące testy chart, clipping, fixed timeline, static assembly, prefix, precompute, AMD chart, ordered map, above regions, runtime layout/parity, map parity oraz NVIDIA regression:

```text
238 passed in 12.82s
```

Istniejące testy sprawdzają osobno ordered-map partition i precompute/chart parity, ale nie mają kombinacji:

```text
v3 + track_map enabled + charts after map + chart_time_scope=window
```

To wyjaśnia, dlaczego obecna regresja przeszła testy.

## 15. Root cause

```text
ROOT CAUSE CONFIRMED
```

Dokładny mechanizm:

1. `export_amd_native_d3d11()` w `src/ffmpeg/amd_native_exporter.py:898–902` ustawia `compose_layout` na `below-map` po ordered split.
2. Ten `compose_layout` jest przekazany do `init_worker()` w linii 1266.
3. `src/ffmpeg/worker_cache.py:104–108` buduje `_precomputed_chart_data` wyłącznie z otrzymanego layoutu; dla v3 layout nie ma chartów, więc wynik jest pusty.
4. `build_telemetry_cache()` w `amd_native_exporter.py:1668–1688` dostaje pusty `chart_data` i przekazuje go do rekordów precomputed.
5. `TelemetryFrameCache.lookup()` zwraca pusty `chart_data` dla każdej klatki.
6. `CPU_ABOVE_MAP` w liniach 1888–1898 renderuje poprawny `above-map` layout, ale z pustym payloadem.
7. `compositor.py:343–361` przekazuje `history_data=None`; `chart.py` nie widzi `time_scope=window` i tworzy fallbackową historię dwóch wartości.
8. `chart_utils.py:640` stosuje domyślne etykiety procentowe.

GPU atlas/region oraz cache nie są miejscem utraty konfiguracji. `GPU_SPLIT` nie ma aktywnych chartów do capture, bo discovery również działa na `compose_layout=below-map`.

## 16. Minimalny plan fixu — bez implementacji

Najmniejszy kierunek ETAPU 7B:

```text
zachować pełny layout jako źródło semantyki danych i chart precompute;
używać below/map/above wyłącznie do z-order i compositingu;
przekazywać ten sam pełny chart_data do below, GPU map i above;
pozostawić guardy GPU oraz CPU_REFERENCE fallback bez zmian.
```

Nie należy przenosić chartów w v3 ani uzależniać poprawności od ich pozycji przed mapą. Prawdopodobny minimalny zakres dotyczy punktu przekazania layoutu do worker/precompute w AMD exporterze lub rozdzielenia `semantic_layout` od `compose_layout`; wybór konkretnego miejsca należy do ETAPU 7B.

## 17. Pliki prawdopodobnie wymagające zmiany w ETAPIE 7B

Najmniejszy prawdopodobny zakres:

```text
src/ffmpeg/amd_native_exporter.py
src/ffmpeg/worker_cache.py                  # tylko jeśli wymagane przez API pełnego layoutu
tests/                                      # regresja v3 + map + charts after map
```

Nie przewiduję zmian w `chart.py`, `chart_builder.py`, `telemetry_precompute.py` ani rendererze mapy dla samej przyczyny ETAP 7A.

## 18. Ryzyko dla mapy, AMD, NVIDIA i CPU reference

- CPU reference: zachowany i poprawny; pełny layout daje `window=60` oraz `-60…0`.
- AMD map: obecny ordered-map z v3 traci chart history przed compositingiem; map parity nie została naruszona w audycie.
- AMD GPU chart: wariant before-map pokazuje dodatkowy, niezależny overlap guard; nie należy go wyłączać bez osobnego dowodu parity.
- NVIDIA: brak zmian i brak runtime testu na tej maszynie.
- Preset v3: niezmieniony.
- Produkcja: w ETAP 7A nie zmodyfikowano żadnego pliku produkcyjnego ani testu; dodano wyłącznie raport oraz tymczasowe skrypty usunięte po audycie.
