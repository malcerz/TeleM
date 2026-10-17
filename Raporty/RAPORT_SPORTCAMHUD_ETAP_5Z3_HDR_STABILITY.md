# SPORTCAMHUD — ETAP 5Z.3: stabilizacja HDR (multi-file, anulowanie, ponowienie, metadane)

Data: 2026-10-16. **STATUS: PASS** — wszystkie wymagane scenariusze A–I wykonano na kanonicznym harnessie (`SportCamHUD.py --test-amd-export`), zarówno eksportem bezpośrednim, jak i przez kolejkę. Scenariusz F (metadane) sprawdzono testami celowanymi, w tym z prawdziwym ffprobe na uszkodzonym pliku, oraz na prawdziwych plikach SDR/HLG.

| test | status |
|---|---|
| A. Multi-file HLG → HEVC Main10 (real export) | **PASS** |
| B. Multi-file HLG → SDR BT.709 (real export) | **PASS** |
| C. Anulowanie Main10 (real export) | **PASS** |
| D. Anulowanie tone mappingu (real export) | **PASS** |
| E. Ponowienie (po anulowaniu Main10 / SDR-TM, po błędzie) (real export, kolejka) | **PASS** |
| F. Błędne metadane — fail-closed | **PASS** (testy + prawdziwe pliki; patrz §16) |
| G. Brak regresji SDR | **PASS** (bitstream identyczny) |
| H. Direct Copy Audio | **PASS** |
| I. VBR/QP | **PASS** |
| Kolejka 3 zadań (HDR → SDR → HDR) | **PASS** |
| Podgląd HDR na monitorze SDR | udokumentowano; dodano informację dla użytkownika (§23) |

## 1. Git
- Start: HEAD `a94781f6fe659969a106dc7498134b92995f66b6`. Zastane, nietknięte zmiany: `def_layout.json`, `src/ffmpeg/intel_native_exporter.py`, `src/ffmpeg/nvidia_native_exporter.py`, raport 5R_F. Nieśledzone `src/ffmpeg/live_av_mux.py`, `tests/test_live_av_mux.py`, `runtime/amd/` i `tools/validate_5w_map_gpu.py` — nietknięte.
- Commity etapu:
  - `1875bfb358ea414d9ecec97966b0195e482efd9a` — fix(export): reject uncertain HDR metadata safely
  - `f62331b58be479e785f22cd7832f5368b8136368` — test(amd): validate multi-file HDR cancellation and retry
- Bez reset/clean/stash/rebase/merge/push.

## 2. DLL
`runtime/amd/bin/telem_amd_native.dll` przed i po etapie: `2ceb50cc4d85343237f9aaf6634c7a2d93bb8de1375388166533d71227e0761e` — **UNCHANGED**, ABI 9. Nie było zmian natywnych ani przebudowy. Test R3 (§14) celowo użył starej DLL `5ad042bb…` z kopii zapasowej 5Z.2, wyłącznie przez `TELEM_AMD_NATIVE_DLL` — ta DLL nie była instalowana.

## 3. def_layout.json
`65fa8390d1cda70ed8d115631a75e35559b24b9990e1ca15f944f0fb371606f4` przed i po etapie. Każdy przebieg harnessu raportował `def_layout_unchanged True`.

## 4. Pliki HLG
W `F:\GoPro\<data>\` i `F:\_DEV\BikeRideHUD-amd\Video\` są wyłącznie osobne nagrania GX01xxxx (rozdział 01 każdego filmu), np. GX010361–364, GX010349/350/354, GX010369–371. Nie ma par rozdziałów GX01nnnn/GX02nnnn tego samego nagrania, a sąsiednie pliki dzielą przerwy od minut do godzin. Część nagrań jest w 8K. Użyto więc kanonicznej pary wieloplikowej z BENCHMARKS.md (to kolejne nagrania jednej aktywności):

| plik | wideo | metadane (ffprobe) | klatki | timecode |
|---|---|---|---|---|
| `F:\_DEV\BikeRideHUD-amd\Video\GX010114.MP4` | 3840x2160, 30000/1001, Main 10 | yuv420p10le, pc, bt2020/arib-std-b67/bt2020nc, rot −180 | 58 639 | 11:39:29:06 |
| `F:\_DEV\BikeRideHUD-amd\Video\GX010115.MP4` | jw. | jw. | 17 760 | 13:18:01;07 |
| FIT `GX010114_116.fit` | kanoniczny dla sekwencji 114–116 | | | |

Źródeł nie kopiowano ani nie modyfikowano. Nie powstały pośrednie MP4.

## 5. Zakres przez granicę
- Oś projektu = konkatenacja klipów, granica przy 1956,588 s (nb_frames A = 58 639).
- Harness: `--videos=GX010114.MP4,GX010115.MP4 --start-seconds 1946.588 --frames 600`, czyli 300 ostatnich klatek A i 300 pierwszych klatek B (10 s + 10 s).
- Log eksportera: `[AMD DIRECT MUX] source_switch 1->2 global_frame=300`.

Polecenie (przykład; pełne wywołania w `run/*.stdout.txt`):
```
python Raporty/etap5z3_artifacts/run_5z3_export.py M1_multi_keep --video F:\_DEV\BikeRideHUD-amd\Video\GX010114.MP4 --fit F:\_DEV\BikeRideHUD-amd\Video\GX010114_116.fit --frames 600 --start-seconds 1946.588 --hdr-mode preserve_hlg "--harness-arg=--videos=...GX010114.MP4,...GX010115.MP4"
```

## 6. Multi-file HDR Main10 — **PASS** (`run/M1_multi_keep.*`, `run/M1b_multi_keep.*`)
- Pipeline: `HLG_PRESERVE`, applied=`HLG_PRESERVE`, oba segmenty sklasyfikowane jako HLG full, rot 180.
- MP4: hvcC profil 2 i 10/10 bit; colr nclx 9/18/9 full; yuv420p10le; 74,96% próbek luma nie jest wielokrotnością 4, czyli rzeczywiste 10 bit.
- 600 klatek, 30000/1001, 40,0 Mb/s.

## 7. Multi-file HDR → SDR — **PASS** (`run/M2_multi_tm.*`)
- Pipeline: `HLG_TO_SDR`.
- MP4: Main 8-bit, colr 1/1/1 limited, yuv420p, 600 klatek, 29,97, 39,9 Mb/s.

## 8. Klatki i timestamps (`boundary_check.py`, `run/M*_boundary.json`)
W obu trybach wynik jest identyczny:
- 600 pakietów wideo i 600 zdekodowanych klatek;
- PTS 0 → 19,9866 s, krok 33,3666–33,3667 ms, **0 nieregularnych kroków**;
- **0 kolejnych identycznych klatek**, czyli brak duplikatów.

Dopasowanie klatek wyjścia do źródeł (luma 320×180, źródła autorotowane):

| wyjście | 294 | 295 | 296 | 297 | 298 | 299 | **300** | 301 | 302 | 303 | 304 | 305 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| źródło | A 58633 | A 58634 | A 58635 | A 58636 | A 58637 | **A 58638** (ostatnia) | **B 0** | B 1 | B 2 | B 3 | B 4 | B 5 |

Kolejność klipów jest poprawna, nie ma pominiętej ani zdublowanej klatki na granicy, a rotacja jest poprawna. Skok obrazu między 299 a 300 to naturalna zmiana sceny między nagraniami. MAE 4–7 wynika z HUD nałożonego tylko na wyjście.

## 9. Ciągłość telemetrii (`cmp/M2_boundary_tiles.jpg`, klatki 296/299/300/303)
- Dystans 12,1 km przed i po granicy — brak resetu.
- Mapa kontynuuje trasę, pozycja na pasku dystansu jest ciągła.
- Zmieniają się naturalnie: godzina, bateria kamery (89,24% → 85,71%, inny klip), HR (95 → 78 bpm) i scena — między nagraniami jest ~66 min przerwy w aktywności.
- Wskaźniki pozostają w tych samych pozycjach; PRZECHYŁ, gauge i wykresy są ciągłe.

## 10. AAC na granicy (oba tryby identycznie)
- 938 pakietów wyjścia (469 z A + 469 z B). **Każdy pakiet ma MD5 payloadu identyczne z pakietem źródłowym** (0 nieoryginalnych).
- Pakiety z A są ciągłe; pakiety z B są ciągłe od pakietu 0. Brak powtórzeń.
- Krok PTS 21,333–21,334 ms, bez dziur i bez ciszy; ostatni PTS 19,989 s przy wideo 20,020 s.
- Przełączenie audio na B przy 10,005 s, wideo przy 10,010 s: **−4,67 ms** (mniej niż 1 ramka AAC).
- Plan natywny (log `[AMD AAC PLAN]`):
  - seg 1: `in=1946.588 first_src=1946.581333 packets=469 sync_ms=−6.667 end_residual_ms=−4.667`;
  - seg 2: `first_src=0 packets=469 sync_ms=+4.667 end_residual_ms=−9.333`.
- Udokumentowane korekty: na końcu A pominięty jest ostatni pakiet AAC (jego dodanie przesunęłoby koniec audio poza koniec wideo segmentu). To korekta całopakietowa zgodna z przyjętą polityką z raportu Direct Copy Audio Boundary Fix (pakiet startowy najbliższy czasowi docelowemu, koniec najbliższy końcowi wideo, tolerancja ±1 ramka 21,333 ms). Wszystkie przesunięcia mieszczą się w ±10 ms.

## 11. Anulowanie Main10 — **PASS** (`run/C1_cancel_keep.*`)
- GX020079, 900 klatek, `--cancel-after-frames=90`. Hook wywołuje normalne `RenderTab._on_cancel` (log `[RenderCancel] SET … source=GUI_BUTTON reason=USER_CANCEL frame=90`).
- Przed anulowaniem działały: proces potomny `python.exe`, `ffmpeg.exe`, named pipe `telem_amf_*.h265` i `telem_amf_audio_*.aac`, `.part` 20,2 MB. AMF kodował i FFmpeg odbierał strumienie.
- Zatrzymanie **1,14 s** po żądaniu. Log:
  1. `[AMD CHILD] cancel received reason=USER_CANCEL`
  2. `Export cancelled by user`
  3. `[AMD CANCEL CLEANUP] removed=…mp4.part`
  4. `[AMD CHILD CANCELLED] status=cancelled`
  5. proces potomny `exitcode=0 terminal=cancelled`
  6. sesja logu `status=cancelled`
- Brak komunikatu o sukcesie i brak `render completed`.

## 12. Anulowanie HLG → SDR — **PASS** (`run/C2_cancel_tm.*`)
Ten sam scenariusz z `pipeline=HLG_TO_SDR`: zatrzymanie po 0,80 s, takie same zdarzenia, `.part` usunięty, `exitcode=0`, status `cancelled`.

## 13. Procesy i zasoby po anulowaniu (snapshot 3 s po `render_stopped`, C1/C2/R1/R2)
- Procesy potomne GUI: **brak** (worker i FFmpeg zakończone, nie ma osieroconych).
- Named pipe `telem_amf_*`: **brak**.
- Pliki wyjściowe: tylko log i stdout. `.part` usunięty zgodnie z istniejącą polityką anulowania (`_cleanup_cancelled_amd_outputs`); żaden plik nie udaje ukończonego MP4. Wcześniej istniejący plik użytkownika nie był w tych testach dotykany (polityka `preexisting partial` ma testy w `test_amd_direct_mp4_mux`).
- D3D11, AMF, shadery, tekstury NV12/P010 i bufory HUD należą do procesu potomnego eksportu, a ten zakończył się kodem 0. Kolejny eksport startuje w nowym procesie, z nowym urządzeniem i nowymi pipe’ami (R1/R2: nowe PID i tokeny pipe).
- Brak deadlocku: GUI wróciło do stanu bezczynności, a harness zakończył się sam.

## 14. Ponowienie — **PASS** (kolejka, bez restartu SportCamHUD)
| test | przebieg | wynik |
|---|---|---|
| R1 Main10 | anulowano przy kl. 90 → status `cancelled` → **GUI przestawione na SDR** → `requeue_jobs` → `done` | MP4 Main10 HLG 9/18/9 full, 300 kl., 41,87 FPS; zadanie zachowało `preserve_hlg`, 40M, FAST |
| R2 HLG→SDR | anulowano → GUI przestawione na „Zachowaj HDR” → requeue → `done` | MP4 Main 8-bit 1/1/1, zadanie zachowało `tonemap_sdr` |
| R3 po błędzie | stara DLL (bez HDR) → status `error` z komunikatem „Załadowana biblioteka AMD … nie obsługuje zachowania HDR. Eksport HDR nie został rozpoczęty.” → podmiana DLL → requeue → `done` | MP4 Main10 HLG; walidacja sprzętu wykonana ponownie (`main10_probe=True`), bez cichego fallbacku |

Zakres czasu (300 kl.), HUD (layout 5Y), bitrate i preset zostały zachowane. Po anulowaniu i błędzie nie było starych pipe’ów, procesów ani blokad pliku (snapshoty), a nowy FFmpeg działał z nowym tokenem pipe.

## 15. Kolejka — **PASS** (`run/Q3_queue3*`, 3 zadania dodane z różnymi trybami)
| zadanie | tryb (zamrożony) | pipeline / applied | MP4 | QP | bitrate |
|---|---|---|---|---|---|
| 1 | preserve_hlg | HLG_PRESERVE / HLG_PRESERVE | profil 2, 10-bit, colr 9/18/9 full | 33,6 (18–37), 300 próbek | 38,93 Mb/s |
| 2 | tonemap_sdr | HLG_TO_SDR / HLG_TO_SDR | profil 1, 8-bit, colr 1/1/1 | 33,3 (19–36), 300 | 38,70 Mb/s |
| 3 | preserve_hlg | HLG_PRESERVE / HLG_PRESERVE | jak 1 | jak 1 | 38,93 Mb/s (identyczny z zad. 1) |

- Brak dziedziczenia `AMD_NATIVE_COLOR_PIPELINE` i `AMD_NATIVE_SOURCE_RANGE`: zadanie 3 wróciło do HDR po zadaniu SDR. Każde zadanie ma własny log i statusy `done`, bez zawieszenia po finalizacji.
- FPS zadań (effective): 28,3 / 30,4 / 30,4.
- Zadanie kontrolne SDR w tej samej kolejce nie było możliwe bez zmiany pliku w harnessie (harness dodaje zadania dla jednego projektu). SDR sprawdzono osobno (§17).

## 16. Klasyfikacja błędnych metadanych — fail-closed (**PASS**)
Zmiana: błąd diagnostyki **nie** jest już równoznaczny z SDR.

| przypadek | wynik |
|---|---|
| A. potwierdzony SDR (8-bit bt709, 10-bit bt709/smpte170m, 8-bit bez tagów) | SDR, ścieżka bez zmian |
| B. potwierdzony HLG | dwa tryby |
| C. PQ/HDR10 | jawna odmowa |
| D. 10-bit bez transferu lub z nieznanym transferem | **odmowa** |
| E. sprzeczności (HLG z BT.709, HLG 8-bit, HLG bez macierzy lub zakresu, BT.2020 bez transferu HDR, segmenty o różnych metadanych) | **odmowa** |
| F. błąd ffprobe, timeout, uszkodzony plik, nieznana głębia | ffprobe ponawiany 1×, potem fallback na istniejący pełny probe eksportera tego pliku; bez wiarygodnych danych → **odmowa** |

- Komunikat GUI/błędu: „**Nie można jednoznacznie ustalić formatu HDR nagrania. Eksport wstrzymany, aby uniknąć nieprawidłowych kolorów.** (plik: szczegół)”.
- Log (`[AMD HDR] source …`) podaje rozpoznane wartości, listę brakujących pól i źródło błędu (np. `ffprobe: kod 1: … Invalid data found`, `brak pól: color_transfer`).
- Nie ma ręcznego wymuszania HLG; HLG nie jest wnioskowany z nazwy ani z samej 10-bitowości.

Testy (`tests/test_hdr_export_mode.py`, 33/33):
- brak `color_transfer`, `unknown` transfer, nieznany `color_range`, BT.2020 bez HLG, HLG z BT.709, nieznana głębia (`None/none/unknown`);
- błąd ffprobe (mock, z ponowieniem), timeout, **uszkodzony plik z prawdziwym ffprobe**, fallback na istniejący probe;
- dwa segmenty o różnych metadanych; kompatybilność SDR.

Prawdziwe pliki:

| plik | wynik |
|---|---|
| DJI_0010 | sdr8 |
| DJI 10-bit ×2 (smpte170m) | sdr10 |
| 20261012-0625 | sdr8 |
| GX020079, GX010114 | hlg |
| README.md jako wideo | unknown (odmowa) |
| plik nieistniejący | unknown (odmowa) |

Testy cyklu muxa z atrapowymi mediami dostały fixture z potwierdzonym SDR; `test_amd_direct_mp4_mux` 14/14 i `test_amd_live_mux_audio_finalization` 14/14 przechodzą.

## 17. VBR i QP — **PASS**
We wszystkich eksportach: `rc=VBR target_bitrate=40000000 peak=60000000`, wyjście 38,7–40,0 Mb/s. Sprzętowy QP: 300 próbek na zadanie 300-klatkowe i komplet na 600-klatkowe, `ok=N fail=0`.

SDR kontrolny (`run/S1_SDR_control.*`, DJI_0010): **MD5 wideo `43e50a3206e54a4e52e5459d59c895a5` i audio `1b9e2120932feaf5cad50faffdc66677` — identyczne z bazą 5Z.2 i produkcją sprzed HDR**; pipeline SDR, 39,2 FPS.

## 18. Single Live Mux — **PASS**
Dokładnie jeden proces FFmpeg na eksport:
```
ffmpeg -y -f hevc -r 30000/1001 -bsf:v setts=… -thread_queue_size 512 -i - -thread_queue_size 512 -f aac -i \\.\pipe\telem_amf_audio_<pid>_<token>.aac -map 0:v -map 1:a:0 -t … -c copy -f mp4 <out>.mp4.part
```
- Źródło AAC to oryginalne pakiety przez pipe (`audio=aac_pipe_copy`), `-c copy`.
- Brak audio_cache, M4A, ADTS na dysku, pośredniego MP4 i drugiego remuxu. `.part` → finalny MP4 to istniejąca finalizacja, nie remux.
- Payloady są identyczne ze źródłami (§10).
- `mp4_audio_feed.py` i `live_mux_common.py` nie były zmieniane.

## 19. FFmpeg i finalizacja
- Udane eksporty: `success True`, `[AMD AAC FEED] completed=True`, FFmpeg returncode 0 (`[AMD DIRECT MUX DIAGNOSTICS] returncode=0`), plik końcowy bez `.part`.
- Anulowane: FFmpeg zakończony razem z workerem w ~1 s, `.part` usunięty.
- Komunikat `[in#1/aac] Error during demuxing: Invalid argument` przy zamknięciu pipe występował już w baseline 5Z.2; jest to EOF pipe’a, nie błąd.

## 20. Render FPS i Effective FPS
| przebieg | Render FPS | Effective FPS |
|---|---|---|
| M1 multi Main10 (zimny cache telemetrii wieloplikowej) | 34,32 | 14,35 |
| M1b multi Main10 (powtórka) | **39,80** | 26,36 |
| M2 multi HLG→SDR | **39,26** | 25,46 |
| R1/R2/R3 (300 kl., po ponowieniu) | 41,87 / 41,88 / 41,91 | 15,2 / 15,7 / 19,9 (z czasem anulowania/błędu) |
| Q3 kolejka | 41,61 | 28,3 / 30,4 / 30,4 |
| S1 SDR | 39,16 | 27,68 |

Hot path nie był zmieniany (brak zmian natywnych, kodera i shaderów), więc pełnego benchmarku nie powtarzano; wyniki odpowiadają 5Z.2 (40,8/40,9). Multi-file (39,3–39,8) obejmuje przełączenie źródła i seek. Czas finalizacji nie jest osobno raportowany przez harness — zawiera się w Effective FPS. Transfery CPU↔GPU: bez zmian (0 nowych).

## 21. Zmienione pliki
- `src/ffmpeg/hdr_color.py` — klasyfikacja fail-closed, ponowienie ffprobe, fallback, komunikat.
- `src/ffmpeg/amd_native_exporter.py` — przekazanie istniejącego probe jako fallback.
- `src/gui/qt/tabs/render_tab.py` — informacja o podglądzie HDR oraz pokazywanie ostrzeżenia także dla `unknown`.
- `src/gui/qt/application.py` — hooki testowe harnessu.
- Testy: `tests/test_hdr_export_mode.py`, `tests/test_amd_direct_mp4_mux.py`, `tests/test_amd_live_mux_audio_finalization.py` (fixture).

Narzędzia w `Raporty/etap5z3_artifacts/`: `run_5z3_export.py`, `boundary_check.py`, `patch_*.py` (jednorazowe patche).

## 22. SHA commitów
`1875bfb358ea414d9ecec97966b0195e482efd9a`, `f62331b58be479e785f22cd7832f5368b8136368`.

## 23. Otwarte ryzyka
1. **Brak prawdziwych rozdziałów GoPro (GX01→GX02)** w materiałach. Granicę testowano na kolejnych nagraniach z przerwą. Logika przełączenia jest wspólna, ale ciągły rozdział (bez przerwy w telemetrii) nie był sprawdzony.
2. **Podgląd HDR na monitorze SDR** nadal pokazuje dane HLG bez tone mappingu (tylko macierz i zakres BT.2020). Dodano zdanie informacyjne w etykiecie HLG w zakładce Eksport. Zarządzany kolorem podgląd to osobny etap.
3. **Fail-closed** odrzuca też 10-bitowe pliki bez tagu transferu i pliki SDR BT.2020 (np. nieoznaczone profile log), które wcześniej szły ścieżką SDR. To zamierzone, ale może wymagać decyzji, jeśli takie pliki pojawią się w praktyce.
4. Ścieżka DLL nie jest wypisywana w logu procesu potomnego. Użyta DLL wynika z braku nadpisania, `dll_color_features=0x3` i niezmienionego SHA.
5. Zachowanie polityki `.part` przy anulowaniu (usuwanie) jest istniejące i nie było zmieniane.

## 24. Status testów
Zob. tabela na początku. Wszystkie scenariusze produkcyjne mają artefakty w `Raporty/etap5z3_artifacts/run/` (`*.json` z wynikami harnessu, zdarzeniami i snapshotami procesów, `*.log` log eksportu, `*.stdout.txt`, `*.color.json` metadane MP4, `*_boundary.json` analiza granicy) oraz `cmp/M2_boundary_tiles.jpg`. Duże MP4 usunięto po analizie.

ntfy: wysłane po zapisaniu raportu — HTTP 200, id `x3wbRZQE0PXR`, time 1792141347 (odpowiedź: `Raporty/etap5z3_artifacts/ntfy_response.txt`).
