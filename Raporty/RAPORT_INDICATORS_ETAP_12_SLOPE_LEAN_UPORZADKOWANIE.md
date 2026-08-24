# RAPORT — Uporządkowanie `Slope`: vertical BAR ≠ Slope, nowy wskaźnik przechyłu (Lean)

**Etap:** 12 (SLOPE/LEAN — SEMANTYKA + NOWY WSKAŹNIK PRZECHYŁU)
**Data:** 2026-08-23
**Baseline:** ETAP 11B (`RAPORT_INDICATORS_ETAP_11B_UNIFIKACJA_BAR_MARKER_JEDNOSTKI.md`) + 10X/10Y.
**Zakres:** uporządkowanie semantyki BAR-a (pionowy BAR ≠ Slope), nowy osobny wskaźnik animowany `Przechył`/Lean (obracana grafika, GPMF gyro / FIT grade, mnożnik, clamp). **Bez zmian** pipeline'ów AMD/NVIDIA/Intel, FFmpeg, SmartSync, map, GPU compositing (jedyna zmiana wspólna to backend-neutralny bbox w `command_builder.py`).

---

## 1. Gdzie `Slope` było używane błędnie jako pionowy BAR

Po ETAP 11B pionowy BAR został zintegrowany z `Ruler` (`orientation=vertical`), ale pojęcie `Slope` wciąż było przypięte do **nachylenia terenu** (grade) wyświetlanego jako pionowy BAR:

- `slope_text` → strumień danych `display_name="Slope / Grade"` (`indicator_mixin._discover_data_streams`),
- `_create_indicator("slope_text")` → label `"SLOPE"`, `field="slope"`,
- legacy schema `_bar_slope_fields` (`get_schema_for_form("bar", bar_style="slope")`),
- renderer `_render_slope` / `_normalize_slope_cfg` (normalizacja do `ruler`+`vertical`),
- `registry.DEFAULT_FORM_RULES` `("slope", "bar", 20.0)` → `bar_style="slope"`.

To mieszało dwa znaczenia: **pionowy BAR** (jak wysokościomierz, wyświetla nachylenie terenu w %) i **prawdziwy `Slope`/Lean** (przechył roweru/kamery z żyroskopu). Zadanie (ETAP 12) rozdziela je.

## 2. Jak uporządkowano model BAR-a i orientacji

- **BAR / Ruler pozostaje zwykłym wskaźnikiem liniowym**: `Forma: bar`, `Styl: ruler`, `Orientacja: pozioma / pionowa`. Pionowy BAR **nie jest nazywany `Slope`**.
- **W GUI** strumień danych nachylenia terenu przemianowano z `"Slope / Grade"` na **`"Nachylenie trasy (Grade)"`** (`indicator_mixin._discover_data_streams`) — żeby nie mylić z nowym `Przechył`.
- `bar_style="slope"` nie jest już wybieranym wariantem (usunięty z wyborów w 11B); `_bar_slope_fields` pozostał wyłącznie jako schema do edycji starych configów.
- **Nowy wskaźnik przechyłu** to osobny `form == "lean"` (klucz `lean_indicator`), **nie BAR**.

## 3. Kompatybilność starych projektów z legacy slope

- Stare projekty z `bar_style="slope"` (pionowy BAR grade) **nadal renderują się identycznie** — `_normalize_slope_cfg` mapuje w pamięci `style=slope → ruler + orientation=vertical`, bez mutacji oryginalnego configu i bez zapisu do pliku (TEST 1).
- `get_schema_for_form("bar", bar_style="slope")` nadal zwraca legacy schema (`_bar_slope_fields`) — stare konfiguracje można edytować.
- Nowo tworzony pionowy BAR używa `bar_style="ruler"` + `orientation="vertical"` (TEST 2).

## 4. Jak nazywa się prawdziwy wskaźnik przechyłu

- **GUI:** `Przechył` (alias: `Lean`).
- **Wewnętrzny klucz:** `lean_indicator`.
- **Forma:** `"lean"` (osobna, nie `bar`).

## 5. Jakie źródła danych obsługuje nowy wskaźnik

| Źródło | Opis | Pole |
|---|---|---|
| `GPMF Gyro` (domyślne) | żyroskop GoPro, wybór osi | `gyro_x` / `gyro_y` / `gyro_z` (rad/s) |
| `FIT Grade / nachylenie terenu` | nachylenie trasy (wyraźnie oznaczone, że to NIE przechył) | `slope` (%) |

Źródła są **wyraźnie rozdzielone** w GUI (etykiety „GPMF Gyro (żyroskop)" vs „FIT Grade / nachylenie terenu") i w logice (`frame_data`), nie są mieszane semantycznie (TEST 8).

## 6. Jak rozwiązano wybór osi

- Właściwość `axis` (`x` | `y` | `z`) — użytkownik wybiera oś żyroskopu.
- W GUI pokazane przyjazne mapowanie: `X (roll)`, `Y (pitch)`, `Z (yaw)` (opis osi GPMF).
- `frame_data` rozwiązuje pole `gyro_{axis}` na podstawie configu — zmiana osi zmienia używane pole telemetryczne (TEST 3).

## 7. Przeliczenie raw → multiplier → clamp → final angle

```python
# src/indicators/lean.py — lean_angle(raw, cfg)
raw
→ normalization:  degrees_per_unit = 180/π dla gyro, 1.0 dla grade
→ sensitivity multiplier
→ clamp [-max_angle, +max_angle]
→ final angle [°]
```

Przykłady (TEST 4/5/6):
- gyro `raw=1.0 rad/s`, `sensitivity=0.2`, `max_angle=90` → `1.0 * (180/π) * 0.2 ≈ 11.5°`,
- grade `raw=5.0%`, `sensitivity=1.0` → `5.0°`,
- `sensitivity=0.1 → 0.4` daje 4× silniejszy wychył, surowa próbka bez zmian,
- duży sygnał (`raw=100`) → clamp do `±max_angle` (np. ±15°), wskaźnik „nie odlatuje".

## 8. Jednostki i normalizacja

- **GPMF gyro:** rad/s (szybkość kątowa). Normalizacja: rad→stopnie (`*180/π`), potem mnożnik i clamp. Finalny kąt wyświetlany w **°**.
- **FIT grade:** % (nachylenie). Normalizacja 1:1 (1% ≈ 1°), mnożnik i clamp.
- Wartość `None` (brak próbki) → kąt 0°, bez „odlotu".

## 9. Grafika obracana i pivot

- Grafika obracana jest wokół **środka grafiki** (pivot centralny — najbezpieczniejszy wybór).
- **`graphic="bike"`** (domyślne): wczytuje zastrzeżony asset `wzor/rower_ico.png` (do tej pory zarezerwowany dla przyszłego Lean — to zadanie go otwiera), skalowany do rozmiaru wskaźnika z zachowaniem proporcji. Gdy brak pliku → fallback proceduralny.
- **`graphic="beam"`**: proceduralna sylwetka roweru (belka + 2 koła + pivot) w `marker_color`.
- **`graphic="none"`**: brak grafiki (tylko linia odniesienia + odczyt).
- Obrót: `Image.rotate(angle)` z `expand=True`, potem centralne `alpha_composite`. Pozytywny kąt → wychył w prawo (zgodnie z ruchem wskazówek).
- **Cały raster NIE jest obracany** — tekst (tytuł, odczyt) zawsze poziomy; obracana jest tylko grafika.
- Elementy pomocnicze (opcjonalne): linia odniesienia 0° (`show_reference`), podziałka kątowa co 10° w zakresie `±max_angle` (`show_ticks`).

## 10. Odczyt liczbowy

- `show_value=True` (domyślne) → odczyt kąta finalnego w **°** (`+5°`, `-3°`), `decimals` liczba miejsc dziesiętnych.
- Odczyt rysowany poziomo pod grafiką.

## 11. Zmienione pliki i funkcje

| Plik | Zmiana |
|---|---|
| `src/indicators/lean.py` (NOWY) | `lean_angle`, `_load_lean_graphic`, `_render_lean_indicator` + małe helpery tekstowe. |
| `src/indicators/dispatcher.py` | import + routing `form == "lean"` → `_render_lean_indicator`. |
| `src/indicators/registry.py` | `("lean", "lean", 14.0)` w DEFAULT_FORM_RULES; `lean_indicator → gpmf` w DEFAULT_SOURCE_MAP. |
| `src/indicators/frame_data.py` | rozwiązywanie `lean_indicator` (gyro_axis / slope) w pętli dynamicznych wskaźników. |
| `src/indicators/compositor.py` | `known_vals["lean_indicator"] = (None, "°", "Przechył")`. |
| `src/gui/qt/models.py` | `lean_indicator_fields()` + `FORM_SCHEMA_MAP["lean"]` + `_form_field` z opcją `("lean","Przechył")`. |
| `src/gui/qt/_mixins/indicator_mixin.py` | strumień `lean_indicator` („Przechył (Lean)"), przemianowanie strumienia grade na „Nachylenie trasy (Grade)", `_create_indicator("lean_indicator")`, `_get_indicator_range("lean_indicator") → (None,None)`. |
| `src/ffmpeg/command_builder.py` | bbox `form == "lean"` (kwadratowy, backend-neutralny) w obu funkcjach pomiaru. |
| `tests/test_lean_indicator_contract.py` (NOWY) | TEST 1–9 (13 testów). |

## 12. Dodane testy

`tests/test_lean_indicator_contract.py` (13 testów):
- **TEST 1** — legacy `style=slope` (pionowy BAR) nadal renderuje się, normalizuje do `ruler`+`vertical`, nie mutuje configu.
- **TEST 2** — nowy pionowy BAR nie używa nazwy/znaczenia `slope`; `lean` to osobna forma (nie bar).
- **TEST 3** — wybór osi zmienia używane pole (`gyro_x/y/z`); źródło `grade` rozwiązuje `slope`.
- **TEST 4** — raw → display angle (rad→deg, mnożnik, clamp) poprawne.
- **TEST 5** — mnożnik zmienia wychył, nie zmienia surowej próbki.
- **TEST 6** — clamp: duży sygnał nie przekracza `max_angle`.
- **TEST 7** — preview/final parity: ten sam kąt obrotu (identyczny raster wskaźnika).
- **TEST 8** — FIT grade vs gyro wyraźnie rozdzielone (różna normalizacja, różne etykiety).
- **TEST 9** — GUI: pionowy BAR nie jest `Slope`; `Przechył` ma osobne właściwości.

## 13. Wyniki testów

- Nowe `test_lean_indicator_contract.py` → **13 passed**.
- Zestaw dotkniętych (lean, orientation, slope, tick, distance, parity, pixel, segment, fit_gui, bar_integration itd.) → **222 passed**.
- **Pełny test suite** → **936 passed, 17 skipped, 9 failed**.
- **9 failures = wszystkie pre-existing** (identyczne jak w ETAP 11B, potwierdzone wcześniej stash-em): `test_amd_native_etap5b` (dynamic fit fields), `test_etap5e1_chart_prefix` (2), `test_etap5e3_dynamic_prefix` (1), `test_etap8m7_chart_frame_clipping` (off-by-one), `test_etap8q_dirty_text_cache`, `test_etap8s_flush_batching`, `test_etap8t_b_async_pipeline`, `test_static_indicator_cache::test_slope_dynamic_marker_and_static_style_miss`.
- `get_errors` na zmienionych plikach → brak błędów.

## 14. Czy preview i final rendering mają parity

**Tak — potwierdzone runtime i testem.** `lean_indicator` przechodzi przez wspólną ścieżkę `prepare_overlay_frame_data` → `compose_overlay` (preview `fast_preview=True` i final `fast_preview=False` używają tego samego rozwiązywania gyro przez `resolve_cache_value`). Smoke na realnych danych (`GX010115`): gyro_z = 0.4569 rad/s → kąt **+5.2°**, bbox i raster wskaźnika **identyczne** dla FINAL i PREVIEW. TEST 7 blokuje parity.

## 15. Czy dotknięto AMD/NVIDIA/Intel

**Pipeline'y — nie.** Nie zmieniano: decoderów/encoderów, NVENC/AMF, D3D11, CUDA, kontekstów sprzętowych, FFmpeg, formatów pikseli, synchronizacji GPU, uploadu/downloadu, kompozytowania, przekazywania do enkodera. Jedyna zmiana wspólna to backend-neutralny bbox `form == "lean"` w `command_builder.py` (dotyczy wszystkich backendów jednakowo). NVIDIA path preserved statically; runtime NVIDIA nie był możliwy na tej maszynie (AMD).

## 16. Co sprawdzić ręcznie w GUI

1. W panelu strumieni danych widać **„Przechył (Lean)"** (nowy) oraz **„Nachylenie trasy (Grade)"** (stary grade) — wyraźnie rozdzielone.
2. Dodaj `Przechył` → Property Editor pokazuje: Źródło (GPMF Gyro / FIT Grade), Oś (X/Y/Z), Mnożnik wychyłu, Maks. kąt, Grafikę (Rower/Belka/Brak), Pokaż wartość, linię odniesienia i podziałkę.
3. Zmień oś (Z→X) → grafika zaczyna reagować na inną oś żyroskopu.
4. Zwiększ Mnożnik → mocniejszy wychył; ustaw dużą wartość → kąt ograniczony do Maks. kąta (clamp).
5. Podczas jazdy po zakrętach grafika (rower) wychyla się w lewo/prawo zgodnie z przechyłem; odczyt liczbowy w ° pod grafiką.
6. Preview vs Render (eksport) → ta sama pozycja/wychył grafiki dla tej samej chwili.
7. Otwórz stary projekt z legacy `slope` (pionowy BAR grade) → nadal renderuje się, w GUI widać go jako Ruler pionowy, a nie `Przechył`.

---

## Podsumowanie (AGENTS.md)

### Changed
`src/indicators/lean.py` (nowy renderer przechyłu), `dispatcher.py`, `registry.py`, `frame_data.py`, `compositor.py`, `models.py` (schema `lean`), `indicator_mixin.py` (stream + creation + nazwa grade), `command_builder.py` (bbox lean), nowy `tests/test_lean_indicator_contract.py`.

### Preserved
- Pionowy BAR (Ruler + `orientation=vertical`) i legacy `style=slope` — kompatybilne, bez zmian wyglądu.
- ETAP 10X (`auto_scale`), 10Y (COUNT/STEP) i 11B (unifikacja Ruler/Slope) — bez zmian.
- Pipeline'y AMD/NVIDIA/Intel, FFmpeg, SmartSync, mapy — bez zmian.
- `wzor/rower_ico.png` — użyty jako grafika Lean (zgodnie z AGENTS.md §32 — to zadanie otwiera Lean), plik nietknięty.

### Tested
13 (nowe) + 222 (dotknięte) + pełny suite 936 passed / 17 skipped. 9 failures — wszystkie pre-existing (potwierdzone stash-em w 11B). Smoke real-data: gyro dostępny, preview==final.

### Not tested
- Runtime GPU (AMD/NVIDIA/Intel) eksportu — ścieżka wspólna, nie uruchamiana. NVIDIA preserved statically.

### Risks / Remaining issues
- Wskaźnik Lean używa chwilowej wartości żyroskopu (rad/s) jako proxy przechyłu; nie integruje kąta (drift). Dla precyzyjnego kąta przechyłu potrzebna byłaby integracja/IMU + kalibracja (poza zakresem; zgodnie z AGENTS.md Lean pozostaje „DEFERRED — IMU NOT RELIABLE" dla produkcji).
- Wygładzanie (EMA) nie dodane (opcjonalne w zadaniu) — możliwe w osobnym etapie bez ryzyka regresji.
- Pre-existing failures: 9 (lista w pkt. 13).
