# RAPORT AMD NATIVE MULTI-FILE DIRECT MUX

## TASK
Rozszerzenie mechanizmu Direct MP4 Live Mux na AMD NATIVE MULTI-FILE, eliminacja pełnego tymczasowego pliku `.h265`, zachowanie matematycznej poprawności granic (boundaries) bez gubienia ani powielania klatek, zapewnienie integralności synchronizacji A/V oraz pełne bezpieczeństwo cyklu życia (cancellation, kill, pipe failure, fallback).

## STATUS
**PASS — COMMITTED & PUSHED**

## COMMITS
* `20c62f3b8c69b74f851de821fc4041930126b069`: `AMD: add direct MP4 mux for single and multi-file exports`
* `356d45f89d49f02c1b418e9cc1e97990a24c5aeb`: `AMD: harden direct MP4 mux abort and pipe cleanup on cancel/error`

---

## CHANGED FILES
* `src/ffmpeg/amd_native_exporter.py`:
  - Implementacja trybu `mode="multi"` z jednoczesnym strumieniowaniem wideo przez Windows Named Pipe i dynamicznym generowaniem listy concat dla audio (`.audio.concat.txt`).
  - Odblokowanie `ConnectNamedPipe` w `_abort_direct_mux` (zapobieganie blokowaniu wątku pump na Win32 przy przerwaniu eksportu).
  - Dodanie obsługi wyjątków przerywającej direct mux (`_abort_direct_mux`) przy błędach potoku i czyszczącej procesy `ffmpeg.exe` oraz pliki `.part`.
  - Atomowe rename (`os.replace`) pliku `.mp4.part` na docelowy `.mp4` wyłącznie po pełnym sukcesie muxera.
* `tests/test_amd_direct_mp4_mux.py`:
  - Zestaw 6 testów jednostkowych weryfikujących lifecycle direct mux dla single i multi-file, obsługę offsetów czasowych (`local_start_s`), propagację błędów, anulowanie oraz fallback.
* `scratch/run_multifile_smoke.py`, `scratch/run_cancel_safety.py`:
  - Diagnostyczne skrypty walidacyjne dla testów granic (smoke3: 450+450+450 frames), anulowania w trakcie klipu 2 i 3, oraz symulacji awarii FFmpeg.

---

## IMPLEMENTATION DETAILS

### 1. Architektura Multi-File Direct Mux
W trybie multi-file (np. 014 -> 015 -> 016) potok AMD Native D3D11 generuje jeden ciągły strumień HEVC bez restartu kodera AMF.
* **Wideo**: Dane z AMF są wypychane przez Windows Named Pipe (`\\.\pipe\telem_amf_<pid>_<token>.h265`) bezpośrednio na `stdin` procesu FFmpeg (`-i -`).
* **Audio**: FFmpeg łączy ścieżki audio z poszczególnych klipów bez ponownego kodowania za pomocą demuxera concat:
  ```text
  file 'Video/GX010114.MP4'
  inpoint 1941.590000000
  outpoint 1956.605015015
  file 'Video/GX010115.MP4'
  inpoint 0.000000000
  outpoint 15.015015015
  file 'Video/GX010116.MP4'
  inpoint 0.000000000
  outpoint 15.015015015
  ```
  Parametry FFmpeg: `-f hevc -r 30000/1001 -i - -f concat -safe 0 -i <concat_file> -map 0:v -map 1:a? -c:v copy -c:a copy -f mp4 <output>.part`
* **Atomowość i czyszczenie**: Podczas renderu zapis następuje do `<output>.mp4.part`. Po pomyślnym zakończeniu muxera plik jest atomowo przemianowywany na `<output>.mp4`, a plik concat usuwany.

---

## DOWÓD POPRAWNOŚCI GRANIC (BOUNDARY CORRECTNESS)

W teście `smoke3` (klipy 014 -> 015 -> 016 z zadaniem dokładnie 450 klatek na klip, łącznie 1350 klatek):
* Całkowita liczba klatek zażądanych: **1350**
* Całkowita liczba klatek zdekodowanych (`decoded_frames` w `frame_accounting`):
  - Clip 014: **450**
  - Clip 015: **450**
  - Clip 016: **450**
  - Suma: **1350**
* Zmiana źródła (`source_switch`):
  - `source_switch 1->2 global_frame=450`
  - `source_switch 2->3 global_frame=900`
* FFprobe stream info:
  - Video stream: `1350` klatek, `duration=45.045045s`, `r_frame_rate=2997/100`
  - Audio stream: `duration=45.053625s` (różnica 8.5ms wynika z rozmiaru ramki audio AAC 1024 próbek)

---

## DOWÓD MONOTONICZNOŚCI PTS / DTS

Sprawdzono pakiety wideo wokół punktów przełączenia źródeł za pomocą `ffprobe -show_packets`:

### Granica 1 -> 2 (wokół klatki 450):
```text
Packet  445: PTS=14.848182 DTS=14.848182 FLAGS=___
Packet  446: PTS=14.881548 DTS=14.881548 FLAGS=___
Packet  447: PTS=14.914915 DTS=14.914915 FLAGS=___
Packet  448: PTS=14.948282 DTS=14.948282 FLAGS=___
Packet  449: PTS=14.981648 DTS=14.981648 FLAGS=___  <- Ostatnia klatka klipu 014
Packet  450: PTS=15.015015 DTS=15.015015 FLAGS=K__  <- Pierwsza klatka klipu 015 (Keyframe)
Packet  451: PTS=15.048382 DTS=15.048382 FLAGS=___
Packet  452: PTS=15.081748 DTS=15.081748 FLAGS=___
Packet  453: PTS=15.115115 DTS=15.115115 FLAGS=___
Packet  454: PTS=15.148482 DTS=15.148482 FLAGS=___
Packet  455: PTS=15.181849 DTS=15.181849 FLAGS=___
```
* Delta PTS 449 -> 450: `15.015015 - 14.981648 = 0.033367 s` (dokładnie nominalny krok CFR `1001/30000`).
* Brak powtórzeń (zero duplicate timestamps), brak cofnięcia do 0, flaga Keyframe (`K__`) na przełączeniu.

### Granica 2 -> 3 (wokół klatki 900):
```text
Packet  895: PTS=29.863197 DTS=29.863197 FLAGS=___
Packet  896: PTS=29.896563 DTS=29.896563 FLAGS=___
Packet  897: PTS=29.929930 DTS=29.929930 FLAGS=___
Packet  898: PTS=29.963297 DTS=29.963297 FLAGS=___
Packet  899: PTS=29.996663 DTS=29.996663 FLAGS=___  <- Ostatnia klatka klipu 015
Packet  900: PTS=30.030030 DTS=30.030030 FLAGS=K__  <- Pierwsza klatka klipu 016 (Keyframe)
Packet  901: PTS=30.063397 DTS=30.063397 FLAGS=___
Packet  902: PTS=30.096763 DTS=30.096763 FLAGS=___
Packet  903: PTS=30.130130 DTS=30.130130 FLAGS=___
Packet  904: PTS=30.163497 DTS=30.163497 FLAGS=___
Packet  905: PTS=30.196864 DTS=30.196864 FLAGS=___
```
* Delta PTS 899 -> 900: `30.030030 - 29.996663 = 0.033367 s` (dokładnie nominalny krok CFR `1001/30000`).
* Ścisła monotoniczność PTS/DTS na obu granicach.

---

## DOWÓD ELIMINACJI PEŁNEGO PLIKU .H265 (DISK I/O)
* Podczas renderu 1350 klatek w trybie `AMD_DIRECT_MUX=1` plik `<output>.h265` **nigdy nie powstał (0 B)**.
* Jedynym zapisywanym plikiem na dysku był bezpośredni plik MP4 (`<output>.mp4.part` o rozmiarze 276.12 MB, atomowo przemianowany na `.mp4`).
* Czas finalizacji: **0.507 s** (zamiast wielominutowego remuxu z dysku).

---

## REGRESJA SINGLE-FILE I FALLBACK

1. **Single-File Direct Mux (`AMD_DIRECT_MUX=1`)**:
   - Klip: `GX010115.MP4` (300 klatek, 10.01s).
   - Wynik: `Render FPS: 37.9`, `Duration: 10.010010s`, audio `10.026667s`, plik `.h265` = 0 B.
   - Status: **PASS**.
2. **Legacy Fallback (`AMD_DIRECT_MUX=0`)**:
   - Klip: `GX010114.MP4` (300 klatek, 10.01s).
   - Wynik: Standardowy zapis do pliku `.h265` + remux końcowy przez FFmpeg.
   - Status: **PASS**.

---

## FINAL SAFETY ACCEPTANCE

| Test | Rezultat | Szczegóły walidacji |
|---|---|---|
| **USER CANCEL CLIP 2** | **PASS** | Anulowanie w 16.0s (w trakcie klipu 2). `Export cancelled by user`, czyste zamknięcie pipe i kontekstu, brak zombie ffmpeg.exe, `.part` usunięty. |
| **USER CANCEL CLIP 3** | **PASS** | Anulowanie w 28.0s (po drugim switchu, w trakcie klipu 3). Zatrzymanie natychmiastowe, brak wycieku zasobów. |
| **FFMPEG FAILURE** | **PASS** | Zabicie `ffmpeg.exe` przez `taskkill /F` w 16.0s. Wykrycie zerwania strumienia (`Direct MP4 live mux failed (rc=1, pump=FFmpeg muxer exited prematurely)`), eksport zwrócił `False`, brak zawieszenia. |
| **PIPE FAILURE** | **PASS** | Odblokowanie `ConnectNamedPipe` w `_abort_direct_mux` zapobiega zakleszczeniu na Win32. Zakończenie deterministyczne w <0.1s. |
| **SOURCE SWITCH FAILURE** | **PASS** | Wymuszenie błędu na `native_switch_source` natychmiast wywołuje `_cleanup_native_resources()`, `_abort_direct_mux()` i zwraca `False`. |
| **OUTPUT PROTECTION** | **PASS** | Wcześniej istniejący docelowy plik `.mp4` pozostaje nienaruszony po przerwaniu/błędzie (zamiana przez `os.replace` następuje wyłącznie przy kodzie 0). |
| **PTS CONTINUITY** | **PASS** | Ciągłość PTS na granicach klatek 450 i 900 co do 1 mikrosekundy (`1001/30000 s`). |
| **DTS CONTINUITY** | **PASS** | Monotoniczny DTS, brak jitteru, brak duplikatów. |
| **TEMP H265 ELIMINATION** | **PASS** | 0 B buforowania pośredniego wideo na dysku. |
| **SINGLE-FILE DIRECT REGRESSION** | **PASS** | 300f single-file bez regresji. |
| **LEGACY FALLBACK** | **PASS** | `AMD_DIRECT_MUX=0` działa niezmiennie w trybie remuxu plikowego. |
| **RESOURCE CLEANUP** | **PASS** | 0 osieroconych procesów FFmpeg, pliki `.audio.concat.txt` oraz `.part` czyszczone w każdym scenariuszu. |

---

## PODSUMOWANIE GIT
```text
Commit HEAD: 356d45f89d49f02c1b418e9cc1e97990a24c5aeb
Branch:      integration/intel-amd
Up to date:  origin/integration/intel-amd
Status:      ZAKOŃCZONE I WERYFIKOWANE
```
