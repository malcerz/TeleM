# Kontrola live AV mux (14.10.2026)

Źródła sprawdzone na plikach pobranych z `C:\_DEV\BikeRideHUD-main-new` o 18:36. Były identyczne z wersją zapisaną wcześniej, bez cudzych zmian. `def_layout.json` i pozostałe niezacommitowane pliki nie były ruszane. Nie wykonywałem żadnych operacji git.

## 1. Trzy zagrożenia: potwierdzone

Numery linii dotyczą `src/ffmpeg/live_av_mux.py` w wersji sprzed tej poprawki.

| # | Zagrożenie | Gdzie | Status |
|---|---|---|---|
| 1 | Wiele plików: `filter_complex concat` + `-c:a aac -b:a 256k`, czyli ponowna kompresja | l. 242–246 | **potwierdzone**, nadal tak jest (patrz punkt 3) |
| 2 | Błąd ffprobe traktowany jak brak audio (`except Exception: pass` → `return False`) | l. 132–153 | **potwierdzone, naprawione dla AMD** |
| 3 | Brak obsługi `-bsf` na wejściu → tylko ostrzeżenie i powrót do wejścia bez znaczników czasu | l. 103–109 | **potwierdzone, naprawione dla AMD multi-file** |

## 2. Co zmieniłem teraz (tylko AMD)

- Nowy wyjątek `LiveMuxConfigError`.
- Nowa funkcja `probe_audio_present()`, która rozróżnia brak strumienia audio (zwraca `False`) od błędu ffprobe (rc≠0, timeout, brak programu, zły JSON: wyjątek).
- `build_live_audio_inputs(..., strict=True)` używa tej funkcji. W trybie strict nieznana długość klipu bez dźwięku też jest błędem, a nie ciszą o długości 0 s.
- `raw_video_timestamp_args(..., required=True)` zgłasza błąd, gdy FFmpeg nie obsługuje `-bsf` na wejściu.
- `amd_native_exporter.py`: `required=is_multi_file`, `strict=True`. Błąd zamyka potok i kończy się `AMDNativeFinalizationError("AMD live A/V mux setup failed: …")`, bez przejścia na inną konfigurację.
- **Single-file bez zmian w działaniu:** jeden fragment nie jest sprawdzany przez ffprobe (mapowanie `1:a:0?`, `-c:a copy`), a `setts` jest dodawany, jeśli FFmpeg go obsługuje, bez wymuszania.
- **Intel i NVIDIA bez zmian:** wywołują helper z domyślnymi `strict=False` i `required=False`, więc działają jak dotąd.

Diff: `zmiany-2-jawne-bledy.diff`.

## 3. Bezstratne AAC bez czytania wideo 4K: da się, ale to zmiana architektury

Sprawdzone ślepe uliczki:
- `-discard:v all` przed `-f concat` nic nie daje: demuxer concat nadal czyta całe pliki (test: 278 MB).
- Filtrów nie da się połączyć ze stream copy, więc samo `filter_complex` zawsze oznacza ponowne kodowanie.

**Opcja A, przetestowana: drugi potok ADTS.** Wątek w Pythonie uruchamia kolejno dla każdego fragmentu `ffmpeg -ss S -t T -i klip.mp4 -map 0:a:0 -c:a copy -f adts pipe:1` i przepisuje wyjście do drugiego named pipe. Główny mux czyta go jako `-f aac -i \\.\pipe\…_audio` z `-c:a copy`. Nie powstaje żaden plik ani drugi remuks.

Wynik testu (FFmpeg master, 2 źródła 60 Mb/s, wideo podawane w tempie kodera, `setts` na wideo):
- 1594 z 1594 pakietów AAC w wyniku jest bit w bit identycznych ze źródłem (porównanie MD5 pakietów),
- 100% pakietów audio odczytanych w trakcie podawania wideo, finalizacja 0,0 s,
- procesy podające przeczytały 36,8 MB ze źródeł (zamiast 278 MB przez concat),
- długość: wideo 34,0006 s, audio 34,0053 s.

Koszty i ryzyka opcji A:
- Drugi named pipe i wątek podający plus po jednym krótkotrwałym procesie ffmpeg na fragment. Trzeba je ubijać przy anulowaniu, a ich błędy przekazywać dalej (w teście przy `-t` główny mux zamyka potok i wątek dostaje BrokenPipe, co trzeba obsłużyć jako normalne zakończenie).
- Cięcie z dokładnością do ramki AAC (21,3 ms) na każdej granicy fragmentu, tak jak przy dawnym `concat`. ADTS nie przenosi edit-listy ani opóźnienia enkodera ze źródła, więc możliwy jest stały offset rzędu jednej ramki na granicy klipu.
- Klip bez dźwięku wymaga osobnego obsłużenia: wstawienia ramek ciszy AAC w ADTS albo powrotu do kodowania.

**Opcja B, nietestowana: czytnik MP4 w Pythonie.** Python czyta tablice próbek (`stco`/`stsz`/`stts`) ścieżki audio, pobiera z pliku tylko pakiety AAC i podaje je jako ADTS do drugiego potoku. Daje to samo co A, bez procesów podających, ale wymaga więcej własnego kodu do parsowania MP4.

**Opcja C, obecna: filtr concat + AAC 256 kb/s.** Najprostsza, z cięciem dokładnym co do próbki, ale stratna.

Zgodnie z poleceniem zatrzymałem się przed implementacją A lub B. Rekomenduję A.

## 4. Dokładna komenda multi-file (AMD, po tej poprawce)

Parametry z Twojego logu, ścieżki GoPro przykładowe:

```
ffmpeg.exe -y -f hevc -r 30000/1001 -bsf:v setts=ts=N*1001/30000/TB:duration=1001/30000/TB -thread_queue_size 512 -i - -thread_queue_size 512 -i E:\DCIM\100GOPRO\GX010123.MP4 -thread_queue_size 512 -i E:\DCIM\100GOPRO\GX020123.MP4 -map 0:v -filter_complex "[1:a:0][2:a:0]concat=n=2:v=0:a=1[aout]" -map "[aout]" -t 1244.076167 -c:v copy -c:a aac -b:a 256k -f mp4 a:\20260827-1505.mp4.part
```

Przy przycięciach przed `-i` dochodzą `-t <długość>` i `-ss <start>` dla danego fragmentu. Inline GPMF, jeśli włączony, jest kolejnym wejściem (indeks 3).

- **AAC:** dekodowane z każdego fragmentu (demuxer MP4 pomija próbki wideo), łączone filtrem concat, kodowane ponownie do AAC 256 kb/s. Przy jednym pliku pakiety są kopiowane bez zmian.
- **DTS/PTS wideo:** generowane na wejściu przez `setts`: `pts = dts = N · 1001/30000 s`, w podstawie czasu demuxera (1/1 200 000), czyli 40 040 jednostek na klatkę, plus `duration` tyle samo. Zakłada to brak ramek B. AMF HEVC ich nie ustawia, NVENC ma `b_frames=0`, QSV `GopRefDist=1`. Dla AMF H.264 nie znalazłem jawnego wyłączenia ramek B (do sprawdzenia, jeśli używasz H.264).
- **DTS/PTS audio:** z demuxera MP4 (`-ss` z dokładnym przewijaniem), dalej ciągłe z liczby próbek po filtrze concat.

## 5. Ryzyka dla innych backendów

- **NVIDIA:** wywołuje `"ffmpeg"` z PATH, nie z `runtime\common\ffmpeg`. Starsza wersja z PATH oznacza po cichu brak `setts` (tryb niestrict), czyli powrót problemu. Bez osobnej weryfikacji nie zmieniałem.
- **Intel:** używa całych klipów od początku (tak jak natywny dekoder) i `-t`. AV1 idzie w IVF, który ma własne znaczniki czasu, więc `setts` go nie dotyczy. Błąd ffprobe nadal oznacza tam „brak audio”.
- **Wszystkie:** FFmpeg master z października 2026 odrzuca `-thread_queue_size` jako opcję wejścia. Ścieżka AMD jej używa, więc aktualizacja FFmpeg zatrzyma eksport AMD z jawnym błędem.

## 6. Czy problem 107 s został przetestowany

**Nie na Twoim sprzęcie.** Nie uruchamiałem eksportu AMD ani pełnego zestawu testów.

Sprawdzone tylko w kontenerze (Linux, FFmpeg master z 14.10.2026, syntetyczne źródła 60 Mb/s na szybkim dysku):
- odtworzony mechanizm: przy starym poleceniu audio czytane dopiero po końcu wideo,
- po poprawce audio czytane w trakcie, finalizacja około 0 s,
- 10 testów `tests/test_live_av_mux.py` przechodzi, w tym test integracyjny, który bez `setts` nie przechodzi.

Nie sprawdzałem:
- Twojej wersji FFmpeg 2026-08-17 (Windows),
- wolnego dysku USB,
- prawdziwych plików GoPro,
- `tests/test_amd_live_mux_audio_finalization.py`, który wymaga Windows.

Minimalna weryfikacja u Ciebie, bez pełnego eksportu:

```
pytest tests/test_live_av_mux.py tests/test_amd_live_mux_audio_finalization.py -q
```

---

# Aktualizacja 14.10.2026 wieczorem: bezstratne AAC wdrożone w AMD (opcja B)

Zapisane w `C:\_DEV\BikeRideHUD-main-new`: nowy `src/ffmpeg/mp4_audio_feed.py`, zmiany w `amd_native_exporter.py`, nowy `tests/test_mp4_audio_feed.py`, zaktualizowany `tests/test_amd_live_mux_audio_finalization.py`. Diff: `zmiany-3-bezstratne-aac.diff`. Bez git, `def_layout.json` nietknięty.

**Komenda multi-file AMD teraz:**

```
ffmpeg.exe -y -f hevc -r 30000/1001 -bsf:v setts=ts=N*1001/30000/TB:duration=1001/30000/TB -thread_queue_size 512 -i - -thread_queue_size 512 -f aac -i \\.\pipe\telem_amf_audio_<pid>_<token>.aac -map 0:v -map 1:a:0 -t <D> -c:v copy -c:a copy -f mp4 out.mp4.part
```

- **AAC:** Python czyta z każdego MP4 tylko tablice próbek ścieżki audio (`stsd/esds`, `stts`, `stsz`, `stsc`, `stco/co64`, `elst`) i same pakiety AAC, dokleja 7-bajtowy nagłówek ADTS i pisze do named pipe. Muxer MP4 zdejmuje nagłówek, więc w pliku są oryginalne pakiety, `-c:a copy`. Bez concat, bez filtra, bez dodatkowego procesu i pliku. Wątek piszący blokuje się, gdy FFmpeg nie potrzebuje danych, więc audio idzie w tempie wideo.
- **Cięcie:** do pełnej ramki AAC (21,3 ms) na granicach fragmentów (ramka wchodzi, jeśli jej środek mieści się w zakresie).
- **Brak dźwięku:** wszystkie klipy bez audio → wynik bez audio. Część klipów z audio, część bez, albo różne formaty AAC → jawny błąd `AMDNativeFinalizationError`, bez ciszy i bez rekompresji. Uszkodzony plik → błąd, nie „brak audio”.
- **DTS/PTS:** wideo przez `setts` jak wcześniej; audio z liczby ramek ADTS (1024 próbki na ramkę), ciągłe.
- **Single-file:** bez zmian (`-c:a copy` z pliku źródłowego).
- **Intel/NVIDIA:** bez zmian, multi-file nadal koduje AAC 256k. Wymaga osobnej weryfikacji przed przeniesieniem.

**Testy (Linux, FFmpeg master):** 17/17. Pakiety audio w wyniku identyczne co do bitu i kolejności ze źródłem, >90% audio odczytane w trakcie podawania wideo, finalizacja ~0 s. Na FFmpeg 6.1 (bez `-bsf` na wejściu) test integracyjny jest pomijany.

**Nie przetestowane:** Windows named pipe (kod `CreateNamedPipeW`/`WriteFile` nie był uruchomiony), prawdziwe pliki GoPro, dysk USB, Twój FFmpeg, `test_amd_live_mux_audio_finalization.py`.
