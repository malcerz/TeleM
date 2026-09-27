# TeleM — INTEL CORE ULTRA — ETAP 1A
## CURRENT INTEGRATION / CORE-ULTRA LOG AUDIT

Data audytu: 2026-09-01  
Tryb: **AUDIT ONLY** — bez zmian produkcyjnych, bez benchmarku i bez renderu  
Repo bazowe: `C:\_DEV\TeleM-integration`  
Worktree audytu: `C:\_DEV\TeleM-intel-coreultra`  
Gałąź: `intel-coreultra`  
HEAD: `843aabbabac4df0fe5421238441c341968bf069b`  
Commit bazowy: `Integration: checkpoint multi-file preview, render and telemetry fixes`

## 1. Zakres i izolacja

Worktree został utworzony z dokładnego checkpointu `843aabb`:

```text
C:/_DEV/TeleM-intel-coreultra  intel-coreultra  843aabb
```

`C:\_DEV\TeleM-integration` pozostało na `integration/intel-amd`, HEAD `843aabb`.
Nie zmieniano tam kodu, nie wykonywano commit/push/merge/rebase. Nie zmieniano
`amd-render`, `intel-render`, `main` ani `def_layout.json`.

Stan wejściowy worktree audytu był czysty:

```text
git status --short:          empty
git diff --stat:             empty
```

## 2. Dostępność surowych logów Core Ultra

Przeszukane lokalne katalogi obejmowały `C:\_DEV`, `TeleM`,
`TeleM-integration`, nowy worktree oraz `C:\Users\Malcerz\Downloads`.

```text
CORE ULTRA RAW LOG PACKAGE: NOT LOCALLY AVAILABLE
```

Nie znaleziono `core_ultra_weekend_20260828_134841.zip` ani równoważnego
rozpakowanego pakietu. Nie znaleziono również logów
`RUN_INTEL_CORE_ULTRA_WEEKEND*`. Wnioski poniżej nie udają pomiarów Core Ultra.

## 3. Identyfikacja sprzętu

Exact Core Ultra/GPU z logów: **NOT AVAILABLE**.

Dostępne historyczne raporty Intel opisują inną maszynę:

- 12th Gen Intel Core i5-12400;
- Intel UHD Graphics 730, Vendor ID `0x8086`, w raportach DXGI index `1`;
- NVIDIA Quadro P400 obecna, ale ignorowana przez `INTEL_FORCE`;
- Intel driver `32.0.101.7085` w historycznym probe.

Są to dane historyczne z UHD 730, nie dowód dla Meteor Lake, Lunar Lake,
Arc ani żadnego konkretnego Core Ultra.

## 4. Aktualna ścieżka Intel w checkpoint `843aabb`

### Wybór backendu i capability gating

GUI oferuje `intel`. Żądanie jawne przechodzi przez `resolve_intel_force()`:

1. enumeruje adaptery DXGI/D3D11;
2. wybiera adapter po Vendor ID `0x8086`, a nie po stałym numerze;
3. sprawdza utworzenie urządzenia D3D11;
4. rozdziela obecność encoderów QSV w FFmpeg od realnej używalności QSV;
5. przy braku używalnego Intel/QSV zgłasza `INTEL_FORCE_FAILED`;
6. nie wykonuje cichego fallbacku do AMD, NVIDIA, NVENC, AMF ani CPU.

Komenda FFmpeg jest dynamicznie przypinana do wybranego adaptera:

```text
-init_hw_device qsv=intel_qsv,child_device=<Intel DXGI index>,child_device_type=d3d11va
-hwaccel qsv -hwaccel_device intel_qsv -hwaccel_output_format qsv
-qsv_device <Intel DXGI index>
```

Ograniczenie: krótki probe `qsv_hardware_usable()` rozstrzyga używalność
QSV, ale sam probe nie jest dowodem tożsamości wybranego adaptera. Twarde
przypięcie jest wykonywane w komendzie produkcyjnej po rozstrzygnięciu
adaptera.

### Ścieżka native GPU-resident

`D3D11_NATIVE` jest kwalifikowana tylko dla pojedynczego źródła SDR 8-bit,
bez rotacji, cut regions i multi-file, z aktywnym HUD-em oraz zgodną
rozdzielczością. Graf:

```text
QSV decode surface
  -> scale_qsv
  -> overlay_qsv
  -> hevc_qsv
```

HUD nadal powstaje po stronie CPU jako RGBA/BGRA i jest uploadowany przez
`hwupload=derive_device=qsv`. Obraz wideo nie jest w tym wariancie
ściągany do CPU. Native nie jest dopuszczany automatycznie dla HDR/P010,
multi-file, rotacji ani cięć.

### Aktualna ścieżka produkcyjna dla multi-file/HDR

Multi-file wyłącza `intel_gpu_resident`. Dla listy plików tworzona jest
tymczasowa lista concat, przekazywana do FFmpeg przez:

```text
-f concat -safe 0 -i render_concat_list.txt
```

Ta ścieżka używa CPU_REFERENCE. Dla typowego 8-bitowego wejścia jest to:

```text
QSV/D3D11 decode
  -> hwdownload,format=nv12
  -> CPU scale/overlay z HUD-em
  -> hevc_qsv nv12
```

Dla wykrytego źródła 10-bitowego single-file kod wybiera bezpieczny wariant:

```text
software HEVC decode
  -> CPU p010le
  -> CPU scale/overlay z HUD-em
  -> hevc_qsv p010le
```

W tym wariancie nie ma `hwdownload`, ponieważ dekoder jest programowy.
Dla multi-file probe formatu nie jest wykonywany per pierwszy plik; domyślna
wartość transportu CPU to `nv12`. Zgodność konkretnej listy multi-file z
heterogenicznymi formatami musi być sprawdzona na Core Ultra na rzeczywistych
plikach wejściowych.

### HUD transport

HUD jest renderowany przez istniejący renderer CPU i dostarczany jako
rawvideo RGBA przez istniejący mechanizm worker/shared-memory + pipe writer.

- CPU_REFERENCE: bounded `REGION` jest możliwy przez
  `TELEM_INTEL_CPU_REF_HUD_REGION` (domyślnie ON), z bezpiecznym bbox i
  fallbackiem do `FULL_CANVAS` powyżej progu `0.85`;
- native SDR: działa ograniczony upload HUD, ale compositor nie przyjmuje
  wieloregionowego wariantu Intel;
- dla 4K AUTO GUI wybiera HUD 75%, czyli `2560x1440` zamiast pełnego
  `3840x2160`, bez zmiany AMD/NVIDIA.

### Kompozycja i encode

CPU_REFERENCE używa standardowego FFmpeg `overlay` po stronie CPU. Native
SDR używa `overlay_qsv`. Encoder Intel jest `hevc_qsv`, preset `veryfast`,
`look_ahead=0`, `async_depth=4`; bitrate pochodzi z GUI, z opcjonalnym
Intel-only override `TELEM_INTEL_QSV_BITRATE_MBPS`.

## 5. Historyczna ścieżka Intel i różnice względem obecnej

Historyczny baseline przed późniejszymi poprawkami miał zasadniczo:

```text
QSV/D3D11 lub software decode
  -> CPU scale/overlay + pełny RGBA HUD
  -> QSV HEVC encode
```

Różnice potwierdzone przez historyczne raporty:

- dodano wybór Intel po Vendor ID oraz dynamiczny QSV/D3D11 pinning;
- dodano osobną kwalifikację native SDR GPU-resident;
- dodano jawne rozdzielenie `hwdownload` od CPU software decode;
- dodano zachowanie P010/HDR zamiast wymuszania NV12 dla Main10;
- dodano bounded HUD REGION i politykę AUTO 75% dla Intel 4K;
- utwardzono writer/EOF/tail-frame lifecycle;
- zachowano multi-file timeline i per-clip absolute timestamp mapping.

Historyczny bezpośredni oneVPL `SetHandle` jest zamkniętym kierunkiem
badań: wcześniejsze próby kończyły się `MFX_ERR_UNDEFINED_BEHAVIOR / -16`.
Nie otwierano tego ponownie i nie dodawano nowej implementacji oneVPL.

## 6. Core Ultra: dane zmierzone, wnioskowane i nieznane

### Zmierzone na Core Ultra

**Brak.** Brak lokalnego pakietu raw logów i brak sprzętu Core Ultra w
środowisku audytu.

### Zmierzone historycznie, ale tylko na UHD 730

Historyczne raporty podają m.in.:

- QSV H.264/HEVC encode probe: PASS;
- QSV/D3D11 device pinning z Intel `8086:4692`: PASS;
- native SDR 720p: działający `scale_qsv` + `overlay_qsv`;
- 4K Main10/HDR CPU_REFERENCE: działający P010/HDR metadata;
- historyczne pomiary 4K zależne od konfiguracji: około 24 FPS przy
  decompozycji encode-bound oraz około 21–22 FPS w późniejszym wariancie
  z CPU scale/overlay i HUD 75%.

Ostatnie dwa punkty nie są równoważnym benchmarkiem i nie tworzą jednego
oficjalnego limitu. Raporty historyczne są dowodem pomocniczym, nie
substytutem pomiaru Core Ultra.

### Wnioskowane, lecz niezmierzone na Core Ultra

- że aktualny driver Core Ultra zaakceptuje identyczny QSV/D3D11 graph;
- że `overlay_qsv` zachowa geometrię i kolory dla każdego formatu P010;
- że adapter index i semantics `qsv_device` będą takie same;
- że multi-file concat zachowa ciągłość wideo, telemetry i HUD;
- że GPU-resident będzie szybszy od CPU_REFERENCE na docelowym Core Ultra.

### Nieznane / NOT PROVEN

- dokładny model Core Ultra, generacja i sterownik;
- QSV decode/encode na konkretnym adapterze Core Ultra przy obecności
  drugiego GPU;
- HDR/P010 `overlay_qsv` na Core Ultra;
- realny FPS, transfery, backpressure i tail-frame behavior na Core Ultra;
- realna walidacja GUI preview/playback oraz exportu multi-file na Core Ultra;
- rzeczywista korzyść z REGION i AUTO HUD 75% na Core Ultra.

## 7. CPU ↔ GPU transfer map

| Wariant | Decode / base | HUD | Composite | Encode |
|---|---|---|---|---|
| Intel native SDR single-file | QSV surface, GPU | CPU RGBA/BGRA → QSV upload | `overlay_qsv`, GPU | `hevc_qsv` |
| Intel CPU_REFERENCE 8-bit / multi-file | QSV surface → `hwdownload` → NV12 CPU | CPU RGBA pipe/shared memory | CPU `overlay` | CPU/system frame → `hevc_qsv` |
| Intel CPU_REFERENCE HDR/P010 | software decode → P010 CPU | CPU RGBA pipe/shared memory | CPU `overlay` on P010 path | P010 → `hevc_qsv` |

Najdroższa architektonicznie granica w CPU_REFERENCE to pełna ramka
GPU→CPU→QSV dla 8-bitowego QSV decode oraz pełnoekranowy CPU scale/overlay
z transportem HUD. W HDR P010 nie ma readbacku, ale koszt przesuwa się na
software decode, CPU composition i QSV encode.

## 8. Multi-file compatibility

`VideoTimeline` zachowuje kolejność wejściową użytkownika i mapuje:

```text
global time → clip → local time → clip absolute timestamp → telemetry
```

Resolver per clip preferuje:

1. własny GPMF `GPS9`;
2. własny GPMF `GPSU`;
3. `container_creation_time`;
4. jawnie oznaczony `continuous_fallback`.

Zatem ważny plik `GX010116` może i powinien użyć własnego GPMF, jeżeli
ekstrakcja zawiera wiarygodny absolute timestamp. Sam audyt ETAP 1A nie
wykonywał realnego eksportu 014/015/016 ani nie może poświadczać konkretnych
wartości timestampów bez wymaganych logów/runtime proof.

Wymagany test Core Ultra powinien potwierdzić osobno dla każdego klipu:
`source`, `quality`, `absolute_start_dt`, `absolute_end_dt`, a następnie
przejście video/HUD/telemetry przez granice klipów.

## 9. Capability gating i bezpieczeństwo backendów

- Intel jawne: `INTEL_FORCE`, Intel adapter po Vendor ID, QSV required,
  cross-GPU fallback disabled.
- Intel native: ograniczone do sprawdzonego SDR single-file graphu.
- HDR/P010, rotacja, cut regions i multi-file pozostają w bezpiecznej
  ścieżce CPU_REFERENCE.
- AMD production: **NO CHANGE**.
- NVIDIA production: **NO CHANGE**.
- shared production code: **NO CHANGE** w tym audycie.

## 10. Główny bottleneck i dowód

Najlepiej udokumentowany historyczny koszt to transport i kompozycja pełnego
HUD-u oraz CPU scale/overlay w Intel CPU_REFERENCE. Dla 4K pełny RGBA HUD
ma `31.64 MiB/frame`; polityka AUTO 75% redukuje raster do `2560x1440`.

Jednocześnie historyczny ETAP 4G wskazywał encode-bound, a ETAP 6C.3
wskazywał CPU scale/overlay jako P0 w innym wariancie. Ponieważ są to różne
przebiegi i nie ma logów Core Ultra, finalny P0 dla Core Ultra pozostaje
**NOT PROVEN**. Nie wolno na tej podstawie zmieniać compositora ani stroić
QSV.

## 11. Jeden rekomendowany ETAP 1B

**ETAP 1B — Intel path observability + capability contract.**

Bez zmiany compositora: dodać testowalny kontrakt diagnostyczny, który dla
każdego renderu zapisuje wybrany adapter/Vendor ID, driver/runtime, decode
format, residency, `hwdownload/hwupload`, HUD bytes/region, compositor,
encoder, QSV device oraz per-clip timestamp source/quality. Do tego dodać
synthetic/static tests dla multi-file i capability gates.

To jest jedyny bezpieczny pierwszy kierunek możliwy do przygotowania na
AMD: nie wymaga fizycznego Core Ultra, nie zmienia ścieżki AMD i dostarczy
porównywalny schemat dowodowy na maszynie docelowej. Nie implementowano go
w ETAP 1A.

## 12. Co można wdrożyć teraz na AMD, a co musi czekać

Możliwe teraz, bez udawania testu Intel:

- testy kontraktów i statyczna walidacja Intel graphu;
- neutralna struktura diagnostyczna/metryczna dla adaptera, transferów,
  HUD i per-clip timestampów;
- przygotowanie fixture/mocków dla capability gating.

Musi poczekać na Core Ultra:

- runtime PASS QSV decode/encode na wybranym adapterze;
- realny native `scale_qsv`/`overlay_qsv`, w tym HDR/P010;
- realny multi-file 014/015/016 przez granice klipów;
- realny GUI preview/playback/export i pomiar FPS/backpressure;
- jakakolwiek decyzja o zmianie domyślnego Intel compositora lub transferu.

## 13. Testy wykonane

Wykonano wyłącznie krótkie testy bez renderu:

```text
python -m pytest -q tests/test_intel_backend.py tests/test_mpv_hwdec.py \
  tests/test_render_tab.py tests/test_intel_auto_hud_policy.py \
  tests/test_etap5d_real_gui_regressions.py
RESULT: 54 passed in 16.27s
```

Szerszy zestaw z `tests/test_video_helpers.py`:

```text
RESULT: 82 passed, 2 failed in 24.97s
```

Oba failure dotyczą istniejących starych asercji oczekujących tekstu
`vflip,hflip` dla Intel przy `rotation=180`. Aktualny kod 5D celowo używa
FFmpeg autorotate i nie dodaje tych ręcznych filtrów; failure jest znaną
niezgodnością starego testu z aktualnym kontraktem, nie został naprawiony w
tym audycie. Nie wykonywano realnego renderu ani benchmarku Core Ultra.

## 14. Zmienione pliki i Git

Produkcja: **0 plików zmienionych**.

Dodany wyłącznie niniejszy raport:

```text
Raporty/RAPORT_INTEL_CORE_ULTRA_ETAP_1A_CURRENT_INTEGRATION_LOG_AUDIT.md
```

Raport pozostaje untracked; nie był stage'owany, commitowany ani pushowany.
Po jego utworzeniu oczekiwany stan nowego worktree to jeden untracked report.
`git diff --stat` nie obejmuje untracked pliku i pozostaje puste.

## 15. Verdict

```text
ETAP 1A: PARTIAL / STOP FOR HARDWARE VALIDATION
```

PASS spełniono dla izolacji worktree, przypięcia do checkpointu, audytu
aktualnej ścieżki, porównania historycznego kodu oraz braku zmian produkcji.
Nie można wydać pełnego PASS, ponieważ raw package Core Ultra nie jest
lokalnie dostępny, a sprzęt Core Ultra nie jest dostępny do realnego runtime
proof. Żadnego Intel runtime PASS nie wywnioskowano z AMD ani z UHD 730.

