# SportCamHUD Intel — naprawa flush enkodera i utraty ostatniej klatki, 2026-10-19

STATUS: naprawione i zweryfikowane. VIDEO_ONLY 5/5 → 1800/1800 klatek (wcześniej 4/4 → 1799). Wszystkie eksporty macierzy testów mają komplet klatek i ostatnią klatkę. Bitstream dla niezmienionych danych wejściowych identyczny; jedyna różnica to odzyskana ostatnia klatka w VIDEO_ONLY. Push: nie wykonano.

## 0. Stan początkowy

- `main`, HEAD `5aab023`. Przeczytano AGENTS.md, `RAPORT_INTEL_C_R3_HANG_AND_VIDEO_ONLY_1799_20261019.md`, `RAPORT_INTEL_QSV_AC_BENCHMARK_STABILITY_20261019.md`.
- Prywatne zmiany użytkownika i nieśledzone pliki (`def_layout.json`, `C`, font, kopie `.bak`, raport root, raport i katalogi `C_r31…36` sesji diagnostycznej) — nietknięte, poza commitem.
- Zasilanie: `PowerLineStatus=Online`, narzędzie z `--require-ac` w każdym przebiegu.

## 1. Rzeczywisty status kończący flush przedwcześnie

Build wyłącznie diagnostyczny (logowanie każdego wywołania flush, bez zmiany zachowania), VIDEO_ONLY ×2 i B ×1:

```text
VIDEO_ONLY r71: [INTEL FLUSH DIAG] entry decoded=1800 submitted=1799 encoded=1791 pending=8 more_data=1 busy=0
                [INTEL FLUSH DIAG] call=1 status=2 syncp=NO pending=8 encoded=1791      -> pętla przerwana, MP4: 1799
VIDEO_ONLY r72: identycznie (status=2, pending=8)                                       -> MP4: 1799
B r71:          entry decoded=1800 submitted=1799 encoded=1799 pending=0 more_data=1
                call=1 status=0 syncp=YES   call=2 status=-10 syncp=NO                  -> MP4: 1800
```

`status=2` = **`MFX_WRN_DEVICE_BUSY`** (`mfxdefs.h`: `MFX_WRN_DEVICE_BUSY = 2`); `-10` = `MFX_ERR_MORE_DATA`.

## 2. Przyczyna

- Pierwsze `EncodeFrameAsync` zwraca `MFX_ERR_MORE_DATA` — enkoder buforuje 1 klatkę (`submitted=1799`, `more_data=1`). Ta klatka wychodzi dopiero przy flushu `EncodeFrameAsync(NULL)`.
- Stara pętla flush w `intel_native_pipeline_finish` kończyła się przy każdym statusie innym niż `MFX_ERR_NONE` z syncpointem. W VIDEO_ONLY `finish()` jest wołany tuż po ostatnim kroku, gdy w enkoderze jest 8 zaległych zadań (AsyncDepth 8). Sprzętowa kolejka jest pełna, flush dostaje przejściowe `MFX_WRN_DEVICE_BUSY` i pętla kończy się bez buforowanej klatki.
- W eksporcie z HUD/pustym layoutem zamykanie workerów HUD daje wątkowi drain czas na zsynchronizowanie zaległych ramek (`pending=0`), więc flush trafia na `MFX_ERR_NONE`. Poprawność produkcji zależała więc od czasu, nie od kontraktu.
- Przy przeglądzie wszystkich produkcyjnych wywołań `EncodeFrameAsync` (krok l. ~2444, flush l. ~2548; pozostałe 4 wywołania są w funkcjach pomiarowych `intel_native_measure_*`, nieużywanych w eksporcie) znaleziono dalsze słabości z tej samej klasy:
  - krok: po 500 próbach `DEVICE_BUSY` (≈ 0.4 s) albo przy innym błędzie ujemnym powierzchnia była zwalniana, a funkcja zwracała 0 — klatka mogła zniknąć po cichu;
  - drain: wynik `SyncOperation` był ignorowany;
  - `finish`: czekał na wątek drain maks. 10 s, potem zamykał wyjście niezależnie od stanu, i zawsze zwracał 0; Python ignorował wynik.

## 3. Poprawka (wyłącznie `src/native/intel` + jedno miejsce w eksporterze Intel)

`src/native/intel/d3d11_intel_pipeline/telem_intel_native.c`:
- **Flush:** `EncodeFrameAsync(NULL)` w pętli, aż do `MFX_ERR_MORE_DATA` (koniec danych zgodnie z kontraktem oneVPL).
  - `MFX_WRN_DEVICE_BUSY` → czekanie na zwolnienie slotu przez wątek drain (`SleepConditionVariableCS(cvEncodeFree, 1 ms)`) i ponowienie.
  - Status ≥ 0 z syncpointem → wyjście kolejkowane do wątku drain (jak dotąd).
  - Każdy inny status (także `NONE` bez syncpointu) → prawdziwy błąd.
  - Twardy limit 30 s, bez stałego `Sleep(1000)`, bez nieskończonej pętli. Przy anulowaniu flush jest pomijany.
- **Drain:** wynik `SyncOperation` zliczany (`sync_errors`, `last_sync_status`) w wątku drain i w `sync_oldest_encode_slot`. `finish` czeka na wątek drain do 30 s; po przekroczeniu wymusza zakończenie, oznacza `drain_timeout` i zgłasza błąd.
- **Kontrola końcowa:** liczba zakodowanych bitstreamów musi równać się liczbie wejść zaakceptowanych przez enkoder (`MFX_ERR_NONE` + `MFX_ERR_MORE_DATA`). `finish` zwraca 0 albo −50 (błąd flush/sync), −51 (zaakceptowana klatka bez bitstreamu), −52 (timeout drain); przy anulowaniu 0.
- **Krok:** `DEVICE_BUSY` ponawiane z limitem czasu 5 s (ta sama pętla co dotąd, tylko z limitem czasu zamiast 500 prób). Niezaakceptowana klatka (busy po limicie albo błąd ujemny inny niż `MORE_DATA`) jest logowana `[INTEL ENCODE] EncodeFrameAsync rejected …` i zwraca −6 zamiast 0. Wyjście z ostrzeżeniem ≥ 0 i syncpointem jest traktowane jak wyjście.
- **Diagnostyka:** stała linia logu `[INTEL FLUSH] end_status outputs busy_retries accepted encoded sync_errors drain_timeout cancelled ms rc`. `IntelStageTiming` rozszerzone o pola flush (osobny eksport, 80 B; ABI `IntelNativePipelineStats` 752 B bez zmian).
- Kolejność zwalniania powierzchni bez zmian: powierzchnia wejściowa jest zwalniana po `EncodeFrameAsync` (enkoder trzyma własną referencję), sesja zamykana po zakończeniu wątku drain.

`src/ffmpeg/intel_native_exporter.py`:
- wynik `intel_native_pipeline_finish()` jest sprawdzany; niezerowy (poza anulowaniem) → `IntelNativeFinalizationError` z liczbą klatek zakodowanych/zdekodowanych. Wcześniej był ignorowany;
- w podsumowaniu linia `Encoder Flush: accepted encoded flushed busy_retries end_status ok sync_errors ms`.

Nie zmieniano: presetów Fast/Balanced/Quality, VBR/VBV/HRD, HLG/HDR, TargetUsage, GOP, AsyncDepth, mapy, HUD, SmartSync, GUI, AMD/NVIDIA, live mux audio. QP nie przywracano.

DLL: `runtime/intel/bin/telem_intel_native.dll` SHA256 `dafa1b9b42dc2af1df23411d5e5d9f9e66556512a3130eb5794e7483cc29c14c` (247808 B), źródło `fc44271a1e86…`, ten sam LLVM-MinGW/FFmpeg/oneVPL i flagi co w `5896e38`. Manifest: `intel_qsv_pipeline_20261019/intel_native_flushfix_build_manifest.json`. Hash i rozmiar zaktualizowane w `runtime/runtime_manifest.json` i `tools/build_portable_release.py`. Poprzednia DLL: `telem_intel_native.dll.bak_before_flush_fix_20261019` (nieśledzona).

## 4–6. Liczniki, klatki MP4, testy wielokrotne

Każde MP4 sprawdzone nowym `tools/check_intel_export_mp4.py` (pakiety ffprobe): liczba klatek, brak duplikatów, ciągłe PTS (krok 1001 @ 1/30000), ostatnia klatka na oczekiwanym PTS, długość, obecność audio, A/V < 0.1 s. Wynik `mp4_check.json` w katalogu każdego przebiegu.

| Test | Przebiegi | decoded / accepted / encoded | Flush (końcowy status, odzyskane, BUSY) | Klatki MP4 | Kontrola pakietów |
|---|---|---|---|---|---|
| A. VIDEO_ONLY 1800, stara DLL (diag) | 2 (+B0_r0 i 3 z sesji diagnostycznej) | 1800 / – / 1791→1799 | status=2 → przerwany | **1799** | FAIL (brak ostatniej klatki, PTS 1799798 zamiast 1800799) |
| A. VIDEO_ONLY 1800, nowa DLL | **5** | 1800 / 1800 / 1800 | −10, 1, BUSY 1–2× | **1800** ×5 | 5/5 OK |
| B. Native bez HUD 1800 | 3 | 1800 / 1800 / 1800 | −10, 1, BUSY 0 | 1800 ×3 | 3/3 OK |
| C. Native pełny HUD 1800 | 3 (+1 na DLL zainstalowanej w runtime) | 1800 / 1800 / 1800 | −10, 1, BUSY 0 | 1800 ×4 | 4/4 OK |
| D. Kolejka, pełny HUD, 300 | 3 | 300 / 300 / 300 | −10, 1, 0 | 300 ×3 | 3/3 OK |
| E. Anulowanie (GUI Cancel po 150) | 3 | 151 / 151 / 143 | flush pominięty (`cancelled=1`), rc=0 | brak pliku (poprawnie odrzucony) | n/d |
| F. Krótkie, pełny HUD | 1, 2, 3, 30, 60 klatek | n / n / n | −10, 1, 0 | 1, 2, 3, 30, 60 | 5/5 OK |
| F. Krótkie, VIDEO_ONLY | 1, 2, 3, 30, 60 klatek | n / n / n | −10, 1, BUSY 0–2× | 1, 2, 3, 30, 60 | 5/5 OK |
| G. H.264 1800, pełny HUD / VIDEO_ONLY | 1 + 1 | 1800 / 1800 / 1800 | −10, 1, BUSY 0 / 1 | 1800 / 1800 | 2/2 OK (H.264 High, yuv420p, BT.709) |
| G. HEVC Main10 | wszystkie powyższe | – | – | – | Main 10, yuv420p10le, HLG |
| Macierz jakości (native/FFmpeg × HEVC/H.264 × Fast/Balanced/Quality, 60) | 12 | – | – | 60 ×12 | 12/12 PASS |
| Python Portable 3.14.7, pełny HUD, 300 | 1 | 300 / 300 / 300 | −10, 1, 0 | 300 | OK |

- Liczba odzyskanych przy flushu klatek zawsze wynosi 1 — to klatka zbuforowana przy pierwszym `MORE_DATA`.
- Stara DLL dla 1 i 3 klatek w VIDEO_ONLY dawała poprawny wynik: błąd wymaga zapełnionej kolejki enkodera (8 zadań w locie), którą mają tylko dłuższe eksporty.
- Anulowanie: zaakceptowane 151, zakodowane 143 — 8 zadań w locie celowo porzuconych, częściowy plik nie powstaje, `success=NO (cancelled)`. To prawidłowa utrata częściowego pliku, nie błąd finalizacji.
- Wątki, powierzchnie i SharedMemory:
  - harness po każdym eksporcie sprawdza brak wątków `IntelPipeForwarder` (`pipe_forwarders_after_export=[]`);
  - blok SharedMemory zwolniony (`released=YES`) we wszystkich eksportach z HUD, także anulowanych; VIDEO_ONLY nie tworzy workerów ani bloku;
  - zawieszenia, przerwy w próbkowaniu i zadziałania watchdoga: 0 we wszystkich eksportach;
  - liczników powierzchni D3D11/oneVPL po sesji nie da się odczytać z zewnątrz: NOT TESTED bezpośrednio. Sesja jest zamykana dopiero po zakończeniu wątku drain, a kolejne eksporty w tych samych testach działają poprawnie.

## 7. Wpływ na finalizację i FPS

Para naprzemienna ×3, pełny HUD, 1800 klatek, ten sam stan zasilania (platforma w limicie mocy po wcześniejszych przebiegach, jak opisano w raporcie AC):

| DLL | Render FPS | Mediana | Finalizacja |
|---|---|---|---|
| przed (`1eb0f478`) | 41.38, 40.23, 37.46 | 40.23 | 0.37–0.77 s |
| po (`dafa1b9b`) | 36.55, 42.04, 41.37 | 41.37 | 0.33–0.41 s |

- Bez mierzalnego pogorszenia przepustowości (różnica w granicach rozrzutu warunków).
- Czas flush+drain (`[INTEL FLUSH] ms`): 0.4–159 ms; VIDEO_ONLY ~130–145 ms, bo teraz faktycznie czeka na zaległe zadania, zamiast je zgubić.
- Pojedynczy kontrolny przebieg C na DLL z runtime: 35.98 FPS (platforma w limicie mocy), 1800/1800.

## 8. Live mux audio i bitstream

- Audio nadal muksowane na żywo z oryginalnego MP4 (`audio_live_mux=True`), bez `ensure_audio_cache` i plików pośrednich. A/V < 0.1 s we wszystkich kontrolach pakietów; SHA256 pakietów audio pełnego HUD `d7acdb75…` identyczny jak przed poprawką.
- Wideo, pełny HUD: SHA256 `fbbd3c0bc71a812d…` — identyczny przed i po (stara DLL, nowa DLL kandydat, DLL zainstalowana).
- Wideo, bez HUD: `335f40b561c1dfdd…` — identyczny przed i po.
- VIDEO_ONLY po poprawce ma ten sam bitstream co bez HUD (`335f40b5…`, 1800 pakietów). Pierwsze 1799 pakietów (framemd5) jest identyczne ze starym wynikiem 1799-klatkowym — jedyna zmiana to odzyskana ostatnia klatka.
- Średnie bitrate macierzy jakości identyczne co do 0.01 Mb/s z macierzą sprzed poprawki.

## 9. Testy regresyjne

- Testy celowane (Intel ×42 pliki, w tym nowy `test_intel_encoder_flush_contract.py`, SHM, izolacja runtime, SmartSync, presety, capability, async, live mux, testy QP AMD/wspólne): **362 passed, 7 skipped, 0 failed** (`intel_qsv_pipeline_20261019/pytest_targeted_flushfix.log`).
- Nowe testy: `tests/test_intel_encoder_flush_contract.py` (6 — kontrakt flush/kroku/sync w źródle, obsługa kodu zwrotnego w eksporterze, `finish()` bez potoku na zainstalowanej DLL) oraz zaktualizowany `test_intel_hud_init_blob.py` (struktura 80 B).
- Macierz jakości 12/12, Python Portable 3.14.7 PASS.
- Znane, poza zakresem: 7 testów ścieżek eksportu w `test_export_gpmf_and_qp_summary.py` zależnych od nieistniejących tu `D:\Video` / `E:\Exports` (bez zmian względem poprzedniego raportu).
- NOT TESTED: AMD/NVIDIA (brak sprzętu; zmiany wyłącznie w Intel DLL i w eksporterze Intel), eksport wieloplikowy (brak kanonicznego zestawu), ręczne GUI, liczniki powierzchni D3D11 po sesji, ścieżka `-50/-51/-52` na prawdziwym błędzie sprzętu (nie dało się wywołać błędu enkodera; zweryfikowana testem kontraktu źródła).

## 10. Commit

Lokalny commit na `main` — SHA w odpowiedzi końcowej. Bez push. Dowody: `Raporty/intel_qsv_pipeline_20261019/` (`cand_B0_r71`, `cand_B0_r72`, `cand_B_r71` — diagnostyka; `B0_TR_r81–85`, `B_TR_r81–83`, `C_r81–83`, `C_TR_r81–83`, `C_TR_Q_r91–93`, `C_TR_CANCEL_r91–93`, `C_TR_r101–160`, `B0_TR_r101–160`, `C_TR_H264_r95`, `B0_TR_H264_r95`, `B0_r201`, `B0_r203`, `C_r99`, `quality_matrix_flushfix`, `portable314_flushfix`, `flush_matrix_summary_20261019.json`). Pliki MP4 nie są w Git.

## Podsumowanie

| Kryterium | Wynik |
|---|---|
| Rzeczywisty status potwierdzony logiem | PASS — `MFX_WRN_DEVICE_BUSY (2)` przy 8 zaległych zadaniach |
| VIDEO_ONLY 1800 ×5 | PASS 5/5 (1800) |
| B ×3, C ×3, kolejka ×3 | PASS |
| Anulowanie bez deadlocka | PASS 3/3 |
| Krótkie 1/2/3/30/60, H.264 i HEVC Main10 | PASS |
| Ciągłość PTS, brak duplikatów, ostatnia klatka, długość, A/V | PASS we wszystkich niezanulowanych eksportach |
| Bitstream bez zmian (poza odzyskaną klatką) | PASS |
| Przepustowość i finalizacja | bez pogorszenia (para ×3) |
| Prawdziwy błąd enkodera zgłaszany | zaimplementowane; NOT TESTED na rzeczywistym błędzie sprzętu |
| AMD/NVIDIA, wieloplikowy | NOT TESTED |
