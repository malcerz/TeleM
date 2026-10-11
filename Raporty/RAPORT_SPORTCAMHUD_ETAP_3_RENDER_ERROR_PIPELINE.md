# SPORTCAMHUD — Etap 3: obsługa błędów renderowania

**Data:** 2026-10-11
**Repozytorium:** `C:\_DEV\BikeRideHUD-main-new`
**Gałąź:** `fix/gui-freeze-hud-composite`

## 1. Stan Git przed rozpoczęciem

- HEAD: `395faf40bf2679c3502a9599125854c333035762`; gałąź była 9 commitów przed origin.
- Zmiany użytkownika: zmodyfikowany `def_layout.json` oraz nieśledzony raport `RAPORT_SPORTCAMHUD_FULL_REGRESSION_AUDIT_20261011.md`.
- Oba pliki użytkownika pozostały nietknięte i poza stagingiem. Backup `C:\_DEV\_SportCamHUD_BACKUP_20261011_175842` nie był modyfikowany.

## 2. Przepływ przed poprawką

```text
RenderMixin -> wyjątek -> str(exception) -> sig_error(str)
                                  \-> ExportQueue.render_error (string)

AMD worker -> terminal IPC {error_type, error, traceback}
          -> parent RuntimeError z tekstem/tracebackiem

FFmpeg error helpers istnieją, lecz eksport nie zachowuje konsekwentnie
typu/kodu, ścieżki, etapu ani polityki kolejki.
```

Niektóre ścieżki Intel zwracały `False` po błędzie muxowania/walidacji, a część backendów usuwała plik `.part` przed przekazaniem błędu do GUI. Błąd procesu potomnego i błąd muxera mogły wyglądać tak samo.

## 3. Przepływ po poprawce

```text
OSError / wyjątek backendu / RenderError
  -> coerce_render_error() -> RenderError z kodem, kategorią, ścieżką i etapem
  -> AMD child IPC: error_payload (JSON-serializable) + stare pola tekstowe
  -> RenderMixin -> sig_render_error(RenderError) + kompatybilny sig_error(str)
  -> ExportQueue: render_error_payload + stan zadania + pauza dla błędu blokującego
  -> GUI: krótki komunikat, lokalizacja, działanie i stan częściowego MP4
```

Anulowanie pozostaje osobnym stanem. Błąd dysku z monitora nie jest już traktowany jako anulowanie, mimo że monitor zatrzymuje render przez istniejący event anulowania.

## 4. Przyczyny utraty informacji i naprawa

- `RenderMixin` redukował wyjątki do tekstu. Worker teraz normalizuje błędy przez istniejący model `RenderError`; stderr/traceback pozostają diagnostyczne, a główny tekst GUI jest krótki.
- AMD child IPC nie przekazywał typu. Terminal `error` zachowuje dotychczasowe pola i dodaje `error_payload`; rodzic odtwarza typ przez `RenderError.from_dict()`. Stary format tekstowy jest nadal obsługiwany.
- `OutputWriteError` odrzucał `output_path`; mapowanie kodów używa errno/tekstu i zachowuje ścieżkę, etap, job ID oraz kontekst częściowego pliku.
- `classify_mux_error()` rozróżnia ENOSPC, EACCES, niedostępne urządzenie, EPIPE, dekoder, GPU, enkoder i ogólny błąd muxera.
- Awaria child process bez terminalnego wyniku otrzymuje `ChildProcessError` z exit code, PID, etapem i diagnostyką.

## 5. Integracja GUI i kolejki

- Dodano `sig_render_error(object)`; `sig_error(str)` pozostał bez zmian dla starszych odbiorców.
- Komunikat błędu zawiera lokalizację oraz zalecane działanie. Nie pokazuje tracebacku jako głównego tekstu.
- `ExportJob.render_error_payload` zachowuje typowany payload przy persystencji kolejki; `render_error` nadal jest tekstem dla istniejącego UI.
- `pause_queue=True` ustawia pauzę po terminalnym błędzie krytycznym. Błąd źródłowy kończy tylko konkretne zadanie. Nie dodano automatycznej zmiany kodeka ani backendu.
- Storage preflight i `check_preflight_sources()` wykonują się w workerze, poza wątkiem Qt. Preflight nie tworzy brakującego katalogu; test zapisu i zapytanie o wolne miejsce nie blokują GUI.
- `RuntimeStorageMonitor` pracuje w osobnym wątku co najmniej co 0,5 s (domyślnie 1,5 s). Brak miejsca lub zniknięcie nośnika przerywa zadanie i przekazuje typowany błąd.
- Szacunkowy preflight pomija tryby rozpoznane jako QP. Wynik wolnego miejsca jest kontrolą ostrożnościową; rzeczywisty błąd zapisu nadal jest rozstrzygający.

## 6. Finalizacja i częściowe MP4

- Wspólny worker potwierdza finalny plik przez istniejący `validate_partial_output()` przed stanem `completed`/100%. To szybki probe struktury/strumieni, bez pełnego dekodowania.
- Awaryjnie odnaleziony `.part` / `.part.mp4` jest walidowany; payload rozróżnia `partial_valid`, `partial_invalid` i `unverified`. Nie deklaruje poprawności bez probe.
- AMD/Intel zachowują plik częściowy przy błędzie muxowania/walidacji. NVIDIA przekazuje exit code/stderr procesu muxującego. Przy ponowieniu istniejący sidecar `.part`/`.tmp.mp4` blokuje start zamiast zostać po cichu nadpisany.
- Istniejące czyszczenie plików przy jawnym anulowaniu pozostało; nie zmieniano semantyki CANCELLED.
- Nie zmieniano argumentów Live Mux, potoków klatek, parametrów kodeków/QP/bitrate ani mechanizmów audio. Zmiany backendów dotyczą wyłącznie klasyfikacji błędów, terminalnego wyniku i zachowania artefaktów błędu.

## 7. Zmienione pliki

- `src/ffmpeg/render_errors.py`
- `src/ffmpeg/output_error.py`
- `src/ffmpeg/amd_child_process.py`
- `src/ffmpeg/amd_native_exporter.py`
- `src/ffmpeg/intel_native_exporter.py`
- `src/ffmpeg/nvidia_native_exporter.py`
- `src/gui/export_queue.py`
- `src/gui/qt/_mixins/render_mixin.py`
- `src/gui/qt/signals.py`
- `src/gui/qt/tabs/render_tab.py`
- `tests/test_output_write_error.py`
- `tests/test_render_error_pipeline_etap3.py` (nowy)
- `tests/test_export_queue_lifecycle.py`
- `tests/test_amd_child_process.py`
- `Raporty/RAPORT_SPORTCAMHUD_ETAP_3_RENDER_ERROR_PIPELINE.md`

## 8. Testy

Testy uruchomiono przez kanoniczne środowisko `uv run --no-project --with pytest --with PySide6 pytest`, z `APPDATA` i `LOCALAPPDATA` skierowanymi do izolowanego katalogu tymczasowego.

- Zestaw błędów, IPC, kolejki, Etapu 2, anulowania, child process, finalizacji i Intel finalization: **91 passed**.
- Symulowane testy obejmują ENOSPC, EACCES, ENOENT, EPIPE, znikający katalog, fault injection monitora, błędy dekodera/GPU/enkodera/muxera, payload JSON, starszy tekst błędu child process, pauzę kolejki i zachowanie ścieżki eksportu.
- `py_compile` dla zmienionych modułów: **PASS**.
- `git diff --check`: **PASS**.
- `tests/test_render_progress_single_source.py`: **NOT TESTED** — pierwszy test zatrzymał się w oczekiwaniu na zdarzenie Qt w trybie offscreen; przerwano po około 20 s bez raportu pytest. `tests/test_render_tab.py` nie uzyskał osobnego, zakończonego przebiegu.
- Realny eksport AMD/Intel/NVIDIA, rzeczywiste pełne/nośniki sieciowe, fizyczne odłączenie USB oraz końcowa walidacja na klipach: **NOT TESTED**. Nie zapełniano nośnika i nie wykonywano realnego renderu bez kanonicznych materiałów.

## 9. Wydajność

- Audyt statyczny: klasyfikacja błędów i monitor nie znajdują się w pętli klatek; monitor dysku działa w oddzielnym wątku, a walidacja finalnego pliku zachodzi raz po renderze.
- Test serializacji typowanego payloadu (5 000 przebiegów JSON round-trip): 0,0694 s łącznie, około **0,0139 ms/przebieg** na tej maszynie.
- Nie mierzono FPS; brak kanonicznych źródeł w `Video/`. Nie deklaruję akceptacji FPS AMD ani pomiaru na GPU.
- Jedyny dodatkowy koszt wspólnej ścieżki to końcowy ffprobe. Nie wykonuje dekodowania całości ani drugiego remuxu.

## 10. Regresje poza zakresem i ryzyka

- Wcześniejszy audyt wskazuje niezależne braki helperów DJI oraz niejednoznacznego AutoFIT; Etap 3 ich nie dotykał.
- Zakończenie GUI w `test_render_progress_single_source.py` wymaga osobnej diagnozy Qt/offscreen.
- Klasyfikacja tekstu stderr jest heurystyczna, gdy backend nie dostarcza errno ani osobnego typu; rzeczywisty kod/status procesu jest zachowywany tam, gdzie dostępny.
- Brak testu na fizycznym urządzeniu oznacza, że UNC/USB zostały pokryte przez symulowane błędy I/O, nie rzeczywisty disconnect.

## 11. Stan danych, backendów i Git

- `def_layout.json` użytkownika i raport audytu pozostały poza zmianami Etapu 3 i poza stagingiem.
- Brak zmian audio, Live Mux command lines, enkoderów AMD/Intel/NVIDIA, AutoFIT i layoutów.
- Implementacja Etapu 3: **063f5fdc740b98e3cbb62fb6e7e4dbe7127efb95**.
- Raport zostanie zapisany osobnym, powiązanym commitem po uzupełnieniu hasha implementacji.
- Push: **nie wykonano**.

## Podsumowanie

**PASS:** spójny model błędów, typowany AMD child IPC z kompatybilnością wsteczną, kolejka, preflight/monitor, brak fałszywego sukcesu przed probe oraz zachowanie partial output mają testy jednostkowe/fault-injection. **NOT TESTED:** GUI offscreen end-to-end i rzeczywiste eksporty sprzętowe/nośniki. Nie uznaję kryteriów wymagających tych przebiegów za zweryfikowane.
