# RAPORT: AMD ETAP 2A — HANDOFF READINESS CHECK (bez modyfikacji kodu)

**Data:** 2026-08-25
**Backend:** AMD_NATIVE_D3D11
**Zadanie:** Weryfikacja gotowości repozytorium do kontynuacji `AMD ETAP 2A — AFTER-MAP GPU Speed Gauge`
**Tryb:** TYLKO ODCZYT — nie zmodyfikowano żadnego pliku produkcyjnego, nie uruchomiono benchmarku, nie przebudowano DLL.
**Raport napisany przez:** ox-alpha (agent)

---

## 1. Stan Git

```text
BRANCH:      amd-render (up to date with origin/amd-render)
HEAD:        d9afa75
WORKTREE:    DIRTY
```

`git diff HEAD --stat`: **35 plików, +2839 / −1004**

### Pliki STAGED (20) — obce względem AMD ETAP 2A (praca GUI/testowa użytkownika — NIE DOTYKAĆ)

```text
src/gui/qt/_mixins/preset_mixin.py
src/gui/qt/_mixins/project_mixin.py
src/gui/qt/_mixins/render_mixin.py
src/gui/qt/application.py
src/gui/qt/controller.py
src/gui/qt/models.py
src/gui/qt/signals.py
src/gui/qt/tabs/render_tab.py
src/gui/telemetry_manager.py
src/indicators/bar.py
tests/test_altitude_bar_rotation.py            (nowy)
tests/test_bar_ruler_size_thickness_etap3.py   (nowy)
tests/test_gpmf_cache.py                       (modyfikacja)
tests/test_hud_resolution_scale.py             (nowy)
tests/test_map_deflayout_lifecycle.py          (nowy)
tests/test_map_overview_first.py               (nowy)
tests/test_render_cancel_process_lifecycle.py  (nowy)
tests/test_render_tab.py                       (modyfikacja)
tests/test_telemetry_processed_cache.py        (nowy)
```

### Pliki UNSTAGED (16) — w tym PODEJRZEWANA IMPLEMENTACJA ETAP 2A

```text
AGENTS.md
def_layout.json
native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp   (+343 linii)
native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.h     (+65 linii)
native/d3d11_amf_pipeline/src/telem_amd_native.cpp    (+101 linie)
src/ffmpeg/amd_native_exporter.py                     (+522 linie)
src/ffmpeg/command_builder.py
src/ffmpeg/streaming.py
src/gui/map_preload.py
src/indicators/compositor.py
src/indicators/dispatcher.py
src/indicators/moving_map.py
src/indicators/static_map.py
src/moving_map.py
src/telemetry_extract.py
tests/test_amd_native_ordered_map_clear.py            (modyfikacja)
```

### Untracked (istotne)

```text
Raporty/*.md (wszystkie raporty etapów AMD, w tym ten plik)
Video/, scratch/
src/telemetry_processed_cache.py
tests/test_map_cold_warm_preload.py
```

---

## 2. Flagi GPU — stan domyślny (working tree)

| Flaga | Default | Lokalizacja | Zgodność z AGENTS.md |
| :--- | :---: | :--- | :--- |
| `AMD_GPU_MAP_ROTATE` | **ON (`True`)** | `amd_native_exporter.py:1445` | ✅ zgodna |
| `AMD_AFTER_MAP_CHART_GPU` | **ON (`True`)** | `amd_native_exporter.py:1321` | ✅ zgodna |
| `AMD_AFTER_MAP_GAUGE_GPU` | **ON (`True`) ⚠️** | `amd_native_exporter.py:1331` | ❌ **NARUSZA §10** |

**Uwaga krytyczna:** flaga `AMD_AFTER_MAP_GAUGE_GPU` **NIE istnieje w HEAD** (`git grep GAUGE_GPU HEAD -- src tests native` → brak trafień). Została dodana wyłącznie w niezacommitowanych zmianach roboczych.

---

## 3. Stara natywna ścieżka GPU Gauge — ISTNIEJE (kompletna)

Potwierdzono pełny łańcuch wymagany przez AGENTS.md §9:

```text
CAPTURE:  kafelek gauge w eksporterze (gauge_data, _GAUGE_KEY="fit_enhanced_speed_text",
          guardy _gauge_gpu_layout_safe @201 oraz _gauge_after_map_layout_safe @234)
UPLOAD:   telem_amd_update_gauge -> UpdateGaugeTexture (d3d11_vp_pipeline.h:207),
          tekstura m_gaugeTexture (.h:440), statystyki uploadów (.h:450)
BLEND:    D3D11VideoProcessorPipeline::BlendGauge() @ d3d11_vp_pipeline.cpp:2181,
          wywołanie z ProcessFrame (@ ~2633), shader m_chartBlendShader
STATS:    telem_amd_get_gauge_stats @ telem_amd_native.cpp:651
LEGACY:   tryb ETAP 5L (telem_amd_set_gauge_mode, AMD_GAUGE_PATH=CPU_REFERENCE|GPU)
```

---

## 4. ODKRYCIE KLUCZOWE: niezacommitowana implementacja ETAP 2A w working tree

W niezatwierdzonych zmianach roboczych znajduje się już implementacja ETAP 2A:

1. **Flaga** `AMD_AFTER_MAP_GAUGE_GPU` (`amd_native_exporter.py:1326–1335`) — default **ON**, sprzeczne z AGENTS.md §10 (wymagane OFF do czasu walidacji).
2. **Kolejność passów** w working-tree `ProcessFrame` (`d3d11_vp_pipeline.cpp`, indeksy względne):

```text
ClearPreviousAboveMap(9757) < BlendCharts(10281) < ResampleAndBlendMap(10913)
  < BlendAboveMap(11613) < BlendGauge(12256) < BlendAfterMapCharts(12631)
```

   czyli `BlendGauge` jest już przesunięty PO mapie i `BlendAboveMap` (pozycja AFTER-MAP).

3. **Guard Z-orderu** `_gauge_after_map_layout_safe()` (`amd_native_exporter.py:234–258`) — wymusza rozłączność bbox gauge i chartów AFTER-MAP, fallback CPU przy nakładaniu.
4. **Zaktualizowany test** `tests/test_amd_native_ordered_map_clear.py:19–23`: asercja kolejności `... above_call < gauge_call < after_chart_call` z komentarzem „ETAP 2A".
5. **BRAK raportu** `RAPORT_AMD_ETAP_2A*.md` w `Raporty/` — brak dowodów smoke test / Z-order / ghosting / pixel-parity / benchmark dla tych zmian.

---

## 5. Walidacja

### TESTED (w ramach tego zadania — tylko odczyt)

- `git status`, `git branch --show-current`, `git rev-parse --short HEAD`, `git diff HEAD --stat` — PASS
- `git grep` potwierdzenie defaultów flag i braku flagi gauge w HEAD — PASS
- Potwierdzenie istnienia capture/upload/BlendGauge/stats w źródłach natywnych i Pythonie — PASS
- Potwierdzenie kolejności passów w working-tree `ProcessFrame` — PASS

### NOT TESTED / NOT PROVEN

- Smoke render dla niezacommitowanych zmian ETAP 2A — **NOT TESTED**
- Z-order / ghosting / pixel-parity dla tych zmian — **NOT TESTED**
- Benchmark vs baseline 1C/1D — **NOT TESTED**
- Zgodność `bin/telem_amd_native.dll` ze zmodyfikowanymi źródłami (brak przebudowy) — **NOT PROVEN**
- Środowiska NVIDIA / Intel — poza zakresem (nienaruszone statycznie)

---

## 6. BLOCKERY przed kontynuacją ETAP 2A

1. `AMD_AFTER_MAP_GAUGE_GPU` ma default ON w niezacommitowanych zmianach — narusza AGENTS.md §10; należy ustawić OFF by default do czasu walidacji.
2. Niezatwierdzona implementacja ETAP 2A w working tree wymaga decyzji właściciela repo: **commit / walidacja / wycofanie** (zabronione: `git reset --hard`, `git restore .`, `git checkout -- .`).
3. Brak raportu walidacyjnego ETAP 2A — wymagany przed oznaczeniem etapu jako COMPLETE.
4. Brak potwierdzenia rebuildu DLL względem zmodyfikowanych źródeł natywnych.

---

## 7. Podsumowanie Końcowe

```text
TELEM OX HANDOFF READY: YES
BRANCH: amd-render
HEAD: d9afa75
WORKTREE: DIRTY (20 staged, 16 unstaged, untracked Raporty//Video//scratch/; 35 files, +2839/-1004 vs HEAD)
GPU MAP DEFAULT: ON (AMD_GPU_MAP_ROTATE=True @ amd_native_exporter.py:1445)
GPU CHART DEFAULT: ON (AMD_AFTER_MAP_CHART_GPU=True @ amd_native_exporter.py:1321)
EXISTING GPU GAUGE PATH: YES (capture + telem_amd_update_gauge/UpdateGaugeTexture + BlendGauge @ d3d11_vp_pipeline.cpp:2181)
ETAP 2A READY: YES (infrastruktura kompletna; ale w working tree istnieją już NIEZACOMMITOWANE zmiany ETAP 2A bez raportu)
BLOCKERS: patrz sekcja 6
STATUS: HANDOFF COMPLETE — NO CODE CHANGES MADE IN THIS TASK
```
