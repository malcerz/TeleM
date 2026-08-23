# RAPORT_INTEL_ETAP_1 — Audyt, izolowany backend Intel i bezpieczna selekcja GPU

- **Data:** 2026-08-23
- **Maszyna testowa:** AMD Ryzen 5 5500U, AMD Radeon iGPU, **BRAK GPU Intel**
- **Zakres:** audyt, nowy izolowany backend Intel, `INTEL_FORCE`, enumeracja adapterów D3D11/DXGI, diagnostyka, przygotowanie QSV, testy bez sprzętu Intel
- **Status:** ✅ Implementacja przygotowana; realne testy Intel wymagają sprzętu Intel

---

## 1. Stan pipeline'u przed zmianami

TeleM używa **stringów jako kodów backendu**: `"nv"`, `"amd"`, `"intel"`, `"cpu"` (brak osobnego enumu klasy „backend"). Główna ścieżka finalnego renderu przechodzi przez:

```
GUI (RenderTab.cmb_encoder)
  → RenderMixin._render_pipeline (walidacja enkodera)
  → stream_overlay_to_ffmpeg (dispatch AMD→natywny; budowa input_args/hwaccel)
  → _build_stream_ffmpeg_cmd (mapa encoder → hevc_nvenc / hevc_amf / hevc_qsv / libx265)
  → FFmpeg
```

Detekcja sprzętu:
- `detect_best_encoder()` (AUTO) — priorytet **NVIDIA > AMD > Intel > CPU** na podstawie `-encoders` + testu enkodera + `nvidia-smi`.
- `detect_gpu_decoder(preferred_encoder)` — dobiera `-hwaccel` (dla `intel` → `d3d11va`/`dxva2`/`vulkan`).

## 2. Znalezione miejsca wyboru GPU

| Plik | Rola | Ryzyko dla Intel |
|---|---|---|
| `src/ffmpeg/detection.py` | `detect_best_encoder`, `detect_gpu_decoder` | AUTO wybiera NVIDIA przed Intel |
| `src/ffmpeg/command_builder.py` | `_build_stream_ffmpeg_cmd` — mapa encoder→kodek, łańcuchy filtrów | Brak pinningu adaptera Intel; `-gpu` tylko dla `nv` |
| `src/ffmpeg/streaming.py` | `stream_overlay_to_ffmpeg` — input_args/hwaccel | Brak wymuszenia adaptera Intel |
| `src/gui/qt/_mixins/render_mixin.py` | walidacja enkodera + **cichy fallback** `detect_best_encoder()` | ⚠️ `intel` przy braku `hevc_qsv` cicho spadał na inny backend |
| `src/gui/qt/tabs/render_tab.py` | `cmb_encoder` | lista `["amd","nv","intel","cpu"]`, bez `auto` |
| `src/gui/qt/mpv_hwdec.py` | `detect_gpu_adapters()` (PowerShell, **tylko nazwa**, bez Vendor ID), podgląd mpv | Brak ID vendorów; tylko podgląd |
| `src/gui/qt/tabs/load_tab.py` | `cmb_preview_accel` (podgląd) | niezależny od renderu |

**Najważniejsze:** nie było żadnej enumeracji adapterów D3D11 po Vendor ID w pipeline renderującym. Na maszynie `Intel iGPU + NVIDIA Quadro P400` tryb AUTO wybrałby NVIDIA (NVENC), a `intel` bez działającego QSV **cicho spadał** na inny backend.

## 3. Zmienione pliki (istniejące)

- `src/ffmpeg/__init__.py` — eksport nowych symboli Intel (`enumerate_d3d11_adapters`, `find_intel_adapter`, `resolve_intel_force`, `IntelBackendError`, `IntelResolution`).
- `src/ffmpeg/streaming.py` — modułowy import `resolve_intel_force` + **wymuszenie `INTEL_FORCE`** na początku `stream_overlay_to_ffmpeg` (tylko dla `encoder == "intel"`; ścieżki AMD/NVIDIA/CPU nietknięte).
- `src/gui/qt/_mixins/render_mixin.py` — obsługa `auto` → `detect_best_encoder()`; dla `intel` **usunięty cichy fallback** (zachowanie `nv`/`amd` bez zmian).
- `src/gui/qt/tabs/render_tab.py` — combobox `["auto","amd","nv","intel","cpu"]` (minimalna zmiana GUI; domyślny wybór nadal `detect_best_encoder()`).
- `tests/test_render_tab.py` — aktualizacja kontraktu comboboxa pod nową listę (zawiera `auto`).

## 4. Nowe pliki

- `src/ffmpeg/intel_backend.py` — izolowany backend Intel (opis w sekcji 5).
- `tests/test_intel_backend.py` — 11 testów jednostkowych (selekcja po Vendor ID, INTEL_FORCE sukces/błąd, brak cross-GPU fallback, rozdzielenie QSV, normalizacja backendu, wymuszenie w pipeline).

## 5. Opis implementacji Intel

`src/ffmpeg/intel_backend.py` zawiera:

- **Stałe:** `BACKEND_AUTO/CPU/NVIDIA/AMD/INTEL`, `VENDOR_ID_INTEL=0x8086`, `VENDOR_ID_AMD=0x1002`, `VENDOR_ID_NVIDIA=0x10DE`.
- **`enumerate_d3d11_adapters()`** — enumeracja D3D11 przez DXGI 1.1 (`IDXGIFactory1::EnumAdapters1` + `IDXGIAdapter1::GetDesc1`) przez ctypes. Dla każdego adaptera zwraca `{index, name, vendor_id, device_id, vendor_code, dedicated_vram_mb, d3d11_device_ok}`. Wszystkie wskaźniki COM są zwalniane. **Bez założenia `adapter 0 == Intel`.**
- **`find_intel_adapter(adapters)`** — wybór po `vendor_id == 0x8086`, **niezależnie od indeksu**.
- **`ffmpeg_encoders_have_qsv()`** — czy FFmpeg **zawiera** `hevc_qsv`/`h264_qsv` (rozdzielenie od sprzętu).
- **`qsv_hardware_usable()`** — czy QSV faktycznie **działa** na tym sprzęcie (realny test enkodera przez `_test_encoder`).
- **`resolve_intel_force()`** — pełna rezolucja `INTEL_FORCE` + diagnostyka.
- **`IntelBackendError`** — kontrolowany błąd inicjalizacji Intel (brak cross-GPU fallback).
- **`normalize_backend()`** — normalizacja kodów do istniejącego zestawu małych liter.

## 6. Sposób wykrywania adaptera Intel

1. `enumerate_d3d11_adapters()` (DXGI 1.1) → lista adapterów z `vendor_id`.
2. `find_intel_adapter()` → pierwszy adapter o `vendor_id == 0x8086`.
3. Wybór **po właściwości adaptera / Vendor ID**, NIE po indeksie.

## 7. Sposób działania INTEL_FORCE

`requested_backend == "intel"` = **FORCE** (nie PREFER):

- używany jest **wyłącznie** adapter Intel (0x8086),
- wymagany działający QSV (rozdzielenie „FFmpeg zawiera QSV” od „sprzęt Intel działa”),
- przy braku któregokolwiek z wymagań inicjalizacja kończy się kontrolowanym błędem `IntelBackendError` (`INTEL_FORCE_FAILED`),
- brak cichego cross-GPU fallback i brak cichego fallbacku CPU.

## 8. Zabezpieczenie przed NVIDIA/AMD fallback

- `render_mixin._render_pipeline`: dla `intel` **usunięto** `encoder = detect_best_encoder()`.
- `stream_overlay_to_ffmpeg`: dla `encoder == "intel"` **przed** jakimkolwiek przetwarzaniem wywoływana jest `resolve_intel_force`; przy błędzie podnoszony jest `IntelBackendError`, więc kod nie dochodzi do dispatchera AMD/NVIDIA.
- Obce adaptery (NVIDIA/AMD) są tylko wykrywane i logowane jako `Adapter ignored: INTEL_FORCE active`.
- Test `test_resolve_intel_force_no_cross_gpu_probe` potwierdza, że przy braku adaptera Intel nie jest nawet próbowany żaden probe enkodera (błędna ścieżka ffmpeg by wybuchła, gdyby próba była wykonana).

## 9. Przygotowanie QSV

- Detekcja obecności enkodera w FFmpeg: `ffmpeg_encoders_have_qsv()` (`h264_qsv`, `hevc_qsv`).
- Detekcja używalności sprzętu: `qsv_hardware_usable()` (realny test `_test_encoder`).
- Diagnostyka rozróżnia te dwa stany:
  - `INTEL_HEVC_QSV: YES/NO`, `INTEL_H264_QSV: YES/NO` (obecność w FFmpeg),
  - `INTEL_QSV_AVAILABLE: YES/NO` (używalność sprzętu),
  - `INTEL_ENCODE_PATH: QSV-HEVC / QSV-H264 / NONE` (ścieżka **używalna**).
- Docelowe `decode=QSV/D3D11VA`, `render=D3D11`, `encode=QSV` — raportowane jako plan (ETAP 2), nie wymuszane.

## 10. Miejsca obecnych transferów GPU ↔ CPU

- **NVIDIA (`nv`):** `-hwaccel cuda -hwaccel_output_format cuda` → HUD RGBA z CPU ładowany przez `hwupload_cuda`; finalny `-pix_fmt cuda` (bez readbacku przy braku rotacji), ale przy rotacji CPU łańcuch (vflip/transpose).
- **AMD (`amd`):** `-hwaccel d3d11va`; w `AMD_NATIVE_D3D11` decode D3D11VA → natywny D3D11 VP + AMF (GPU-resident, bez readbacku). W `CPU_REFERENCE`/fallbackach CPU: NV12 blend w CPU (transfer GPU→CPU).
- **CPU (`cpu`):** cały pipeline w CPU (brak transferów GPU).
- **Intel (plan ETAP 2):** docelowo `QSV decode → D3D11 surface → overlay/compositor → QSV encode` bez `GPU→CPU→GPU`; w ETAP 1 **nie** wprowadzono agresywnego zero-copy — bezpieczne fundamenty.

## 11. Wykonane testy

### Nowe testy `tests/test_intel_backend.py` — 11 PASS

- `test_find_intel_adapter_quadro_first` — adapter 0=NVIDIA, adapter 1=Intel → INTEL_FORCE → adapter 1 ✅
- `test_find_intel_adapter_intel_first` — adapter 0=Intel, adapter 1=NVIDIA → INTEL_FORCE → adapter 0 ✅
- `test_find_intel_adapter_none` — brak Intel → `None` ✅
- `test_resolve_intel_force_success` — sukces + pełna diagnostyka + `Adapter ignored` ✅
- `test_resolve_intel_force_no_intel_adapter_raises` — `INTEL_FORCE_FAILED` ✅
- `test_resolve_intel_force_no_qsv_raises` — adapter Intel bez używalnego QSV → błąd + rozdzielenie QSV ✅
- `test_resolve_intel_force_no_cross_gpu_probe` — brak probe'u przy braku Intel ✅
- `test_resolve_intel_force_ffmpeg_missing_qsv` — brak QSV w FFmpeg → błąd ✅
- `test_resolve_intel_force_empty_adapter_list` — pusta lista DXGI → błąd kontrolowany ✅
- `test_normalize_backend` ✅
- `test_stream_pipeline_enforces_intel_force` — `stream_overlay_to_ffmpeg(encoder="intel")` przerywa przed przetwarzaniem ✅

### Regresja (narrow) — 77 PASS łącznie

- `test_mpv_hwdec.py`, `test_video_helpers.py`, `test_render_tab.py`, `test_amd_native_overlay_handoff.py`, `test_gpu_compositor.py` + nowe Intel — **77 passed**.

### Testy statyczne / runtime na Ryzen 5 5500U

- Import wszystkich zmodyfikowanych modułów + legacy `src.ffmpeg_pipeline` — OK.
- Realna enumeracja DXGI: 3 adaptery — AMD Radeon ×2 (`0x1002`), Microsoft Basic Render Driver (`0x1414`); **brak Intel**.
- Realny `INTEL_FORCE` → **kontrolowany błąd** (sekcja 12).
- Realny probe QSV: `ffmpeg_has_qsv=True`, `qsv_hardware_usable=False` (rozdzielenie potwierdzone).

## 12. Wyniki na Ryzen 5 5500U (AMD, bez Intel)

Realny przebieg `resolve_intel_force()` na tej maszynie (oczekiwany, poprawny wynik):

```
[GPU] Requested backend: INTEL_FORCE
[GPU] D3D11 adapters discovered:
[GPU] 0: AMD Radeon(TM) Graphics
[GPU]    vendor=0x1002
[GPU] 1: AMD Radeon(TM) Graphics
[GPU]    vendor=0x1002
[GPU] 2: Microsoft Basic Render Driver
[GPU]    vendor=0x1414
[INTEL] Intel adapter: NOT FOUND
[INTEL] INTEL_FORCE_FAILED
[INTEL] No usable Intel GPU/QSV device available.
[INTEL] Cross-GPU fallback: DISABLED
```

TeleM **nie udaje**, że Intel działa — poprawnie odrzuca maszynę bez adaptera Intel.

## 13. Elementy, których NIE DAŁO się sprawdzić bez GPU Intel

- Realne `hevc_qsv` / `h264_qsv` encode.
- Realna ścieżka `QSV/D3D11VA` decode.
- Pinning adaptera Intel w FFmpeg (`-hwaccel_device`/`-init_hw_device qsv`) — świadomie odłożony do ETAP 2 (nie zmieniano wspólnego buildera komend).
- Zachowanie na maszynie `Intel iGPU + NVIDIA Quadro P400` (w tym pełna ignorancja Quadro przy `INTEL_FORCE`).
- NVIDIA: **nie testowana runtime** na tej maszynie AMD; ścieżka NVIDIA zachowana statycznie (niezmieniona).

## 14. Checklista testów na komputerze `Intel iGPU + NVIDIA Quadro P400`

1. **A. Brak regresji:** normalne uruchomienie ścieżki AMD (domyślny wybór) nadal działa, wyniki/ustawienia bez zmian.
2. **B. AUTO:** `detect_best_encoder()` zwraca zgodny z oczekiwaniem backend dla tej maszyny; sprawdzić priorytet.
3. **C. INTEL_FORCE (wybór Intel):** w logach:
   - `[GPU] Requested backend: INTEL_FORCE`,
   - `[GPU] D3D11 adapters discovered:` zawiera Intel UHD (vendor=0x8086) i NVIDIA Quadro P400 (vendor=0x10DE),
   - `[INTEL] Selected adapter: Intel UHD Graphics`,
   - `[NVIDIA] Adapter ignored: INTEL_FORCE active`,
   - `[INTEL] INTEL_QSV_AVAILABLE: YES`,
   - `[INTEL] INTEL_H264_QSV` / `INTEL_HEVC_QSV` — wg FFmpeg,
   - `[INTEL] INTEL_CROSS_GPU_FALLBACK: DISABLED`.
4. **D. Quadro całkowicie ignorowana:** przy `INTEL_FORCE` NVENC/AMF/CUDA/AMD backend/NVIDIA backend **nie mogą** być wywołane (statycznie + logi).
5. **E. Wybór po Vendor ID (nie indeksie):** uruchomić testy `test_find_intel_adapter_quadro_first` i `test_find_intel_adapter_intel_first` na prawdziwej enumeracji; potwierdzić, że przy `adapter 0=NVIDIA, adapter 1=Intel` wybór = adapter 1.
6. **F. QSV:** `ffmpeg -encoders` zawiera QSV; realny test `hevc_qsv`/`h264_qsv` na Intel przechodzi (jeśli FFmpeg ma QSV, ale brak sprzętu — powinien być kontrolowany błąd, nie fallback).
7. **G. Rotacja/kompozycja Intel:** weryfikacja, że łańcuch Intel (CPU chain przy rotacji, `-pix_fmt nv12`, `hevc_qsv`) nie używa CUDA (`overlay_cuda` absent) — testy `test_intel_rotation180_no_nv2` / `test_video_helpers.py`.
8. **H. Preview mpv:** `build_mpv_options("intel")` → hwdec `d3d11va,dxva2,auto`, gpu-context d3d11 (test `test_mpv_hwdec.py`).
9. **I. Final render:** pełny eksport z enkoderem Intel na docelowym sprzęcie; potwierdzić w logach `INTEL_ENCODE_PATH: QSV-HEVC` (lub `QSV-H264`).

## 15. Rekomendowany zakres: INTEL ETAP 2

- Pinning adaptera Intel w FFmpeg (`-hwaccel_device` / `-init_hw_device qsv` / `-qsv_device`) tak, aby przy `INTEL_FORCE` dekodowanie i enkodowanie używały **wyłącznie** adaptera Intel (nawet przy obecności Quadro).
- Realna ścieżka `QSV decode → D3D11 surface → overlay/compositor → QSV encode` z ograniczeniem `GPU→CPU→GPU`.
- Decyzja o wspólnym helperze vendor-neutralnym dopiero po udowodnieniu równoważności zachowań (zgodnie z AGENTS.md — bez „ładniejszego” refaktora AMD+NVIDIA+Intel).

---

## Podsumowanie / ograniczenia

- **NVIDIA path preserved statically; runtime validation was not possible on this machine.**
- AMD/NVIDIA/CPU backends **niezmienione** poza punktami wymuszenia `INTEL_FORCE` (tylko dla `encoder == "intel"`).
- Implementacja Intel przygotowana; testy bez sprzętu Intel przeszły; `INTEL_FORCE` poprawnie odrzuca komputer bez adaptera Intel; **realny test QSV/D3D11 wymaga sprzętu Intel.**
