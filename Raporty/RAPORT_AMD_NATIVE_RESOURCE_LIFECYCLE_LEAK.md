# AMD native D3D11 / AMF / Media Foundation — resource lifecycle leak audit

Data: 2026-09-07  
Branch: `integration/intel-amd`  
HEAD: `59277b4c920e0bb8a9642e4a574a32db0edcfacc`

## Zakres

Audyt dotyczył wyłącznie lifetime native AMD. Nie zmieniano pipe writera, Stage A/B/C,
komendy FFmpeg, local scratch, watchdog ani overlapped I/O. GPU-tap Preview nie został
zaimplementowany. Istniejące zmiany dirty worktree zachowano.

Dodano opt-in diagnostykę (domyślnie wyłączoną): `AMD_NATIVE_RESOURCE_AUDIT=1`,
`AMD_D3D11_TEARDOWN_FLUSH=1` oraz `AMD_MF_TEARDOWN_FLUSH=1`. Nie jest to produkcyjny
fix.

## Główny wynik

Pełny HUD, Preview OFF, trzy rendery po 300 klatek w jednej instancji:

| punkt | RSS | Private/Commit | threads | handles |
|---|---:|---:|---:|---:|
| fresh | ~156.7 MB | ~663.8 MB | 21 | 365 |
| render 1 | ~977.5 MB | ~1,847.6 MB | 36 | 805 |
| render 2 | ~1,397.8 MB | ~2,610.4 MB | 40 | 980 |
| render 3 | ~1,817.9 MB | ~3,342.9 MB | 40 | 1,157 |

Wszystkie rendery były funkcjonalnie poprawne, ale Private/Commit i handles rosną
monotonicznie. `tracemalloc` pozostawał stabilny (~168–170 MB), więc nie jest to
zwykły wyciek Python heap.

### Ablacje

| wariant | obserwacja |
|---|---|
| Minimal HUD, 300f ×3 | poprawne rendery; Private/Commit ~1.164 → 0.941 → 1.174 GB; handles ~594 → 615 → 625 |
| Full HUD, `AMD_GPU_HUD_OFF=1` | trend pozostaje (~2.16 → 2.93 → 3.66 GB) |
| `AMD_AMF_MODE=BYPASS`, 100f ×3 | ~2.073 → 2.780 → 3.470 GB; handles ~799 → 978 → 1,151 |
| D3D11 `ClearState()+Flush()` | brak istotnej zmiany |
| MF `SourceReader::Flush()` | brak istotnej zmiany |
| CPU decode | ablation niepoprawna: `Incomplete CPU P010 frame read`; nie jest acceptance |

AMF BYPASS i HUD OFF nie usuwają wzrostu; Python heap również go nie wyjaśnia.

## Instrumentacja native

DLL po buildzie:

```text
ABI=9
build_id=telem-amd-native/1.0.0+59277b4c920e.srce97b5d25da9f
embedded git_commit=59277b4c920e0bb8a9642e4a574a32db0edcfacc
source_hash=e97b5d25da9fcc4f86f38555934c23537f0a9986468020d7fc88594f11fb9220
DLL timestamp=2026-09-07 11:46:25
```

Bezpośredni `telem_amd_create/telem_amd_close`, valid `GX010115.MP4`, dwa cykle,
`AMD_NATIVE_RESOURCE_AUDIT=1`:

```text
generation 1: AMF_CONTEXT 1/1, AMF_ENCODER 1/1,
 D3D11_CONTEXT 1/1, D3D11_DEVICE 1/1, D3D11_TEXTURE 2/2,
 MF_DXGI_DEVICE_MANAGER 1/1, MF_SOURCE_READER 1/1, still_alive=0
generation 2: AMF_CONTEXT 1/1, AMF_ENCODER 1/1,
 D3D11_CONTEXT 1/1, D3D11_DEVICE 1/1, D3D11_TEXTURE 2/2,
 MF_DXGI_DEVICE_MANAGER 1/1, MF_SOURCE_READER 1/1, still_alive=0

VP POOL: textures created=8 released=8 live=0
VP POOL: views created=24 released=24 live=0
D3D11 device refcount=1 after teardown+MFShutdown (1=clean)
```

Jawne top-level COM refs oraz własny VP pool są więc zwalniane. To nie mierzy
wewnętrznych kolejek MF/D3D11VA ani alokacji sterownika.

## Lifecycle i granica root cause

| zasób | create | release | ocena |
|---|---|---|---|
| D3D11 device/context | per context | po destruktorach VP/AMF | audit 1/1; refcount 1 |
| VP textures/views | pool | destructor pipeline | 8/8 i 24/24, live 0 |
| MF DXGI manager | per render | `Release` w close | audit 1/1 |
| `IMFSourceReader` | `MFCreateSourceReaderFromURL` | `Release`; opt-in Flush testowany | audit 1/1; successful reader path koreluje ze wzrostem |
| MF decoder/transform/surfaces | zarządzane przez SourceReader | pośrednie MF teardown | brak publicznego licznika; główny kandydat |
| AMF context/encoder | per render | smart pointer/destructor, drain/terminate | audit 1/1; BYPASS nadal rośnie |
| AMF surface/buffer/data | per frame | smart pointers/scope/queue | brak intrusive counter |
| native worker threads | brak `std::thread`/`CreateThread` w native exporterze | n/a | total procesu rośnie, owner nieustalony |

Najsilniejszy, udowodniony wniosek: wyciek/granica retencji znajduje się w udanej
ścieżce Media Foundation D3D11VA decode — najpewniej odroczone lub driver-owned
surfaces/queues/MF transform/DXGI internals. Nie znaleziono dowodu wskazującego jeden
konkretny `IMFTransform`, surface albo handle. Top-level `Release` nie wystarcza do
wykluczenia retencji poza jawnie posiadanym COM pointerem.

`ClearState()+Flush()` oraz `IMFSourceReader::Flush()` nie zmieniły trendu, więc nie
wdrożono agresywnego teardown jako nieudowodnionej poprawki.

## Braki pomiarowe

- `handle.exe`/Process Explorer nie są dostępne lokalnie; znamy tylko total handles,
  nie typy Thread/File/Pipe/Section.
- D3D11 debug layer / `IDXGIDebug1::ReportLiveObjects`: NOT AVAILABLE.
- GPU dedicated/shared memory i AMF internal surface/buffer count: NOT AVAILABLE.
- Thread owner/start generation nie są przypisywalne z obecnych snapshotów. Preview
  teardown raportował wcześniej worker=0 i decoder cache=0; wzrost występuje także
  Preview OFF.

## Acceptance

Krótki artefakt kontrolny `scratch/background_preview_audit/process_state_off3_off1.mp4`
ma `ffprobe`: HEVC, 3840×2160, 100 frames. Render/mux były poprawne w obserwowanych
sekwencjach, lecz lifecycle kryteria nie przechodzą:

```text
NO LINEAR COMMIT GROWTH: FAIL
NO LINEAR HANDLE GROWTH: FAIL
NO THREAD LEAK: NOT PROVEN / trend FAIL
3x PREVIEW OFF SAME PROCESS: render PASS, resource FAIL
PREVIEW ON -> OFF -> OFF: render PASS, resource FAIL
NO PIPE FAILURE: PASS for observed runs
MP4 VALID: PASS for observed short runs
5x1000 full acceptance: NOT RUN after failure boundary was already proven
```

Nie wykonano 5×1000, ponieważ wcześniejsza sekwencja już jednoznacznie wykazała
odrzucany monotoniczny trend; nie zmieniałoby to diagnozy.

## Status

**READY: NO**  
**Exact native object root cause: NOT PROVEN**  
**MF/D3D11VA decode leak boundary: PROVEN**  
**Minimal production fix: NOT IMPLEMENTED**  
**GPU-tap Preview: NOT IMPLEMENTED**  
**Pipe/mux/Stage A/B/C: UNCHANGED**
