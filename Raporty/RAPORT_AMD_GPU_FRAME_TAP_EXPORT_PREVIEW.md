# AMD GPU frame tap Export Preview — feasibility and implementation audit

## Zakres

Zadanie wykonano na `integration/intel-amd`, HEAD `59277b4`. Nie wykonano
`reset`, `clean`, `rebase`, commit ani push. Nie zmieniano ścieżki Intel ani
polecenia Stage A/B/C, named-pipe writera, AMF encode ani D3D11 compositora
poza dodaniem opcjonalnego tapu Preview.

## Znaleziony punkt frame tap

Kanoniczna finalna powierzchnia jest zwracana przez
`D3D11VideoProcessorPipeline::ProcessFrame` jako `pOutNV12Tex`. W
`telem_amd_process_frame` jest ona ustawiana po pełnym compose:

`decode → map → BELOW/ABOVE HUD → AFTER-MAP charts/gauge/lean → final NV12`

Następnie, przed wywołaniem AMF `CreateSurface/SubmitSurface`, opcjonalny tap
wykonuje `SubmitPreviewTap(pOutNV12Tex, frame_index)`. Nie powstaje druga
kompozycja HUD.

## Implementacja GPU tapu

`D3D11VideoProcessorPipeline` tworzy lazily:

- osobny `ID3D11VideoProcessorEnumerator` z wyjściem 960×540 (konfigurowalne);
- osobny GPU VideoProcessor: NV12 → BGRA + downscale;
- dwa tekstury wyjściowe BGRA;
- dwa staging textures CPU-read;
- dwa `D3D11_QUERY_EVENT` do asynchronicznego completion.

Na klatkę eksportera:

1. tylko co około 500 ms wykonywany jest submit zależny od `interval_frames`;
2. gdy poprzedni capture jest in-flight, bieżący preview jest pomijany;
3. `PollPreviewTap` używa `GETDATA_DONOTFLUSH` i `MAP_DO_NOT_WAIT`;
4. gotowy BGRA jest kopiowany do bufora Python i przekazywany do Qt.

Render nigdy nie czeka na Preview. Błąd lub brak gotowości tapu nie ustawia
cancel renderera.

## Latest-state-only i Edit Mode

`AMDGPUNativeFrameTapPreview` nie tworzy procesu FFmpeg, dekodera HEVC,
workerów ani kolejki. Po stronie Qt przechowywana jest najwyżej jedna gotowa
klatka GPU tapu i jeden queued signal; nowsza zastępuje starszą.

Tryb edycji nadal korzysta z istniejącego MPV/QMedia/PIL lifecycle. GPU tap
jest tworzony wyłącznie podczas `render_active=True`. Po render complete/error/
cancel tap jest wyłączany, label eksportu jest ukrywany, a zwykły Edit Preview
jest odtwarzany.

Przyciemnienie jest nakładane wyłącznie na QImage w GUI dla tapu eksportowego
(`QPainter` alpha overlay). Finalny MP4 nie jest zmieniany.

Checkbox `Podgląd HUD podczas renderowania`:

- OFF: brak `AMDGPUNativeFrameTapPreview`, brak native configure, brak submit,
  poll i readback;
- ON: loguje `backend=gpu_frame_tap`.

Produkcja AMD nie uruchamia już pełnego HEVC sidecara. Klasa
`AMDContinuousHEVCPreview` pozostała tylko jako kod diagnostyczny/fallback,
ale nie jest tworzona przez `RenderTab` dla AMD.

## Zmienione pliki

- `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.h/.cpp` — GPU scaler,
  staging/query tap i teardown;
- `native/d3d11_amf_pipeline/src/telem_amd_native.cpp` — ABI
  `telem_amd_set_preview_tap` / `telem_amd_poll_preview_tap` oraz submit przed
  AMF;
- `src/ffmpeg/amd_hevc_preview.py` — `AMDGPUNativeFrameTapPreview`;
- `src/ffmpeg/amd_native_exporter.py` — ABI binding, bind po create i
  non-blocking poll;
- `src/gui/qt/tabs/render_tab.py` — GPU tap selection, latest-state Qt,
  dimming i powrót do Edit Preview;
- `tests/test_amd_gpu_frame_tap_preview.py` — kontrakt fake ABI/latest-only.

## DLL

DLL została przebudowana z bieżących źródeł przez MinGW/Ninja:

`telem-amd-native/1.0.0+59277b4c920e.src4dde4660667c`

ABI: `9`. Eksporty `telem_amd_set_preview_tap` i
`telem_amd_poll_preview_tap` są obecne w DLL.

## Testy automatyczne i smoke

- `py_compile`: PASS;
- testy AMD Preview/mux + fake GPU tap: **13 passed**;
- multi-file 20 klatek, pełny HUD, Preview ON: PASS; tap podał 2 klatki,
  `CPU readback avg=0.461 ms`, `dropped=0`, `workers=0`;
- MP4 20f: final mux `returncode=0`, source boundary PASS;
- multi-file 3000, minimal HUD, Preview OFF: PASS, Render FPS `42.434`;
- multi-file 3000, minimal HUD, GPU tap ON: PASS, Render FPS `42.439`,
  Effective FPS `41.018`, `updates=200`, `dropped=0`, brak sidecara;
- `ffprobe` dla 3000f GPU-tap ON: HEVC 3840×2160, `nb_frames=3000`,
  duration `100.100000`.

## Ograniczenie acceptance full-HUD

Pełny HUD 3000f ON i OFF w bieżącej, już dirty instancji procesu zakończył się
znanym wcześniejszym `MemoryError` w Pillow (`tobytes` w
`_extract_exact_above_regions` / `map_img`), a nie błędem tapu, pipe ani AMF.
W przebiegu ON tap dostarczył 76 klatek przed błędem i nie zgłosił żadnego
dropu ani `last_error`. Ten problem należy do wcześniej zaobserwowanego
narastania pamięci renderera/native resource lifecycle i nie został zmieniony
w tym zadaniu.

W konsekwencji pełny-HUD 3000f oraz pełny-HUD 10000f nie są jeszcze dowodem
gotowości całego projektu. Nie wykonano testu 85574 klatek.

## Status

**IMPLEMENTED / GPU TAP SMOKE PASS — NOT READY FOR FULL ACCEPTANCE**

GPU tap, latest-state-only, checkbox OFF i Edit Preview separation są
zaimplementowane i działają w smoke testach. Kryteria READY wymagające pełnego
HUD 3000/10000, braku istniejącego resource leak oraz testu Chrome foreground
pozostają **NOT PROVEN**.

GPU copy/VideoProcessor wall time nie jest osobno raportowany przez obecny ABI;
zmierzony czas dotyczy gotowego staging `Map` + CPU copy do BGRA.
