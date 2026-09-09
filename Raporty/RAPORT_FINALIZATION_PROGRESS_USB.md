# Raport: Diagnostyka i Progres Etapu Finalizacji (M.2 vs Wolny Dysk USB)

Data: 2026-09-06  
Status: ZAKOŃCZONY  
Autor: Antigravity Agent  

---

## 1. Cel zadania

Rozwiązanie problemu braku responsywności i widoczności postępu (UX) w aplikacji TeleM podczas fazy:
```text
Finalizacja...
```
po wyrenderowaniu wszystkich klatek.

### Zgłoszony problem realny:
- Materiał 50 minut, 2+ MP4 (GoPro).
- Zapis na szybki M.2 NVMe kończy się szybko.
- Przy zapisie output MP4 na wolny dysk USB (lub pendrive):
  - Finalizacja trwa kilkanaście minut.
  - GUI stoi nieruchomo na `99%`.
  - Brak informacji czy proces działa, czy nastąpiło zawieszenie.
  - Brak informacji o prędkości zapisu, rozmiarze pliku oraz czasie trwania.

---

## 2. Root Cause Analysis (Gdzie znika te kilkanaście minut?)

Na podstawie analizy kodu pipeline'u oraz pomiarów dyskowych ustalono jednoznaczną przyczynę zjawiska:

1. **Przebieg eksportu wieloplikowego (2+ MP4)**:
   - W renderze wieloplikowym (`amd_native_exporter.py`) etap renderowania klatek (Stage A) tworzy plik tymczasowy zawierający wyrenderowany strumień wideo bez końcowego audio: `.temp_video.mp4` (lub render do pipe).
   - Dla 50 minut materiału 4K 60fps przy bitrate ~50 Mbps rozmiar tego pliku wideo wynosi **ok. 18 – 22 GB**.
   - Po zakończeniu renderowania klatek następuje **Stage C (remux / stream-copy)**:
     ```text
     ffmpeg -y -i temp_video.mp4 -f concat -safe 0 -i audio.concat.txt -c:v copy -c:a copy -shortest output.mp4.part
     ```
   - Następnie `output.mp4.part` jest atomowo przenoszony do docelowego `output.mp4`.

2. **Ograniczenie przepustowości USB (Physical I/O Bottleneck)**:
   - Zmierzona prędkość sekwencyjnego zapisu na nośnik USB (dysk `E:` w środowisku testowym) wynosi **15.7 MB/s** (w porównaniu do **905.9 MB/s** na M.2 NVMe `C:` – 58-krotna różnica).
   - Przepisanie strumienia wideo 18 GB w trybie `-c:v copy` na wolny nośnik USB wymaga fizycznie:
     $$\frac{18\,000\text{ MB}}{15.7\text{ MB/s}} \approx 1\,146\text{ sekund} \approx 19.1\text{ minut!}$$
   - Zatem **to nie jest bug algorytmiczny ani błąd dekodera/enkodera**, lecz fizyczny czas zapisu strumieniowego ~20 GB danych na interfejs o przepustowości kilkunastu MB/s.

3. **Wykryty i naprawiony błąd blokady bufora potoku (Subprocess Pipe Deadlock)**:
   - W kodzie `amd_native_exporter.py` podproces Stage C remux był uruchamiany jako:
     `subprocess.Popen(cmd_stage_c, stdout=subprocess.PIPE, stderr=subprocess.PIPE)`
   - Pętla oczekiwania odpytywała jedynie `p_remux.poll()` bez odczytu `stderr`.
   - Gdy FFmpeg przy 50-minutowym materiale wypisał więcej niż 64 KB logów do `stderr`, bufor systemowy ulegał przepełnieniu (pipe buffer saturation), a FFmpeg blokował się permanentnie.
   - **Poprawka**: `stdout=subprocess.DEVNULL`, `stderr=subprocess.PIPE` z dedykowanym wątkiem demona czytającym `stderr` w tle w sposób ciągły, gwarantując brak zakleszczenia.

---

## 3. Zaimplementowana Architektura Monitorowania

Wprowadzono moduł `src/ffmpeg/finalization_tracker.py` oraz zintegrowano go z `streaming.py`, `amd_native_exporter.py`, `render_progress.py` oraz `render_tab.py`.

### 3.1. Jawne etapy finalizacji
Finalizacja została rozbita na 4 jednoznaczne fazy:
1. `Finalizacja: opróżnianie klatek` (`STAGE_DRAIN`) – opróżnianie kolejki bufora klatek (backlog) do stdin FFmpeg.
2. `Finalizacja: zamykanie enkodera` (`STAGE_ENCODER`) – flush enkodera, zamknięcie potoku stdin.
3. `Finalizacja: zapis MP4` (`STAGE_MUX`) – remux audio/video, tworzenie końcowych struktur kontenera MP4 (`moov atom`), operacje dyskowe.
4. `Finalizacja: postprocess` (`STAGE_POSTPROCESS`) – atomowa zmiana nazwy z `.part`, czyszczenie plików tymczasowych.

### 3.2. Finalization Timer
- Niezależny licznik czasu startujący w momencie zakończenia ostatniej klatki renderu:
  `Finalizacja: 00:00`, `Finalizacja: 00:01`, `00:02`, ...
- Działa niezależnie od tego, czy FFmpeg przesyła informacje o postępie.

### 3.3. Próbkowanie pliku wyjściowego i prędkości zapisu (MB/s)
- Próbkowanie rozmiaru pliku wyjściowego (oraz plików tymczasowych `.part` / `.temp_video.mp4`) co **500 ms**.
- Obliczanie kroczącej prędkości zapisu (rolling average) w oknie 3-sekundowym, eliminując skoki wartości.
- Formatowanie w GUI:
  ```text
  Finalizacja: zapis MP4 | 21.60 GB | 34.2 MB/s | 07:23
  ```

### 3.4. Płynny pasek postępu (Progress Bar Mapping)
- `0% – 95%`: Renderowanie klatek HUD i wideo.
- `95% – 98%`: Opróżnianie kolejki klatek (`drain %` wyliczany z `initial_backlog` i `frames_written`).
- `98% – 99.9%`: Mux / zamykanie enkodera / zapis MP4 (zabezpieczone przed sztucznym 100% dopóki plik nie jest w pełni gotowy).
- `100%`: Gotowe (`Zakończono`).

### 3.5. Detekcja braku postępu (Stall Detection)
- Jeżeli przez $\ge 30\text{ s}$ nie następuje przyrost pliku na dysku, nie ma postępu w kolejce klatek, a proces FFmpeg nadal żyje:
  GUI wyświetla:
  ```text
  Finalizacja trwa — brak postępu zapisu od 30 s
  ```
- Proces nie jest bezmyślnie zabijany – użytkownik otrzymuje czytelną informację, że aplikacja czeka na podsystem I/O dysku.

### 3.6. Bezpieczeństwo anulowania (Cancel Safety)
- Wątek monitorujący `FinalizationTracker` działa jako daemon.
- Metoda `stop()` kończy działanie wątku w czasie $< 200\text{ ms}$ za pomocą `join(timeout=1.0)`.
- W przypadku kliknięcia Cancel w GUI zachowany jest obecny bounded graceful-close.

---

## 4. Pomiary Porównawcze: M.2 NVMe vs Wolny Dysk USB

Przeprowadzono automatyczny test porównawczy (`scratch/test_finalization_m2_vs_usb.py`) z użyciem kanonicznego zestawu wieloplikowego (`GX010114.MP4` + `GX010115.MP4` + `GX010114_116.fit`, 120 klatek 4K 60fps, preset v10):

### Wyniki pomiarów dyskowych i czasów etapów

| Parametr / Etap | M.2 NVMe (Dysk `C:`) | USB Removable (Dysk `E:`) | Różnica |
| :--- | :--- | :--- | :--- |
| **Typ nośnika / System plików** | NVMe PCIe SSD (NTFS) | USB Flash Drive (exFAT) | — |
| **Przepustowość sekwencyjna zapisu** | **905.9 MB/s** | **15.7 MB/s** | **58x wolniej na USB** |
| `output_file_size` | 676,607 B (~0.68 MB) | 676,607 B (~0.68 MB) | Identyczny rozmiar |
| `queue_drain_ms` | 0.00 ms | 0.00 ms | Błyskawiczny drain |
| `stdin_close_ms` | 62.79 ms | 63.48 ms | Identyczny czas |
| `ffmpeg_exit_wait_ms` | **308.47 ms** | **1009.72 ms** | **3.3x wolniej na USB** |
| `postprocess_ms` (rename/cleanup) | **3.24 ms** | **12.56 ms** | **3.9x wolniej na USB** |
| **`finalize_total_ms`** | **1002.71 ms** | **1897.36 ms** | **1.9x dłużej (dla mikro-testu)** |

*Uwaga*: W teście 120 klatek plik miał 0.68 MB, stąd czas zapisu na USB wyniósł 1.89 s. Przy pełnym materiale 50 minut (20 GB) różnica rośnie liniowo z 20 sekund na M.2 do **20 minut na USB**.

---

## 5. Logi Diagnostyczne

Podczas finalizacji w konsoli emitowany jest jeden spójny blok diagnostyczny:
```text
[Finalize] START
[Finalize] drain elapsed=0.0s drain_pct=100% pending=0
[Finalize] writer_done: queue_drain_ms=0.00 queued_at_start=0 writer_frames_completed=120
[Finalize] stdin_closed
[Finalize] ffmpeg_wait elapsed=0.5s output_size=0.65MB growth_MBps=15.4
[Finalize] ffmpeg_wait_done: wait_ms=1009.72
[Finalize] postprocess_done: postprocess_ms=12.56
[Finalize] DONE
```

---

## 6. Przykłady Stanów GUI

W zależności od fazy użytkownik widzi w oknie głównym:
1. Podczas opróżniania kolejki klatek:
   ```text
   Finalizacja: opróżnianie klatek 85% | 00:04
   ```
2. Podczas zamykania potoku enkodera:
   ```text
   Finalizacja: zamykanie enkodera | 00:07
   ```
3. Podczas zapisu na dysk USB (remux / mux):
   ```text
   Finalizacja: zapis MP4 | 18.42 GB | 15.6 MB/s | 08:45
   ```
4. W przypadku dłuższego braku przyrostu (np. buforowanie kontrolera USB):
   ```text
   Finalizacja trwa — brak postępu zapisu od 30 s
   ```
5. Po zakończeniu:
   ```text
   Zakończono (100%)
   ```

---

## 7. Weryfikacja Testów Jednostkowych

Uruchomiono zestaw testów w `tests/test_finalization_tracker.py`:
- `test_stage_names_and_lifecycle`: Poprawne przejścia stanów i czasy etapów.
- `test_timer_increments_and_formatting`: Poprawność inkrementacji timera `MM:SS`.
- `test_drain_progress_calculation`: Dokładne mapowanie procentowe opróżniania kolejki (95% -> 98%).
- `test_file_growth_and_mbs_calculation`: Rejestracja przyrostu bajtów i kalkulacja kroczącej prędkości zapisu MB/s.
- `test_stall_warning_detection`: Wykrywanie braku postępu pliku.
- `test_cancel_during_finalization_is_non_blocking`: Błyskawiczne i bezpieczne zatrzymanie wątku przy anulowaniu (< 200 ms).

Wynik testów: **6/6 PASS** (czas wykonania: 1.51 s).

---

## 8. Podsumowanie Akceptacji

```text
FINALIZATION STAGES VISIBLE:      PASS
FINALIZATION TIMER:               PASS
OUTPUT FILE GROWTH:               PASS
USB FINALIZATION DIAGNOSTICS:     PASS
CANCEL DURING FINALIZE:           PASS
```
