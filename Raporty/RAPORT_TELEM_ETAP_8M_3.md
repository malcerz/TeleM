# RAPORT: TeleM — ETAP 8M.3: rzeczywisty runtime layout i znikające `time_block` / GPMF

**Data wykonania:** 2026-08-19  
**Status etapu:** ZAKOŃCZONY SUKCESEM (Pełny parytet Preview / Native AMD Export dla wszystkich wskaźników)  
**Cel etapu:** Identyfikacja rzeczywistego mechanizmu znikania `time_block`, `iso_text`, `exposure_text`, `temp_text` w eksporcie GUI, implementacja minimalnej poprawki bez optymalizacji performance, eliminacja rozbieżności między Preview a finalnym wideo.

---

## 1. Executive Summary

W realnym teście użytkownika po ETAPIE 8M.2 wskaźniki `Solar Pct`, `Battery Pct`, `track_map`, `cad chart`, `HR chart` oraz `gauge` renderowały się poprawnie, natomiast wskaźniki:
- `time_block`
- `iso_text` (ISO)
- `exposure_text` (Exposure / Ext)
- `temp_text` (TMPC / temperatura)

były całkowicie nieobecne w wynikowym pliku wideo.

W toku szczegółowego audytu ścieżki wykonawczej zidentyfikowano **dwa niezależne pierwotne źródła błędu (root causes)**:

1. **Współdzielenie obiektu bufora Pillow między warstwami mapy w eksporterze (`amd_native_exporter.py`) — zniknięcie `time_block` i warstwy `below_indicators`:**
   Dla obsługi z-order nakładek względem mapy (`_ordered_map_layout_parts`), layout jest dzielony na wskaźniki rysowane pod mapą (`below_layout`) oraz nad mapą (`map_above_layout`).
   - Funkcja `compose_overlay` domyślnie korzysta z thread-local bufora pamięci (`_get_reusable_canvas`).
   - W eksporterze AMD najpierw wywoływano `composed_img = compose_overlay(layout=compose_layout)` (gdzie renderowany był m.in. `time_block`), a następnie `above_full = compose_overlay(layout=map_above_layout)`.
   - Drugie wywołanie pobierało **tę samą instancję obrazu Pillow canvas**, a na początku procedury czyszczenia czyściło obszary poprzednich bounding boxów (`prev_bboxes.values()`), w tym `time_block`.
   - W efekcie `composed_img` i `above_full` wskazywały na ten sam obiekt obrazu, z którego **cała zawartość `below_layout` (`time_block`) została usunięta przed uploadem do GPU**.

2. **Brak przekazywania i rozwiązywania próbek GPMF w potoku eksportu (`worker_cache.py` & `render_mixin.py`) — brak wartości dla ISO, Exposure, Temp:**
   - W `render_mixin.py` słownik `field_samples` przekazywany do funkcji renderującej zawierał próbki GPS/IMU, ale pomijał `iso_samples`, `exposure_samples` oraz `temperature_samples`.
   - W `worker_cache.py` funkcja `_resolve_cache_samples(field_name, source="gpmf")` odpytywała wyłącznie słownik `field_samples`, zamiast sprawdzać bezpośrednio `WORKER_CACHE["iso_samples"]`, `WORKER_CACHE["exposure_samples"]` i `WORKER_CACHE["temperature_samples"]` (które były poprawnie zainicjalizowane przez `init_worker`). W efekcie dla źródeł GPMF zwracana była pusta lista `[]`, a interpolator zwracał `None`.

---

## 2. Analiza kanonicznego layoutu i hashy

Porównano strukturę i hashe kanonicznego pliku `def_layout.json` z layoutami przekazywanymi w czasie działania aplikacji:

| Layout | Hash MD5 / SHA256 (canonical JSON) | Status `time_block` | Status `iso_text` | Status `exposure_text` | Status `temp_text` |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **def_layout.json (dysk)** | `b7a7c14c1fe57abd` | `enabled: true` | `enabled: true` | `enabled: true` | `enabled: true` |
| **Runtime GUI Preview Layout** | `b7a7c14c1fe57abd` | `enabled: true` | `enabled: true` | `enabled: true` | `enabled: true` |
| **Runtime AMD Export Layout** | `048be853269114a1`* | `enabled: true` | `enabled: true` | `enabled: true` | `enabled: true` |

*\*Uwaga: Różnica w hashu wynika wyłącznie z obecności klucza `cut_regions: []` dodawanego dynamicznie przez kontroler w trakcie sesji eksportu. Wszystkie 4 wskaźniki pozostają `enabled: true` z identycznymi współrzędnymi `(x, y)`.*

---

## 3. Zastosowane minimalne poprawki

### A. Izolacja canvasu warstwy `above_map` w `src/ffmpeg/amd_native_exporter.py`
W wywołaniu `compose_overlay` dla warstwy `map_above_layout` dodano parametr `reuse_canvas=False`, zapobiegając nadpisaniu i skasowaniu bufora `composed_img`:
```python
above_full = compose_overlay(
    canvas_w=video_width,
    canvas_h=video_height,
    layout=map_above_layout,
    font_path=font_path,
    _bboxes=above_bboxes,
    gpu_capture_keys=set(),
    split_chart_keys=None,
    reuse_canvas=False,  # Izolacja canvasu: nie modyfikuje i nie czyści bufora composed_img
    **frame_kwargs,
)
```

### B. Poprawka rezolucji próbek GPMF w `src/ffmpeg/worker_cache.py`
W funkcji `_resolve_cache_samples` dodano bezpośrednie odpytanie `WORKER_CACHE` przed rezerwowym sprawdzeniem `field_samples`:
```python
if source == "gpmf":
    key = gpmf_map.get(field_name, "")
    if key and key in WORKER_CACHE and WORKER_CACHE[key]:
        return list(WORKER_CACHE[key])
    return list(field_samples.get(key, []) or [])
```

### C. Uzupełnienie słownika `field_samples` w `src/gui/qt/_mixins/render_mixin.py`
Przekazano kanały telemetryczne GPMF kamery (`iso_samples`, `exposure_samples`, `temperature_samples`) do potoku renderingu:
```python
field_samples = {
    "speed_samples": speed,
    "track_samples": track,
    "alt_samples": alt,
    "iso_samples": self.telemetry.iso_samples,
    "exposure_samples": self.telemetry.exposure_samples,
    "temperature_samples": self.telemetry.temperature_samples,
    ...
}
```

### D. Zabezpieczenie `render_time_block` i `prepare_overlay_frame_data`
- W `src/indicators/time_block.py` zastąpiono `layout["global"]` defensywnym `layout.get("global", {}).get("text_outline", 3)`.
- W `src/indicators/frame_data.py` dodano bezpieczną obsługę formatowania znaczników czasu, gdy `target_dt is None`.

---

## 4. Weryfikacja punkt po punkcie w łańcuchu GPU / AMD Native

Przeprowadzono pełny test eksportu 720p 60-ramkowego z zrzutem buforów pamięci na każdym etapie przetwarzania (Frame 30, $t = 1.0\text{ s}$):

| Etap / Checkpoint | Plik diagnostyczny | `time_block` | `iso_text` | `exposure_text` | `temp_text` | `solar_pct` | `battery_pct` |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Python Pillow** | `01_python_hud_30.png` | $\alpha > 0$ (2074 px) | $\alpha > 0$ (1287 px) | $\alpha > 0$ (1193 px) | $\alpha > 0$ (1474 px) | $\alpha = 0$ (above) | $\alpha = 0$ (above) |
| **2. Backing Memory** | `02_buffer_sent_to_dll.png`| $\alpha > 0$ (2074 px) | $\alpha > 0$ (1287 px) | $\alpha > 0$ (1193 px) | $\alpha > 0$ (1474 px) | $\alpha = 0$ (above) | $\alpha = 0$ (above) |
| **3. GPU Texture** | `H_hud_canvas_30.png` | $\alpha > 0$ (2074 px) | $\alpha > 0$ (1287 px) | $\alpha > 0$ (1193 px) | $\alpha > 0$ (1474 px) | $\alpha = 0$ (above) | $\alpha > 0$ (1860 px) |
| **4. GPU NV12 Blend** | `D_after_gpu_hud.png` | **WIDOCZNY** | **WIDOCZNY** | **WIDOCZNY** | **WIDOCZNY** | **WIDOCZNY** | **WIDOCZNY** |
| **5. AMF Encoder In** | `E_amf_input.png` | **WIDOCZNY** | **WIDOCZNY** | **WIDOCZNY** | **WIDOCZNY** | **WIDOCZNY** | **WIDOCZNY** |
| **6. Final MP4 Frame**| `F_final_mp4.png` | **WIDOCZNY** (1082 dark / 284 bright px) | **WIDOCZNY** (644 dark / 143 bright px) | **WIDOCZNY** (633 dark / 155 bright px) | **WIDOCZNY** (755 dark / 165 bright px) | **WIDOCZNY** (230 dark / 79 bright px) | **WIDOCZNY** (676 dark / 3 bright px) |

---

## 5. Wyniki testów automatycznych

1. **Nowe dedykowane testy regresyjne:** `tests/test_etap8m3_runtime_layout_and_parity.py`
   - `test_worker_cache_gpmf_resolution`: PASSED
   - `test_canvas_isolation_between_below_and_above_map`: PASSED
   - `test_time_block_defensive_outline`: PASSED
2. **Cały zestaw testów regresyjnych projektu:**
   - **349 PASSED**, 17 SKIPPED, 3 preexisting legacy baseline (0 nowych regresji).

---

## 6. Wnioski i Parzystość

- Pełna parzystość między **GUI Preview** a **Native AMD D3D11 Export** została w 100% przywrócona.
- Wszystkie wskaźniki bazowe (`time_block`), GPMF (`ISO`, `Exposure`, `TMPC`), FIT (`Solar Pct`, `Battery Pct`), `track_map`, wykresy oraz `gauge` renderują się na prawidłowych pozycjach w docelowej rozdzielczości wyjściowej.
- Gotowe do finalnego zatwierdzenia przez użytkownika.
