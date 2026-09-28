# RAPORT — GPU Runtime Capability Production

Data: 2026-09-23  
Repozytorium: `C:\\_DEV\\BikeRideHUD-amd`  
Branch: `amd-bikeridehud`  
Commit bazowy: `0ef407e`

## TASK

Wprowadzenie produkcyjnego, runtime'owego systemu capability GPU dla eksportu AMD:

- jeden model capability zamiast rozproszonych limitów,
- probe AMF/DXGI/D3D11 przy starcie,
- cache w `%LOCALAPPDATA%\\BikeRideHUD\\gpu_capabilities.json`,
- walidacja cache po schema/LUID/vendor/device/driver,
- GUI gate rozdzielczości wyjściowej i `source` na podstawie aktualnych wymiarów,
- clamp nieprawidłowej rozdzielczości do 4K z logiem `OUTPUT_RESOLUTION_CLAMPED`,
- preflight przed renderem bez fałszywego sukcesu i bez automatycznego CPU x265 fallback,
- zachowanie istniejącej ścieżki compute shader 8K→4K.

## INITIAL STATE

Repozytorium było już silnie zmodyfikowane przez wcześniejsze prace AMD. Zmiany
użytkownika zostały zachowane; nie wykonano `reset`, `clean`, `restore`, `stash`,
`rebase`, `commit` ani `push`.

Przed zmianą:

- GUI i część detekcji używały statycznego/awaryjnego limitu AMD 4096,
- cache nie sprawdzał pełnej tożsamości adaptera,
- brakowało wspólnego modelu capability,
- nieznane capability mogło prowadzić do ukrytej polityki `AMD => 4096`,
- nieudany eksport natywny mógł spaść do CPU/libx265.

## IMPLEMENTATION

### Central model and probe

Dodano `GpuCapabilities` w `src/ffmpeg/amd_capabilities.py` z polami:

- vendor, adapter name, vendor/device ID, adapter LUID, driver version,
- hardware encoder, codec, HEVC/Main10 encode,
- maksymalny encode width/height,
- hardware decode i HEVC Main10 decode,
- source, timestamp, schema, cache/probe timing i error.

`query_amf_caps.exe` wykonuje:

- DXGI adapter identity,
- `ID3D11VideoDevice::CheckVideoDecoderFormat` dla HEVC Main10/P010,
- AMF `AMFIOCaps` dla HEVC input range i P010.

Cache jest akceptowany tylko przy zgodności schema, adapter LUID, vendor ID,
device ID i driver version. Probe identity-only jest wykonywany przed odczytem
cache; zmiana któregokolwiek z tych pól wymusza pełny probe.

### Actual AMD result

Na aktywnym AMD Cezanne probe zwrócił:

```text
GPU_NAME=AMD Radeon (TM) Graphics
GPU_VENDOR=0x1002
GPU_DEVICE_ID=0x15e7
ADAPTER_LUID=0x00000000:0x0000b1ef
DRIVER_VERSION=31.0.21925.1001
HEVC_MAIN10_AVAILABLE=YES
D3D11_HARDWARE_DECODE_AVAILABLE=YES
D3D11_HEVC_MAIN10_DECODE_AVAILABLE=YES
HEVC_MAX_WIDTH=4096
HEVC_MAX_HEIGHT=4096
```

### GUI and render gate

- `RenderTab` pobiera capability model z kontrolera.
- Rozdzielczości 5.3K/8K są blokowane tylko wtedy, gdy aktualny model
  potwierdza, że encoder ich nie obsługuje.
- `source` jest oceniane osobno po otrzymaniu wymiarów źródła.
- Przy wyborze zablokowanego wariantu GUI ustawia 4K i emituje:

```text
OUTPUT_RESOLUTION_CLAMPED=True FROM=<source-or-selection> TO=3840x2160 REASON=ENCODER_CAPABILITY
```

- `UNKNOWN` nie otrzymuje domyślnego limitu 4096. W takim przypadku pierwsza
  próba eksportu uruchamia one-frame hardware preflight `hevc_amf`; niepowodzenie
  blokuje render.
- Błąd AMD native export nie przełącza już automatycznie joba na CPU x265.

### Hardcoded gate audit

Wspólny limit `AMD => 4096` został usunięty z runtime gate. Pozostałe wystąpienia
4096 dotyczą wyłącznie:

- wyniku aktualnego runtime probe,
- testowych fixture'ów AMD Cezanne,
- istniejącego, niezależnego ograniczenia/bezpiecznego pathu D3D11/VP.

Nie zmieniano zachowania NVIDIA, Intel/QSV ani CUDA.

## CHANGED FILES

Zmiany związane z tym zadaniem:

- `src/ffmpeg/amd_capabilities.py`
- `src/ffmpeg/detection.py`
- `src/ffmpeg/__init__.py`
- `src/ffmpeg/streaming.py`
- `src/gui/qt/controller.py`
- `src/gui/qt/tabs/render_tab.py`
- `src/gui/qt/_mixins/render_mixin.py`
- `native/d3d11_amf_pipeline/src/query_amf_caps.cpp`
- `native/d3d11_amf_pipeline/CMakeLists.txt`
- `tests/test_gpu_runtime_capabilities.py`

Plik raportu: `Raporty/RAPORT_GPU_RUNTIME_CAPABILITY_PRODUCTION.md`.

## TESTS

PASS:

- `ninja -C native\d3d11_amf_pipeline\build telem_amd_native query_amf_caps`
- rzeczywisty `query_amf_caps.exe` na aktywnym AMD Cezanne,
- `python -m pytest -q tests/test_gpu_runtime_capabilities.py tests/test_render_tab_controls_cleanup.py -k "gpu_runtime or amd_encoder_resolution_gate"`
  — `10 passed, 8 deselected`,
- `python -m py_compile` dla zmienionych modułów Python,
- cache hit po poprawnym identity-only probe; zmiana drivera w teście unieważnia cache,
- capability policy: 1080p/4K PASS, 5.3K/8K FAIL dla Cezanne,
- capability policy: 8K PASS dla fixture przyszłego AMD z limitem 8192,
- source 8K→4K PASS, source 8K→source FAIL, source 4K→source PASS,
- unknown capability bez vendorowego fallbacku 4096,
- no automatic CPU x265 fallback,
- ręczny Qt smoke: `source` 7680×4320 disabled/clamped do 4K; `source`
  3840×2160 enabled.

Niepowiązany regression command dla istniejącego `tests/test_video_helpers.py`
ma 2 FAIL w testach Intel/CPU (`vflip,hflip`). Traceback wskazuje ścieżkę
`C:\\_DEV\\BikeRideHUD\\tests\\test_video_helpers.py`; nie zmieniano Intel/NVIDIA
ani tego zakresu.

## PERFORMANCE

Measured capability startup timings:

- pełny cold AMF/DXGI probe: około 83–92 ms,
- disk-cache warm start wraz z identity probe: około 99 ms,
- memory-cache hit w procesie: natychmiastowy względem probe.

Nie wykonywano długiego benchmarku renderera, ponieważ zadanie dotyczy capability
gate, a znany runtime VP E_FAIL blokuje wiarygodny test pełnego eksportu.

## 8K → 4K STATUS

Istniejąca ścieżka compute shader 8K→4K została zachowana i nie została
przepisana. Jej ponowny realny eksport end-to-end: **NOT PROVEN / BLOCKED**
przez znany obecny stan runtime D3D11/VP (`VP E_FAIL`), zgodnie z zakresem
zadania. Nie naprawiano tego problemu.

## TIMING

```text
TOTAL_STAGE_WALL_TIME: ~35 min
AUDIT_TIME: ~8 min
REPRO_TIME: ~6 min
IMPLEMENTATION_TIME: ~12 min
VALIDATION_TIME: ~9 min
LONGEST_SINGLE_COMMAND_SECONDS: ~7.8 s (native build)
```

## REGRESSIONS / RISKS

- Pełny render 8K→4K nie jest w tym raporcie dowodem PASS.
- Gdy runtime probe jest niedostępny, eksport AMD jest blokowany po nieudanym
  one-frame preflight; nie ma automatycznego CPU fallbacku.
- Dwa istniejące testy Intel/CPU pozostają FAIL poza zakresem AMD.

## BACKEND ISOLATION

Zmiany produkcyjne dotyczą modelu capability, AMD/AMF, GUI gate oraz AMD native
export failure handling. Nie zmieniano implementacji NVENC/CUDA, QSV ani Intel
GPU surfaces/decode/encode. Wspólny preflight jest aktywowany tylko dla
encoderów AMD/AMF.

## FINAL SUMMARY

**CASE B / PARTIAL PASS** — capability model, real AMF probe, cache identity,
GUI gate, source gate, clamp, preflight i brak CPU fallbacku są zaimplementowane
i zwalidowane. Realny eksport 8K→4K pozostaje `NOT PROVEN` z powodu znanego
VP E_FAIL, którego zadanie zabraniało naprawiać.

## REQUIRED MACHINE-READABLE RESULT

```text
CAPABILITY_SYSTEM_IMPLEMENTED=True

AMD_RUNTIME_PROBE=AMFIOCaps + DXGI/D3D11 VideoDevice
AMF_HEVC_AVAILABLE=True
AMF_HEVC_MAIN10_AVAILABLE=True
AMF_MAX_WIDTH=4096
AMF_MAX_HEIGHT=4096

ACTIVE_ADAPTER=AMD Radeon (TM) Graphics
ADAPTER_LUID=0x00000000:0x0000b1ef
DRIVER_VERSION=31.0.21925.1001

CAPABILITY_CACHE_PATH=%LOCALAPPDATA%\\BikeRideHUD\\gpu_capabilities.json
CAPABILITY_CACHE_HIT=True
CAPABILITY_PROBE_COLD_MS=~83-92
CAPABILITY_CACHE_WARM_MS=~99.47
CAPABILITY_CACHE_WARM_TARGET_MS=10
CAPABILITY_CACHE_WARM_TARGET_MET=False

GLOBAL_AMD_8K_HARDCODE_REMOVED=True
HARDCODED_GPU_GATES=GUI/detection encoder gate removed; native 4096 VP/compute safety thresholds retained

CEZANNE_8K_SOURCE_LOAD=PASS (referenced D3D11VA P010 validation)
CEZANNE_1080P_ENABLED=True
CEZANNE_4K_ENABLED=True
CEZANNE_5K_ENABLED=False
CEZANNE_8K_ENABLED=False
CEZANNE_SOURCE8K_ENABLED=False

FUTURE_AMD_8192_5K_ENABLED=True
FUTURE_AMD_8192_8K_ENABLED=True
FUTURE_AMD_8192_SOURCE_ENABLED=True

SOURCE_4K_ON_4096_ENABLED=True
NO_CPU_X265_AUTO_FALLBACK=True
RENDER_PREFLIGHT_IMPLEMENTED=True
FALSE_SUCCESS_ON_BLOCKED_RENDER=False

8K_TO_4K_PATH=existing D3D11 compute shader downscale
8K_TO_4K_REAL_RENDER=BLOCKED_BY_CURRENT_D3D11_RUNTIME_STATE

PYTEST=10 passed, 8 deselected; py_compile PASS; native query/build PASS
MODIFIED_FILES=src/ffmpeg/amd_capabilities.py, src/ffmpeg/detection.py, src/ffmpeg/streaming.py, src/gui/qt/controller.py, src/gui/qt/tabs/render_tab.py, src/gui/qt/_mixins/render_mixin.py, native/d3d11_amf_pipeline/src/query_amf_caps.cpp
CREATED_FILES=tests/test_gpu_runtime_capabilities.py, Raporty/RAPORT_GPU_RUNTIME_CAPABILITY_PRODUCTION.md

TOTAL_STAGE_WALL_TIME=~10 min (this follow-up audit)
LONGEST_SINGLE_COMMAND_SECONDS=~3.9 (query_amf_caps rebuild)
NTFY_SUCCESS=True (3 attempts, HTTP 200)
CASE=B
```
