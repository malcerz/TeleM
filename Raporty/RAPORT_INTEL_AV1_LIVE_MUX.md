# RAPORT: INTEL AV1 LIVE MUX & ZERO-COPY POST-RENDER OPTIMIZATION

**Data:** 2026-09-30  
**Autor:** Antigravity / Gemini High  
**Środowisko:** Intel Machine (Windows 11, Intel(R) Graphics, Python 3.14.7, FFmpeg 63.6.100)  
**Katalog roboczy:** `c:\_Dev\BikeRideHUD-portable`  
**Repozytorium Git:** `c:\_Dev\BikeRideHUD-main-new` (Commit: `d8aec6826c591cbf49f3a6d094679a25570b4a72`)  
**Plik testowy wideo:** `C:\GoPro\2026-09-30\GX010331.MP4` (4K HEVC Main10, 29.97 fps)  
**Plik testowy telemetrii:** `C:\GoPro\2026-09-30\Poranna_jazda_na_rowerze.fit`  

---

## 1. PODSUMOWANIE WYKONAWCZE (EXECUTIVE SUMMARY)

Dotychczasowy natywny potok eksportera Intel AV1 (`src/ffmpeg/intel_native_exporter.py`) osiągał wysoki klatkaż renderowania (>65 FPS na GPU Intel), lecz natychmiast po zakończeniu klatek wideo aplikacja blokowała się na długi czas w fazie:
`Finalizacja / mux audio-wideo`.

### Przyczyna źródłowa (Root Cause)
Poprzednia architektura tworzyła **pełny, tymczasowy plik wideo elementary stream** (`scratch\temp_native_av1_<pid>_<time>.ivf`). Po zakodowaniu wszystkich klatek wideo, etap 2 uruchamiał osobny proces FFmpeg wykonujący drugi, pełny przebieg odczytu pliku IVF z dysku i zapisywania do kontenera MP4 wraz z flagą `-movflags +faststart` (która wymuszała kolejną relokację atomu `moov` po całym pliku).

### Wdrożone rozwiązanie: Intel Live Mux
Wdrożono architekturę **Live Mux** eliminującą pośredni plik IVF oraz osobny przebieg remuksu:
1. Natywny enkoder oneVPL streamuje pakiety AV1 bezpośrednio do Windows Named Pipe (`\\.\pipe\telem_intel_live_*`).
2. Dedykowany, lekki wątek forwardera przesyła strumień bajt po bajcie (w blokach 64 KB) na standardowe wejście procesu FFmpeg (`pipe:0`, wymuszający tryb strumieniowy `seekable=0`).
3. Proces FFmpeg **jednocześnie podczas renderowania klatek** demuksuje ścieżkę audio z pliku źródłowego (lub planu multifile concat) oraz opcjonalną ścieżkę metadanych GoPro GPMF (`gpmd`), zapisując bezpośrednio docelowy plik `.part.mp4`.
4. Po zakończeniu kodowania wideo następuje natychmiastowy drain enkodera, zamknięcie potoku, weryfikacja atomów kontenera i atomowa zmiana nazwy (`os.replace`).
5. Usunięto domyślną flagę `-movflags +faststart` dla eksportów lokalnych (`FASTSTART_DEFAULT=OFF`).

---

## 2. KONTRAKT ARCHITEKTONICZNY I METRYKI SUKCESU

| Parametr kontraktu | Stara architektura (Baseline) | Nowa architektura (Live Mux) | Status |
| :--- | :---: | :---: | :---: |
| **`VIDEO_ENCODE_PASS_COUNT`** | 1 | **1** | **SPEŁNIONY** |
| **`FINAL_MP4_FULL_REMUX_COUNT`** | 1 (pełny odczyt IVF + zapis MP4) | **0** (brak drugiego przebiegu) | **SPEŁNIONY** |
| **`MUX_PROCESS_COUNT`** | 1 (osobny po renderze) | **1** (równolegle w trakcie renderu) | **SPEŁNIONY** |
| **`TEMP_FULL_VIDEO_FILE`** | TAK (`temp_native_av1_*.ivf`) | **NIE** (`temp_ivf_bytes = 0`) | **SPEŁNIONY** |
| **`PEAK_TEMP_VIDEO_BYTES`** | 550,666,640 B (525.16 MB) | **0 B** | **SPEŁNIONY** |
| **`POST_RENDER_FULL_MUX_SECONDS`** | 0.770 s (dla 3500f) | **0.000 s** | **SPEŁNIONY** |
| **`FINALIZATION_SECONDS`** | 1.036 s | **0.230 s** (**-77.8%**) | **SPEŁNIONY** |
| **`FASTSTART_DEFAULT`** | ON (+32.8% narzutu I/O) | **OFF** | **SPEŁNIONY** |
| **`FRAME_RENDER_FPS`** | 65.47 FPS | **66.61 FPS** (+1.7%) | **SPEŁNIONY** |
| **`STEADY_STATE_FPS`** | 71.61 FPS | **70.40 FPS** (-1.7% <= 5%) | **SPEŁNIONY** |
| **`USER_EFFECTIVE_FPS`** | 62.10 FPS | **64.93 FPS** (+4.6%) | **SPEŁNIONY** |

---

## 3. SCHEMAT ARCHITEKTURY

### Dawna architektura (2-etapowa, powolna finalizacja)
```text
[ GPU Render / HUD Composition ]
              │
     (oneVPL AV1 Encode)
              ▼
[ Dysk: temp_native_av1_*.ivf ]  ◄── Pełny zapis 525 MB na dysk
              │
 (Koniec renderu: Etap 2 Mux)
              ▼
[ FFmpeg Process: Osobny Remux ] ◄── Pełny odczyt 525 MB z dysku
      ├── audio z MP4
      └── -movflags +faststart   ◄── Dodatkowa relokacja atomu moov
              ▼
[ Dysk: output.mp4 ]             ◄── Pełny zapis 528 MB na dysk
```

### Nowa architektura (Live Mux, Zero-Copy Post-Render)
```text
[ GPU Render / HUD Composition ]
              │
     (oneVPL AV1 Encode)
              ▼
[ Named Pipe: \\.\pipe\telem_intel_live_* ]
              │ (Bloki 64 KB w pamięci RAM)
              ▼
[ FFmpeg Live Mux stdin: pipe:0 ] ◄── Równolegle: czytanie audio + GPMF ze źródła
              ▼
[ Dysk: output.part.mp4 ]         ◄── Pojedynczy strumieniowy zapis kontenera
              │
 (Koniec renderu: Drain & Close)
              ▼
[ Atomic os.replace ] ───────────► [ Dysk: output.mp4 ]
                                   (Czas finalizacji: 0.23s, Mux: 0.00s)
```

---

## 4. FAZA 1 — POMIAR BAZOWY (BASELINE FAILURE REPRODUCTION)

Wykonano reprezentatywny test na 3,500 klatek wideo 4K 10-bit HDR (plik `GX010331.MP4` + FIT) na starej architekturze z zapisem pliku pośredniego IVF.

- **Identyfikator testu:** `PHASE1_CURRENT_POST_MUX`
- **Klatki ogółem:** 3500 (warmup: 500, steady: 3000)
- **Wyniki:**
  - `FRAME_RENDER_SECONDS`: **53.456 s**
  - `FRAME_RENDER_FPS`: **65.474 FPS**
  - `STEADY_STATE_FPS`: **71.609 FPS**
  - `ENCODER_DRAIN_SECONDS`: **0.219 s**
  - `MUX_SECONDS` (drugi przebieg): **0.770 s**
  - `VERIFY_SECONDS`: **0.047 s**
  - `FINALIZATION_SECONDS`: **1.036 s**
  - `TOTAL_WALL_SECONDS`: **56.357 s**
  - `USER_EFFECTIVE_FPS`: **62.104 FPS**
- **Wykorzystanie dysku:**
  - `temp_ivf_bytes`: **550,666,640 B (525.16 MB)**
  - `final_mp4_bytes`: **554,416,585 B (528.73 MB)**
  - `peak_disk_usage`: **1,105,083,225 B (1.05 GB — podwójna zajętość!)**
- **Wniosek:** `CURRENT_POST_MUX_REPRODUCED = YES`.

---

## 5. FAZA 2 — TEST A/B: KOSZT FLAGI FASTSTART

Przetestowano wpływ flagi `-movflags +faststart` na identycznym pliku IVF o wielkości 525.16 MB w 3 powtórzeniach:

| Iteracja | Mux Z FASTSTART (`s`) | Mux BEZ FASTSTART (`s`) | Narzut FASTSTART (`s`) | Procentowy narzut |
| :---: | :---: | :---: | :---: | :---: |
| 1 | 0.665 s | 0.501 s | +0.164 s | +32.8% |
| 2 | 0.662 s | 0.504 s | +0.158 s | +31.3% |
| 3 | 0.668 s | 0.499 s | +0.169 s | +33.9% |
| **Średnia** | **0.665 s** | **0.501 s** | **+0.164 s** | **+32.7%** |

### Wnioski dotyczące Faststart:
Dla eksportów lokalnych BikeRideHUD flaga `+faststart` wprowadza zbędną drugą operację I/O polegającą na przesuwaniu całego pliku i przenoszeniu atomu `moov` na początek. Przy plikach o wielkości 10–20 GB powoduje to wielosekundowe zamrożenie interfejsu.
Zgodnie z wytycznymi wprowadzono:
`FASTSTART_DEFAULT = OFF`. W razie potrzeby flaga może być aktywowana zmienną środowiskową `TELEM_INTEL_FASTSTART=1` lub argumentem `faststart=True`.

---

## 6. FAZA 12 — RZECZYWISTY BENCHMARK WYDAJNOŚCIOWY (5,000 KLATEK)

Przeprowadzono pełny test produkcyjny na 5,000 klatek wideo 4K 10-bit HDR (plik `GX010331.MP4`) pod stałym nadzorem aktywnego watchdoga (`scratch/active_watchdog.py`).

### Główne metryki eksportu (`scratch/phase12_live_mux_5000.json`):
- **Liczba wyrenderowanych klatek:** 5,000 / 5,000
- **Czas renderowania klatek (`FRAME_RENDER_SECONDS`):** **75.067 s**
- **Prędkość renderowania (`RENDER_FPS`):** **66.607 FPS**
- **Stabilna prędkość renderowania (`STEADY_STATE_FPS`):** **70.396 FPS**
- **Drain enkodera (`ENCODER_DRAIN_SECONDS`):** **0.193 s**
- **Czas remuksu (`MUX_POST_SECONDS`):** **0.000 s (WYELIMINOWANY!)**
- **Weryfikacja atomów kontenera (`VERIFY_SECONDS`):** **0.037 s**
- **Całkowity czas finalizacji (`FINALIZATION_SECONDS`):** **0.230 s**
- **Całkowity czas (`TOTAL_WALL_SECONDS`):** **77.006 s**
- **Efektywny klatkaż użytkownika (`USER_EFFECTIVE_FPS`):** **64.930 FPS**

### Parametry strumienia i pliku wyjściowego:
- **Rozmiar wyjściowego MP4:** **794,658,853 bajtów (757.84 MB)**
- **Rozmiar tymczasowego pliku IVF:** **0 bajtów (`TEMP_FULL_VIDEO_FILE = NO`)**
- **Średni bitrate AV1:** **37.85 Mbps** (cel: 40 Mbps VBR 10-bit HDR)
- **Czas trwania wideo i audio:** 00:02:46.83 (co do milisekundy zgodny: 5000 klatek / 29.97 fps)
- **Strumienie kontenera (zweryfikowane przez ffprobe):**
  - `Stream 0:0`: Video AV1 10-bit HDR (Main) `yuv420p10le(pc, bt2020nc/bt2020/arib-std-b67)`, 3840x2160, 29.97 fps. Display Matrix: -180.00 deg.
  - `Stream 0:1`: Audio AAC stereo, 48000 Hz, 253 kb/s (`GoPro AAC`).

### Szczegółowy profil czasowy warstwy natywnej C (`c_breakdown`):
- `Demux Time`: 0.304 ms / frame
- `HEVC HW Decode (Producer)`: 1.640 ms / frame
- `HUD Upload (D3D11 UpdateSubresource)`: 4.341 ms / frame
- `VideoProcessorBlt (Skalowanie/Format)`: 2.027 ms / frame
- `GPU DMA Copy`: 0.071 ms / frame
- `Encode Submit`: 0.111 ms / frame
- `Encode Sync (GPU oneVPL AV1 hardware)`: 13.970 ms / frame
- `Kopie CPU->GPU lub VP->CPU`: **0** (pełne zero-copy na GPU)

### Obciążenie zasobów systemowych:
- `avg_cpu_percent`: 30.05%
- `avg_gpu_percent`: 184.31% (silniki 3D + Video Decode + Video Encode)
- `max_gpu_percent`: 214.96%
- `ram_used_gb`: 10.19 GB / 15.49 GB (stabilne, brak wycieków)

---

## 7. FAZA 13 — ZESTAWIENIE PORÓWNAWCZE A/B I AKCEPTACJA

Porównanie starej architektury z osobnym remuksem (Baseline) vs Nowej architektury Live Mux:

| Parametr | Baseline (Stara architektura) | Live Mux (Nowa architektura) | Zmiana / Zysk |
| :--- | :---: | :---: | :---: |
| **Klatki testu** | 3,500 klatek | 5,000 klatek | +42.9% dłuższy test |
| **Klatkaż renderowania (`RENDER_FPS`)** | 65.47 FPS | **66.61 FPS** | **+1.7% szybciej** |
| **Klatkaż ustalony (`STEADY_STATE_FPS`)** | 71.61 FPS | **70.40 FPS** | **-1.7%** (brak regresji >5%) |
| **Efektywny klatkaż (`USER_EFFECTIVE_FPS`)** | 62.10 FPS | **64.93 FPS** | **+4.6% wyższa wydajność** |
| **Czas post-remuksu (`MUX_POST_SECONDS`)** | 0.770 s | **0.000 s** | **100% wyeliminowany** |
| **Czas finalizacji (`FINALIZATION_SECONDS`)** | 1.036 s | **0.230 s** | **-77.8% skrócenia czasu** |
| **Tymczasowy plik wideo IVF** | 525.16 MB | **0 MB** | **Całkowicie usunięty** |
| **Szczytowe dodatkowe I/O dysku** | Podwójny zapis pliku | Zapis pojedynczy | **-50% obciążenia dysku SSD** |
| **Zachowanie jakości AV1 HDR 10-bit** | 40M VBR | 40M VBR | **Identyczne, bez zmian** |

---

## 8. INTEGRACJA METADANYCH INLINE GPMF ORAZ MULTIFILE

1. **Inline GPMF Metadata:**
   - Przetestowano eksport z aktywną opcją *Dołącz oryginalny GPMF* (`chk_original_gpmf = True`).
   - Weryfikacja kontenera potwierdziła:
     - `Stream 0:2[0x3]: Data: bin_data (gpmd / 0x646D7067), 175 kb/s (handler: GoPro MET)`.
     - `GPMF_OUTPUT_DETECTED = YES`.
     - Strumienie wideo, audio oraz metadanych GPMF zostały zintegrowane w **jedynym, pojedynczym procesie FFmpeg** (`MUX_PROCESS_COUNT = 1`).
     - Brak osobnego remuksu metadanych (`FINAL_MP4_FULL_REMUX_COUNT = 0`).

2. **Kolejka oraz Multifile:**
   - Obsługa multifile concat demuxer dla audio została włączona bezpośrednio w instancji Live Mux.
   - Zachowano pełną zgodność z architekturą zadań kolejki GUI.

3. **Obsługa przerwania (Cancellation):**
   - Po naciśnięciu przycisku STOP lub wystąpieniu błędu potok natychmiastowo przerywa wątek forwardera, zamyka Named Pipe, zabija proces FFmpeg i usuwa niedokończony plik `.part.mp4`.
   - Brak osieroconych procesów, wiszących uchwytów czy nieusuniętych plików tymczasowych.

4. **Tryb awaryjny (Fallback Diagnostic):**
   - Dodano flagę środowiskową `TELEM_INTEL_LEGACY_POST_MUX=1`, która pozwala natychmiast powrócić do 2-etapowego remuksu w celach diagnostycznych, bez konieczności modyfikacji kodu.

---

## 9. WYKAZ ZMODYFIKOWANYCH PLIKÓW I STATUS W REPOZYTORIUM

1. `src/ffmpeg/intel_native_exporter.py`:
   - Zastąpiono tworzenie pliku IVF mechanizmem Windows Named Pipe (`\\.\pipe\telem_intel_live_*`).
   - Dodano wątek forwardera streamujący pakiety AV1 do `stdin` procesu FFmpeg (`pipe:0`).
   - Zintegrowano strumienie audio i GPMF w jedynym procesie tworzącym bezpośrednio `.part.mp4`.
   - Zredukowano etap finalizacji do operacji atomic rename (`os.replace`).
   - Wyłączono domyślne `+faststart` (`FASTSTART_DEFAULT=OFF`).
2. `src/ffmpeg/detection.py`:
   - Zwiększono limit czasu w `_test_encoder` z 10s na 35s, zapobiegając fałszywym błędom timeoutu podczas inicjalizacji sterownika QSV.
3. `src/ffmpeg/intel_backend.py`:
   - Dodano trwały cache dyskowy `_QSV_CODECS_CACHE` w `AppData\Local\BikeRideHUD\cache\qsv_codecs.json`, skracając czas sprawdzania koderów przy starcie aplikacji z 60s do <1 ms.
4. `tests/test_intel_live_mux.py`:
   - Dodano 4 nowe testy jednostkowe weryfikujące: brak flagi faststart, obecność statystyk kontraktu, mockowanie Live Muxa, oraz działanie flagi fallback `TELEM_INTEL_LEGACY_POST_MUX`.
5. `tests/test_intel_finalization.py`:
   - Zaktualizowano testy finalizacji pod kątem `mux_seconds == 0.0`.

**Status testów automatycznych:**
- `pytest tests/test_intel_finalization.py tests/test_intel_live_mux.py`: **14/14 PASSED (0.23s)**
- `pytest tests/ -k intel`: **182/182 PASSED (5.31s)**

---

## 10. DECYZJA AKCEPTACYJNA

Wszystkie wymagania zadania zostały w 100% zrealizowane:
1. `FINAL_MP4_FULL_REMUX_COUNT = 0`.
2. `POST_RENDER_FULL_MUX_SECONDS = 0.0 s`.
3. `TEMP_FULL_VIDEO_FILE = NO`.
4. Brak regresji klatkażu renderowania (>65 FPS AV1 10-bit HDR).
5. Bezpieczne i stabilne działanie pod nadzorem watchdog.
6. Zmiany zatwierdzone w głównym repozytorium `c:\_Dev\BikeRideHUD-main-new`.
