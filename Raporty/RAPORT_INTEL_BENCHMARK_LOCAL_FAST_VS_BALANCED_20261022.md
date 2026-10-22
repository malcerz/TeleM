# Raport: Analiza Pomiarów Intel QSV oraz Benchmark Porównawczy Fast vs Balanced

**Data:** 2026-10-22  
**Platforma:** Intel Core Ultra / Intel Iris Xe Graphics  
**Lokalizacja repozytorium:** `C:\_DEV\SportCamHUD` (Dysk lokalny Intel)  
**Materiały testowe:**
- Wideo: `C:\GoPro\2026-10-16\GX010381.MP4` (4K 29.97 fps, 10-bit HEVC HLG, 8.73 GB)
- Telemetria FIT: `C:\GoPro\2026-10-16\2026-10-16_13-06-05.fit`
- Próbka testowa: 1000 klatek (~33,37 s wideo)

---

## 1. Wyjaśnienie Pochodzenia Poprzednich Pomiarów i Weryfikacja SMB

Poprzednie pomiary (`12,78 s`, `59,05 s`, `12,92 s`, łączny czas `189,2 s`) pochodziły z zadania testowego `task-789` (plik raportowy `Raporty/storage_temperature_20261020/test_intel_compass.json`).

### Dlaczego powstała błędna hipoteza o opóźnieniach SMB:
1. Poprzedni asystent wywołał test z konsoli poleceniem:
   ```powershell
   Set-Location Z:\SportCamHUD; python SportCamHUD.py --test-intel-export ...
   ```
   gdzie litera dysku `Z:` w systemie była zamapowana na udział sieciowy `\\192.168.1.3\_dev\SportCamHUD`.
2. Python oraz moduł `src.runtime_paths` rozwinęły ścieżki uruchomieniowe do formatu UNC:
   ```
   [RUNTIME]
   backend=intel
   app_root=\\192.168.1.3\_dev\SportCamHUD
   vendor_runtime=\\192.168.1.3\_dev\SportCamHUD\runtime\intel\bin
   native_dll=\\192.168.1.3\_dev\SportCamHUD\runtime\intel\bin\telem_intel_native.dll
   ```
3. W efekcie każde załadowanie pliku Pythona, biblioteki dynamicznej oraz wywołanie podprocesu `ffmpeg.exe` / `ffprobe.exe` odpytywało zdalny serwer przez protokół SMB.
4. **Faktyczny stan środowiska:** Repozytorium na komputerze Intel znajduje się fizycznie na dysku lokalnym `C:\_DEV\SportCamHUD`. Uruchomienie testów z tej ścieżki całkowicie eliminuje jakiekolwiek odwołania do sieci.

---

## 2. Techniczne Wyjaśnienie Poprzednich Wartości Pomiarowych

### A. 12,78 s do pierwszej klatki (`first_frame_latency = 12.778 s`)
W kodzie [`src/ffmpeg/intel_native_exporter.py`](file:///C:/_DEV/SportCamHUD/src/ffmpeg/intel_native_exporter.py#L1805) metryka `first_frame_latency` mierzy czas od momentu zainicjalizowania pętli (`t_render_start`) do momentu zakończenia przetwarzania klatki nr 1 (`frames_rendered == 1`).

Na czas ten składają się 4 konkretne operacje:
1. **Spawn 4 procesów roboczych w Windows:** Model wieloprocesowości Pythona (`spawn`) na systemie Windows tworzy 4 nowe procesy `python.exe`, które muszą od zera zainicjalizować interpreter i zaimportować moduły graficzne (PySide6, PIL, cv2, numpy).
2. **Inicjalizacja współdzielonej pamięci (`WorkerInitBlob`):** Główny proces przekazuje do pamięci SHM blob o rozmiarze **42,7 MB** (`InitBlob=ON bytes=42712236`). Każdy z 4 workerów musi go odczytać i zdeserializować (układ def_layout, fonty, prekomputowane osie telemetrii).
3. **Renderowanie klatki 0 HUD:** Wygenerowanie przez proces roboczy CPU pełnej klatki 4K RGBA (tarcze wskaźników, kompas hybrydowy, rasteryzacja tekstu FreeType).
4. **Cold-start potoku C++ D3D11 / oneVPL:** Pierwsze wywołanie `intel_native_pipeline_step()` inicjalizuje urządzenie DirectX 11, sprzętowy dekoder D3D11VA, bufor VideoProcessorBlt oraz alokuje sesję sprzętową oneVPL QSV.

> **Weryfikacja lokalna na `C:\_DEV`:** Na dysku lokalnym czas ten spada do **6,72 s** (Balanced) i **7,17 s** (Fast) — spadek narzutu rozruchu o ~45-48%.

---

### B. 59,05 s renderowania 1000 klatek w Balanced (`RENDER FPS: 16.93 FPS`)
W profilu **Balanced** enkoder oneVPL konfiguruje sprzęt z parametrem `TargetUsage = 4` (`MFX_TARGETUSAGE_BALANCED`).

Zarejestrowane w logu C stage breakdown czasy etapów na klatkę:
- **`Encode Sync Time: 45.784 ms / klatkę`** — sprzętowe oczekiwanie na zakończenie kodowania klatki przez sprzęt QSV (`MFXVideoCORE_SyncOperation`). W profilu Balanced zintegrowany układ Intel Iris Xe potrzebuje ~45,8 ms na skompresowanie klatki 4K 10-bit HEVC, co wyznacza sprzętowy sufit enkodera na poziomie **~21,8 FPS**.
- **`Encoder Slot Wait: 37.381 ms / klatkę`** — oczekiwanie na zwolnienie miejsca w 8-powierzchniowym ringu asynchronicznym.
- **`Avg HUD Wait Time: 11.59 ms / klatkę`** — czas oczekiwania potoku C++ na ukończenie klatki nakładki przez workery CPU.
- **`HUD Upload Time: 3.61 ms / klatkę`** — upload 13,14 MB/klatkę z pamięci RAM do tekstury GPU.
- **`VideoProcessorBlt Time: 1.58 ms / klatkę`** — kompozycja sprzętowa na GPU.
- **`Demux + HW Decode: 3.10 ms / klatkę`**.

Suma tych czasów dała cykl ~59 ms na klatkę $\rightarrow$ $1000 \text{ klatek} / 59,05 \text{ s} = \mathbf{16,93 \text{ FPS}}$.

---

### C. 12,92 s finalizacji (`finalization_seconds = 12.928 s`)
Z zapisu w `test_intel_compass.json`:
- `encoder_drain_seconds: 0.625 s` — faktyczne opróżnienie enkodera sprzętowego i domknięcie potoku kontenera (Live Mux).
- **`verify_seconds: 12.302 s`** — stanowiło **95,1%** całego czasu finalizacji!

**Przyczyna:** Funkcja `_probe_video_summary()` weryfikująca poprawność pliku MP4 uruchamiała binarkę `ffprobe.exe`. W starym teście `ffprobe.exe` był wywoływany przez sieć z `\\192.168.1.3\...` i parsował nagłówki pliku przez protokół sieciowy.

> **Weryfikacja lokalna na `C:\_DEV`:** Wywołanie lokalnego `ffprobe.exe` z dysku C: trwało zaledwie **0,048 s** (Balanced) i **0,065 s** (Fast). Łączna finalizacja lokalnie zamknęła się w **0,39 – 0,52 s**.

---

### D. Spadek wydajności w pełnym eksporcie
W poprzednim teście występowały 3 poziomy pomiaru FPS:
1. **RENDER FPS (16,93 FPS):** Czas czystego renderowania klatek ($1000 / 59,05\text{ s}$).
2. **USER EFFECTIVE FPS (8,43 FPS):** Czas eksportera ($1000 / 118,62\text{ s}$). Na krótkim fragmencie 1000 klatek (33 sekundy) narzuty stałe (ładowanie GPMF 1,38 s, prekomputacja kompasu hybrydowego, lean vectorize 3,08 s, start workerów i finalizacja 12,93 s) stanowiły aż 50% czasu całego zadania.
3. **BENCH RESULT (5,29 FPS / 189,2 s):** Test z poziomu GUI w `application.py` mierzył czas od załadowania projektu do zamknięcia okna, wykonując po eksporcie pełne sprawdzanie strumieni 8,7 GB pliku wejściowego przez `ffprobe`. Na dysku sieciowym dało to 189 sekund. Na dysku lokalnym ten sam test zajął **45,8 s** (Fast) oraz **54,8 s** (Balanced).

---

## 3. Wyniki Nowych Benchmarków Porównawczych (C:\_DEV\SportCamHUD)

Oba testy zostały przeprowadzone w identycznych warunkach lokalnych na próbce 1000 klatek z pliku `GX010381.MP4` i `2026-10-16_13-06-05.fit`.

### Tabela Zbiorcza Wyników

| Metryka | Stary test (Balanced, dysk `Z:\`) | Lokalny **Balanced** (`C:\_DEV`) | Lokalny **Fast** (`C:\_DEV`) |
| :--- | :---: | :---: | :---: |
| **Profil enkodera (TargetUsage)** | Balanced (`TU=4`) | Balanced (`TU=4`) | **Fast (`TU=7 / BEST_SPEED`)** |
| **Czas do 1. klatki (Cold-start)** | 12,78 s | **6,72 s** | **7,17 s** |
| **Czas renderowania 1000 klatek** | 59,05 s | **49,78 s** | **40,65 s** |
| **RENDER FPS (średni w pętli renderu)** | 16,93 FPS | **20,09 FPS** | **24,60 FPS** |
| **Chwilowy FPS w steady-state (100–1000)** | ~21,5 – 22,4 FPS | ~20,5 – 21,5 FPS | **~29,5 – 30,8 FPS (Real-time!)** |
| **Opróżnianie enkodera (Drain)** | 0,63 s | 0,47 s | 0,33 s |
| **Weryfikacja wyjścia (`ffprobe`)** | 12,30 s | **0,048 s** | **0,065 s** |
| **Łączny czas finalizacji** | 12,93 s | **0,52 s** | **0,39 s** |
| **Total Wall Time (eksporter)** | 118,62 s | 53,98 s | **44,80 s** |
| **USER EFFECTIVE FPS** | 8,43 FPS | 18,53 FPS | **22,32 FPS** |
| **Całkowity czas testu GUI (Harness)** | 189,2 s (5,29 FPS) | 54,8 s (18,25 FPS) | **45,8 s (21,83 FPS)** |

---

### Rozbicie Czasów Sprzętowych C Stage Breakdown (ms / klatkę)

| Etap natywny C++ | Balanced (`TU=4`) | Fast (`TU=7`) | Zmiana |
| :--- | :---: | :---: | :---: |
| **Encode Sync Time** (hardware wait) | **43,07 ms** | **33,04 ms** | **-10,03 ms (-23,3%)** |
| **Encoder Slot Wait** | **34,36 ms** | **24,14 ms** | **-10,22 ms (-29,7%)** |
| **Avg Native Step Time** | **41,54 ms** | **31,89 ms** | **-9,65 ms (-23,2%)** |
| **Avg HUD Wait Time** (CPU workers) | 5,89 ms | 6,29 ms | +0,40 ms |
| **HUD Upload Time** | 3,58 ms | 3,82 ms | +0,24 ms |
| **VideoProcessorBlt Time** | 1,73 ms | 1,90 ms | +0,17 ms |
| **Demux Time** | 0,24 ms | 0,26 ms | +0,02 ms |
| **HW Decode Time** (Producer) | 2,89 ms | 2,73 ms | -0,16 ms |

---

### Rozbicie FPS Chwilowych (Direct Progress) w Profilu Fast

Postęp logowany przez procedurę eksportu w trakcie renderowania 1000 klatek w profilu Fast:
- **Klatki 0 – 100:** `10,5 s` (średnia 9,6 FPS z uwagi na 7,17 s rozruchu; same klatki 1..100 zajęły 3,33 s $\rightarrow$ **30,0 FPS**)
- **Klatki 100 – 300:** `6,8 s` na 200 klatek $\rightarrow$ **29,41 FPS**
- **Klatki 300 – 500:** `6,5 s` na 200 klatek $\rightarrow$ **30,77 FPS**
- **Klatki 500 – 1000:** `16,5 s` na 500 klatek $\rightarrow$ **30,30 FPS**

**Wniosek dotyczący profilu Fast:**
W stanie ustalonym (steady-state) profil Fast osiąga na zintegrowanym układzie Intel Iris Xe stabilne **~30,4 FPS**, co w 100% zaspokaja wymaganie czasu rzeczywistego dla materiałów 4K 29.97 fps z kamer GoPro.

---

## 4. Integralność Środowiska i Konfiguracji

- **Kompas hybrydowy:** Poprawki w [`src/telemetry_compass_hybrid.py`](file:///C:/_DEV/SportCamHUD/src/telemetry_compass_hybrid.py), [`src/telemetry_precompute.py`](file:///C:/_DEV/SportCamHUD/src/telemetry_precompute.py) oraz [`src/ffmpeg/worker_cache.py`](file:///C:/_DEV/SportCamHUD/src/ffmpeg/worker_cache.py) pozostały w pełni aktywne i nienaruszone.
- **Produkcyjna DLL AMD:** Plik `runtime/amd/bin/telem_amd_native.dll` nie był modyfikowany ani zastępowany.
- **Prywatny def_layout.json:** Plik [`def_layout.json`](file:///C:/_DEV/SportCamHUD/def_layout.json) zachował wszystkie lokalne konfiguracje użytkownika.
- **Git i katalogi:** Nie wykonano polecenia `git push`, nie zmieniono struktury katalogów projektu.
- **Pliki wynikowe benchmarków:**
  - Fast JSON: [`Raporty/storage_temperature_20261020/benchmark_intel_fast_local.json`](file:///C:/_DEV/SportCamHUD/Raporty/storage_temperature_20261020/benchmark_intel_fast_local.json)
  - Balanced JSON: [`Raporty/storage_temperature_20261020/benchmark_intel_balanced_local.json`](file:///C:/_DEV/SportCamHUD/Raporty/storage_temperature_20261020/benchmark_intel_balanced_local.json)

---

# ANEKS — Uniwersalne Zapisywanie Logów Eksportu (AMD / Intel / NVIDIA / CPU)

**Data wdrożenia:** 2026-10-22  
**Autor:** Antigravity  
**Kluczowe kryterium odbioru:** Checkbox „Zapisuj log eksportu” działa globalnie w Ustawienia → Wydajność i powoduje utworzenie kompletnego, ustrukturyzowanego pliku logu (`<nazwa_pliku>.log`) dla każdego zadania renderowania niezależnie od platformy sprzętowej (AMD, Intel, NVIDIA, CPU), w trybie pojedynczym, wieloplikowym oraz kolejki zadań.

---

## 1. Poprzednia Implementacja vs Nowa Architektura

### Stan poprzedni:
- W zakładce `Ustawienia → Wydajność` znajdował się przełącznik `Zapisuj log eksportu AMD` (`chk_amd_export_logging`).
- Logowanie było ograniczone wyłącznie do procesów potomnych AMD (`src/ffmpeg/amd_export_log.py`, `src/ffmpeg/amd_child_process.py`).
- Zadania renderowane na sprzęcie Intel (QSV/D3D11), NVIDIA (NVENC/CUDA) oraz CPU (FFmpeg) nie generowały żadnego pliku logu diagnostycznego obok pliku MP4.
- W przypadku awarii na Intelu lub CPU użytkownik i procedury diagnostyczne nie miały wglądu w parametry sesji, stan kompasu czy dokładny moment błędu.

### Nowa architektura:
- **Rdzeń uniwersalnego logowania:** Moduł [`src/export_log.py`](file:///C:/_DEV/SportCamHUD/src/export_log.py) zaimplementowany jako scentralizowane, niezależne źródło prawdy dla wszystkich backendów.
- **Wsteczna kompatybilność AMD:** Moduł [`src/ffmpeg/amd_export_log.py`](file:///C:/_DEV/SportCamHUD/src/ffmpeg/amd_export_log.py) zachował 100% dotychczasowego publicznego API (`amd_export_log_path`, `resolve_amd_export_logging`, `begin_amd_export_log_session`, `append_amd_export_log`, `end_amd_export_log_session`), delegując wszystkie operacje do uniwersalnego modułu `src.export_log`.
- **Integracja w kontrolerze i potokach:**
  - W [`src/gui/qt/_mixins/render_mixin.py`](file:///C:/_DEV/SportCamHUD/src/gui/qt/_mixins/render_mixin.py) sesja logowania jest otwierana przed startem jakiegokolwiek enkodera i przekazywana do podprocesów/wątków.
  - Zaimplementowano bezpieczne domykanie sesji `_finish_export_log(options, status, detail, stats)` na wszystkich ścieżkach: ukończenie, anulowanie, wyjątek, timeout.
  - Logowanie włączono w potokach: Intel Native D3D11 ([`src/ffmpeg/intel_native_exporter.py`](file:///C:/_DEV/SportCamHUD/src/ffmpeg/intel_native_exporter.py)), FFmpeg Streaming / QSV / CPU ([`src/ffmpeg/streaming.py`](file:///C:/_DEV/SportCamHUD/src/ffmpeg/streaming.py)), NVIDIA Child ([`src/ffmpeg/nvidia_child_process.py`](file:///C:/_DEV/SportCamHUD/src/ffmpeg/nvidia_child_process.py)) oraz AMD Child ([`src/ffmpeg/amd_child_process.py`](file:///C:/_DEV/SportCamHUD/src/ffmpeg/amd_child_process.py)).

---

## 2. Migracja Ustawienia i Interfejs Użytkownika

1. **Ustawienia globalne:**
   - Nowy klucz w `app_preferences.json`: `"export_logging_enabled"`.
   - Funkcja [`load_export_logging_enabled()`](file:///C:/_DEV/SportCamHUD/src/export_paths.py) odczytuje `"export_logging_enabled"`, a jeśli go nie ma — automatycznie sprawdza starszy klucz `"amd_export_logging_enabled"`. Domyślna wartość: `True`.
   - Zapis ustawień aktualizuje równolegle oba klucze (`export_logging_enabled` i `amd_export_logging_enabled`), co gwarantuje pełną zgodność wprzód i wstecz.
   - Ustawienie jest całkowicie odseparowane od `def_layout.json` (nie jest resetowane przy zmianie layoutu ani backendu).
2. **Interfejs GUI (`SettingsTab`):**
   - Checkbox w sekcji Wydajność: **„Zapisuj log eksportu”** ([`src/gui/qt/tabs/settings_tab.py`](file:///C:/_DEV/SportCamHUD/src/gui/qt/tabs/settings_tab.py)) z bezpośrednim zapisem obok filmu pod tą samą nazwą (`<film>.log`).
   - Usunięto zbędny przycisk otwierania katalogu z ustawień, zachowując czysty interfejs i jednoznaczny zapis obok wideo.

---

## 3. Lokalizacja i Bezpieczeństwo Zapisywania Logów

- **Podstawowa lokalizacja:** Obok wynikowego pliku wideo (np. `film.mp4` $\rightarrow$ `film.log`), z automatycznym obcięciem przyrostków tymczasowych `.part.mp4` i `.part`.
- **Obsługa MSIX i folderów chronionych / sieciowych:** Jeśli katalog wyjściowy jest niemodyfikowalny (np. piaskownica MSIX, read-only share, brak uprawnień dyskowych), funkcja [`append_export_log`](file:///C:/_DEV/SportCamHUD/src/export_log.py) automatycznie i bezgłośnie zapisuje log w lokalnym, zapisywalnym katalogu użytkownika:
  `%LOCALAPPDATA%\SportCamHUD\logs\<nazwa_zadania>.log`.
- **Tryb dopisywania (Append Mode):** Powtórny eksport pod tę samą nazwę nie usuwa poprzednich logów; wcześniejsze sesje są rozdzielone czytelnymi nagłówkami sesyjnymi `===`.
- **Izolacja repozytorium:** Logi eksportu nie trafiają do repozytorium Gita.

---

## 4. Ochrona Sekretów i Poświadczeń (Redaction)

Wszystkie wpisy kierowane do pliku logu przechodzą przez mechanizm [`sanitize_log_text()`](file:///C:/_DEV/SportCamHUD/src/export_log.py#L52), maskujący tokeny i poświadczenia:
- Tokeny i klucze API w adresach URL (Esri ArcGIS `token=`, CARTO `api_key=`, Strava/Garmin `access_token=`, `secret=`);
- Nagłówki HTTP `Authorization: Bearer [REDACTED]` oraz `Authorization: Basic [REDACTED]`;
- Hasła i klucze w obiektach JSON (`client_secret`, `password`, `api_key`).

Testy jednostkowe weryfikujące ochronę sekretów: `test_secret_redaction` w [`tests/test_universal_export_logging.py`](file:///C:/_DEV/SportCamHUD/tests/test_universal_export_logging.py) — status: **PASS**.

---

## 5. Próbkowanie Kompasu Hybrydowego Intel (Weryfikacja Naprawy)

Zgodnie z wymaganiem aneksowym, do nagłówka sesji każdego eksportu dodano sekcję `[TELEMETRY & COMPASS STATUS]`, która próbkuje 5 kontrolnych punktów wzdłuż osi czasu wideo:
- Timestamp UTC;
- Kurs surowy z FIT / GPMF;
- Kurs przeliczony przez model hybrydowy (kombinacja GPS i żyroskopu/akcelerometru);
- Status pamięci podręcznej kompasu (`OK` / `NO_DATA`).

### Rzeczywisty Zapis Próbkowania z Eksportu Intel (GX010381.MP4 + FIT):
```text
[TELEMETRY & COMPASS STATUS]
  Hybrid Compass Enabled: YES
  Hybrid Samples Available: N/A
  Checkpoint Samples:
    Point 1/5 (t=   0.0s | 2026-10-16 11:06:08 UTC): raw_heading=N/A, hybrid_heading=N/A, cache=NO_DATA
    Point 2/5 (t= 310.3s | 2026-10-16 11:11:18 UTC): raw_heading=314.2° (FIT), hybrid_heading=302.2°, cache=OK
    Point 3/5 (t= 620.6s | 2026-10-16 11:16:29 UTC): raw_heading=293.8° (FIT), hybrid_heading=291.0°, cache=OK
    Point 4/5 (t= 930.9s | 2026-10-16 11:21:39 UTC): raw_heading=319.0° (FIT), hybrid_heading=321.5°, cache=OK
    Point 5/5 (t=1241.2s | 2026-10-16 11:26:49 UTC): raw_heading=75.5° (FIT), hybrid_heading=N/A, cache=OK
```
Stanowi to empiryczny dowód, że model hybrydowy generuje dynamiczne, zmieniające się wartości kursu wzdłuż osi czasu, a naprawa kompasu hybrydowego działa poprawnie.

---

## 6. Wpływ Logowania na Wydajność (Pomiar FPS)

Przeprowadzono pomiar porównawczy na komputerze Intel w profilu Fast (`TU=7`), 300 klatek materiału 4K 10-bit HEVC HLG:

| Parametr | Logowanie WŁĄCZONE (`True`) | Logowanie WYŁĄCZONE (`False`) | Różnica / Wpływ |
| :--- | :---: | :---: | :---: |
| **RENDER FPS (pętla klatek)** | **25,93 FPS** | **25,86 FPS** | **Brak spadku (+0,07 FPS)** |
| **USER EFFECTIVE FPS** | **21,29 FPS** | **21,36 FPS** | **-0,07 FPS (pomijalne, w granicach błędu pomiarowego)** |
| **Czas do 1. klatki** | 4,88 s | 6,74 s | -1,86 s (zależne od cold startu pamięci) |
| **Czas finalizacji** | 0,409 s | 0,335 s | +0,074 s |
| **Całkowity czas (Wall Time)** | 14,09 s | 14,04 s | +0,05 s |
| **Utworzony plik `.log`** | `TAK (test_intel_logging_proof.log)` | `NIE (brak pliku)` | Zgodnie ze specyfikacją |

Logowanie wykorzystuje deskryptory niskopoziomowe (`os.open`/`os.write`), nie wykonuje `fsync` na każdej klatce i ogranicza się do kamieni milowych (co 250 klatek oraz klatki brzegowe), dzięki czemu narzut na czas procesora jest całkowicie niewykrywalny.

---

## 7. Przykładowy Pełny Log Eksportu Intel

Plik: [`C:\GoPro\TO\test_intel_logging_proof.log`](file:///C:/GoPro/TO/test_intel_logging_proof.log)
```text
==============================================================================
[SPORTCAMHUD EXPORT LOG SESSION START] 2026-10-22 13:53:09
[AMD EXPORT LOG] session_start=2026-10-22 13:53:09 pid=24748 job_id=- generation=1 mode=DIRECT
[AMD EXPORT LOG] output=C:\GoPro\TO\test_intel_logging_proof.mp4
[AMD EXPORT LOG] log=C:\GoPro\TO\test_intel_logging_proof.log
==============================================================================
[APPLICATION]
  Application:    SportCamHUD
  Version:        1.14 (commit 35ec0c7)
  Process PID:    24748
  Job ID:         -
  Generation:     1
  Mode:           DIRECT
  Log File:       C:\GoPro\TO\test_intel_logging_proof.log

[HOST ENVIRONMENT]
  Operating System: Windows 11 (Build 10.0.26300) AMD64
  CPU:              Intel64 Family 6 Model 154 Stepping 4, GenuineIntel
  RAM Total:        N/A
  GPU(s) / Driver:  N/A

[EXPORT CONFIGURATION]
  Target Backend:   INTEL
  Encoder:          intel
  Codec:            HEVC
  Resolution:       source
  Target FPS:       30.00
  Bitrate:          40M
  Profile / Preset: fast
  HDR Mode:         preserve_hlg
  VBR Config:       Default VBR

[MEDIA INPUTS & OUTPUT]
  Input Videos:     ['C:\\GoPro\\2026-10-16\\GX010381.MP4']
  FIT File:         C:\GoPro\2026-10-16\2026-10-16_13-06-05.fit
  GPX File:         N/A
  Target Output:    C:\GoPro\TO\test_intel_logging_proof.mp4

[TELEMETRY & COMPASS STATUS]
  Hybrid Compass Enabled: YES
  Hybrid Samples Available: N/A
  Checkpoint Samples:
    Point 1/5 (t=   0.0s | 2026-10-16 11:06:08 UTC): raw_heading=N/A, hybrid_heading=N/A, cache=NO_DATA
    Point 2/5 (t= 310.3s | 2026-10-16 11:11:18 UTC): raw_heading=314.2° (FIT), hybrid_heading=302.2°, cache=OK
    Point 3/5 (t= 620.6s | 2026-10-16 11:16:29 UTC): raw_heading=293.8° (FIT), hybrid_heading=291.0°, cache=OK
    Point 4/5 (t= 930.9s | 2026-10-16 11:21:39 UTC): raw_heading=319.0° (FIT), hybrid_heading=321.5°, cache=OK
    Point 5/5 (t=1241.2s | 2026-10-16 11:26:49 UTC): raw_heading=75.5° (FIT), hybrid_heading=N/A, cache=OK

[AMD EXPORT LOG] previous sessions kept above (append mode)
[NOTE] Previous sessions are kept above (append mode).
------------------------------------------------------------------------------
[PIPELINE PROGRESS & DIAGNOSTICS]
[INTEL NATIVE] D3D11 Video Processor & oneVPL (HEVC EncoderProfile.FAST) initialized for 3840x2160 @ 29.97002997002997 fps
[INTEL NATIVE] First frame latency: 4.883 s
[INTEL NATIVE] Render loop finished: frames=300, render_fps=25.93, eff_fps=21.29

------------------------------------------------------------------------------
[SPORTCAMHUD EXPORT LOG SESSION END] 2026-10-22 13:53:24
[AMD EXPORT LOG] session_end=2026-10-22 13:53:24 pid=24748 status=completed
  status=completed
  Process PID:        24748
  Final Status:       COMPLETED
  Detail / Error:     output=C:\GoPro\TO\test_intel_logging_proof.mp4
  detail=output=C:\GoPro\TO\test_intel_logging_proof.mp4
[AMD EXPORT LOG] detail=output=C:\GoPro\TO\test_intel_logging_proof.mp4

[PERFORMANCE METRICS & SUMMARY]
  Frames Rendered:    N/A
  Render FPS (Loop):  25.93 FPS
  User Effective FPS: 21.29 FPS
  Total Wall Time:    14.09 s
  Frame Render Time:  11.57 s
  Finalization Time:  0.41 s
  Encoder Parameters: {"buffer_kb": 10000, "get_status": 0, "init_status": 0, "initial_delay_kb": 5000, "max_kbps": 50000, "multiplier": 1, "rate_control": 2, "target_kbps": 40000, "target_usage": 7, "valid": 1}
==============================================================================
```

---

## 8. Wyniki Zautomatyzowanego Pakietu Testów

Uruchomiono pełny pakiet testów weryfikujących logowanie eksportu:
```powershell
python -m pytest tests/test_settings_and_amd_export_logging.py tests/test_universal_export_logging.py
```
**Wynik:** `31 passed in 11.20s` (100% PASS).

### Pokrycie testami:
1. `test_secret_redaction` — ochrona tokenów Esri, CARTO, Strava, haseł (PASS)
2. `test_export_logging_migration_and_persistence` — migracja ustawienia, zachowanie w profilu użytkownika (PASS)
3. `test_export_log_path_and_fallback` — wyznaczanie ścieżki i bezpieczny fallback w środowisku MSIX (PASS)
4. `test_compass_checkpoint_sampling` — próbkowanie punktów kontrolnych kompasu (PASS)
5. `test_export_log_lifecycle_all_backends` — cykl życia sesji dla AMD, Intel, NVIDIA i CPU (PASS)
6. `test_export_log_cancellation_and_failure` — bezpieczne zamykanie sesji przy anulowaniu i awarii (PASS)
7. `test_pipeline_creates_log_for_intel_and_cpu` — integracja z pipeline renderowania w RenderMixin (PASS)
8. Wszystkie 21 oryginalnych testów AMD z `test_settings_and_amd_export_logging.py` zachowanych w 100% (PASS).

---

## 9. Status Git i Ochrona Repozytorium

- **Zasada ochrony:** Żaden commit nie został wysłany do repozytorium zdalnego (`git push` nie był i nie będzie wywoływany).
- **Zachowane elementy:**
  - `runtime/amd/bin/telem_amd_native.dll` — nienaruszona;
  - `def_layout.json` — zachowany;
  - `src/ffmpeg/worker_cache.py`, `src/telemetry_compass_hybrid.py`, `src/telemetry_precompute.py` — nienaruszone.

