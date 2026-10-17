# RAPORT SPORTCAMHUD — ETAP 5T: ELIMINACJA DŁUGIEJ FINALIZACJI MULTI-FILE

Data: 2026-10-14  
Gałąź: `fix/gui-freeze-hud-composite`  
Commit bazowy: `a66b0536ac49d72bf146c9e5cf36fa01dbd31fa8` (Etap 5S-A)  
Commit wdrożenia 5T: `a1c152218d85d5da10457964bacdfa5bc926eed9`  
Plik logu użytkownika będący podstawą diagnozy: `D:\GoPro\BRH\scratch\amd_child_1_1791970019148.log`  

---

## 1. ZBADANY PROBLEM I PEŁNA DIAGNOZA PRZYCZYNY

### A. Stan wyjściowy (Log `amd_child_1_1791970019148.log`)
- **Źródła:** 2 pliki GoPro 4K (`F:\GoPro\2026-08-27\GX010163.MP4` - 1.01 GB, `GX010164.MP4` - 7.99 GB, łącznie 8.99 GB / ~8.57 GiB).
- **Klatki:** 37 285 klatek 4K (3840x2160 @ 29.97 fps).
- **Czas renderowania wideo:** 1034.99 s (~17.25 minuty) przy 36.024 Render FPS.
- **Czas finalizacji (`mux_wait_ms`):** **107 460.56 ms (~107.46 sekundy)**.
- **Objaw:** W trakcie `mux_wait` FFmpeg odczytał z nośnika USB (dysk `F:`) dodatkowo 8566.62 MB (~8.57 GB) przy 100% obciążeniu dysku, podczas gdy CPU (2–5%) i GPU (0%) były bezczynne.

---

### B. Szczegółowa diagnoza mechanizmu FFmpeg i błędu w kodzie

#### 1. Dlaczego FFmpeg odczytał z dysku aż 8.57 GB (zamiast 37.5 MB samego AAC)?
- Zbadano kod źródłowy FFmpeg:
  - `libavformat/concatdec.c` (demuxer concat)
  - `libavformat/mov.c` (demuxer QuickTime/MP4).
- W `mov.c` funkcja `mov_read_packet()` pomija pakiety wideo bez ich odczytu z dysku (`goto retry`) **wyłącznie wtedy, gdy na danym strumieniu ustawiona jest flaga `st->discard == AVDISCARD_ALL`**.
- W `concatdec.c` funkcja `open_file()` tworzy wewnętrzny kontekst `AVFormatContext` (`cat->avf`) dla każdego pliku z listy concat, jednak **nigdy nie propaguje zewnętrznej flagi `discard` na wewnętrzne strumienie pliku MOV**.
- W rezultacie wewnętrzny demuxer `mov.c` uznaje strumień wideo 4K (53 Mbps) za aktywny i fizycznie odczytuje każdy pakiet wideo z nośnika (co daje 8.57 GB dla obu plików), po czym `concatdec.c` po sprawdzeniu `cs->out_stream_index < 0` natychmiast zwalnia ten pakiet w pamięci RAM (`av_packet_unref(pkt)`).
- **Wniosek:** Dopóki używany jest natywny `concat demuxer` FFmpeg, fizyczny odczyt całego pliku źródłowego z nośnika jest nieuniknioną cechą implementacji `concatdec.c`.

#### 2. Dlaczego cały odczyt 8.57 GB nastąpił w fazie finalizacji (`mux_wait`), a nie w trakcie 17 minut renderowania?
- W module [`src/ffmpeg/amd_native_exporter.py`](file:///C:/_DEV/BikeRideHUD-main-new/src/ffmpeg/amd_native_exporter.py#L3422-L3430) w linii 3423 znajdowały się parametry:
  ```python
  audio_args = [
      "-copyts", "-avoid_negative_ts", "make_zero",
      "-f", "concat", "-safe", "0",
      "-thread_queue_size", "512",
      "-i", str(audio_concat_path)
  ]
  ```
- Flaga `-copyts` w FFmpeg działa **globalnie**. Spowodowała ona, że wejście wideo nr 0 (surowy strumień HEVC z potoku stdin `-f hevc -r 30000/1001 -i -`) **nie otrzymywało wygenerowanych syntetycznych znaczników czasu DTS/PTS** (pakiety wideo miały znacznik `AV_NOPTS_VALUE`, co generowało w logu FFmpeg ostrzeżenie: *`[mp4] Timestamps are unset in a packet for stream 0. This is deprecated...`*).
- Mechanizm przeplotu pakietów FFmpeg (`ff_interleave_packet_per_dts`) porównuje znaczniki DTS wejść. Gdy wejście wideo nie posiadało prawidłowych DTS, FFmpeg **nie potrafił przeplatać audio z wideo w czasie rzeczywistym**.
- FFmpeg konsumował strumień wideo z potoku tak szybko, jak podawał go enkoder AMD, **całkowicie wstrzymując odczyt wejścia audio nr 1 przez pełne 17 minut trwania renderowania** (strumień audio tkwił w punkcie 0.0 s).
- Dopiero po wygenerowaniu 37 285 klatek i zamknięciu potoku stdin (`stdin_closed=True`), FFmpeg wszedł w fazę `mux_wait` i musiał nadrobić odczyt całego strumienia audio od 0 do 1244 sekund.
- W połączeniu z punktem 1 oznaczało to konieczność przeczytania całych 8.57 GB z pendrive'a USB dopiero na sam koniec eksportu, co przy prędkości ~80 MB/s zajęło dokładnie **107.46 sekundy**.

---

## 2. WDROŻONA POPRAWKA KODU

W pliku [`src/ffmpeg/amd_native_exporter.py`](file:///C:/_DEV/BikeRideHUD-main-new/src/ffmpeg/amd_native_exporter.py#L3415-L3428) usunięto destrukcyjne flagi `-copyts -avoid_negative_ts make_zero`:

```python
# PRZED POPRAWKĄ (błędne flagi globalne blokujące DTS potoku wideo):
audio_args = [
    "-copyts", "-avoid_negative_ts", "make_zero",
    "-f", "concat", "-safe", "0",
    "-thread_queue_size", "512",
    "-i", str(audio_concat_path)
]

# PO POPRAWCE (właściwe argumenty zapewniające ciągłe generowanie DTS i równoległy przeplot):
audio_args = [
    "-f", "concat", "-safe", "0",
    "-thread_queue_size", "512",
    "-i", str(audio_concat_path)
]
```

### Skutek poprawki:
1. Surowe wejście HEVC z potoku stdin otrzymuje od demuxera HEVC monotoniczne znaczniki czasu DTS na podstawie zadeklarowanego klatkażu (`-r 30000/1001` -> 0, 1001, 2002...).
2. Wejście concat audio posiada monotoniczne znaczniki czasu DTS.
3. Przeplot FFmpeg działa równolegle w trakcie renderowania wideo: pakiety audio są pobierane i muxowane na bieżąco, klatka po klatce.
4. Odczyt danych z nośnika źródłowego rozkłada się równomiernie na cały czas trwania renderowania (transfer zaledwie ~8.3 MB/s zamiast 100% zatoru dyskowego na koniec).
5. W momencie zakończenia renderowania wideo całe audio jest już wmuxowane w plik docelowy. Czas `mux_wait` spada do ułamka sekundy.

---

## 3. WYNIKI KONTROLOWANEGO TESTU A/B

Test przeprowadzono na reprezentatywnym teście klipów z rzeczywistego eksportu (`GX010163.MP4` i `GX010164.MP4` na dysku `F:`), przecinającym granicę klipów:

| Parametr / Metryka | Wariant A (obecny z `-copyts`) | Wariant B (po poprawce: usunięcie `-copyts`) | Wynik porównania |
|---|:---:|:---:|:---:|
| **Czas finalizacji (`mux_wait`)** | **Zawieszenie / opóźnienie** (błąd DTS) | **0.12 s (120 ms)** | **Skrócenie o >99%** |
| **Prędkość muxera** | 4.26x | **78.6x** | **18x szybciej** |
| **Pakiety AAC w pliku docelowym** | 234 pakiety (tylko 5.0 s, klip 2 odrzucony) | **469 pakietów (pełne 10.01 s)** | **100% kompletności** |
| **Ciągłość PTS/DTS na granicy 5.0 s** | Brak (strumień przerwany) | **Idealna ciągłość monotoniczna** (`4.992s -> 5.000s -> 5.021s`) | **PASS** |
| **Liczba procesów FFmpeg** | 1 | 1 | **Zgodne z regułami** |
| **Format audio** | AAC copy (bez rekompresji) | AAC copy (bez rekompresji) | **Zgodne z regułami** |

---

## 4. ZACHOWANIE OGRANICZEŃ ARCHITEKTONICZNYCH

- **Single Live Mux:** nienaruszony (jeden proces FFmpeg, surowe HEVC z AMD przez istniejący potok stdin, brak drugiego przebiegu).
- **Single-file:** nienaruszony (działa na bezpośrednim demuxerze MOV/MP4 bez concat).
- **Zakaz tworzenia plików pośrednich:** nienaruszony (brak `M4A`, `ADTS`, osobnych `AAC`, `audio_cache`, brak pośredniego MP4).
- **Pozostałe moduły:** brak zmian w AMD DLL, D3D11, AMF, HUD, Lean, Compass, Bar, FIT/GPX, GUI oraz `def_layout.json`.
- **Trwałe logowanie:** w pełni zachowane (zgodnie z Etapem 5S logi eksportu nie są usuwane).
- **Weryfikacja pełnego filmu (37 285 klatek):** zgodnie z instrukcją ("Nie wykonuj ponownie pełnego filmu 37 285 klatek") pełny eksport pozostaje oznaczony jako **NOT TESTED**.

---

## 5. TESTY JEDNOSTKOWE

Dodano test jednostkowy [`test_amd_multi_file_live_mux_args_no_copyts`](file:///C:/_DEV/BikeRideHUD-main-new/tests/test_amd_child_process.py#L284-L298) weryfikujący, że argumenty multi-file live mux nie zawierają `-copyts` ani `-avoid_negative_ts`, a demuxer concat jest wywoływany z parametrami `-f concat -safe 0 -thread_queue_size 512`.

Wynik uruchomienia zestawu testowego:
`tests/test_amd_child_process.py`: **12 passed in 4.82s**.
