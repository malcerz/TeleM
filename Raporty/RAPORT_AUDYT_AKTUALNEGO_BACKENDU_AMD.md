# TeleM — audyt aktualnego backendu AMD

Data audytu: 2026-08-14  
Zakres: wyłącznie analiza aktualnego repozytorium, bez modyfikacji kodu i bez uruchamiania eksportu.

## Najważniejszy werdykt

- Produkcyjny backend nadal działa jako **FFmpeg software decode → CPU NV12 → staging texture → `CopyResource`**.
- HUD jest obecnie wariantem **A: CPU `BlendRGBAToNV12`**.
- HUD nie jest composited przez compute/pixel shader.
- HUD nie jest Stream 1 VideoProcessora.
- VideoProcessor dostaje tylko Stream 0, czyli już złożoną na CPU klatkę NV12, i wykonuje pełny NV12→NV12 blit.
- VP→AMF jest bez jawnej kopii CPU: AMF opakowuje tę samą teksturę D3D11.
- Wcześniejszy D3D11VA→P010→VP Stream 1→AMF nadal częściowo istnieje, lecz jest omijany przez aktywną ścieżkę Pythona.

Kod odpowiedzialny za dispatch znajduje się w `src/ffmpeg/streaming.py`, aktywny eksporter w `src/ffmpeg/amd_native_exporter.py`, a CPU blend w `native/d3d11_amf_pipeline/src/telem_amd_native.cpp`.

## 1. CURRENT REAL PIPELINE

```text
GUI RenderMixin
  │
  ├─ zbiera GPMF / FIT / GPX / ISO / exposure / temperature / battery
  └─ stream_overlay_to_ffmpeg(encoder="amd")
       │
       └─ detect_amd_compose_backend() == AMD_NATIVE_D3D11
            │
            └─ export_amd_native_d3d11()
                 │
SOURCE MP4 ───────┤
                 │
                 ▼
          FFmpeg subprocess
          software HEVC decode
          scale=W:H, format=nv12
                 │
                 │ raw NV12 przez stdout pipe
                 │ CPU, 12.44 MB dla 4K
                 ▼
          Python bytes: raw_nv12
                 │
                 ├───────────── HUD branch ──────────────────────┐
                 │                                               │
                 │  prepare_overlay_frame_data() — CPU           │
                 │  compose_overlay() / Pillow — CPU RGBA        │
                 │  pełny canvas 3840×2160 RGBA                  │
                 │  composed_img.tobytes() — pełna kopia         │
                 │  ctypes → telem_amd_update_hud()              │
                 │  memcpy → persistent currentHUDRGBA           │
                 │                                               │
                 └─────────────────────┬─────────────────────────┘
                                       ▼
                          telem_amd_update_video_frame()
                          Map persistent staging NV12
                          memcpy pełnej bazowej klatki
                          BlendRGBAToNV12 na CPU
                                       │
                                       ▼
                          Unmap + CopyResource
                          staging NV12 → default NV12 texture
                          CPU/system memory → GPU
                                       │
                                       ▼
                          ID3D11VideoProcessor
                          Stream 0 only
                          NV12 → NV12 full-frame blit
                          persistent output pool[4]
                                       │
                                       ▼
                          CreateSurfaceFromDX11Native
                          ta sama ID3D11Texture2D
                          bez jawnego CPU round-trip
                                       │
                                       ▼
                          AMD AMF HEVC Main / NV12
                                       │
                          encoded packet → CPU vector
                                       │
                                       ▼
                          output.mp4.h265
                                       │
                                       ▼
                          drugi FFmpeg subprocess
                          video: copy z .h265
                          audio: copy z wejściowego MP4
                                       │
                                       ▼
                                  FINAL MP4
```

## Przepływ jednej klatki

Dla 3840×2160:

- NV12: `W×H×1.5` = **12 441 600 B = 11,865 MiB**
- RGBA8: `W×H×4` = **33 177 600 B = 31,641 MiB**
- P010/yuv420p10le: nominalnie `W×H×3` = **24 883 200 B = 23,73 MiB**

| Etap | CPU/GPU i format | Kopie / conversion | Czas życia |
|---|---|---|---|
| Odczyt źródła | CPU/file I/O, skompresowany HEVC | Brak pełnej surowej klatki w kodzie aplikacji | Pakiety per-frame/per-GOP |
| Decode FFmpeg | CPU; dla badanego `GX020079.mp4`: HEVC Main10 → `yuv420p10le` | Pełny decode; bufor około 23,73 MiB | Bufory FFmpeg per-frame/pool |
| `scale,format=nv12` | CPU, NV12 8-bit | 10→8 bit, planar→semi-planar; scale, jeśli rozmiar różny | Per-frame |
| `pipe:1` | CPU/OS pipe, NV12 11,865 MiB | Pełny transfer międzyprocesowy i utworzenie Python `bytes` | Per-frame |
| Dane telemetryczne | CPU, obiekty Python | Interpolacja/step lookup; brak obrazu | Sample i cache persistent |
| Generowanie HUD | CPU/Pillow, RGBA8 31,641 MiB | Rysowanie wskaźników i mapy; canvas persistent | Canvas persistent, warstwy głównie per-frame |
| `tobytes("RGBA")` | CPU, RGBA8 | Pełna kopia 31,641 MiB | Per-frame |
| `telem_amd_update_hud` | CPU, RGBA8 | `memcpy` kolejnych 31,641 MiB | `std::vector` persistent, zawartość wymieniana per-frame |
| Upload bazowego video | CPU → staging NV12 | Pełne `memcpy` 11,865 MiB | Staging persistent |
| CPU HUD blend | CPU, RGBA→NV12 | Pełny skan 8,29 mln pikseli; zapis tylko tam, gdzie alpha > 0 | Per-frame operation |
| `CopyResource` | CPU-visible staging → GPU default NV12 | Pełna kopia 4K, nominalnie 11,865 MiB | Obie tekstury persistent |
| VideoProcessor | GPU, NV12→NV12 | Pełny blit do kolejnej tekstury poolu | Pool czterech tekstur persistent; input view per-frame |
| AMF surface | GPU NV12 | `CreateSurfaceFromDX11Native`; brak jawnej kopii aplikacyjnej | Wrapper AMF per-frame |
| HEVC encode | GPU/VCN | NV12→skompresowany HEVC Main 8-bit | Enkoder persistent |
| Packet output | Akcelerator/GPU → CPU | Kopia skompresowanego pakietu do `std::vector` | Per-frame |
| Audio mux | CPU/file I/O, AAC packets | `-c:a copy`, bez decode i bez re-encode | Po zakończeniu całego video |

Rozmiar tekstur może być większy od wartości nominalnej z powodu `RowPitch`, tilingu i wyrównania sterownika.

## HUD i telemetria

`prepare_overlay_frame_data()` jest rzeczywiście wywoływane dla każdej klatki w `amd_native_exporter.py`.

Faktyczny przebieg:

- date/time są tworzone per-frame z `target_dt + tz_offset`;
- speed/distance/altitude wybierają GPMF, GPX albo FIT według konfiguracji wskaźnika;
- ISO/exposure/temperature są interpolowane z przekazanych kanałów;
- power/ATemp/HR/cadence/battery przechodzą przez cache i interpolację schodkową;
- dynamiczne pola `fit_*` są rozwiązywane po nazwie pola;
- dane wykresów i zakresy min/max są precomputowane;
- renderer mapy jest cache’owany, ale sam obraz mapy, trasa i marker są składane na CPU per-frame.

Następnie `compose_overlay()` renderuje wszystkie aktywne wskaźniki do pełnego RGBA. Canvas jest trwały i częściowo czyszczony przez bounding boxy, ale eksport AMD nie korzysta z tych bounding boxów przy dalszym przesyle.

Istotny szczegół: „Smart Canvas Scaling” z GUI oblicza `overlay_w=1920`, ale backend natywny otrzymuje `render_w/render_h` i tworzy HUD w pełnej rozdzielczości video. Optymalizacja 1920 px nie działa w ścieżce native AMD.

## 2. CPU↔GPU transfers per frame

### Regularna klatka

| Kierunek | Dane |
|---|---:|
| CPU → GPU | Pełny NV12 przez staging + `CopyResource`: **co najmniej 11,865 MiB** |
| CPU → GPU HUD texture | **0 B** — nie ma aktywnej tekstury HUD |
| GPU → CPU raw video | **0 B** w regularnej klatce |
| GPU/encoder → CPU | Skompresowany pakiet HEVC, rozmiar zmienny |
| GPU → GPU | VideoProcessor: pełny NV12 wejście→wyjście, około **11,865 MiB nominalnie** |
| VP → AMF | Brak jawnej kopii; ta sama tekstura zostaje opakowana jako AMF surface |

Na APU pamięć może być fizycznie współdzielona, ale operacja `CopyResource`, synchronizacja i pełny ruch pamięci nadal istnieją logicznie.

### Wyjątek: klatka 30

Produkcja bezwarunkowo wykonuje ciężkie checkpointy:

- GPU→CPU readback `B_base_d3d11`;
- dwa kolejne readbacki VP: `C_vp_output` i `D_after_gpu_hud`;
- readback `E_amf_input`;
- kilka konwersji NV12→RGBA i zapisów PNG;
- po muxie uruchamia następny FFmpeg do utworzenia `F_final_mp4.png`.

To nie jest koszt każdej klatki, ale powoduje duży jednorazowy stall i zapisuje pliki diagnostyczne w bieżącym katalogu.

## 3. Pełne kopie i przebiegi 4K per frame

Jawne pełne kopie:

1. FFmpeg → pipe → Python: pełny NV12, 11,865 MiB.
2. Python NV12 → mapped staging: pełny NV12, 11,865 MiB.
3. Pillow canvas → `rgba_bytes`: pełny RGBA, 31,641 MiB.
4. `rgba_bytes` → `currentHUDRGBA`: pełny RGBA, 31,641 MiB.
5. Staging → default texture: pełny NV12 przez `CopyResource`.
6. Default texture → VP output: pełny GPU blit NV12.

Dodatkowo:

- `BlendRGBAToNV12` nie kopiuje całej klatki do nowego bufora, ale skanuje cały RGBA i całą siatkę 4K;
- FFmpeg ma własne wewnętrzne pełne bufory decode i swscale;
- systemowy pipe może powodować dodatkowe kopie w jądrze;
- AMF może wykonać wewnętrzną kopię sterownika, ale nie jest ona widoczna ani wymuszana w kodzie aplikacji.

Dwie same kopie RGBA to **66,36 MB/klatkę**, czyli około **1,99 GB/s** przy 29,97 FPS. Jawny CPU data movement przed uwzględnieniem wewnętrznych buforów FFmpeg i samego blendu wynosi co najmniej około **91,2 MB/klatkę**.

## 4. Pixel-format conversions

Dla obecnego materiału testowego:

1. HEVC Main10, `yuv420p10le`, full-range BT.2020/HLG → zdekodowana klatka CPU.
2. `scale=3840:2160,format=nv12`:
   - 10-bit → 8-bit,
   - planar 4:2:0 → semi-planar NV12,
   - potencjalne skalowanie.
3. Pillow RGBA straight-alpha → NV12:
   - wykonywane ręcznie w `BlendRGBAToNV12`;
   - współczynniki odpowiadają ograniczonemu zakresowi YUV;
   - UV jest aktualizowane raz na blok 2×2 na podstawie lewego-górnego piksela HUD.
4. VideoProcessor: aktywnie **NV12 → NV12**, mimo nazw `pBaseP010Tex` i `pP010Texture`.
5. AMF: NV12 8-bit → HEVC Main 8-bit.
6. Audio: AAC → AAC packet copy; brak conversion.
7. Mux: elementary HEVC + AAC → MP4; brak video/audio re-encode.

Argument `SetupVideoProcessor(DXGI_FORMAT_P010, DXGI_FORMAT_NV12)` jest mylący: `inputFormat` nie jest używany do tworzenia wejścia ani walidacji. Produkcyjna tekstura bazowa jest faktycznie `DXGI_FORMAT_NV12`.

## 5. Największe prawdopodobne bottlenecki

1. **CPU `BlendRGBAToNV12` na pełnym 4K.** Dwie zagnieżdżone pętle wykonują ponad 8,29 mln iteracji na klatkę, nawet gdy większość HUD jest przezroczysta.

2. **Pełnoekranowy HUD Pillow oraz dwie pełne kopie RGBA.** Mapa, supersampling, tekst i obracane elementy są renderowane na CPU. Potem następują `tobytes()` i native `memcpy`.

3. **Software decode HEVC Main10 + swscale 10→8 na CPU.** Polecenie dekodera nie zawiera `-hwaccel`; wcześniejsze D3D11VA nie uczestniczy w produkcyjnym decode.

4. **Rawvideo pipe i pełne kopiowanie NV12 do staging.** Co najmniej dwa pełne przebiegi 4K po RAM przed uploadem.

5. **Twarda synchronizacja CPU/GPU w VideoProcessor.** Dla każdej klatki przekazywany jest `vpStats`, a kod aktywnie kręci się w `while(GetData(...) == S_FALSE)`. Powoduje to per-frame GPU flush/wait i blokuje pipelining.

6. **Redundantny VideoProcessor NV12→NV12.** HUD jest już zmieszany, a VP wykonuje jeszcze jeden pełny blit tylko po to, by uzyskać teksturę wejściową AMF.

7. **AMF i zarządzanie kolejką.** `AMF_INPUT_FULL` jest traktowane jak sukces bez retry; pula VP ma cztery tekstury bez śledzenia, kiedy AMF faktycznie zwolni powierzchnię. Obecne artefakty mają prawidłową liczbę klatek, ale przy większym backpressure to ryzyko utraty lub przedwczesnego ponownego użycia powierzchni.

8. **Checkpointy klatki 30.** Nie wpływają na średni koszt każdej klatki tak jak powyższe punkty, lecz powodują bardzo duży stall, dodatkowe readbacki i I/O.

## 6. Co pozostało z wcześniejszego D3D11VA→VP→AMF

### Nadaje się do ponownego wykorzystania

- Media Foundation SourceReader z `IMFDXGIDeviceManager`, żądaniem P010/NV12 i pobraniem `IMFDXGIBuffer` nadal znajduje się w `telem_amd_native.cpp`.
- Jest aktywnie inicjalizowany przy `telem_amd_create()`.
- `ReadSample()` i pobranie `ID3D11Texture2D` nadal istnieją.
- Ścieżka jest jednak pomijana, ponieważ Python najpierw zawsze wywołuje `telem_amd_update_video_frame()`, ustawiając `hasUpdatedVideoFrame=true`.
- VP, jego enumerator, color-space state i trwała pula czterech tekstur NV12 są gotowe.
- AMF działa na tym samym urządzeniu D3D11 i używa `CreateSurfaceFromDX11Native`.
- Kod wcześniejszego Stream 1 istnieje w historii Git (`514abd3`, `ff1acdc`).
- Obecna funkcja `CreateHUDTexture()` nadal potrafi utworzyć BGRA texture i input view, ale nie jest wywoływana.
- `D3D11HUDBridge` zawiera użyteczne pełne i dirty-rect `UpdateSubresource`, lecz nie jest instancjonowany.
- Oddzielny `native/d3d11_compositor` zawiera wcześniejszy pixel-shader PoC straight-alpha.

### Martwe albo niespójne pozostałości

- `D3D11_VIDEO_PROCESSOR_STREAM streams[1]` oznacza dokładnie jeden stream; komentarz „Stream 0 + Stream 1 HUD Composition” jest nieprawdziwy.
- `enableHUD` wpływa tylko na sztucznie przypisywane statystyki. Nie zmienia kompozycji.
- `InitHUDComputeShader()` istnieje, ale nigdy nie jest wywoływane. Nie ma tworzenia SRV/UAV plane views ani `Dispatch`.
- `m_hudTexture` i `m_hudInputView` w VP pozostają `nullptr` w produkcji.
- Pola HUD w `TelemAMDContext` są niewykorzystywane.
- `src/indicators/gpu_compositor.py` inicjalizuje OpenCL w GUI, ale nie uczestniczy w natywnym eksporcie.
- `native/d3d11_pipeline/src/d3d11va_surface_test.cpp` ma rozmiar zero.
- Skrypty `run_etap*`, starsze raporty i PoC opisują inne ścieżki niż bieżąca produkcja.
- Parametry Python `codec`, `quality`, `rc`, `qp_*` i bitrate nie trafiają przez ABI; DLL ma na sztywno HEVC, speed, CQP 28/28.
- `input_files[0]` oznacza, że native exporter ignoruje kolejne pliki wejściowe. Nie obsługuje też aktywnie rotacji ani regionów cięcia przekazanych do ogólnego eksportera.
- Tryb bez HUD nadal tworzy przezroczysty pełny canvas, kopiuje go dwukrotnie i skanuje w `BlendRGBAToNV12`.
- Ostatni `return True` w eksporterze jest nieosiągalny.

### Problem odtwarzalności DLL

Obecny `native/d3d11_amf_pipeline/CMakeLists.txt` buduje tylko `d3d11_etap2c_poc`. Nie zawiera:

- targetu `telem_amd_native.dll`,
- `telem_amd_native.cpp`,
- bibliotek Media Foundation,
- `d3d11_hud_bridge.cpp`.

DLL jest ignorowany przez `*.dll` w `.gitignore`. Znajdujący się w `bin` plik ma timestamp kilka sekund po aktualnych źródłach, a jego strings zawierają nowy symbol `telem_amd_update_video_frame` i aktualne checkpointy. Jest więc bardzo prawdopodobne, że odpowiada kodowi, ale repo nie daje deterministycznego sposobu jego odbudowy ani formalnego potwierdzenia wersji.

## ctypes API

ABI jest spójne typowo dla MinGW/cdecl:

- `telem_amd_create(wchar_t*, wchar_t*, UINT, UINT, UINT, UINT) -> void*`
- `telem_amd_update_hud(void*, uint8_t*, UINT, UINT, UINT) -> int`
- `telem_amd_update_video_frame(void*, uint8_t*, UINT, UINT, UINT) -> int`
- `telem_amd_process_frame(void*, UINT, int) -> int`
- `telem_amd_dump_checkpoint(void*, UINT, char*, wchar_t*) -> int`
- `telem_amd_flush(void*) -> int`
- `telem_amd_close(void*) -> int`
- `telem_amd_get_stats(void*, UINT64*, UINT64*, UINT64*, UINT64*) -> void`

`c_char_p` może przekazywać binarne bufory z zerami, ponieważ C nie używa funkcji stringowych i zna rozmiar z wymiarów. Python utrzymuje obiekt `bytes` przy życiu przez czas wywołania.

Słabości:

- return value `update_hud` i `update_video_frame` jest ignorowane;
- błąd `process_frame` jest logowany, ale eksport jest kontynuowany;
- `active_process_holder` nie przechowuje procesu dekodera;
- ABI nie przenosi ustawień jakości, bitrate, kolorów ani znaczników czasu.

## 7. Minimalny plan dalszej optymalizacji

### Etap 0 — zamrożenie poprawności

- Dodać odtwarzalny target DLL i build ID eksportowany przez ABI.
- Ustalić golden export oraz zestaw klatek porównawczych dla HUD, FIT, GPMF, mapy, daty/czasu i kolorów bazowego video.
- Zmierzyć oddzielnie decode, HUD render, `tobytes`, HUD memcpy, blend, staging copy, VP wait i AMF.
- Zachować obecny backend A jako zawsze dostępny fallback.

### Etap 1 — usunąć koszty niezmieniające obrazu

- Checkpointy klatki 30 uruchamiać tylko flagą diagnostyczną.
- Usunąć per-frame busy-wait timestamp queries albo odczytywać je asynchronicznie/co N klatek.
- Dla braku HUD całkowicie pominąć `compose_overlay`, HUD copy i `BlendRGBAToNV12`.
- Naprawić retry dla `AMF_INPUT_FULL` i własność powierzchni z puli.
- Nie zmieniać jeszcze algorytmu blendu ani kolorów.

### Etap 2 — GPU HUD przy zachowaniu obecnego decode

- Zachować FFmpeg→CPU NV12→staging jako stabilną bazę.
- Przywrócić trwałą teksturę HUD i dirty-rect upload.
- Najpierw przetestować VP Stream 1 z aktualnym obrazem jako referencją.
- Jeżeli VP ponownie powoduje artefakty alpha/color, użyć kompletnego pixel/compute compositora, nie obecnego niedokończonego shadera.
- Zachować przełącznik natychmiastowego fallbacku do `BlendRGBAToNV12`.

To usuwa CPU blend i pełne native `memcpy` HUD, nie dotykając jeszcze dekodera.

### Etap 3 — przywrócić GPU-resident decode

- Uruchomić istniejący SourceReader/IMFDXGIBuffer jako osobny eksperymentalny backend.
- Zweryfikować prawdziwy format powierzchni P010, subresource index, frame count, timestampy, rotację, cięcia i wiele plików.
- Przepływ docelowy: MF/D3D11VA P010 → VP P010 + HUD Stream 1 → NV12 → AMF.
- Dopiero po pełnym porównaniu obrazu przełączyć produkcję.

To eliminuje FFmpeg software decode, rawvideo pipe, CPU NV12 i staging `CopyResource`.

### Etap 4 — ograniczyć HUD CPU i upload

- Przekazywać dirty rectangles/bounding boxes przez ABI.
- Unikać `Image.tobytes()` pełnego 4K; użyć stabilnego bufora lub atlasu.
- Cache’ować statyczne warstwy, glyphy, map background i niezmienne części wskaźników.
- Ewentualne renderowanie HUD w niższej rozdzielczości wprowadzać dopiero po wizualnym A/B, ponieważ zmieni antyaliasing i geometrię.

Najbezpieczniejsza kolejność to: **diagnostyka i synchronizacja → GPU HUD z obecnym decode → dopiero potem D3D11VA decode**. Pozwala to optymalizować po jednym dużym elemencie, cały czas zachowując obecny poprawny backend CPU jako punkt odniesienia i fallback.
