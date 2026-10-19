# SportCamHUD — Intel D3D11/QSV, 2026-10-17

## Stan i zakres

Praca na aktualnym `main`, HEAD `e21d625`, zgodnie z późniejszym poleceniem użytkownika. Nie przełączano gałęzi. Nie zmieniano backendu AMD, natywnych shaderów, pętli kompozytora D3D11, ustawień ani wyglądu HUD.

Zastane zmiany użytkownika zachowano: `intel_native_exporter.py`, `nvidia_native_exporter.py`, nowy `live_av_mux.py` i `test_live_av_mux.py`. Pliku NVIDIA nie edytowano. Zmiany Intel poniżej nakładają się na zastaną poprawkę live muxowania.

Maszyna rzeczywiście sprawdzona przez CIM: **Intel Core i7-1265U, Intel Iris Xe, sterownik 32.0.101.7085**. Windows; Python systemowy 3.15.0 / PySide6 6.12.0; Portable Python 3.14.7 / PySide6 6.11.1. Native DLL SHA-256: `113abafbab0c877bc406692a4f60d287041d7e6307912a1b6e790d602888ba4b` — bez zmian.

## 1. ProcessPoolExecutor — przyczyna i naprawa

W CPython 3.15 `Lib/concurrent/futures/__init__.py` deklaruje `lazy from .process import ProcessPoolExecutor`. W zwykłym wątku import może poprawnie rozwiązać klasę. Po utworzeniu `QApplication` import tego eksportu pakietu w wątku roboczym zwrócił jednak **`<class 'lazy_import'>`**, a wywołanie zakończyło się dokładnym `TypeError: 'lazy_import' object is not callable`.

Odtworzenie na tym komputerze, niezależne od plików filmu i GPU:

```python
import threading
from PySide6.QtWidgets import QApplication
app = QApplication([])
def worker():
    from concurrent.futures import ProcessPoolExecutor
    executor = ProcessPoolExecutor(1)  # TypeError w tej kombinacji Qt/Python 3.15
thread = threading.Thread(target=worker)
thread.start()
thread.join()
```

Nie znaleziono w kodzie aplikacji własnego nadpisania klasy przez `lazy_import`. Obiekt pochodzi z mechanizmu lazy imports biblioteki standardowej, ujawnionego w kombinacji Qt i importu w wątku. Podobna niezgodność eksportów `concurrent.futures` z Pythonem 3.15 została naprawiona także [upstream w PySide](https://github.com/pyside/pyside-setup/commit/c3a4d68fd9dcbe4f1b9c8a74acf8056f48c8a7a8). Lokalny reproducer jest ważniejszym dowodem dla tego przypadku niż sam analogiczny upstream fix.

Naprawa: import klasy z modułu definiującego, `concurrent.futures.process`, w `_RenderExecutor` i drugim istniejącym miejscu użycia, `second_pass.py`. Jawny kontekst `spawn`, zgodny z Windows; istniejące `freeze_support()` w launcherze zachowano. Nie wymieniono executora, modelu pracy rendererów ani transportu SHM. Wyjątek opuszczający context executora uruchamia ograniczone czasowo sprzątanie procesów zamiast bezwarunkowego `shutdown(wait=True)`.

Test regresji uruchamia świeży interpreter, tworzy QApplication, następnie startuje wątek i prawdziwy worker spawn. Przeszedł w Pythonie 3.15 i Portable 3.14. Test z podmienionym eksportem pakietu dodatkowo dowodzi, że renderer używa klasy z właściwego modułu.

## 2. Kod -11 i błędny wybór AV1

Dokładne miejsce: `src/native/d3d11_intel_pipeline/telem_intel_native.c:1643–1649`. `intel_native_pipeline_init_multi_ex` wywołuje `MFXVideoENCODE_Init`; przy statusie innym niż `MFX_ERR_NONE` usuwa rozszerzenia parametrów i próbuje drugi raz. Ponowny status inny niż `MFX_ERR_NONE` daje **własny kod wrappera `-11`**. Status oneVPL nie jest przekazywany do Pythona. Inne wystąpienie `return -11` dotyczy osobnego testu capacity, a nie tego samego kontraktu inicjalizacji eksportu.

**Nie wolno interpretować tego `-11` jako konkretnego statusu oneVPL ani diagnozy uszkodzonego sterownika.** Dotychczasowy komentarz Pythona błędnie utożsamiał go z `MFX_ERR_INVALID_VIDEO_PARAM`; usunięto tę interpretację. Dodano czytelne objaśnienie znaczenia własnego kodu. Nie przebudowywano DLL ani architektury D3D11.

Przyczyny błędnej enumeracji/GUI:

- wyjątek sondowania w Pythonie oznaczał AV1/H.264/HEVC jako dostępne;
- HEVC 8-bit utożsamiano z HEVC Main10;
- cache na dysku był powiązany z nazwą/mtime FFmpeg, nie ze sprzętem i sterownikiem, więc mógł przenosić obce wyniki;
- GUI domyślnie wybierało „AV1 — zalecany” i blokowało tylko HEVC;
- kanoniczny harness Intel sam wymuszał AV1;
- fallback dobierał inny kodek niż żądany, a command builder nie rozróżniał H.264 od HEVC.

Naprawa: cztery rzeczywiste próby kodowania na adapterze Intel wybranym przez Vendor ID `0x8086`, z QSV wyprowadzonym z D3D11. Osobne NV12/H.264 High, NV12/HEVC Main, P010/HEVC Main10/HLG oraz P010/AV1 Main/HLG. Brak trwałego cache; cache wyłącznie w bieżącym procesie. Błąd sondowania oznacza brak potwierdzenia dostępności. GUI używa kanonicznego FFmpeg z runtime aplikacji. Nie ma rozpoznawania możliwości przez generację CPU.

GUI wyłącza każdą nieobsługiwaną kombinację. Domyślny HDR wybierany jest spośród potwierdzonych enkoderów. Jeśli żaden HDR nie jest dostępny, wymagany jest jawny wybór użytkownika — SDR nie jest wybierany automatycznie. Preflight sprawdza także przywrócone ustawienie lub zadanie kolejki i pokazuje obsługiwane alternatywy. Jawny wybór H.264/HEVC SDR pozwala na konwersję; samo niepowodzenie HDR jej nie uruchamia.

Na tej maszynie potwierdzono:

| Kombinacja | Rzeczywista próba QSV | Pełny eksport |
|---|---|---|
| H.264 8-bit SDR | PASS | Native D3D11 i FFmpeg PASS |
| HEVC Main 8-bit SDR | PASS | FFmpeg QSV PASS |
| HEVC Main10 / HLG HDR | PASS | Native D3D11 i FFmpeg PASS |
| AV1 10-bit HDR | niedostępny | poprawna odmowa w GUI, brak eksportu |

i7-1265U/Iris Xe dekoduje AV1, ale nie ma sprzętowego enkodera AV1; zgodne z [dokumentacją Intel](https://www.intel.com/content/www/us/en/docs/onevpl/developer-reference-media-intel-hardware/1-1/details.html) i rzeczywistym odrzuceniem `av1_qsv` przez runtime. AV1 pozostaje opcją dostępną dopiero po pozytywnym teście na kompatybilnym urządzeniu. Dodatni test AV1 na takim urządzeniu: **NOT TESTED**.

Native HEVC pozostaje Main10; nowa jawna opcja HEVC 8-bit SDR korzysta z istniejącego fallbacku FFmpeg QSV. W fallbacku zachowano żądany kodek/profil, 10-bit przy kompozycji HDR oraz właściwe znaczniki BT.709/HLG. Konwersja SDR odbywa się przed kompozycją HUD, wyłącznie po jawnym wyborze wyjścia SDR.

## 3. Cleanup i muxowanie

Przyczyna 10 sekund oczekiwania: wyjątek inicjalizacji korzystał z tej samej dziesięciosekundowej ścieżki graceful co normalne anulowanie. `cancel_started=None` powodowało, że każda linia diagnostyczna drukowała `elapsed=0.000s`.

Teraz błąd przerywa FFmpeg od razu, przed próbą zamknięcia potencjalnie zablokowanego buforowanego stdin. Oczekiwanie po terminate/kill jest ograniczone. Lokalny zegar cleanup istnieje także bez cancel event. Normalne anulowanie zachowuje graceful close i czas na finalizację.

Native live mux ma właściciela zasobów także przed wejściem do render-loop `try/finally`: sprzątanie procesu, holdera i wątku named pipe. Zablokowane ConnectNamedPipe/ReadFile może być anulowane przy błędzie inicjalizacji. Typy uchwytów WinAPI są jawne dla 64-bit Windows. Wyjątek renderowania nie czeka 30 sekund na mux.

Dodatkowy negatywny test harnessu wstrzyknął `-11` przed otwarciem natywnego writer pipe. Fallback HEVC Main10 zakończył się poprawnym MP4 z audio, a lista pozostawionych wątków `IntelPipeForwarder` była pusta. Jest to test sprzątania kontrolowanego błędu, nie twierdzenie o uzyskaniu surowego statusu z oneVPL.

Wymuszenie błędu executora przez **kanoniczny harness** przeszło przez native i fallback. Oba zamknięcia FFmpeg: **0.051 s**. Cała obsługa błędu: **2.26 s**, lista potomnych FFmpeg po błędzie: **pusta**. Wynik harnessu `success=false` jest oczekiwanym wynikiem negatywnego testu, nie udanym eksportem.

Podczas weryfikacji wykryto dodatkowo, że limit klatek fallbacku mógł zostawiać dłuższe audio. Dla Intel czas muxowania jest teraz ograniczony do rzeczywiście eksportowanego zakresu. Audio nadal pochodzi bezpośrednio z oryginalnego MP4; **nie tworzono plików audio ani nie przywracano `ensure_audio_cache`**. Zachowano zastaną poprawkę `live_av_mux.py` użytkownika.

## 4. Harness i pliki MP4

Użyto istniejącego `SportCamHUD.py --test-intel-export`, rzeczywistego GUI/controller/renderer — nie zastąpiono go testowym rendererem. Dodano wybór kodeka/ścieżki, timeout diagnostyczny, kontrolowane wstrzyknięcie błędu i walidację MP4. Usunięto wyścig harnessu: czeka teraz na koniec ładowania telemetrii, zamiast uruchamiać eksport w trakcie i zatrzymywać się na modalnym komunikacie.

Kanoniczna para z BENCHMARKS.md `Video/GX020079.MP4 + GX020079.fit` nie była lokalnie dostępna. Przed próbami jawnie zgłoszono użycie `C:\GoPro\GX010378.MP4` + `C:\GoPro\2026-10-15_15-03-50.fit`, wskazanych również przez istniejący harness wizualny. Użyto pojedynczego dostępnego klipu. Log SmartSync ostrzega o odrzuconym dopasowaniu trajektorii; nie zastąpiono FIT innym plikiem. **Poprawność synchronizacji telemetrii tej pary nie jest przedmiotem ani wynikiem tej naprawy.**

4K 3840×2160, źródło HLG, 40M. Dokładne polecenia i wyniki są w artefaktach. Szkielet wywołania:

```powershell
python SportCamHUD.py --test-intel-export --video C:\GoPro\GX010378.MP4 --fit C:\GoPro\2026-10-15_15-03-50.fit --codec hevc --intel-path native --frames 60 --output ... --result-json ...
```

Każdy poniższy plik dodatkowo przeszedł odczyt wszystkich klatek przez ffprobe i pełne dekodowanie wideo+audio przez FFmpeg, sprawdzenie profilu, rozdzielczości, koloru i liczby klatek. Wszystkie mają audio AAC z oryginału.

| Przypadek / plik w `scratch/intel_fix/` | Klatki | Profil / kolor | Różnica długości A/V | Wynik |
|---|---:|---|---:|---|
| native_hevc.mp4 | 30 | HEVC Main10 / HLG | 0.019667 s | PASS |
| native_h264.mp4 | 60 | H.264 High / BT.709 | 0.018000 s | PASS |
| ffmpeg_hevc_final.mp4 | 60 | HEVC Main10 / HLG | 0.039333 s | PASS |
| ffmpeg_h264.mp4 | 60 | H.264 High / BT.709 | 0.039333 s | PASS |
| ffmpeg_hevc_sdr.mp4 | 30 | HEVC Main / BT.709 | 0.041000 s | PASS |
| queue_h264.mp4 | 60 | H.264 High / BT.709 | 0.018000 s | PASS |
| portable_native_hevc_final.mp4 | 60 | HEVC Main10 / HLG | 0.018000 s | PASS |
| portable_native_h264.mp4 | 60 | H.264 High / BT.709 | 0.018000 s | PASS |
| native_init_failure_fallback.mp4 | 30 | HEVC Main10 / HLG, wstrzyknięte -11 → FFmpeg | 0.041000 s | PASS |

Surowa [walidacja MP4](intel_qsv_fix_20261017/mp4_validation.json) zawiera również hashe plików, czas początku strumieni i wynik pełnego dekodowania. Negatywny test AV1 rzeczywiście sprawdził treść QMessageBox i odrzucenie przed startem renderera, bez zmiany na SDR.

## 5. Testy automatyczne

- Końcowy zestaw `tests/test_intel*.py`, `test_encoder_profiles_intel.py`, `test_render_cancel_process_lifecycle.py`, `test_live_av_mux.py`: **204 passed, 1 skipped**. Pominięto wyłącznie legacy capacity AV1, którego sprzęt nie obsługuje. Trzy istniejące ostrzeżenia dotyczą niezarejestrowanego znacznika pytest `intel`.
- Portable runtime: **11 passed**, w tym QApplication + wątek + prawdziwy spawn worker, GUI dla różnych macierzy możliwości, przyczyna odmowy startu zadania kolejki, brak cichego HDR→SDR, szybki abort oraz normalny graceful stop z MP4 i audio bezpośrednio z oryginalnego pliku.
- Starsze testy zakładające AV1 zawsze dostępny i zawsze domyślny poprawiono na testowanie faktycznej macierzy możliwości. Test NV12 jawnie żąda HEVC SDR. Test liczby widgetów dostosowano do istniejącego, niezmienionego layoutu 17 widgetów zamiast historycznych 14.
- Próba zebrania całego `tests` z filtrem `-k` ujawniła niezależny, istniejący błąd importu `TelemetryOrchestrator` w `test_auto_telemetry_source_order.py`. Dlatego pełny zestaw całego projektu nie jest deklarowany jako PASS; końcowy zestaw Intel uruchomiono przez jawne wskazanie plików.
- `git diff --check`: PASS.

## 6. Portable i granice walidacji

Badano odizolowany katalog `scratch/intel_portable_validation`, zawierający aktualny kod i runtime z `C:\GoPro\SportCamHUD-Portable`, z launcherem `python -s -E`. Nie modyfikowano zainstalowanego Portable. `psutil` doinstalowano wyłącznie w kopii testowej, ponieważ istniejący harness Intel go wymaga. Nie opierano testu na systemowym Pythonie 3.15. Native DLL i FFmpeg w kopii mają takie same hashe jak użyte w repo.

Nie utworzono oficjalnej paczki wydania ani commitu. Testowana kopia jest snapshotem roboczym, nie opublikowanym Portable. Działanie pojedynczej wersji na innych urządzeniach wynika z sondowania runtime, lecz pełne testy eksportu na innych GPU/sterownikach są **NOT TESTED**.

## 7. Zmienione pliki

Kod:

- `src/ffmpeg/streaming.py` — import/spawn, cleanup, zachowanie żądanego kodeka i czasu wyjścia;
- `src/ffmpeg/second_pass.py` — ten sam bezpośredni import klasy;
- `src/ffmpeg/intel_backend.py` — rzeczywiste sondowanie formatów/profili, cache procesowy, kontrakt H.264;
- `src/ffmpeg/intel_native_exporter.py` — fail-closed capabilities/preflight, cleanup init/live mux, znaczenie -11; zachowane wcześniejsze zmiany audio użytkownika;
- `src/ffmpeg/command_builder.py` — H.264/HEVC SDR/Main10, jawna konwersja SDR, zachowanie głębi HDR, limit czasu muxowania Intel;
- `src/gui/qt/tabs/render_tab.py` — selektor czterech kombinacji, dostępność i preflight;
- `src/gui/qt/application.py` — wyłącznie rozszerzenia istniejącego harnessu Intel.

Testy: `test_intel_runtime_capabilities.py` (nowy), `test_intel_native_7g.py`, `test_intel_native_8a.py`, `test_intel_native_8b.py`, `test_intel_native_8c.py`, `test_intel_pipeline_async.py`, `test_intel_queue_native_fallback_hwdownload.py`.

Pliki AMD bez zmian. Zastany diff `nvidia_native_exporter.py` oraz niezacommitowane pliki live mux użytkownika nie są przedstawiane jako własne zmiany tej naprawy.

## 8. Wydajność, ryzyka, końcowy status

Nie zmieniano natywnej pętli D3D11, kolejności HUD, shaderów, rozmiarów ringów, liczby workerów ani produkcyjnych ustawień GPU. Sondowanie wykonuje się poza pętlą klatek i korzysta z cache procesu. Potwierdzony cleanup po błędzie skrócono z oczekiwania 10 s do 0.051 s na FFmpeg.

Krótkie próby 30/60 klatek obejmują zimny start, inicjalizację i zmienny koszt HUD; **nie są kontrolowanym benchmarkiem A/B**. Brak regresji FPS na pełnym obciążeniu / długim eksporcie: **NOT PROVEN**. Benchmark długotrwały, pixel parity oraz smoke AMD/NVIDIA: **NOT TESTED**. Na tym komputerze nie ma sprzętu AMD/NVIDIA ani AV1 encode do takich testów. Wzmianka `DIRECT_VP_SURFACE ... CopyResource fallback` występuje w istniejącej DLL; nie przebudowano tego mechanizmu.

**PASS** dla odtworzenia i naprawy importu, preflight/GUI, rzeczywiście obsługiwanych kodeków, native Intel, fallback FFmpeg, kolejki, cleanup i walidacji MP4 z audio na i7-1265U. **Nie deklaruje się walidacji na każdym sprzęcie ani pełnej akceptacji wydajnościowej.**
