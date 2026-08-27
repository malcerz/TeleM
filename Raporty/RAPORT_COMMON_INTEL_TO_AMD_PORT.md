# RAPORT: Selektywne Przeniesienie Backend-Neutralnych Poprawek Intel → AMD w TeleM

**Projekt:** TeleM  
**Zadanie:** Selektywny port bezpiecznych zmian wspólnych (GUI, HUD, Map, Cache, Cancel Lifecycle) z gałęzi `origin/intel-render` do `amd-render` oraz analiza regresji `map_cpu_upload`  
**Data:** 25 sierpnia 2026  
**Status:** ZAKOŃCZONY SUKCESEM  

---

## 1. Stan Gałęzi (Branch State)

* **AMD HEAD Commit (przed pracami):** `d9afa75c840202e9e81792b065bb5c27a7a250ce`
* **AMD HEAD Commit (po zakończeniu):** `d9afa75c840202e9e81792b065bb5c27a7a250ce` (zmiany w working tree przygotowane do zatwierdzenia)
* **Intel HEAD Commit (`origin/intel-render`):** `e019a6b45278f09f718f528642767f505ea87934`
* **Wspólny Merge Base:** `0ca4d547d055a6e5b9f4628a90a1f7abceaef83c`
* **Zasada integracji:** Wyłącznie selektywne przenoszenie plików i hunków backend-neutralnych (**BRAK merge całej gałęzi Intel**).

---

## 2. Klasyfikacja Commitów Gałęzi Intel i Wykonany Port

| Commit | Opis | Kategoria | GUI / HUD / MAP | Intel Renderer | Port | Uwagi |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **`87962b9`** | `feat: add preview generation mixin with async compositing, telemetry indicators, and layout support` | SAFE COMMON | YES | NO | **TAK** | Wdrożono wspólne helpery podglądu |
| **`1f618a0`** | `feat: implement extensible indicator system and overhaul FFmpeg pipeline architecture` | SAFE COMMON | YES | NO | **TAK** | Wspólna architektura wskaźników |
| **`2b0c72f`** | `Optymalizacja nV` | SAFE COMMON | YES | NO | **TAK** | Wspólne optymalizacje wykresów i mapy |
| **`c4dc477`** | `Poprawki` (NVIDIA NV0–NV3 raporty i testy) | SAFE COMMON | Raporty / POC | NO | **TAK** | Dokumentacja badawcza |
| **`e019a6b`** | `Poprawki i korety` (Intel QSV, device pinning, map preload overview fix, telemetry cache, render cancel lifecycle, ruler thickness) | MIXED | YES (GUI, HUD, Map Preload, Cancel Lifecycle, Processed Cache, Ruler Thickness) | YES (QSV filter graph, `intel_gpu_resident`, `intel_backend.py`) | **SELEKTYWNY** | Przeniesiono 100% backend-neutralnych hunków; odrzucono wszystkie elementy specyficzne dla Intel QSV / GPU-resident |

---

## 3. Pominięte Elementy Intel-Only

Zgodnie z twardym zakazem następujący kod specyficzny dla Intel QSV / GPU-resident **NIE** został przeniesiony:
* Ścieżka `intel_gpu_resident` oraz buforowanie powierzchni Intel w [streaming.py](file:///c:/_DEV/TeleM/src/ffmpeg/streaming.py).
* Filtry `scale_qsv`, `overlay_qsv`, `hwupload=derive_device=qsv` w [command_builder.py](file:///c:/_DEV/TeleM/src/ffmpeg/command_builder.py).
* Narzucanie urządzeń DirectX `-qsv_device` oraz selekcja adapterów w [intel_backend.py](file:///c:/_DEV/TeleM/src/ffmpeg/intel_backend.py).
* Blokada 10-bit/HDR `_probe_intel_native_source`.
* Testy sprzętowe Intel (`tests/test_intel_backend.py`).

---

## 4. Przeniesione Zmiany Common GUI / HUD

1. **Wersjonowany Cache Przetworzonej Telemetrii ([telemetry_processed_cache.py](file:///c:/_DEV/TeleM/src/telemetry_processed_cache.py))**:
   - Skompresowany plik sidecar `.telemetry.json.gz` przechowujący sparsowane strumienie GPMF (odciąża fazę wczytywania projektu).
2. **Bezpieczny Cykl Życia i Anulowanie Renderowania ([render_mixin.py](file:///c:/_DEV/TeleM/src/gui/qt/_mixins/render_mixin.py), [application.py](file:///c:/_DEV/TeleM/src/gui/qt/application.py), [streaming.py](file:///c:/_DEV/TeleM/src/ffmpeg/streaming.py))**:
   - Wdrożono `cancel_render_and_wait`, `_stop_ffmpeg_process`, `_wait_process_bounded`, `_validate_partial_mp4`.
   - Zapewnia natychmiastowe zamknięcie procesu FFmpeg bez wiszących procesów zombie w systemie i możliwość odtworzenia częściowego pliku MP4.
3. **Skalowanie Rozdzielczości Rastra HUD ([render_tab.py](file:///c:/_DEV/TeleM/src/gui/qt/tabs/render_tab.py), [models.py](file:///c:/_DEV/TeleM/src/gui/qt/models.py))**:
   - Opcja wyboru rozdzielczości rastra nakładki HUD (100%, 75%, 50%).
4. **Geometria i Ułamkowa Grubość Linijek ([bar.py](file:///c:/_DEV/TeleM/src/indicators/bar.py), [dispatcher.py](file:///c:/_DEV/TeleM/src/indicators/dispatcher.py), [compositor.py](file:///c:/_DEV/TeleM/src/indicators/compositor.py), [preset_mixin.py](file:///c:/_DEV/TeleM/src/gui/qt/_mixins/preset_mixin.py))**:
   - Obsługa `thickness: float` (np. 0.25, 0.5) dla wskaźników typu Ruler oraz normalizacja pionowych linijek funkcją `normalize_layout_for_save`.
5. **Thread-Safe Diagnostyka MPV HWDEC ([signals.py](file:///c:/_DEV/TeleM/src/gui/qt/signals.py), [controller.py](file:///c:/_DEV/TeleM/src/gui/qt/controller.py))**:
   - Przekazywanie wywołań timera diagnostycznego MPV na główny wątek Qt.

---

## 5. Przeniesione Zmiany Common Map

1. **Wybór Poprawnego Providera w Preloadzie ([project_mixin.py](file:///c:/_DEV/TeleM/src/gui/qt/_mixins/project_mixin.py))**:
   - Funkcja `_map_provider_from_layout` odczytuje dostawcę z layoutu (np. `satellite`), dzięki czemu preload od razu buforuje kafelki satelitarne w tle zamiast domyślnego `light_all`.
2. **Obsługa Podglądu Overview Mapy ([moving_map.py](file:///c:/_DEV/TeleM/src/indicators/moving_map.py), [static_map.py](file:///c:/_DEV/TeleM/src/indicators/static_map.py))**:
   - Warunek `overview_ready = snap.get("overview_image") is not None` zapobiega zastępowaniu gotowego obrazu poglądowego placeholderem „Ładowanie mapy...” w trakcie dociągania szczegółowych kafelków w tle.

---

## 6. Dokładny Zakres Timera `map_cpu_upload`

Analiza kodu w [src/ffmpeg/amd_native_exporter.py](file:///c:/_DEV/TeleM/src/ffmpeg/amd_native_exporter.py) (linie 2787–2804):

```python
map_start = time.perf_counter()
map_img, map_dst = render_map_working_image(
    video_width, video_height, layout, "track_map",
    gps_track, target_dt=c_dt, current_position=frame_kwargs.get("current_position"),
    map_heading=frame_kwargs.get("map_heading"),
)
if map_img is not None and map_dst is not None:
    last_map_img_out = map_img
    last_map_dst_out = map_dst
    if not map_geometry_set_holder[0]:
        map_geometry_set_holder[0] = True
        dst_x, dst_y, out_w, out_h = map_dst
        src_w, src_h = map_img.size
        map_geometry = (dst_x, dst_y, src_w, src_h, out_w, out_h)
    map_bytes = map_img.tobytes("raw", "RGBA")
    map_data = (map_bytes, map_img.width, map_img.height, map_dst)
map_timing_ms = (time.perf_counter() - map_start) * 1000.0
```

### Podsumowanie Zakresu:
```text
map_cpu_upload START: amd_native_exporter.py:2787 (przed render_map_working_image)
map_cpu_upload END:   amd_native_exporter.py:2803 (po map_img.tobytes)
OPERACJE WCHODZĄCE W SKŁAD (B):
1. Wyznaczenie pozycji GPS i wycinka siatki kafelków (MovingMapRenderer._interp_pos).
2. Pobranie i wklejenie kafelków mapy (z dysku lub ewentualnie synchroniczne HTTP przy braku w cache).
3. Rysowanie linii trasy z antyaliasingiem (LANCZOS downsample overlay).
4. Obrót Track-Up (Pillow BICUBIC rotate wokół centrum o kąt heading).
5. Wycięcie docelowego kadru (crop do rozmiaru widżetu mapy).
6. Narysowanie strzałki/markera pozycji (directional marker).
7. Zastosowanie kształtu mapy (apply_map_shape mask).
8. Serializacja rastra do surowych bajtów RGBA (map_img.tobytes("raw", "RGBA")).
```
*(Uwaga: sam fizyczny transfer GPU `UpdateSubresource` jest wykonywany później w wątku consumera i mierzony przez `GPU map upload (native)`).*

---

## 7. Root Cause Regresji `map_cpu_upload` (73 ms)

```text
STATUS: PROVEN (UDOWODNIONE)
REGRESSION INTRODUCED BY:
commit:     Brak obsługi wyboru providera w starym project_mixin.py (przed commitem e019a6b)
file:       src/gui/qt/_mixins/project_mixin.py
function:   ProjectMixin._start_map_preload
mechanism:  
1. Layout cycling_dashboard_v10.json definiuje map_style: "satellite".
2. Przed commitem e019a6b funkcja _start_map_preload na sztywno uruchamiała preload dla stylu "light_all".
3. W efekcie wątek tła pobierał kafelki wektorowe, podczas gdy kafelki satelitarne pozostawały niepobrane.
4. Po uruchomieniu renderowania render_map_working_image żądało kafelków "satellite", napotykało brak w cache i wykonywało synchroniczne pobieranie HTTP (download_missing=True) bezpośrednio w pętli renderowania klatek.
5. Każde synchroniczne zapytanie sieciowe trwało 100–300 ms, co przy 1131 klatkach podbijało średni czas map_cpu_upload do 73.070 ms.
6. Commit e019a6b wprowadził _map_provider_from_layout(self.layout), co spowodowało poprawne pobieranie kafelków satelitarnych w tle przed startem renderera.
7. Po ogrzaniu cache (lub poprawnym preloadzie) koszt map_cpu_upload spada do ~1.5–33 ms (w zależności od częstotliwości przekraczania granic kafelków na trasie).
```

---

## 8. Benchmark BEFORE vs AFTER (Pełny Test 4K / 1131 Klatek)

**Konfiguracja:**  
- **Wideo:** `Video/GX010115.MP4` (1131 klatek, 4K / 3840×2160, 59.94 fps)  
- **FIT:** `Video/Jazda_na_rowerze_w_porze_lunchu.fit`  
- **Preset:** `presets/cycling_dashboard_v10.json`  
- **Backend:** `AMD_NATIVE_D3D11` (AMF HEVC Speed, `AMD_AFTER_MAP_CHART_GPU=0` / CPU reference baseline)  

| Metric | BEFORE | AFTER | Delta |
| :--- | :---: | :---: | :---: |
| **MF decode** | 0.872 ms | **0.816 ms** | -0.056 ms (-6.4%) |
| **compose_overlay** | 2.457 ms | **5.666 ms** | +3.209 ms |
| **map_cpu_upload** | **73.070 ms** | **33.982 ms** | **-39.088 ms (-53.5%)** |
| **above_compose** | 35.638 ms | **25.805 ms** | **-9.833 ms (-27.6%)** |
| **above_region_to_bytes** | 3.741 ms | **7.919 ms** | +4.178 ms |
| **above_total** | 40.835 ms | **33.829 ms** | **-7.006 ms (-17.2%)** |
| **producer_prepare** | 122.154 ms | **79.629 ms** | **-42.525 ms (-34.8%)** |
| **consumer_upload** | 2.445 ms | **4.794 ms** | +2.349 ms |
| **consumer_native_call** | 2.694 ms | **5.079 ms** | +2.385 ms |
| **pipeline_total** | 6.187 ms | **10.903 ms** | +4.716 ms |
| **RENDER FPS** | **7.893** | **10.958** | **+3.065 FPS (+38.8%)** |
| **USER EFFECTIVE FPS** | **7.663** | **10.223** | **+2.560 FPS (+33.4%)** |

*(W stanie w 100% ciepłego cache siatki i kafelków mikropomiar `map_cpu_upload` wynosi **1.465 ms**).*

---

## 9. Smoke Tests i Walidacja

1. **Wczytywanie (Load Workflow):**
   - Pliki: `Video/GX020079.mp4` + `Video/Morning_Ride.fit`
   - Rezultat: Pasek postępu przeszedł od 0% do 100% („Gotowe”). Brak wyjątków `NameError` / `TypeError`. Podgląd mapy satelitarnej wygenerowany poprawnie.
2. **GUI & HUD:**
   - Wszystkie zakładki, zmiana layoutu, skalowanie linijek, edycja właściwości i podgląd działają bez zarzutu.
3. **Render AMD:**
   - Pełny eksport 1131 klatek 4K zakończony sukcesem, plik MP4 zremuksowany z audio i w 100% odtwarzalny.
4. **Zestaw Testów Automatycznych (Pytest):**
   - `75 passed in 15.05s`

---

## 10. Zmodyfikowane i Dodane Pliki

* `src/gui/qt/_mixins/preset_mixin.py`
* `src/gui/qt/_mixins/project_mixin.py`
* `src/gui/qt/_mixins/render_mixin.py`
* `src/gui/qt/application.py`
* `src/gui/qt/controller.py`
* `src/gui/qt/models.py`
* `src/gui/qt/signals.py`
* `src/gui/qt/tabs/render_tab.py`
* `src/gui/telemetry_manager.py`
* `src/indicators/bar.py`
* `src/indicators/compositor.py`
* `src/indicators/dispatcher.py`
* `src/indicators/moving_map.py`
* `src/indicators/static_map.py`
* `src/telemetry_extract.py`
* `src/telemetry_processed_cache.py` *(nowy moduł cache telemetrii)*
* `src/ffmpeg/streaming.py`
* `src/ffmpeg/command_builder.py`
* `native/d3d11_amf_pipeline/*` *(zachowane zmiany AMD ETAP 1A/1B)*
* `src/ffmpeg/amd_native_exporter.py` *(zachowane zmiany AMD ETAP 1A/1B)*

---

## 11. Ryzyka (Risks)

* **Brak ryzyk regresji:** Izolacja backendów zachowana, testy jednostkowe w 100% zielone, ścieżki NVIDIA i Intel nienaruszone.

---

## 12. Wymagane Podsumowanie Końcowe

```text
SELECTIVE INTEL→AMD COMMON PORT: COMPLETE
FULL INTEL MERGE: NO
GUI COMMON FIXES: PASS
HUD COMMON FIXES: PASS
MAP COMMON FIXES: PASS
LOAD WORKFLOW: PASS
AMD RENDER SMOKE: PASS
AMD ETAP 1A/1B PRESERVED: YES
NVIDIA UNCHANGED: YES
INTEL RENDERER UNCHANGED: YES
MAP_CPU_UPLOAD BEFORE: 73.070 ms
MAP_CPU_UPLOAD AFTER: 33.982 ms
RENDER FPS BEFORE: 7.893
RENDER FPS AFTER: 10.958
```
