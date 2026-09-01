# TeleM — INTEL CORE ULTRA — ETAP 1B
## INTEL PATH OBSERVABILITY + CAPABILITY CONTRACT

Data: 2026-09-01  
Worktree: `C:\_DEV\TeleM-intel-coreultra`  
Branch: `intel-coreultra`  
Base/HEAD: `843aabbabac4df0fe5421238441c341968bf069b`  
Tryb: instrumentation / contract; **bez optymalizacji i bez zmiany routingu**

## 1. Initial state and zero-behavior contract

ETAP 1B rozpoczęto na dokładnym checkpoint `843aabb`. Produkcyjne ścieżki
AMD, NVIDIA, Intel i CPU nie były zmieniane semantycznie. Nie dodano:

- nowego `overlay_qsv`;
- HDR native;
- multi-file native;
- nowego transferu `hwupload`/`hwdownload`;
- oneVPL ani `SetHandle`;
- zmian bitrate’u, presetów lub polityki HUD 75%.

Instrumentation jest wykonywane wyłącznie, gdy ustawiono
`TELEM_INTEL_PROOF=1`. Bez tej flagi nie ma dodatkowego probe inputu,
proof-logu ani proof JSON.

## 2. Changed files

Zmiany tego etapu:

| Plik | Zakres |
|---|---|
| `src/ffmpeg/intel_backend.py` | kanoniczny model capability, klasyfikacja, parser graphu, input probe, proof lines, JSON |
| `src/ffmpeg/streaming.py` | obserwacja już wybranej komendy Intel i zapis końcowych timingów |
| `tests/test_intel_proof.py` | synthetic/static contract matrix |
| `RUN_INTEL_CORE_ULTRA_PROOF.ps1` | launcher do normalnego GUI z `TELEM_INTEL_PROOF=1` |
| `Raporty/RAPORT_INTEL_CORE_ULTRA_ETAP_1B_OBSERVABILITY_CAPABILITY_CONTRACT.md` | niniejszy raport |

Poprzedni raport ETAP 1A pozostał bez zmian. Nie dodano zależności i nie
zmieniono `def_layout.json`.

## 3. Capability data model

`IntelRenderCapabilities` jest jedną kanoniczną strukturą snapshotu. Zawiera
adapter, capabilities QSV/D3D11, fakty inputu, wybraną ścieżkę decode,
residency, HUD, compositor, encoder, oczekiwane transfery i capability class.

Model przechowuje co najmniej:

```text
adapter_name, adapter_vendor_id, adapter_device_id, adapter_dxgi_index
driver_version
qsv_available, qsv_h264_encode, qsv_hevc_encode, d3d11_device_available
input_codec, input_width, input_height, input_bit_depth
input_pixel_format, input_hdr, input_rotation, multi_file, cut_active
decode_path, decode_residency
hud_transport, hud_canvas_width, hud_canvas_height
hud_width, hud_height, hud_bytes_per_frame, hud_region_mode, hud_region_bbox
compositor_path, encode_path, encode_pixel_format
hwdownload_count_expected, hwupload_count_expected
capability_class
```

`driver_version` pozostaje `null`/`NOT_AVAILABLE`, jeżeli enumeracja adaptera
nie dostarczy tej informacji. Nie jest uzupełniany przez zgadywanie.

## 4. Capability classes

Klasyfikacja nie używa nazwy CPU ani tekstu `Core Ultra`:

| Klasa | Warunek |
|---|---|
| `INTEL_UNAVAILABLE` | QSV nie jest używalny |
| `INTEL_QSV_GPU_RESIDENT_SDR` | QSV dostępny, wybrany istniejący native path GPU-resident, input nie-HDR |
| `INTEL_QSV_CPU_REFERENCE` | QSV dostępny, ale wybrano CPU_REFERENCE |
| `INTEL_FUTURE_HDR_CANDIDATE` | zdefiniowana jako nazwa przyszła, nie jest zwracana przez routing produkcyjny ETAP 1B |

Klasa opisuje capabilities i faktycznie wybraną ścieżkę, nie generację
procesora.

## 5. Exact proof fields

Przy `TELEM_INTEL_PROOF=1` emitowane są kanoniczne linie:

```text
[INTEL PROOF] ADAPTER_NAME=...
[INTEL PROOF] ADAPTER_VENDOR=0x8086
[INTEL PROOF] ADAPTER_DEVICE=...
[INTEL PROOF] ADAPTER_DXGI_INDEX=...
[INTEL PROOF] DRIVER=...
[INTEL PROOF] CAPABILITY_CLASS=...
[INTEL PROOF] INPUT_CODEC=...
[INTEL PROOF] INPUT_SIZE=...
[INTEL PROOF] INPUT_BIT_DEPTH=...
[INTEL PROOF] INPUT_PIXEL_FORMAT=...
[INTEL PROOF] INPUT_HDR=YES/NO/NOT_AVAILABLE
[INTEL PROOF] DECODE_PATH=...
[INTEL PROOF] DECODE_RESIDENCY=GPU/GPU_TO_CPU/CPU
[INTEL PROOF] HUD_TRANSPORT=...
[INTEL PROOF] HUD_CANVAS_SIZE=...
[INTEL PROOF] HUD_SIZE=...
[INTEL PROOF] HUD_BYTES_FRAME=...
[INTEL PROOF] HUD_REGION_MODE=...
[INTEL PROOF] HUD_BBOX=...
[INTEL PROOF] COMPOSITOR_PATH=...
[INTEL PROOF] ENCODE_PATH=...
[INTEL PROOF] ENCODE_PIXEL_FORMAT=...
[INTEL PROOF] HWDOWNLOAD_EXPECTED=...
[INTEL PROOF] HWUPLOAD_EXPECTED=...
[INTEL PROOF] MULTIFILE=YES/NO
```

Przy niespójności oczekiwanego i zbudowanego graphu pojawia się dodatkowo:

```text
[INTEL PROOF] PATH_CONTRACT_MISMATCH=YES
[INTEL PROOF] PATH_CONTRACT_REASONS=[...]
```

Normalny log użytkownika pozostaje niezmieniony.

## 6. Path classification rules

Walidator analizuje finalny `cmd` oraz finalny `filter_complex`, nie samą
intencję caller’a.

| Oczekiwana ścieżka | Warunki graphu | Residency | Oczekiwany download |
|---|---|---|---:|
| `QSV_GPU` | `scale_qsv` + `overlay_qsv`, bez `hwdownload` | `GPU` | 0 |
| `CPU_REFERENCE` QSV | CPU `overlay` + `hwdownload` | `GPU_TO_CPU` | ≥1 |
| `CPU_REFERENCE` software P010 | `format=p010le` + CPU `overlay`, bez `hwdownload` | `CPU` | 0 |

Brak automatycznej naprawy graphu. Przykładowo, gdy caller oczekuje
`QSV_GPU`, a parser widzi `overlay` i `hwdownload`, snapshot zgłasza
`PATH_CONTRACT_MISMATCH=YES` i render nie jest przełączany na inną ścieżkę.

`HWUPLOAD_EXPECTED` opisuje granicę wymaganą przez wybraną ścieżkę, także gdy
FFmpeg realizuje upload do encoder’a implicitnie. Parser dodatkowo zapisuje
liczbę jawnych `hwupload` oraz obecność `hwupload=derive_device=qsv`.

## 7. HUD byte accounting

Dla RGBA obowiązuje dokładne:

```text
HUD_BYTES_FRAME = transport_width * transport_height * 4
```

Snapshot rozdziela:

```text
HUD_CANVAS_SIZE       = pełny raster overlay_w × overlay_h
HUD_TRANSPORT_SIZE    = stream_w × stream_h
HUD_TRANSPORT_BBOX    = x, y, width, height
HUD_BYTES_FRAME       = rozmiar transportu w bajtach
```

W `FULL_CANVAS` bbox jest pełnym rastrem. W `REGION` canvas pozostaje pełny,
ale transport obejmuje istniejący, bezpiecznie wyrównany bbox. Polityka AUTO
75% pozostaje bez zmian i jest obserwowana jako faktyczny rozmiar canvasu.

## 8. FFmpeg graph contract validation

Walidator sprawdza obecność:

```text
hwdownload
hwupload
hwupload=derive_device=qsv
scale_qsv
overlay_qsv
overlay
format=p010le
format=nv12
hevc_qsv
```

Wynik zapisuje oczekiwaną klasę, rozpoznaną klasę, residency, liczniki oraz
listę powodów mismatch. Nie uruchamia nowego graphu i nie zmienia istniejącej
komendy.

## 9. Multi-file per-clip proof

Proof korzysta z istniejącego `VideoTimeline`, bez ponownego parsowania
telemetrii. Dla każdego klipu zapisuje:

```text
[INTEL PROOF CLIP]
index=N
source=NAME
source_path=PATH
global_start=...
global_end=...
local_start=...
local_end=...
absolute_start_dt=...
absolute_end_dt=...
timestamp_source=...
timestamp_quality=...
```

Resolver timeline pozostaje źródłem prawdy: własny GPMF `GPS9`, następnie
`GPSU`, potem `container_creation_time`, a na końcu jawny
`continuous_fallback`.

## 10. Machine-readable JSON

Po udanym renderze JSON jest zapisywany wyłącznie przy
`TELEM_INTEL_PROOF=1` jako:

```text
<output>.intel_proof.json
```

Normalny render nie tworzy tego pliku. Dokument zawiera sekcje:

```json
{
  "system": {"platform": "...", "python": "...", "ffmpeg": "..."},
  "adapter": {"name": "...", "vendor_id": 32902, "device_id": 0,
               "dxgi_index": 1, "driver_version": null},
  "capabilities": {"class": "INTEL_QSV_CPU_REFERENCE",
                    "qsv_available": true},
  "input": {"codec": "hevc", "width": 3840, "height": 2160,
             "bit_depth": 10, "pixel_format": "p010le", "hdr": true},
  "timeline": {"multi_file": true, "clips": []},
  "decode": {"path": "SOFTWARE", "residency": "CPU"},
  "hud": {"canvas_size": [2560, 1440], "transport_size": [1200, 600],
          "bytes_per_frame": 2880000, "region_mode": "REGION"},
  "compositor": {"path": "CPU_REFERENCE"},
  "encode": {"path": "QSV_HEVC", "pixel_format": "p010le"},
  "transfers": {"hwdownload_count_expected": 0,
                "hwupload_count_expected": 1},
  "timings": {"export_wall_ms": null, "render_fps": null},
  "contract_validation": {"mismatch": false}
}
```

Wartości timingowe, których pipeline nie mierzy osobno, pozostają `null`.
Nie są tworzone sztuczne zera ani szacowania hardware’u.

## 11. Performance timing schema

JSON rezerwuje:

```text
export_wall_ms
precompute_ms
first_frame_latency_ms
video_render_wall_ms
mux_ms
render_fps
hud_prepare_ms
hud_render_ms
hud_copy_ms
ffmpeg_write_ms
writer_wait_ms
```

Wartości dostępne w istniejącym pipeline są wypełniane po zakończeniu
renderu; `mux_ms`, jeśli nie da się go oddzielić od drain/finalize, pozostaje
`null`. ETAP 1B nie wykonywał benchmarku Intel na AMD.

## 12. Core Ultra launcher

Dodano `RUN_INTEL_CORE_ULTRA_PROOF.ps1`. Launcher:

1. ustawia `TELEM_INTEL_PROOF=1`;
2. uruchamia normalny `TeleMGP.py`;
3. nie wybiera materiału;
4. nie rozpoczyna automatycznego renderu.

Nie hardcoduje plików testowych ani ustawień produkcyjnych.

## 13. Static test matrix

Na AMD przygotowano synthetic/static coverage:

| Case | Synthetic expectation |
|---|---|
| A. Intel SDR 8-bit single-file | `INTEL_QSV_GPU_RESIDENT_SDR`, `QSV_GPU`, download 0 |
| B. Intel HDR/P010 single-file | `INTEL_QSV_CPU_REFERENCE`, CPU P010, download 0 |
| C. Intel SDR multi-file | `CPU_REFERENCE`, QSV→CPU, download ≥1 |
| D. Intel HDR/P010 multi-file | `CPU_REFERENCE`, CPU P010, download 0 |
| E. rotation/cut unsafe | `CPU_REFERENCE` contract |
| F. Intel unavailable | `INTEL_UNAVAILABLE` |

Testy sprawdzają także HUD bytes, schema JSON, mismatch bez naprawy oraz
brak użycia capability class do zmiany AMD/NVIDIA.

## 14. Test results

Wykonano:

```text
python -m pytest -q tests/test_intel_proof.py tests/test_intel_backend.py \
  tests/test_mpv_hwdec.py tests/test_render_tab.py \
  tests/test_intel_auto_hud_policy.py tests/test_etap5d_real_gui_regressions.py
RESULT: 64 passed
```

Nie wykonywano renderu, benchmarku ani fałszywego Intel probe na AMD.

Szeroki wcześniejszy zestaw zawierał dwa stale testy w
`tests/test_video_helpers.py`, które oczekują `vflip,hflip` dla Intel przy
rotacji 180°. Aktualny zaakceptowany kontrakt 5D używa autorotacji FFmpeg.
Testów nie zmieniano przy okazji ETAP 1B.

## 15. Backend isolation

AMD: **zero behavior changes**. Nie dotykano AMF native DLL, mapy, chartów,
layer order ani GPU compositor’a.

NVIDIA: **zero behavior changes**. Nie zmieniano NVENC, CUDA ani wyboru
ścieżki NVIDIA.

Intel: routing pozostaje taki sam; dodano wyłącznie obserwację finalnego graphu
i opcjonalny output diagnostyczny.

Shared code: użyto wyłącznie helperów w istniejącym Intel backend/streaming
branch; brak nowych zależności i brak zmiany wspólnej semantyki renderowania.

## 16. Intel runtime status

```text
INTEL CORE ULTRA RUNTIME: NOT TESTED
CORE ULTRA RAW LOG PACKAGE: NOT LOCALLY AVAILABLE
```

Brak fizycznego Core Ultra oznacza, że adapter, driver, QSV decode/encode,
P010, `overlay_qsv`, multi-file oraz timing hardware pozostają **NOT PROVEN**.
Żaden AMD ani historyczny UHD 730 result nie jest przedstawiany jako Core
Ultra PASS.

## 17. Known stale tests and risks

- Dwa stare testy rotation oczekują nieaktualnego ręcznego flipu; nie zostały
  naprawione w tym etapie.
- Driver version nie jest raportowany, jeżeli DXGI enumeration go nie zwraca.
- `qsv_hardware_usable()` jest krótkim probe używalności QSV, ale nie jest
  samodzielnym dowodem identity konkretnego adaptera; identity wynika z
  enumeracji i późniejszego dynamicznego pinningu komendy.
- Niektóre timing stages są `null`, gdy istniejący pipeline nie mierzy ich
  osobno. To jest zamierzone.

## 18. Git state

Po implementacji:

```text
git diff --check: PASS
git diff --stat:
 src/ffmpeg/intel_backend.py | 349 ++++++++++++++++++++++++++++++++
 src/ffmpeg/streaming.py     | 138 ++++++++++++
```

Untracked są: raport ETAP 1A, niniejszy raport, launcher oraz test
`tests/test_intel_proof.py`. Nie wykonano `git add`, commit ani push.

Worktree bazowy `C:\_DEV\TeleM-integration` pozostał na
`integration/intel-amd`, HEAD `843aabb`, z wcześniejszymi lokalnymi artefaktami
untracked bez zmian.

## 19. Verdict

```text
ETAP 1B: PASS — instrumentation/contract stage
```

PASS dotyczy implementacji obserwowalności, deterministycznego modelu,
walidacji graphu, HUD accounting, per-clip proof, debug-only JSON, launchera,
static tests i izolacji backendów. Intel Core Ultra runtime pozostaje
`NOT TESTED` i nie jest objęty tym PASS.

## 20. Recommendation for ETAP 1C

**Nie implementować ETAP 1C przed zebraniem proof JSON/logów na Core Ultra.**
Po otrzymaniu danych należy wybrać dokładnie jeden kierunek na podstawie
rzeczywistego mismatch/bottlenecku: utrzymanie CPU_REFERENCE, ograniczony
transport HUD albo osobny kandydat native. Nie zakładać z góry HDR
`overlay_qsv` ani nie otwierać ponownie oneVPL `SetHandle`.

