# RAPORT ETAP 15 — time_display: Ikona + Globalna Skala Rozmiar + Cache

**Status:** ✅ Zakończone
**Zakres:** `src/indicators/time_display.py`, `src/gui/qt/models.py`, `src/gui/qt/_mixins/indicator_mixin.py`, nowy `tests/test_time_display_icon_size.py`
**Testy:** pełny suita — **984 passed / 17 skipped / 9 failed** (9 failed = te same, znane i pre-existing, niezwiązane z time_display)

---

## 1. Cel zadania

Naprawić `time_display` (blok Data / Godzina / Czas / Śr. prędkość):

1. Nowo tworzony wskaźnik nie może być **gigantyczny** — musi mieć rozsądne domyślne rozmiary.
2. Globalne **Rozmiar** (`size`) ma być **master scale całego bloku**: `1.0` = standardowy wygląd, `0.5` = połowa, `2.0` = podwójny.
3. **Rozmiar musi faktycznie działać** (nie „nie reaguje").
4. Per-line lokalne font sizes (`date/time/elapsed/avg_speed_font_size`) mają działać niezależnie.
5. Przywrócić pole **Ikona** w Property Editor (domyślnie `clock`).
6. Renderer obsługiwał ikonę od zawsze — GUI miało brakować pola.
7. **Ikona skaluje się z Rozmiarem.**
8. Cache musi być unieważniany po zmianie size / fontów / kolorów / ikony / etykiet.
9. **Preview == Final** (ten sam renderer, wynik deterministyczny).
10. **Backward compat**: stare projekty (bez `icon`, z `size=0.1`) nie mogą się zepsuć ani zmienić wyglądu.
11. Baseline = wcześniejszy poprawnie wyglądający preset.

---

## 2. Baseline (sprawdzony wizualnie preset v10)

`presets/cycling_dashboard_v10.json` → `indicators.time_display`:

```jsonc
{
  "icon": "clock",
  "size": 0.1,          // ← stara semantyka: renderer mnożył ×10 → efektywnie 1.0
  "font_size": 1.8,     // globalny bazowy rozmiar
  "date_font_size": 1.2,
  "time_font_size": 1.9,
  "elapsed_font_size": 1.5,
  "avg_speed_font_size": 1.5,
  "date_color": "#C8C8C8", "time_color": "#FFFFFF",
  "elapsed_color": "#E8E8E8", "avg_speed_color": "#FFD42A"
}
```

Wszystkie presety v1..v10 używają `size = 0.1` (stary mnożnik `0.1 × 10 = 1.0`). To jest **dobry baseline** dla nowych domyślnych wartości.

---

## 3. Przyczyny źródłowe (audyt)

### 3.1. Gigantyczny nowy wskaźnik — rozjazd semantyki `size`

- Renderer: `size_mult = cfg.get("size", 0.1) * 10` → oczekiwał `size ~0.1`.
- Schemat/utworzenie wskaźnika: domyślny `size = 2.5` (wspólny domyślny z innych wskaźników).
- Nowy `time_display` dostawał `size = 2.5` → `size_mult = 25` → każda linia: `s(font_size, min_dim) × 25` (np. ~450 px) — **gigant**.

### 3.2. „Rozmiar nie reaguje" — cache key bez stylów

Klucz cache zawierał `canvas, font_path, teksty, show_*, icon`, ale **NIE zawierał** `size`, `font_size`, `{prefix}_font_size`, `{prefix}_color`, `{prefix}_label`, `show_{prefix}_label`. Zmiana „Rozmiar" (lub per-line fonta/koloru) nie zmieniała klucza → renderer zwracał **nieaktualny raster** z `_STATIC_CACHE`.

### 3.3. Brak pola Ikona

`time_display_indicator_fields()` budowało własny header **bez pola `icon`** (w przeciwieństwie do `_header_fields()`). Renderer obsługiwał `cfg["icon"]` (clock/camera/temperature/battery/solar), ale GUI nie miało gdzie go ustawić.

### 3.4. Per-line defaulty nie bazowały na baseline

Domyślne `date_font_size/time_font_size/elapsed_font_size/avg_speed_font_size` = `2.0/2.5/2.5/2.0`, a poprawny baseline to `1.2/1.9/1.5/1.5`.

---

## 4. Wprowadzone zmiany

### 4.1. Renderer — `src/indicators/time_display.py`

1. **Normalizacja legacy → nowa skala master**:
   ```python
   _TIME_DISPLAY_LEGACY_SIZE_MAX = 0.25

   def _time_display_master_size(cfg):
       raw = float(cfg.get("size", 0.1))
       if raw <= _TIME_DISPLAY_LEGACY_SIZE_MAX:   # legacy v1..v10: 0.1 → 1.0
           return raw * 10.0
       return raw                                  # nowa semantyka: 1.0 = standard
   ```
   - `size=0.1` (legacy) → master `1.0` — **identyczny wynik jak przed zmianą** (stary `0.1×10=1.0`).
   - `size=1.0` → master `1.0` (standard), `0.5` → połowa, `2.0` → podwójny.

2. **`size_mult` zastąpione przez `master`** we wzorze na czcionkę każdej linii:
   ```python
   fs = max(1, int(s(cfg.get(f"{prefix}_font_size", global_fs), min_dim) * master))
   ```

3. **Klucz cache** rozszerzony o wszystkie parametry wyglądu (naprawa „Rozmiar nie reaguje"):
   ```python
   cache_key = _static_cache_key(
       "time_display", canvas_w, canvas_h, font_path,
       date_text, time_text, elapsed_str, avg_speed_str,
       show_date, show_time, show_elapsed, show_avg_speed,
       master, cfg.get("font_size", 0.025), cfg.get("icon", "none"),
       *_style_parts,   # {prefix}_font_size, {prefix}_color, {prefix}_label, show_{prefix}_label
   )
   ```

4. **Ikona skaluje się z Rozmiarem**:
   ```python
   icon = _get_clock_icon(cfg.get("icon"), max(12, int(global_fs * master * 0.9)))
   icon_gap = max(2, int(global_fs * master * 0.18)) if icon else 0
   ```

5. Brak `icon` w cfg → nadal brak ikony (`cfg.get("icon")` = `None` → `_get_clock_icon` zwraca `None`). **Stare projekty v1..v8 bez `icon` wyglądają identycznie** (bez zegara).

### 4.2. Schema — `src/gui/qt/models.py` (`time_display_indicator_fields`)

- `size`: `default=2.5` → **`1.0`** (master scale), zakres `0.05..10.0`, krok `0.05` (legacy `0.1` nadal mieszczący się w zakresie).
- Dodane pole **`icon`**: `choice none/clock/camera/temperature/battery/solar`, **default `"clock"`**.
- Per-line defaulty dopasowane do baseline v10: `date_font_size=1.2`, `time_font_size=1.9`, `elapsed_font_size=1.5`, `avg_speed_font_size=1.5`.

### 4.3. Utworzenie wskaźnika — `src/gui/qt/_mixins/indicator_mixin.py` (`_create_indicator`)

- Pierwsza sekcja `time_display`: per-line font sizes + `font_size=1.8` (baseline v10).
- Druga sekcja (po clobberze `form=="text" → size=font_size`):
  ```python
  defaults["form"] = "time_display"
  defaults["size"] = 1.0   # master scale, standard
  defaults["icon"] = "clock"
  ```

> Uwaga implementacyjna: `get_form_for_key("time_display")` zwraca `("text", {})`, więc wcześniejsza linia `if defaults.get("form") == "text": defaults["size"] = defaults["font_size"]` nadpisałaby `size` — dlatego `size=1.0` ustawiane jest w **drugiej** sekcji.

---

## 5. Testy — `tests/test_time_display_icon_size.py` (21 testów, TEST 1–13)

| # | Test | Co weryfikuje |
|---|------|---------------|
| 1 | `test_new_default_size_is_sane` | Nowy wskaźnik ma rozsądny rozmiar (nie gigant) |
| 1 | `test_new_default_size_matches_v10_baseline` | `size=1.0` renderuje **piksel-w-piksel** identycznie jak legacy `0.1` |
| 2 | `test_global_master_scale_halves_bbox` | master `0.5` → wysokość ~połowa |
| 2 | `test_global_master_scale_doubles_single_line` | master `2.0` → linia ~2× wyższa |
| 3 | `test_master_scale_affects_every_line` | każda z 4 linii skaluje się z Rozmiarem |
| 4 | `test_local_font_size_affects_only_its_line` | per-line font zmienia tylko swoją linię |
| 5 | `test_schema_has_icon_field` | schema zawiera pole `icon` z pełną listą wyboru |
| 5 | `test_schema_icon_default_is_clock` | default ikony = `clock` |
| 5 | `test_schema_size_default_is_one` | default Rozmiaru = `1.0` |
| 6 | `test_icon_clock_wider_than_none` | ikona `clock` poszerza blok vs `none` |
| 6 | `test_icon_scales_with_master_size` | ikona rośnie wraz z Rozmiarem |
| 7 | `test_cache_invalidation_on_size_change` | zmiana size → inny raster (cache fix) |
| 7 | `test_cache_invalidation_on_icon_change` | zmiana ikony → inny raster |
| 7 | `test_cache_invalidation_on_per_line_style_change` | zmiana per-line fonta → inny raster |
| 7 | `test_cache_invalidation_on_color_change` | zmiana koloru dociera do rastra |
| 7 | `test_property_live_update_reflects_immediately` | symulacja GUI: mutacja cfg → natychmiastowy efekt |
| 8 | `test_render_is_deterministic_preview_final_parity` | ten sam input → identyczne rastry (Preview == Final) |
| 8 | `test_compose_overlay_path_renders_time_display` | końcowa składnia (`compose_overlay`) obsługuje time_display |
| 9 | `test_legacy_config_without_icon_renders_like_none` | legacy bez `icon` == `icon="none"` |
| 9 | `test_minimal_legacy_cfg_does_not_crash` | minimalny legacy config renderuje bez błędu |
| 10 | `test_canonical_defaults_match_v10_baseline` | kanoniczne defaulty = baseline v10 |

Testy skali wysokości używają prawdziwego fontu TrueType (Arial, rozwiązywany przez `resolve_indicator_font_path`) — fallback PIL `load_default()` rysuje stałą wysokość niezależnie od rozmiaru. Porównania rastrów robione są w kanale **RGB** (gotcha: `getbbox()` na RGBA zwraca `None`, gdy różnice są tylko w RGB, a alfa jest zerowa).

---

## 6. Wyniki

### 6.1. Nowe testy

```
tests/test_time_display_icon_size.py  → 21 passed
```

### 6.2. Powiązane testy (time_display / schema / GUI / kompozycja)

```
tests/test_time_display_optimization.py
tests/test_time_display_icon_size.py
tests/test_indicator_config_parity.py
tests/test_font_selection.py
tests/test_amd_chart_map_split.py   → 90 passed
```

### 6.3. Pełny suita

```
984 passed, 17 skipped, 9 failed (89.55s)
```

9 failed = **te same pre-existing** (potwierdzone wcześniej przez `git stash`, niezwiązane z time_display):
`test_amd_native_etap5b`, `test_etap5e1_chart_prefix` (2), `test_etap5e3_dynamic_prefix`, `test_etap8m7_chart_frame_clipping`, `test_etap8q_dirty_text_cache`, `test_etap8s_flush_batching`, `test_etap8t_b_async_pipeline`, `test_static_indicator_cache`.

### 6.4. Sanity-check na realnym presecie (1280×720, Arial)

```
v10 (size=0.1, legacy)  → master 1.0 → bbox (120, 58)
nowy (size=1.0)         → bbox (120, 58) → IDENTYCZNY (byte-for-byte)
size=2.5 (nowa semantyka)→ master 2.5 → bbox (302, 144)  (stara semantyka dałaby ~25× → ~1200 px)
```

---

## 7. Podsumowanie AGENTS.md

### Changed
- `src/indicators/time_display.py` — `_time_display_master_size()` (normalizacja legacy), użycie `master` w per-line font sizes, cache key z pełnym zestawem stylów, ikona skalująca się z Rozmiarem.
- `src/gui/qt/models.py` — `time_display_indicator_fields()`: `size` default `1.0`, nowe pole `icon` (default `clock`), per-line defaulty = baseline v10.
- `src/gui/qt/_mixins/indicator_mixin.py` — `_create_indicator` dla `time_display`: `size=1.0`, `icon="clock"`, font sizes = baseline v10.
- `tests/test_time_display_icon_size.py` — nowy (21 testów).

### Preserved
- **CPU/AMD/NVIDIA/Intel** — pipeline renderowania nietknięte; dotknięty tylko jeden wskaźnik (time_display).
- Legacy presety **v1..v10**: `size=0.1` → master `1.0` (identyczny wynik); brak `icon` → nadal bez ikony (v1..v8). Wygląd zapisanych projektów bez zmian.
- Kolejność kompozycji (z-order), kanał czasu/telemetria, `time_block` (osobny renderer) — bez zmian.
- Pozostałe wskaźniki (text/gauge/bar/chart/map/lean) — bez zmian.

### Tested
- Nowe testy (21) + powiązane (90) + pełny suita (984 passed / 17 skipped / 9 pre-existing failed).
- Render realnego presetu v10 (1280×720) i porównanie legacy `0.1` vs nowe `1.0` (byte-for-byte).
- Preview==Final przez determinizm renderera + `compose_overlay` (ta sama ścieżka dla preview i eksportu).

### Not tested
- NVIDIA: brak runtime (maszyna AMD). Zmiany dotyczą wyłącznie CPU renderera `time_display` (wspólnego dla wszystkich backendów), nie dotykają GPU paths → NVIDIA zachowana statycznie.
- Pełny render 4K: nie uruchamiano (wymóg ekonomii testów; zmiana skaluje się proporcjonalnie z rozdzielczością).

### Risks / Uwagi
- **Próg normalizacji `size ≤ 0.25`**: wartości z zakresu `0.1..0.25` w konfiguracjach ręcznych traktowane są jako legacy-frakcja (×10). Wszystkie oficjalne presety używają dokładnie `0.1`, a nowa domyślna wartość to `1.0`, więc praktyczne ryzyko jest minimalne; próg udokumentowany w `_time_display_master_size`.
- Minimalny rozmiar ikony (clamp `12` px) oznacza, że przy bardzo małym masterze ikona nie kurczy się poniżej 12 px — celowe (czytelność).
- Globalne `font_size` nadal nie jest polem Property Editor (renderer używa go jako fallback) — poza zakresem zadania, do ewentualnego osobnego etapu.

---

## 8. Wnioski

- Przyczyna „gigantycznego" time_display: rozjazd semantyki `size` (renderer oczekiwał `0.1`, GUI dawało `2.5` → `×25`). Naprawione przez master scale z normalizacją legacy.
- Przyczyna „Rozmiar nie reaguje": cache key nie zawierał parametrów stylu. Naprawione.
- Pole Ikona przywrócone do schematu; renderer obsługiwał je od zawsze.
- Backward compat zachowany: legacy `0.1` == nowe `1.0` (byte-for-byte), legacy bez ikony == `icon=none`.
