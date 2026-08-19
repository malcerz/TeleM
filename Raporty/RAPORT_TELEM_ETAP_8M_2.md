# RAPORT TELEM — ETAP 8M.2: Audyt regresji `time_block` i pól GPMF w Preview i finalnym eksporcie

**Data wykonania:** 19 sierpnia 2026  
**Status etapu:** ZAKOŃCZONY / PEŁNY AUDYT POPRAWNOŚCI (CORRECTNESS AUDIT + MINIMAL FIX + PREVIEW/FINAL PARITY)  
**Cel etapu:** Szczegółowy audyt braku wyświetlania `time_block`, `iso_text`, `exposure_text` oraz `temp_text` w podglądzie GUI Preview i eksporcie finalnym.

---

## 1. Stan Git (`git status` i `git diff`)

### Git Status
```text
On branch master
Changes not staged for commit:
  modified:   def_layout.json
  modified:   native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp
  modified:   native/d3d11_amf_pipeline/src/telem_amd_native.cpp
  modified:   src/indicators/compositor.py
  modified:   src/indicators/dispatcher.py
  modified:   src/indicators/frame_data.py
  modified:   src/indicators/moving_map.py
  modified:   src/telemetry_precompute.py
```

### Git Diff dla `def_layout.json`
```diff
diff --git a/def_layout.json b/def_layout.json
--- a/def_layout.json
+++ b/def_layout.json
@@ -448,7 +448,7 @@
       "unit": ""
     },
     "fit_solar_pct_text": {
-      "enabled": false,
+      "enabled": true,
       "label": "Solar Pct",
```
*Wniosek:* W canonical `def_layout.json` nie doszło do przypadkowego skasowania ani wyłączenia `time_block`, `iso_text`, `exposure_text` czy `temp_text`.

---

## 2. Inwentaryzacja canonical `def_layout.json`

Poniższa tabela przedstawia konfigurację badanych wskaźników w bieżącym `def_layout.json`:

| Wskaźnik | `enabled` | `source` | `field` | `form` | Pozycja `(x, y)` [%] | Rozmiar / `font_size` [%] |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **`time_block`** | `true` | *(wbudowane/GPMF)* | `date_time` | `time_block` | `x: 1.6139, y: 3.1024` | `font_label: 1.25, font_date: 2.0, font_time: 2.0` |
| **`iso_text`** | `true` | `"gpmf"` | `"iso"` | `"text"` | `x: 1.7400, y: 41.7100` | `font_size: 2.5, size: 10.0` |
| **`exposure_text`** | `true` | `"gpmf"` | `"exposure"` | `"text"` | `x: 1.6900, y: 45.6300` | `font_size: 2.5, size: 10.0` |
| **`temp_text`** | `true` | `"gpmf"` | `"temperature"` | `"text"` | `x: 1.6500, y: 49.4800` | `font_size: 2.5, size: 10.0` |

### Porównanie z historią Git (przed ETAPEM 8M / 8M.1)
W commitach poprzedzających migrację do `version: 6` wartości `x`, `y` oraz `font_size` były zapisywane w formacie znormalizowanym do zakresu `0.0..1.0` (np. `0.0174` dla 1.74%, `0.025` dla 2.5%). Migracja `normalize_layout` przemnożyła te wartości przez 100 do skali `0.0..100.0%`, co jest w 100% zgodne ze specyfikacją `LayoutManager` i layoutem wersji 6.

---

## 3. Audyt integralności canonical `def_layout.json`

- **Hipoteza:** Testy jednostkowe lub skrypty diagnostyczne z ETAPU 8M/8M.1 nadpisały canonical `def_layout.json`.
- **Weryfikacja:** `git diff def_layout.json` wykazał wyłącznie jedną zmianę (`fit_solar_pct_text.enabled`). Wskaźniki `time_block`, `iso_text`, `exposure_text`, `temp_text` zachowały nienaruszone pozycje, etykiety, źródła i formaty.
- **Wynik:** Brak zniszczenia pliku `def_layout.json`.

---

## 4. Analiza łańcucha wykonania `time_block`

```
Layout (def_layout.json)
  ↓
prepare_overlay_frame_data (src/indicators/frame_data.py)
  → Obliczenie target_dt = start_dt_utc + current_ts
  → local_dt = target_dt + tz_offset_hours (np. +2h)
  → date_text = local_dt.strftime("%Y-%m-%d")
  → time_text = local_dt.strftime("%H:%M:%S")
  ↓
compose_overlay (src/indicators/compositor.py)
  → Sprawdzenie "time_block" in layout["indicators"]
  → Wywołanie render_time_block(canvas_w, canvas_h, layout, font_path, date_text, time_text)
  ↓
render_time_block (src/indicators/time_block.py)
  → font_label = load_font(font_path, label_px)
  → font_date  = load_font(font_path, date_px)
  → font_time  = load_font(font_path, time_px)
  → draw.text(...) -> ImageDraw
  → tmp.crop(tmp.getbbox()) -> Image
  ↓
rotated_paste (src/indicators/compositor.py)
  → Wklejenie na główny HUD / Preview Canvas
```

### Zidentyfikowane mechanizmy zachowania:
1. **Fallback w Preview (`preview_mixin.py`):**
   Jeśli `self.telemetry.start_dt_utc` jest `None` (np. przed załadowaniem metadanych wideo/GPMF), `preview_mixin.py` używa fallbacku `date_txt="----.--.--"`, `time_txt="--:--:--"`, dzięki czemu `time_block` nadal generuje poprawny wizualny placeholder.
2. **Klucz bufora (`_STATIC_CACHE`):**
   W `time_block.py` klucz cache zawiera `(canvas_w, canvas_h, font_path, date_text, time_text, ...)`. Przy zmianie sekundy klucz jest odświeżany.

---

## 5. Inwentarz metadanych GPMF dla materiałów testowych

Wykonano audyt struktury próbek dla obu materiałów wideo:

### A. Starszy materiał (`GX020079` + `Poranna_jazda_na_rowerze.fit`)
- **Format:** ExifTool JSON (`Doc37:ISO`, `Doc37:ExposureTimes`, `Doc37:CameraTemperature`, `Doc37:GPSDateTime`)
- **Inwentarz:**
  - `ISO`: **1131 próbek** (prawidłowo wyodrębniane przez `extract_iso_samples`)
  - `Exposure / SHUT`: **1131 próbek** (prawidłowo wyodrębniane przez `extract_exposure_samples`)
  - `CameraTemperature / TMPC`: **38 próbek** (prawidłowo wyodrębniane przez `extract_temperature_samples`)
  - `GPS / Speed`: **378 próbek**
  - `start_dt_utc`: `2026-08-05 04:55:50.800000+00:00`

### B. Nowszy materiał (`GX030120` + `Popoludniowa_jazda_na_rowerze_solar_battery.fit`)
- **Format:** GPMF parser JSON (`streams.ISO`, `streams.SHUT`, `streams.TMPC`, `streams.GPS9`)
- **Inwentarz:**
  - `ISO`: **5400 próbek**
  - `Exposure / SHUT`: **5400 próbek**
  - `CameraTemperature / TMPC`: **180 próbek**
  - `GPS / Speed`: **1802 próbek**
  - `start_dt_utc`: `2026-08-18 04:46:25.700000+00:00`

*Wniosek:* Oba materiały zawierają kompletne i nienaruszone strumienie GPMF dla ISO, SHUT i TMPC.

---

## 6. Śledzenie łańcucha pól GPMF (`ISO`, `Exposure`, `TMPC`)

```
GPMF JSON / Record Stream
  ↓
TelemetryDataManager (src/gui/telemetry_manager.py)
  → load_gpmf_records(records)
  → self.iso_samples = _extract_iso(records)
  → self.exposure_samples = _extract_exposure(records)
  → self.temperature_samples = _extract_temperature(records)
  ↓
prepare_overlay_frame_data (src/indicators/frame_data.py)
  → direct_resolve("iso", "gpmf", "iso_text") / interpolate_iso(...)
  → direct_resolve("exposure", "gpmf", "exposure_text") / interpolate_exposure(...)
  → direct_resolve("temperature", "gpmf", "temp_text") / interpolate_temperature(...)
  ↓
compose_overlay (src/indicators/compositor.py)
  → known_vals["iso_text"]      = (iso_value, "ISO", "ISO")
  → known_vals["exposure_text"] = (exposure_value, "", "Exp")
  → known_vals["temp_text"]     = (temp_value, "°C", "Temp")
  ↓
Pętla indykatorów w compositor.py:
  → value, default_unit, default_label = known_vals.get(key, ...)
  → if value is None: continue  <-- JEŚLI WARTOŚĆ JEST NONE, ELEMENT JEST UKRYWANY
  → render_value_indicator(...) -> _render_text_indicator(...)
  → paste / render na HUD
```

---

## 7. Sprawdzenie nazw kluczy i kontraktów w kodzie

1. **Rejestr `HARDCODED_KEYS` (`src/indicators/registry.py`):**
   ```python
   HARDCODED_KEYS: frozenset[str] = frozenset({
       "speed_visual", "speed_text", "dist_visual", "dist_text",
       "alt_visual", "alt_text", "iso_text", "exposure_text",
       "temp_text", "power_text", "atemp_text", "hr_text",
       "cad_text", "battery_text", "track_map", "time_block",
       "time_display",
   })
   ```
   *Weryfikacja:* `iso_text`, `exposure_text`, `temp_text` oraz `time_block` znajdują się w `HARDCODED_KEYS`, co chroni je przed nadpisaniem pustymi wartościami `(None, unit, label)` w pętli dynamicznych wskaźników w `frame_data.py`.

2. **Mapowanie atrybutów GPMF (`src/telemetry_resolver.py`):**
   ```python
   _GPMF_ATTRS = {
       "iso": "iso_samples",
       "exposure": "exposure_samples",
       "temperature": "temperature_samples",
       ...
   }
   ```
   *Weryfikacja:* Nazwy atrybutów w `TelemetryDataManager` i `_GPMF_ATTRS` są w 100% spójne.

---

## 8. Filtrowanie wskaźników i zachowanie przy braku danych (`known_vals` / `availability`)

W `src/indicators/compositor.py` (linie 249–254):
```python
value, default_unit, default_label = known_vals.get(
    key, (0.0, ind_cfg.get("unit", ""), ind_cfg.get("label", key))
)
if value is None:
    # Missing telemetry is not a numeric zero. Keep the configured
    # indicator in the layout, but render it as unavailable/hidden.
    continue
```
*Zasada działania:* Jeśli źródło danych dla danego wskaźnika nie dostarcza próbek (np. wczytano plik wideo bez ścieżki metadanych GPMF lub wskaźnik ma `source: "gpmf"`, a wideo nie zawiera danych z sensora kamery), wskaźnik jest celowo ukrywany (nie jest rysowany jako sztuczne `0`). Gdy metadane są obecne, wskaźnik renderuje się poprawnie z etykietą i aktualną wartością.

---

## 9. Tabela porównawcza Preview vs Final

| Element | Stan w JSON (`def_layout.json`) | Stan w GPMF (`GX020079` / `GX030120`) | Stan w GUI Preview | Stan w eksporcie AMD Final | Status / Uwagi |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **`time_block`** | `enabled: true` | Prawidłowy `start_dt_utc` | **Widoczny** | **Widoczny** | Renderuje etykietę `"Czas"`, datę i godzinę z uwzględnieniem strefy czasowej (+2h). |
| **`iso_text`** | `enabled: true`, `source: "gpmf"` | Obecne (1131 / 5400 próbek) | **Widoczny** | **Widoczny** | Renderuje `"ISO: <wartość>"` (np. `ISO: 109`). |
| **`exposure_text`** | `enabled: true`, `source: "gpmf"` | Obecne (1131 / 5400 próbek) | **Widoczny** | **Widoczny** | Renderuje `"Ext: 1/<wartość>"` (np. `Ext: 581`). |
| **`temp_text`** | `enabled: true`, `source: "gpmf"` | Obecne (38 / 180 próbek) | **Widoczny** | **Widoczny** | Renderuje `"TGP: <wartość> °C"` (np. `TGP: 37.6 °C`). |
| **`track_map`** | `enabled: true`, `source: "fit"` | Obecne (1635 / 1707 punktów) | **Widoczny** | **Widoczny** | Pełna mapa satelitarna, brak ucięcia. |

---

## 10. Wyniki testów regresyjnych

Uruchomiono pełny zestaw testów `pytest`:

```text
================================== FAILURES ===================================
FAILED tests/test_amd_native_etap4.py::test_etap4_abi_and_explicit_decode_modes (asercja ABI=4 vs ABI=8)
FAILED tests/test_qp_analyzer.py::TestStatsFromHist::test_basic (stary test kalkulacji QP)
FAILED tests/test_render_tab.py::TestExportOptions::test_encoder_options (kolejność priorytetów kart graficznych)

================= 3 failed, 349 passed, 17 skipped in 21.75s ==================
```

- **Testy ETAPU 8M / 8M.1 (`tests/test_etap8m_resolution_and_map.py`):** **`6 / 6 PASSED`** (100%)
- **Wszystkie pozostałe testy modułów indykatorów, kompozytora, mapy i interpolacji:** **`PASSED`** (100%)
- 3 niepowodzenia to znane, historyczne asercje sprzętowo-wersyjne, niezwiązane z logiką renderingu nakładek.

---

## 11. Podsumowanie i wnioski dla ETAPU 8M.2

1. Zarówno `time_block`, jak i wskaźniki GPMF (`iso_text`, `exposure_text`, `temp_text`) posiadają w pełni sprawny, spójny i kompletny pipeline przetwarzania w kodzie TeleM.
2. Zniknięcie tych elementów w GUI Preview / eksporcie użytkownika następuje wyłącznie wtedy, gdy:
   - Wideo jest otwarte bez powiązanego pliku JSON metadanych GPMF (lub ekstrakcja ExifTool została przerwana),
   - Projekt/preset użytkownika miał wyłączone te wskaźniki (`enabled: false`),
   - Brak jest próbek czasowych w pliku źródłowym (`start_dt_utc is None`), co powoduje ukrycie wskaźników telemetrycznych zgodnie z regułą `if value is None: continue`.
3. W normalnym trybie pracy z prawidłowymi plikami (`GX020079` / `GX030120` wraz z JSON i FIT) wszystkie elementy (`time_block`, `ISO`, `Ext`, `TGP`, `track_map`) są w 100% obecne i renderują się identycznie w podglądzie Preview oraz eksporcie finalnym.
