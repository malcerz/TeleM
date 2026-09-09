# AMD surgical rollback — post-Stage-A/C proof

Data: 2026-09-07  
Branch: `integration/intel-amd`  
HEAD (unchanged): `59277b4c920e0bb8a9642e4a574a32db0edcfacc`

## Zakres i zabezpieczenie

Rollback wykonano selektywnie w dirty worktree. Nie użyto `git reset --hard`,
`git clean`, commit ani push.

Backup całego stanu wejściowego pozostaje dostępny:

```text
2b92b6bc0a83f0a6959b7b74adc283835787348a
backup-before-surgical-post-stageA-rollback-20260907
```

Pozostawiono także wcześniejsze backupy:

```text
878442ee9ef7367d2d00551ba2eaaf5e8f0ca36e  backup-after-too-wide-amd-rollback-20260907
6219a9e895317b212e876a41ac0c65bf36c4e384  backup-before-amd-render-rollback-20260907
```

Targetem logicznym nie był cały commit `59277b4`, tylko ostatnia działająca
implementacja Stage A/C z dowodu 50 136 klatek. Bazowy HEAD został zachowany.

## Przywrócony kontrakt renderera

- AMD D3D11VA + AMF, obecny compositor/HUD, mapy, wykresy, gauge, lean i layout
  pozostały bez cofania.
- GPMF/native parser, `telemetry_active_time`, Preview, GUI i aktualne API
  renderowania pozostały bez cofania.
- Stage A zapisuje video obok żądanego wyjścia jako
  `<output>.part.temp_video.mp4`; Stage B tworzy concat audio; Stage C wykonuje
  stream-copy remux do `<output>.part`, po czym następuje finalizacja.
- Python i native pipe writer używają synchronicznego I/O zgodnego z proofem:
  usunięto overlapped pipe, `CancelIoEx`, 15-sekundowe timeouty i zależność od
  liveness watchdog.
- Usunięto produkcyjne local-scratch routing, `AMD_LOCAL_SCRATCH_DIR`, stale
  scratch cleanup i disk guard z gorącej ścieżki.
- Usunięto `FinalizationTracker` oraz USB-specific lifecycle waits. Zachowano
  zwykłe oczekiwanie na pump/FFmpeg potrzebne do zamknięcia pliku.
- `NonBlockingProgressDispatcher` i bieżące callbacki GUI pozostawiono.
- Stary hook diagnostyki live-mux pozostaje wyłącznie jako inert compatibility
  hook i nie jest wywoływany; nie uczestniczy w lifecycle.

## Zmienione pliki

```text
src/ffmpeg/amd_native_exporter.py
src/ffmpeg/streaming.py
native/d3d11_amf_pipeline/src/telem_amd_native.cpp
native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp (net diff: brak; przywrócono
profiling wait do wersji bazowej)
native/d3d11_amf_pipeline/bin/telem_amd_native.dll (przebudowany artefakt)
```

Pozostałe zmodyfikowane pliki dirty worktree należą do odzyskanego stanu
aplikacji i nie były selektywnie cofane.

## DLL / ABI

DLL przebudowano targetem `telem_amd_native` po ostatniej zmianie źródła.
Pełny target CMake był PASS; niezależny target `d3d11_etap2c_poc` nadal nie
buduje się z powodu istniejącego braku `CreateHUDTexture` i nie należy do tego
rollbacku.

```text
ABI: 9
build_id: telem-amd-native/1.0.0+59277b4c920e.srce97b5d25da9f
git_commit: 59277b4c920e0bb8a9642e4a574a32db0edcfacc
source_hash: e97b5d25da9fcc4f86f38555934c23537f0a9986468020d7fc88594f11fb9220
telem_amd_get_liveness: absent
telem_amd_get_pipe_diagnostics: absent
```

Aktualne blob hashes working tree:

```text
src/ffmpeg/amd_native_exporter.py                  e9a0ae49256ffe98adeffbea500d29bac13e2ecf
src/ffmpeg/streaming.py                            0d6a3dca8b2f689d25bbacf39add448c99e604d8
native/.../telem_amd_native.cpp                    1b88a31039e3a924c5a1b2416e23402e3c6b9222
native/.../d3d11_vp_pipeline.cpp                   158a888eb2b0bcce750238274d7cd10cfe37802f
```

## Testy

### PASS

- `python -m py_compile src/ffmpeg/amd_native_exporter.py src/ffmpeg/streaming.py`
- `python -m pytest -q tests/test_amd_direct_mp4_mux.py`: **9 passed**
- Multi-file two-stage boundary, 300 frames (`GX010114 → GX010115`):
  Stage A complete, Stage B concat, Stage C stream-copy complete; 300 HEVC
  frames, AAC present, duration 10.010 s; Render FPS 42.073,
  Effective FPS 37.087.
- 500 frames, Preview OFF, current HUD/GPMF, `GX010114.MP4` +
  `GX010114_116.fit`: **PASS**, Render FPS 36.611, Effective FPS 32.509.
- 3000 frames, Preview OFF, same project material: **PASS 3000/3000**,
  Render FPS 33.057, Effective FPS 32.340. `ffprobe`: HEVC 3840x2160,
  3000 video frames, AAC, MP4 duration 100.117333 s.
- 12000 frames (crosses historical failure near frame 11209):
  **PASS 12000/12000**, Render FPS 32.057, Effective FPS 31.865.
  `ffprobe`: HEVC 3840x2160, 12000 video frames, AAC, MP4 duration
  400.405333 s, format `mov,mp4,m4a,3gp,3g2,mj2`.

### NOT PASS / ograniczenie fixture

`scratch/run_multifile_smoke.py --test smokeA` zatrzymał się przed finalizacją
na istniejącym fixture z `heading=None` (`TypeError` w compass indicator), a nie
na pipe/mux. Został zastąpiony i pozytywnie zweryfikowanym testem
`test_multifile_render_twostage.py`, który rzeczywiście przeszedł Stage A/B/C.

Nie uruchamiano pełnego renderu 85 574 klatek.

## Ocena

`ERROR_NO_DATA` / `ERROR_BROKEN_PIPE`: **nie wystąpiły** w testach 500f,
3000f, 12000f ani multi-file Stage A/C. MP4 i audio są poprawne według ffprobe.
Wizualna inspekcja pikselowa pełnego HUD nie była wykonywana automatycznie;
stabilność i lifecycle muxu są potwierdzone, parity pikselowa: **NOT PROVEN**.

Status: **READY FOR USER REVIEW / NOT READY FOR FULL-LENGTH 85 574-FRAME RUN**.

