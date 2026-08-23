# RAPORT — Unifikacja BAR Ruler/Slope + orientacja + marker + jednostki + adaptacyjna podziałka

**Etap:** 11B (BAR ORIENTATION + MARKER RUNTIME + UNITS + ADAPTIVE MAJOR STEP)
**Data:** 2026-08-23
**Baseline:** ETAP 10X (auto_scale) i 10Y (kontrakt major_step/major_ticks) — **nie cofnięte**.
**Zakres:** wspólny BAR Ruler z orientacją (horizontal/vertical), migracja `style=slope`, runtime bug markera dystansu, jeden kontrakt m→km, jawny tryb AUTO major tick (nice-step), spójność GUI. **Bez zmian** pipeline'ów AMD/NVIDIA/Intel (poza wspólnym, backend-neutralnym pomiarem bbox), FFmpeg, SmartSync, map, GPU compositing.

---

## 1. Jak wcześniej różniły się Ruler i Slope

| Właściwość | Ruler (horizontal) | Slope (vertical) |
|---|---|---|
| Wariant | `bar_style="ruler"` | `bar_style="slope"` (osobny wybór w GUI) |
| Orientacja | hardcoded pozioma | hardcoded pionowa (tylko jako „slope") |
| Renderer | `_render_ruler` | `_render_slope` (całkowicie osobna funkcja, inny layout) |
| Kontrakt ticków | `major_ticks`/`minor_ticks` (COUNT) + `major_step` (STEP) | `major_tick`/`minor_tick` (wartościowe) |
| Etykiety | min/środek/max pod osią | etykiety wartości przy tickach (z lewej) |
| Marker | kropka na osi | linia pozioma + kropka |
| Cechy wspólne | kolory, fonty, marker_color, tick_profile | osobne kolory domyślne, `zero_tick_color` |
| Kolor zera | brak | biały podświetlony tick zerowy |
| Format wartości | `-12.3` | `+12.3` (ze znakiem) |

**Potrzebna różnica:** orientacja osi (pozioma/pionowa). **Niepotrzebna:** osobny styl i osobny renderer, osobny kontrakt ticków, angielskie/niezgodne nazwy właściwości w GUI.

## 2. Jak zostały zunifikowane

- Jest **jeden renderer** `_render_ruler` (horizontal, zachowany bez zmian) + **wspólny pionowy** `_render_ruler_vertical` (nowa funkcja, ta sama matematyka skali/ticków/markera co horizontal, geometria osi pionowa).
- Wspólne funkcje matematyczne: `_fraction` (value→0..1), `_resolve_major_tick_plan` (kontrakt ticków) i `_nice_step` (AUTO) są **współdzielone** przez oba warianty — nie ma dwóch niezależnych silników.
- `Slope` nie jest już wybierany przez użytkownika; jego **użyteczne funkcje** (etykiety ticków ze znakiem, podświetlenie zera, marker linia) stały się opcjami wspólnego Rulera:
  - `show_tick_labels`, `tick_label_signed`, `zero_tick_color`, `marker_style` (`dot` | `line`).

## 3. Config `orientation` — jak wygląda teraz

```jsonc
"form": "bar",
"bar_style": "ruler",
"orientation": "horizontal",   // lub "vertical"
"major_tick_mode": "count",    // "auto" | "count" | "step"
"major_ticks": 8,
"major_step": 0.0,
"minor_ticks": 5,
"show_tick_labels": false,
"tick_label_signed": false,
"zero_tick_color": "#FFFFFF",
"marker_style": "dot",
"auto_scale": false,
"min_val": 0.0,
"max_val": 100.0
```

Nowy pionowy BAR to `bar_style="ruler"` + `orientation="vertical"` (bez tworzenia Slope). Dla legacy `slope` pola `major_tick`/`minor_tick` są mapowane na `major_step`/`minor_ticks` (kontrakt STEP) przy normalizacji.

## 4. Migracja starych `style=slope`

- **W pamięci, przy renderze**: `_normalize_slope_cfg(cfg)` robi prywatną kopię configu i przekształca:
  ```
  style=slope  ->  bar_style=ruler + orientation=vertical
  ```
  zachowując wygląd legacy (`show_tick_labels=True`, `tick_label_signed=True`, `marker_style="line"`, `show_range_labels=False`, `major_step=major_tick`, `minor_ticks=major_tick/minor_tick`).
- **Bez zapisu do pliku** przy samym otwarciu projektu (AGENTS.md A5).
- **Bez mutacji** oryginalnego configu (TEST 16): oryginał pozostaje nietknięty.
- `get_schema_for_form("bar", bar_style="slope")` nadal zwraca `_bar_slope_fields()` (legacy schema) — stare konfiguracje można edytować, nowe BAR-y tworzy się przez `Ruler` + `Orientacja`.
- `_create_indicator("slope_text")` tworzy od teraz `bar_style="ruler"` + `orientation="vertical"` z pełnymi polami unified (major_tick_mode="step", major_step=5, minor_ticks=5, show_tick_labels=True, tick_label_signed=True, marker_style="line").

## 5. Tekst pionowego BAR-a zawsze poziomy

- `_render_ruler_vertical` **nigdy nie obraca** całego rastra. Oś jest pionowa (linia osi, ticki, marker — geometria Y), ale **wszystko co jest tekstem** (tytuł, etykiety ticków, min/max, bieżąca wartość) jest rysowane normalnie, poziomo:
  - tytuł — u góry, wyśrodkowany (poziomy),
  - etykiety ticków — na lewo od osi, wyrównane do prawej (poziome),
  - wartość bieżąca — na prawo od markera, `anchor="lm"` (pozioma),
  - min/max — na dole/u góry (poziome).
- Zweryfikowane testem TEST 4 (bboks tekstu wartości: szerokość > 2×wysokość, tekst nigdy nie jest pionową kolumną) oraz geometrią: frakcja 0 = dół, 1 = góra.

## 6. Gdzie znajdował się runtime bug markera dystansu w preview

Audyt pełnej ścieżki runtime (realne dane `Video/GX010115.MP4` + `Jazda_na_rowerze_w_porze_lunchu.fit`, v10 preset) wykazał:

**Root cause: `compose_overlay` nie normalizował wartości dystansu dla wskaźników przychodzących przez `extra_indicators` (np. `fit_distance_text`).**

W `compositor.py` konwersja m→km (`/1000`) była wykonywana tylko w pętli po `indicator_values` (pokrywa `dist_visual`/`dist_text`). Wartości z `extra_indicators` (dynamiczne pola FIT, np. `fit_distance_text`) trafiały do `known_vals` **bez konwersji**:

```python
# STARY BUG:
if extra_indicators:
    for k, v in extra_indicators.items():
        known_vals[k] = v        # fit_distance_text = (10129.14, "km", ...) — metry!
```

Potwierdzone runtime: renderer dostawał `('fit_distance_text', 10129.14, 'km', 0.0, 25.0)` — czyli **10129 metrów jako km** na skali 0–25 km.

## 7. Dlaczego marker był na końcu skali

Wartość bieżąca `fit_distance_text` = 10129 m (zamiast 10.129 km), a skala skuteczna = 0–25 km (10Y ustawia max_val w km). Frakcja:
```
frac = (10129 − 0) / (25 − 0) ≈ 405 → clamp 1.0 → marker ZAWSZE na 100% (koniec skali)
```
Dokładnie objaw „marker zawsze lub prawie zawsze przy ostatniej wartości skali" w preview.

## 8. Dlaczego marker znikał w final rendering

Ścieżka finalna (`frame_renderer`, `amd_native_exporter`, `streaming`) używa **tego samego** `compose_overlay` i tych samych danych — więc:
- po poprawce jednostek marker jest liczony w tej samej frakcji co preview i **jest widoczny**;
- wcześniej, jeśli `extra_indicators` dla `fit_distance_text` rozwiązywało się na `None` w danym workerze (brak próbki FIT), wartość = `None` → renderer pomijał marker (brak wartości → brak markera). To był drugi, niezależny objaw „marker niewidoczny w final".

## 9. Jak teraz przechodzi current distance

```
RAW TELEMETRY (metry):     10000 m   (FIT distance / GPMF dist / GPX track)
        ↓  producenci (frame_data / precompute / frame_renderer)
indicator_values["dist_*"] / extra_indicators["fit_distance_text"] = metry
        ↓  JEDEN etap normalizacji w compose_overlay (_dist_display_value)
NORMALIZED DISPLAY (km):   10.0 km
        ↓
BAR: current_value = 10.0, min_val = 0, max_val = np. 25, unit = "km"
        ↓
fraction = _fraction(10.0, 0, 25) = 0.4
        ↓
marker_x / marker_y wg geometrii (horizontal/vertical)
```

## 10. Gdzie następowała niespójność m/km

- **Główne źródło**: `compose_overlay` nie konwertował wartości dystansu z `extra_indicators` (bug z pkt. 6–7) → `unit="km"` z wartością w metrach → „10129 km".
- **Wcześniej naprawione (10Y)**: `register_fit_fields` (max/min /1000, unit km) i `_create_indicator` (unit km dla dystansu) — te dotyczyły **zakresu**, nie wartości bieżącej; teraz wartość bieżąca też jest normalizowana.
- `_get_indicator_range` (10Y) już przeliczał zakres dystansu na km.

## 11. Konwersja dokładnie raz

- Konwersja jest **tylko w `compose_overlay`** — w jednym helperze `_dist_display_value(k, raw)` używanym dla **obu** ścieżek: `extra_indicators` i `indicator_values`.
- `dist_visual`/`dist_text`: baza `distance_m/1000` (km) nadpisywana wartością z `indicator_values` również `/1000` (metry) — wynik zawsze km, **nigdy nie podwójna** konwersja.
- `fit_distance_text` (i każdy klucz z `distance`/`dist_`): `/1000` z surowych metrów.
- Renderer (BAR) otrzymuje już wartości w jednostce display i **nigdy** nie konwertuje jednostek.

## 12. FIT / GPMF / GPX po normalizacji

| Źródło | surowy dystans | normalizacja | do BAR-a |
|---|---|---|---|
| FIT (`distance`, `fit_distance_text`) | metry | `raw/1000` w compose_overlay | km |
| GPMF (`dist_visual`/`dist_text`, `track_samples`) | metry | `raw/1000` w compose_overlay | km |
| GPX (`gpx_track_samples`, `dist_text_gpx`) | metry | `raw/1000` w compose_overlay | km |

Wszystkie trzy dają tę samą semantykę: `10000 m → 10 km`. Zweryfikowane testem TEST 5 oraz runtime (diag: `fit_distance_text` 10129.14 → 10.12914 km).

## 13. Dokładny kontrakt skali i ticków

```
auto_scale (10X, bez zmian):
  false (default) → renderer SZANUJE ręczne min_val/max_val
  true            → max_val = pełny dystans (max_distance_m/1000) dla dystansu

major_tick_mode (nowe, jawny):
  "count" (default nowych BAR-ów) → major_ticks = liczba głównych przedziałów
  "step"                          → major_step > 0 = krok główny (wartość)
  "auto"                          → nice-step z efektywnego zakresu
  brak (legacy 10Y)               → major_step > 0 => STEP, inaczej COUNT

minor_ticks: zawsze liczba drobnych podziałek między głównymi (niezależna od trybu)
```

Działa każda kombinacja: manual range + auto ticks, auto range + auto ticks, manual range + manual step, auto range + manual step (TEST 15).

## 14. Algorytm adaptive nice-step

```python
rough = effective_range / 8
mag   = 10 ** floor(log10(rough))
norm  = rough / mag
nice  = 1.0  jeśli norm < 1.5
        2.0  jeśli norm < 3.0
        5.0  jeśli norm < 7.0
       10.0  w przeciwnym razie
step  = nice * mag
```
Cel: ~5–12 głównych przedziałów. Wybiera 1/2/5×10^n — **nie hardcoduje** pól telemetrycznych.

## 15. Przykładowe kroki AUTO

| Wartość | Zakres | Krok |
|---|---|---|
| Dystans | 0–3 km | 0.5 km (3/0.5 = 6) |
| Dystans | 0–10 km | 1 km |
| Dystans | ~24 km | 2 km |
| Dystans | ~50 km | 5 km |
| Dystans | ~100 km | 10 km |
| Temperatura | 0–10 °C | 1 °C |
| Temperatura | 0–30 °C | 2 lub 5 °C |
| Kadencja | 0–100 rpm | 10 rpm |
| Heart Rate | 40–200 bpm | 20 bpm |
| Prędkość | 0–50 km/h | 5 lub 10 km/h |

## 16. Zmienione pliki i funkcje

| Plik | Funkcja / miejsce | Zmiana |
|---|---|---|
| `src/indicators/compositor.py` | `compose_overlay` (+ helper `_dist_display_value`) | Normalizacja m→km dla dystansu z `extra_indicators` (root-cause fix markera/jednostek). |
| `src/indicators/bar.py` | `_nice_step`, `_resolve_major_tick_plan`, `_render_ruler_vertical`, `_normalize_slope_cfg`, `_render_slope` (wrapper), `_render_bar_indicator`, `_render_ruler` | Unifikacja Ruler/Slope, orientacja, AUTO nice-step, pionowy renderer z poziomym tekstem, migracja legacy. |
| `src/gui/qt/models.py` | `_bar_ruler_fields`, `_bar_slope_fields`, `bar_indicator_fields` | `orientation`, `major_tick_mode`, `show_tick_labels`, `tick_label_signed`, `zero_tick_color`, `marker_style`; usunięto Slope z wyboru; polskie etykiety. |
| `src/gui/qt/_mixins/indicator_mixin.py` | `_create_indicator` (slope_text) | Tworzy `ruler` + `orientation=vertical` + unified ticki. |
| `src/ffmpeg/command_builder.py` | bbox bar/segment_bar (2 miejsca) | Wspólna miara dla `orientation=vertical` (backend-neutralne). |
| `tests/test_bar_orientation_contract.py` | nowy plik | TEST 1–16 (27 testów). |

## 17. Dodane testy

`tests/test_bar_orientation_contract.py` (27 testów):
- **TEST 1** — migracja `style=slope` → `ruler`+`vertical` (w pamięci, bez mutacji, zachowanie właściwości).
- **TEST 2** — Ruler horizontal: skala i marker.
- **TEST 3** — vertical: identyczny plan ticków i `_fraction`, zmienia się tylko oś (min=dół, max=góra).
- **TEST 4** — tekst w pionie NIE obracany (bboks wartości szeroki, nie pionowa kolumna).
- **TEST 5** — `fit_distance_text` m→km w compose_overlay (10000 m → 10.0 km).
- **TEST 6** — marker: zakres 0–20 km, raw 10000 m → 10 km → frakcja 0.5.
- **TEST 7/8** — parity preview/final marker + marker widoczny w final (dla 0/5/10 km).
- **TEST 9–12** — AUTO nice-step: dystans 10 km→1, kadencja 100→10, temperatura mały zakres→1, duże zakresy→bez setek ticków.
- **TEST 13** — manual STEP ma priorytet (legacy 10Y).
- **TEST 14** — COUNT respektuje `major_ticks`.
- **TEST 15** — minor_ticks działa: horizontal, vertical, auto, manual-step, count.
- **TEST 16** — immutability configu (renderer nie mutuje configu).

## 18. Wyniki testów

- **Nowe** `test_bar_orientation_contract.py` → **27 passed**.
- **Zestaw dotkniętych** (slope, tick, distance, parity, pixel, segment, fit_gui, bar_integration, orientation itd.) → **214 passed**.
- **GUI/kontroler** (render_tab, mp4_inspector, qp_analyzer, drag, font, text_size, track_up_map, etap10m2, solar_pct, etap6b, controller_properties, layout_manager) → **117 passed**.
- **Pełny test suite** → **923 passed, 17 skipped, 9 failed**.
- **9 failures = wszystkie pre-existing** (potwierdzone przez `git stash` na czystym baseline bez moich zmian):
  - `test_static_indicator_cache::test_slope_dynamic_marker_and_static_style_miss` (sprawdza `_STATIC_CACHE` stats; slope/vertical używa osobnego `_RULER_BASE_CACHE`),
  - `test_amd_native_etap5b::test_current_layout_uses_only_four_dynamic_fit_fields`,
  - `test_etap5e1_chart_prefix` (2),
  - `test_etap5e3_dynamic_prefix` (1),
  - `test_etap8m7_chart_frame_clipping::test_chart_outer_geometry_stable_after_padding`,
  - `test_etap8q_dirty_text_cache`, `test_etap8s_flush_batching`, `test_etap8t_b_async_pipeline`.
- `get_errors` na zmienionych plikach → brak błędów.

## 19. Czy ETAP 10X i 10Y nadal przechodzą

**Tak.** `auto_scale` gating w `compositor.py` niezmieniony; `test_distance_bar_scale_contract.py` (11) i `test_etap10n3_distance_marker.py` (6) przechodzą w całości. Kontrakt 10Y (COUNT/STEP, `major_step` legacy, `ticks` fallback) zachowany w `_resolve_major_tick_plan` (test `test_bar_ruler_tick_contract.py` 12 passed).

## 20. Czy preview/final marker parity jest potwierdzone

**Tak — runtime i testem.** `compose_overlay` jest wspólną ścieżką dla preview (`fast_preview=True`) i final (`fast_preview=False`, frame_renderer/AMD/NVIDIA/Intel). Diagnostyka na realnych danych pokazała identyczną pozycję markera w obu ścieżkach; TEST 7/8 blokuje parity i widoczność (0/5/10 km).

## 21. Czy dotknięto AMD/NVIDIA/Intel

**Pipeline'y — nie.** Nie zmieniano: decoderów/encoderów, NVENC/AMF, D3D11, CUDA, kontekstów sprzętowych, FFmpeg, formatów pikseli, synchronizacji GPU, uploadu/downloadu, kompozytowania, przekazywania do enkodera.

**Jedyna zmiana współdzielona/backend-neutralna:** `src/ffmpeg/command_builder.py` (pomiar bbox HUD) — rozszerzono warunek „wysoki/wąski raster" o `orientation="vertical"` dla ruler. Dotyczy wszystkich backendów jednakowo i nie zmienia zachowania dla istniejących configów (tylko dodaje nowy przypadek). NVIDIA path preserved statically; runtime NVIDIA nie był możliwy na tej maszynie (AMD).

## 22. Co sprawdzić ręcznie w GUI

1. **Dystans horizontal**: BAR 0–pełny dystans, marker przesuwa się z filmem (po włączeniu Auto skala — dla pełnej trasy; manual respektuje ręczny zakres).
2. **Dystans vertical**: ten sam BAR po zmianie tylko `Orientacja → Pionowa` (bez tworzenia Slope) — marker wg tej samej frakcji, min=dół/max=góra.
3. **Teksty w pionie**: wartości, jednostki, label pozostają poziome.
4. **Preview vs Render**: dla tej samej chwili marker w tym samym miejscu.
5. **FIT**: 10 000 m wyświetlane jako `10 km`, nigdy `10000 km` (dodaj `fit_distance_text`).
6. **Auto major step**: sprawdź dystans, temperaturę, kadencję, prędkość, HR (Tryb podziałki gł. → Auto).
7. **Stary projekt ze Slope**: po wczytaniu wygląda tak samo, ale jest obsługiwany jako vertical Ruler (w Property Editor widać `Orientacja: Pionowa`).

---

## Podsumowanie (AGENTS.md)

### Changed
`src/indicators/compositor.py` (normalizacja dystansu w extra_indicators — root-cause fix), `src/indicators/bar.py` (unifikacja Ruler/Slope, orientacja, AUTO nice-step, pionowy renderer), `src/gui/qt/models.py` (schematy: orientation, major_tick_mode itd., usunięcie Slope z wyboru), `src/gui/qt/_mixins/indicator_mixin.py` (tworzenie slope→ruler+vertical), `src/ffmpeg/command_builder.py` (bbox vertical, backend-neutralne), nowy `tests/test_bar_orientation_contract.py`.

### Preserved
- ETAP 10X (`auto_scale`) i 10Y (COUNT/STEP, legacy `ticks`, `major_step`) — bez zmian.
- Matematyka markera `_fraction` i geometria horizontal `_render_ruler` — bez zmian.
- Legacy `style=slope` renderuje identycznie (normalizacja w pamięci, bez zapisu do pliku).
- Pipeline'y AMD/NVIDIA/Intel, FFmpeg, SmartSync, telemetria, mapy — bez zmian.

### Tested
27 (nowe) + 214 (dotknięte) + 117 (GUI) + pełny suite 923 passed / 17 skipped. 9 failures — wszystkie potwierdzone pre-existing (stash).

### Not tested
- Runtime GPU (AMD/NVIDIA/Intel) eksportu na sprzęcie — ścieżka wspólna, ale nie uruchamiana. NVIDIA preserved statically.

### Risks / Remaining issues
- `_SLOPE_BASE_CACHE` pozostał jako martwa stała (stary slope nie jest już używany); bezpieczne do usunięcia w osobnym zadaniu.
- Stare projekty z dystansowym `max_val` zapisanym w metrach (sprzed 10Y) przy `auto_scale=False` nadal wymagają `auto_scale=True` lub poprawy `max_val` (odnotowane też w 10X).
- Pre-existing failures: 9 (lista w pkt. 18).
