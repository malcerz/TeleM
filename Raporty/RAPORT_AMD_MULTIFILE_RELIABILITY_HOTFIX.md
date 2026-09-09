# RAPORT: AMD MULTIFILE RELIABILITY HOTFIX
## GPMF PROGRESS + PREVIEW TIMELINE + DIRECT MUX FINALIZATION

**Data:** 2026-09-04  
**Gałąź:** `integration/intel-amd`  
**Autor:** Antigravity  
**Status:** COMPLETE (4/4 PASS)

---

## 1. Cel zadania

Usunięcie trzech krytycznych błędów niezawodności w obsłudze projektów wieloplikowych (multi-file) w aplikacji TeleM na ścieżce renderowania AMD native D3D11:
1. **P0 (Render Finalization):** Render wieloplikowy docierał do 100% klatek wideo (50,136 klatek w teście użytkownika), po czym proces kończył się z kodem `rc=1, pump=None`, plik `.part` był usuwany, a plik wyjściowy nie powstawał.
2. **P0 (Preview Timeline):** Podgląd wieloplikowy po przełączeniu z klipu 1 na klip 2 odtwarzał obraz w MPV, ale pasek postępu (scrubber), czas globalny oraz wartości telemetrii HUD zamrażały się na końcu klipu 1.
3. **P1 (GPMF Progress):** Ładowanie telemetrii GPMF dla projektów wieloplikowych trwało bardzo długo i blokowało pasek postępu na około ~70%.

Zadanie miało być wykonane wyłącznie na lokalnej gałęzi `integration/intel-amd` bez ruszania integracji Intel, bez dalszej optymalizacji renderera i z zachowaniem istniejących zmian użytkownika w `def_layout.json`.

---

## 2. Diagnoza przyczyn źródłowych (Root Causes)

### A. Render Finalization (P0)
- **Problem:** W trybie `AMD DIRECT MUX` dla multi-file, render wideo pędził z pełną wydajnością sprzętową GPU (~41-42 FPS), wysyłając surowe pakiety HEVC do strumienia `stdin` procesu nadrzędnego FFmpeg. FFmpeg w tym samym czasie czytał audio poprzez demukser `-f concat` z dysku.
- Przy dużych plikach/wielu klipach strumień audio w `-f concat` nie nadążał za tempem wideo przekazywanego przez rurę wideo.
- Po zakończeniu kodowania wideo, wątek nadrzędny w Pythonie zamykał rurę wideo i czekał na zakończenie procesu FFmpeg:
  ```python
  proc_mux.wait(timeout=30.0)
  ```
- Przy 50,136 klatkach (ok. 28 minut wideo), FFmpeg po zamknięciu `stdin` wideo potrzebował więcej niż 30 sekund na dokończenie przetwarzania i buforowania audio z pliku concat.
- Skutkowało to rzuceniem wyjątku `TimeoutExpired`, wejściem do bloku:
  ```python
  proc_mux.kill()
  ...
  if os.path.exists(output_part):
      os.remove(output_part)
  ```
  Przez co wyrenderowane całe wideo 4K było bezpowrotnie kasowane! Dodatkowo w przypadku wystąpienia błędu FFmpeg, logi stderr były zalewane znakami powrotu karetki `\r` ze wskaźnika postępu, ukrywając prawdziwą przyczynę błędu.

### B. Preview Scrubber & Telemetry Freeze (P0)
- **Problem 1 (Zakleszczenie flagi przejścia):** W `_on_seek_changed` w `playback_mixin.py`:
  ```python
  self._mpv.wait_until_playing(timeout=0.3)
  ```
  Jeśli użytkownik przesuwał suwak podglądu, gdy odtwarzacz był **wstrzymany (PAUSED)**, `wait_until_playing` wyrzucało timeout / zwracało fałsz przed zresetowaniem `self._source_transition_in_progress = False`. Flaga ta pozostawała na zawsze ustawiona na `True`, przez co kolejne wywołania ticków zegara podglądu ignorowały aktualizacje suwaka i telemetrii.
- **Problem 2 (Brak telemetrii dla klipu 2):** Metoda `_load_or_generate_telemetry` w `project_mixin.py` parsowała telemetrię GPMF wyłącznie dla pierwszego pliku (`self.project.video_files[0]`). Dla klipu 2 brakowało jakichkolwiek próbek czasowych w strukturach menedżera telemetrii, w efekcie czego funkcje interpolacji (`interpolate_speed`, itp.) zaciskały odczyty do ostatniej próbki z klipu 1.
- **Problem 3 (Rozjazd konwersji czasu):** Obliczenia czasu globalnego w podglądzie nie korzystały bezpośrednio ze zunifikowanych metod osi czasu `VideoTimeline`, co przy różnych przesunięciach początkowych prowadziło do niezgodności.

### C. GPMF Stall / Zawieszenie paska na ~70% (P1)
- **Problem:** W `build_timeline_from_paths` w `src/multifile.py`, `resolve_clip_timestamp` dla każdego klipu z osobna uruchamiał proces ekstrakcji GPMF przez FFmpeg, ignorując fakt, że przetworzona telemetria mogła już znajdować się w pamięci podręcznej `.telemetry.json.gz`.
- W `project_mixin.py` funkcja `_load_telemetry_threaded` raportowała postęp w sposób skokowy (np. 30% -> 70%) bez podziału na poszczególne klipy w projekcie wieloplikowym.

---

## 3. Zastosowane rozwiązania i architektura

### A. Multi-File Robust Two-Stage Mux (`src/ffmpeg/amd_native_exporter.py`)
Dla projektów wieloplikowych wprowadzono sprawdzony, deterministyczny model **Two-Stage Muxing**:
1. **Stage A (GPU Native Stream):** Silnik AMD D3D11 renderuje i koduje wideo w pełnym tempie GPU bezpośrednio do pliku tymczasowego `.part.temp_video.mp4` bez audio (`-an -c:v copy`). Eliminuje to jakiekolwiek opóźnienia i blokady rury stdin/audio ze strony demuksera `-f concat`.
2. **Stage B (Audio Concat Script):** Generowany jest precyzyjny skrypt konkatenacji audio z dokładnymi punktami wejścia/wyjścia (`inpoint`, `outpoint`) dla każdego klipu na podstawie `video_timeline`.
3. **Stage C (Fast Stream-Copy Remux):** FFmpeg w ułamku sekundy (ok. 200 ms) łączy gotowe bezstratne wideo z połączoną ścieżką audio:
   ```cmd
   ffmpeg -y -i <temp_video.mp4> -f concat -safe 0 -i <audio_concat.txt> -map 0:v -map 1:a? -c:v copy -c:a copy -shortest -f mp4 <output.part>
   ```
4. **Stage D (Atomic Finalization):** Po zweryfikowaniu integralności pliku kontener `.part` jest atomowo przenoszony do docelowego pliku `.mp4`.
5. **Gwarancja bezpieczeństwa:** Jeżeli z jakiegokolwiek powodu etap C lub D napotka błąd, plik tymczasowy z wyrenderowanym wideo (`.temp_video.mp4`) **NIE JEST USUWANY**, co uniemożliwia utratę wielogodzinnego renderu!
6. **Filtrowanie logów stderr:** Funkcja `_filter_logical_stderr` filtruje powroty karetki `\r`, zachowując czytelne komunikaty błędów FFmpeg i eliminując spam w logach.
7. **Single-File Preservation:** Dla renderu pojedynczego pliku zachowano bezpośredni live mux z elastycznym czasem oczekiwania: `timeout = max(60.0, duration_s * 0.25)`.

### B. Naprawa osi czasu i odtwarzacza podglądu (`src/multifile.py`, `src/gui/qt/_mixins/playback_mixin.py`, `src/gui/qt/_mixins/preview_mixin.py`)
1. **Kanonizacja w `VideoTimeline`:** W `src/multifile.py` dodano kanoniczne metody:
   - `clip_local_to_global(clip_index, local_time)`
   - `clip_local_to_absolute(clip_index, local_time, base_dt)`
   oraz modułowe funkcje pomocnicze `canonical_clip_local_to_global`, `canonical_clip_local_to_absolute`.
2. **Preview Scrubber:** W `preview_mixin.py` metody `_local_to_global` oraz `_resolve_preview_time` delegują bezpośrednio do metod kanonicznych `VideoTimeline`.
3. **Bezpieczny cykl życia przejścia klipu:** W `playback_mixin.py` obsługa przewijania (`_on_seek_changed`) zastąpiła zawodny `wait_until_playing` wywołaniem `wait_for_property("seekable")`. Całość została objęta blokiem `try ... finally`, gwarantując, że `_source_transition_in_progress = False` oraz `_mpv_pending_seek_s = None` są zawsze zerowane, nawet w trybie pauzy.
4. **Diagnostyka czasu podglądu:** Dodano kontrolowane logowanie diagnostyczne `[PREVIEW_TIME]` (maksymalnie 1/s) w postaci:
   ```text
   [PREVIEW_TIME] clip=X/Y local=... global=... absolute=... slider=... telemetry_index=...
   ```

### C. Wieloplikowe ładowanie telemetrii i cache GPMF (`src/gui/qt/_mixins/project_mixin.py`, `src/multifile.py`)
1. **Pętla po wszystkich klipach:** W `_load_or_generate_telemetry` zaimplementowano funkcję `_load_single_clip_telemetry(p)` i agregację próbek telemetrii (`speed_samples`, `track_samples`, `alt_samples`, `field_samples`) dla wszystkich plików w projekcie.
2. **Płynny postęp:** Pasek postępu emituje rzeczywiste wartości procentowe proporcjonalnie do analizowanego klipu: `pct = 30 + int(35 * (idx / total_clips))` z etykietą `Analiza GPMF (i/N)...`.
3. **Szybki warm cache:** W `src/multifile.py` funkcja `resolve_clip_timestamp` sprawdza najpierw `read_processed_cache` dla pliku `.telemetry.json.gz`, eliminując powtarzające się, minutowe wywołania FFmpeg przy tworzeniu osi czasu.

---

## 4. Zmodyfikowane pliki

- `src/ffmpeg/amd_native_exporter.py`: Two-Stage Mux dla multi-file, filtr stderr, bezpieczne timeouty, zachowanie wideo w razie błędu.
- `src/gui/qt/_mixins/playback_mixin.py`: `finally:` dla flagi przejścia klipów, usunięcie zawieszającego `wait_until_playing`, log diagnostyczny `[PREVIEW_TIME]`.
- `src/gui/qt/_mixins/preview_mixin.py`: kanoniczna delegacja konwersji czasu do `VideoTimeline`.
- `src/gui/qt/_mixins/project_mixin.py`: ładowanie i scalanie telemetrii dla wszystkich klipów multi-file, proporcjonalny postęp GPMF, fallback daty początkowej.
- `src/multifile.py`: metody kanoniczne `clip_local_to_global`, `clip_local_to_absolute`, sprawdzanie `read_processed_cache` w `resolve_clip_timestamp`.
- `def_layout.json`: **NIETKNIĘTY** (zachowano oryginalne lokalne zmiany użytkownika).

---

## 5. Wyniki testów weryfikacyjnych

### Test 1: MULTIFILE LOAD
- **Skrypt:** `scratch/test_multifile_load.py`
- **Dane:** `Video/GX010114.MP4` + `Video/GX010115.MP4` (łączny czas 107.7 minuty)
- **Wynik:**
  - Utworzenie osi czasu z cache: **92.9 ms** (brak zawieszeń na 70%)
  - Całkowita liczba wczytanych próbek prędkości: **25,483** (pokrycie obu klipów)
  - Średnia prędkość Klip 1 (t=500s): `19.12 km/h`
  - Średnia prędkość Klip 2 (t=3800s): `18.59 km/h` (brak zamrożenia / brak ekstrapolacji ze schyłku klipu 1)
- **Werdykt:** **PASS**

### Test 2: MULTIFILE PREVIEW
- **Skrypt:** `scratch/test_multifile_preview_scrubber.py`
- **Weryfikacja:** 6 punktów seeku wzdłuż osi czasu obejmujących oba klipy i przejście graniczne
- **Wyniki próbkowania pozycji:**
  1. `t=0.0s`: clip=0, local=0.00s, global=0.00s, telem_idx=0
  2. `t=1000.0s`: clip=0, local=1000.00s, global=1000.00s, telem_idx=3942
  3. `t=3200.0s`: clip=0, local=3200.00s, global=3200.00s, telem_idx=12615
  4. `t=3235.0s`: clip=1, local=3.87s, global=3235.00s, telem_idx=12753
  5. `t=4000.0s`: clip=1, local=768.87s, global=4000.00s, telem_idx=15769
  6. `t=6000.0s`: clip=1, local=2768.87s, global=6000.00s, telem_idx=23653
- **Test przejścia klipu w MPV:** Flaga `_source_transition_in_progress` poprawnie resetowana do `False` po skoku w stanie pauzy.
- **Werdykt:** **PASS**

### Test 3: MULTIFILE RENDER
- **Skrypt:** `scratch/test_multifile_render_twostage.py` (Part 1)
- **Konfiguracja:** 300 klatek na granicy klipów GX010114 (150 klatek) -> GX010115 (150 klatek), rozdzielczość 4K (3840x2160), AMD Native D3D11 + AMF HEVC.
- **Przebieg wykonania:**
  - Stage A (Wideo): 300 klatek w 7.132 s (Render FPS: 42.062)
  - Stage B (Audio concat): natychmiastowe utworzenie skryptu
  - Stage C (Remux): **213.49 ms** (rc=0)
  - Finalizacja: 0.215 s
- **Weryfikacja pliku wyjściowego (`ffprobe`):**
  - Czas trwania kontenera: 10.010 s (dokładnie 300 klatek przy 29.970 FPS)
  - Wideo: HEVC, `nb_frames=300`
  - Audio: AAC obecne, brak desynchronizacji
  - Plik końcowy poprawnie utworzony, pliki tymczasowe wyczyszczone
- **Werdykt:** **PASS**

### Test 4: SINGLE FILE REGRESSION
- **Skrypt:** `scratch/test_multifile_render_twostage.py` (Part 2)
- **Konfiguracja:** GX010115 150 klatek 4K, ścieżka single-file live mux.
- **Przebieg wykonania:**
  - Tryb: `[AMD DIRECT MUX] mode=single clips=1 video=pipe audio=source`
  - Video encode: 3.495 s (Render FPS: 42.924)
  - Finalize: 0.014 s
- **Weryfikacja pliku wyjściowego (`ffprobe`):**
  - Czas trwania kontenera: 5.013 s
  - Wideo: HEVC, `nb_frames=150`
  - Audio: AAC obecne
- **Werdykt:** **PASS**

---

## 6. Izolacja backendów

- Wszystkie wprowadzone zmiany w renderowaniu dotyczą wyłącznie modułu `src/ffmpeg/amd_native_exporter.py` i ścieżki AMD.
- Backend Intel (QSV) oraz NVIDIA (NVENC/CUDA) nie zostały zmodyfikowane.
- Zmiany w `multifile.py` oraz mixinach GUI (`playback_mixin.py`, `preview_mixin.py`, `project_mixin.py`) są neutralne i zorientowane wyłącznie na poprawność zarządzania czasem wieloplikowym.

---

## 7. Podsumowanie werdyktów

| Obszar | Status | Uwagi |
| :--- | :---: | :--- |
| **MULTIFILE LOAD** | **PASS** | Cache GPMF (<100ms), 25k próbek, proporcjonalny pasek postępu |
| **MULTIFILE PREVIEW** | **PASS** | Zresetowane flagi przejścia, poprawny scrubber i telemetria na Klipie 2 |
| **MULTIFILE RENDER** | **PASS** | Two-stage mux, zachowanie wideo w razie awarii, 300/300 klatek w 4K |
| **SINGLE FILE REGRESSION** | **PASS** | Bezpośredni live mux nienaruszony, 150/150 klatek w 4K |
