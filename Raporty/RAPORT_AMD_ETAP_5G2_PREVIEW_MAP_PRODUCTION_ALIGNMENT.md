# RAPORT: AMD ETAP 5G.2 — PREVIEW MAP RESTORE & PRODUCTION ALIGNMENT

**Data:** 2026-08-28  
**Backend:** AMD (Ryzen 7 7730U / Radeon Graphics — 8C/16T, 32GB RAM UMA)  
**Gałąź:** `amd-render`  
**Status:** COMPLETE (STOP GATES 1 & 2: PASS)

---

## 1. Executive Summary

W ramach etapu **ETAP 5G.2**:
1. **Przywrócono i przetestowano sprawność podglądu mapy w GUI (Preview Map Restore):**
   - Usunięto błąd desynchronizacji dostawcy mapy (`map_style`) przy wczytywaniu presetu w `preset_mixin.py`.
   - Zaimplementowano regułę **Local Cache First** w `src/indicators/moving_map.py`: jeśli kafelki dla bieżącej pozycji GPS znajdują się w lokalnym cache SQLite/RAM (`coverage >= 0.5`), podgląd renderuje się natychmiast, bez czekania na preloader ani blokowania GUI.
   - Zabezpieczono przywracanie flagi sieciowej `set_map_network_allowed(True)` w sekcji `finally` potoku `export_amd_native_d3d11`.
   - Zweryfikowano 6 testów matrycy funkcjonalnej (wszystkie 6/6: **PASS**).
2. **Wykonano pełną matrycę porównawczą konfiguracji produkcyjnej (Config A/B Matrix P0..P4):**
   - 20 pełnych eksportów 1131 klatek 4K (1 warmup + 3 measured dla 5 wariantów).
   - Różnica wydajności pomiędzy najprostszym trybem synchronicznym `P0 (SYNC)` (38.524 True FPS / 29.359s) a asynchronicznym `P4 (ASYNC Queue=2)` (38.575 True FPS / 29.319s) wyniosła zaledwie **+0.13% True FPS / -0.14% czasu eksportu** (poniżej progu +3%).
   - Zgodnie ze **STOP GATE 2**, bezpieczny, bezkolejkowy i stabilny tryb `SYNC + REFERENCE` pozostaje twardym kodowym standardem produkcyjnym (0.26 ms VideoProcessor CPU submit vs 14.14 ms w ASYNC).
3. **Wdrożono zunifikowany nagłówek diagnostyczny konfiguracji produkcyjnej (C6):**
   - Na początku każdego eksportu logowane są efektywne wartości wszystkich przełączników pipeline'u.

---

## 2. Preview Map Restore Details

### Przyczyny źródłowe przed naprawą:
- W `_on_load_preset` wczytanie nowego pliku JSON z `track_map.map_style = "satellite"` nie aktualizowało stanu dostawcy w `MapContext`. W efekcie `snap["provider"] != map_style` stale blokował renderer na komunikacie „Ładowanie mapy…”.
- Błąd lub anulowanie eksportu mogło pozostawić `_map_network_allowed = False` w pamięci procesu GUI.
- Nawet przy obecności 100% kafelków w lokalnej bazie `tilecache.sqlite`, renderer podglądu czekał na stan gotowości preloadera zamiast wyświetlić mapę bezpośrednio z dysku.

### Zmienione pliki:
- `src/gui/qt/_mixins/preset_mixin.py`: Dodano wywołanie `_map_preload_provider_switch(_map_provider_from_layout(self.layout))` w `_on_load_preset`.
- `src/gui/qt/_mixins/project_mixin.py`: Uodporniono `_map_preload_provider_switch` na brak `snap["gps_track"]` poprzez fallback do `self.telemetry.get_gps_track_for_source`.
- `src/indicators/moving_map.py`: Dodano priorytetowy odczyt lokalnego cache (`renderer.viewport_tile_coverage >= 0.5`) przed bramkowaniem placeholderem `MapContext`.
- `src/ffmpeg/amd_native_exporter.py`: Umieszczono `set_map_network_allowed(True)` w `finally:` głównego bloku `export_amd_native_d3d11`.

### Wyniki testów matrycy Preview Map (Harness: `scratch/test_etap5g2_preview_map_matrix.py`):
```text
=== MATRIX SUMMARY ===
  TEST 1 (Load Preset & Render Map):                   PASS (map_bbox=(2832, 417, 634, 634))
  TEST 2 (Provider Switch light_all <-> satellite):    PASS (provider=light_all status=ready)
  TEST 3 (Normal Export Return & Network Lock):        PASS (is_network_allowed=True)
  TEST 4 (Cancel Export Return & Network Lock):        PASS (is_network_allowed=True)
  TEST 5 (Second Preset Load):                         PASS (map_bbox=(2832, 417, 634, 634))
  TEST 6 (Offline Local Cache Render):                 PASS (offline_render_bbox=(2832, 417, 634, 634))

OVERALL RESULT: ALL PASS
```

---

## 3. Config A/B Matrix Results (1131 frames, 4K, Power Max Performance)

Pomiary wykonano na kanonicznym zestawie `GX020079.MP4` + `GX020079.fit` + `cycling_dashboard_v10.json` (3 powtórzenia pomiarowe po 1 biegu rozgrzewkowym dla każdego wariantu):

| Wariant | Pipeline | VP Mode | AMF Query Mode | True FPS (Mean) | True FPS (Median) | Total Export (s) | ProdPrep (ms) | VP Submit (ms) | Consumer Native (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **P0 (GUI Default)** | `SYNC` | `REFERENCE` | `REFERENCE` | **38.524** | **38.442** | **29.359** | 12.12 | 0.26 | 7.84 |
| **P1** | `SYNC` | `STATIC_CACHE` | `REFERENCE` | **38.438** | **38.510** | **29.425** | 11.75 | 7.56 | 8.37 |
| **P2** | `SYNC` | `REFERENCE` | `DRAIN_READY` | **38.191** | **38.276** | **29.614** | 11.75 | 0.27 | 8.59 |
| **P3** | `SYNC` | `STATIC_CACHE` | `DRAIN_READY` | **38.262** | **38.315** | **29.560** | 12.28 | 7.17 | 7.95 |
| **P4 (Benchmark Best)**| `ASYNC (Q=2)` | `STATIC_CACHE` | `DRAIN_READY` | **38.575** | **38.575** | **29.319** | 14.31 | 14.14 | 15.08 |

### Analiza różnic:
- **P0 vs P4:** Różnica wynosi **+0.13% True FPS** (zaledwie +0.05 FPS) i **-0.14% czasu eksportu** (zaledwie 40 ms na 1131 klatkach).
- **VideoProcessor Submit:** W trybie `SYNC` wynosi zaledwie **0.26 ms** na klatkę (brak blokad wątkowych i rywalizacji o D3D11 Device Context), podczas gdy w `ASYNC` rośnie do **14.14 ms**.
- **Decyzja:** Zgodnie z kryterium STOP GATE 2 (wymagany zysk >= +3% do zmiany domyślnej architektury), zachowano bezpieczny i deterministyczny tryb **SYNC** jako kodowy standard produkcyjny.

---

## 4. Production Default State po ETAP 5G.2

```text
=== AMD REAL PRODUCTION EFFECTIVE CONFIG ===
  CPU_GPU_PIPELINE = SYNC
  QUEUE_DEPTH      = 0
  VP_STATE         = REFERENCE
  VP_POOL          = 8
  AMF_QUERY        = REFERENCE
  MAP_PATH         = GPU
  MAP_ALIGN        = 16
  GAUGE_GPU        = 1 (AUTO)
  CHART_GPU        = 1 (GPU_SPLIT)
  LEAN_GPU         = 1
  HUD_MODE         = GPU_HUD
  HUD_UPLOAD       = DIRTY
  NV12_COMPOSITOR  = FUSED
  PROFILING        = 0
============================================
```

---

## 5. Podsumowanie i Gotowość do ETAP 5G.3

- **STOP GATE 1 (Preview Map):** **PASS** — mapa działa bezbłędnie we wszystkich scenariuszach GUI i offline.
- **STOP GATE 2 (Production Config):** **PASS** — pełna zgodność parametrów, stabilność i udokumentowana racjonalność architektury SYNC.
- **Następny krok:** **ETAP 5G.3** (korekta źródeł `compass` i `slope_text` w `cycling_dashboard_v10.json` na `fit` oraz ustanowienie nowego kanonicznego baseline'u).
