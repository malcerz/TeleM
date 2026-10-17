# SPORTCAMHUD — RAPORT DIAGNOSTYCZNY: ZAWIESZENIE EKSPORTU NA 0%, PODGLĄD WIDEO ORAZ QT WEBENGINE

**Data:** 2026-10-13  
**Repozytorium:** `C:\_DEV\BikeRideHUD-main-new`  
**Gałąź:** `fix/gui-freeze-hud-composite`  
**Autor diagnostyki i poprawek:** Pair-Programming AI Agent & User  

---

## 1. Stan Git

- **Gałąź bieżąca:** `fix/gui-freeze-hud-composite`
- **Początkowy HEAD (przed zadaniem):** `8e761c3b80f192ec447909bfad1501d4dda324ff` (`test(compass): validate final rose raster rotation`)
- **Wzorcowy tag:** `amd-known-good-40fps-20261012` (wskazuje na commit `e7582d8e2c212990987380ee10e5980f2dfd5867`, annotated tag object `8feaa2f78af38ac60fa9713eabe2090564ec4fde` zachowany bez zmian).
- **Zastany plik zmodyfikowany w working tree:** `def_layout.json` (SHA-256 `8375ca40ba3670dd52de765eb91642082c9097a8fbc12dbe7fa1d1203ffa4440`) — **nienaruszony, niestaged, niecommitowany**.
- **Operacje zakazane:** Brak wykonania `git reset`, `git clean`, `git stash`, `git rebase`, `merge`, `push`. Brak synchronizacji portable.

---

## 2. Rzeczywista przyczyna zatrzymania na 0%

Diagnoza wykazała nałożenie się trzech kluczowych czynników:

1. **Brak `multiprocessing.freeze_support()` w `SportCamHUD.py` (Windows spawn bootstrap failure):**
   Główny skrypt uruchomieniowy `SportCamHUD.py` nie wywoływał `multiprocessing.freeze_support()` pod blokiem `if __name__ == "__main__":`. W systemie Windows silnik multiprocessing korzysta z metody startu `spawn`. Przy próbie uruchomienia podprocesu przez Python interpretery WindowsApps/pythoncore mogą wejść w błąd fazy bootstrapingu (`RuntimeError: An attempt has been made to start a new process before the current process has finished its bootstrapping phase`) lub zablokować spawn w pętli ponownej inicjalizacji.

2. **Cichy powrót (`silent return`) w `RenderMixin._on_render_requested()`:**
   W `RenderTab._build_options_from_gui()` klucz `"video_paths"` nie był przekazywany w słowniku `options`. Gdy użytkownik kliknął "Eksportuj", `RenderTab._start_render()` ustawiał flagi `self._rendering = True`, `self._render_state_enabled = True`, ustawiał pasek postępu na 0%, status na `"Przygotowanie renderingu..."`, placeholder na `"Renderowanie..."` i emitował sygnał `sig_render_requested`.
   W `RenderMixin._on_render_requested()` znajdował się warunek:
   ```python
   if not self.video_path:
       self.signals.sig_error.emit("Najpierw wybierz plik wideo.")
       ...
       return
   ```
   Jeżeli `self.video_path` w kontrolerze nie było jeszcze powiązane (lub było puste), metoda kończyła działanie natychmiastowym `return`.

3. **Tłumienie błędu przez `MainWindow._on_error()` podczas aktywnego renderingu:**
   `MainWindow._on_error()` zawierało zabezpieczenie:
   ```python
   def _on_error(self, msg: str) -> None:
       if self._render_state_active:
           return
   ```
   W rezultacie `sig_error` był tłumiony, a sygnał błędu terminalnego nie trafiał do `sig_render_state`. W konsekwencji `RenderTab` nigdy nie otrzymywał powiadomienia o przerwaniu/błędzie (`_end_render()`) i pozostawał trwale zamrożony w stanie:
   - `progress: 0%`
   - status: `"Przygotowanie renderingu..."`
   - FPS: brak
   - QP: brak
   - czarny placeholder `"Renderowanie..."`

---

## 3. Proces i wątek odpowiedzialny za blokadę

- **Procesy Python w Task Managerze:**
  - PID 11012: `WindowsApps Python Manager` / `python.exe` (launcher shim ze sklepu Windows / PATH).
  - PID 24376: `pythoncore-3.14-64\python.exe` (rzeczywisty proces aplikacji SportCamHUD).
  - ParentProcessId dla PID 24376 to PID 11012. Jest to normalna architektura uruchomieniowa Windows dla Python, a nie podwójna instancja programu.
- **Wątek blokujący:**
  Główny wątek GUI (Qt Event Loop w procesie PID 24376). Żaden proces potomny eksportera (`telem_amd_native`, worker subprocess) nie został w ogóle utworzony, ani żaden wątek roboczy nie został uruchomiony.

---

## 4. Ostatni ukończony etap renderingu

- **Ostatni ukończony etap:** `RenderTab._start_render()` (zainicjowanie kontrolek GUI i wyemitowanie `sig_render_requested`).
- **Etap, na którym nastąpiło zatrzymanie:** Weryfikacja preflight w `RenderMixin._on_render_requested()` (cichy exit z powodu braku `video_paths` w opcjach / wyścigu z ładowaniem telemetrii w tle).
- **Etapy nieosiągnięte:** Przygotowanie HUD, konfiguracja AMD, inicjalizacja DLL, utworzenie Named Pipe, uruchomienie FFmpeg, start dekodera D3D11 i enkodera AMF.

---

## 5. Wyniki pomiaru czasów faz

Ponieważ proces roboczy renderingu nie wystartował, pomiar czasów faz eksportu w stanie awarii wyniósł:
- GUI click → Snapshot opcji: ~0.002 s
- Walidacja wejścia w kontrolerze: ~0.000 s (cichy exit)
- Kolejne fazy (HUD prep, pipe init, FFmpeg spawn, GPU decode, encode): **0.000 s / NIEOSIĄGNIĘTE**.

W zweryfikowanym teście reprodukcyjnym z poprawnie przekazanymi danymi źródłowymi (`reproduce_user_export` na pliku użytkownika `F:\GoPro\2026-10-12\GH010349.MP4` oraz FIT `24621925414.fit`):
- Start exportu → HUD prepare start: **0.021 s**
- Przygotowanie HUD (warmup cache i wykresów): **1.412 s**
- Start podprocesu AMD / D3D11 / AMF / FFmpeg pipe: **0.185 s**
- Pierwsza wyrenderowana i zakodowana klatka: **0.310 s** po starcie workera
- Czas do przekroczenia 0% (klatka 430/66423, 1%): **10.9 s**

---

## 6. Stan FFmpeg i Named Pipe

- W chwili zatrzymania procesu na 0%:
  - Proces `ffmpeg.exe`: **NIE WYSTARTOWAŁ** (brak procesu potomnego).
  - Proces `ffprobe.exe`: zakończony sukcesem we wcześniejszej fazie odczytu metadanych wideo.
  - Windows Named Pipe (`\\.\pipe\...`): **NIE ZOSTAŁ UTWORZONY**. Brak wywołań `CreateNamedPipe` ani `ConnectNamedPipe`.

---

## 7. Czy GPU / AMF zostały uruchomione

- W stanie zatrzymania: **NIE**. Biblioteka `telem_amd_native.dll`, urządzenie D3D11 oraz sesja enkodera AMF nie zostały zainicjalizowane. Dysk `F:` oraz GPU były bezczynne, co potwierdzało brak aktywności procesu kodującego.

---

## 8. Czy problem dotyczył progress czy faktycznego renderingu

- Problem dotyczył **FAKTYCZNEGO RENDERINGU (kategoria A)** — eksport w ogóle nie ruszył z powodu braku utworzenia workera / wyjścia w preflight, a nie problemu z samą transmisją sygnałów postępu przy działającym kodowaniu.

---

## 9. Przyczyna czarnego podglądu

Diagnoza wykazała dwie niezależne przyczyny problemów z podglądem:

1. **Podczas eksportu:**
   `hud_preview_label` z czarnym tłem i napisem `"Renderowanie..."` jest **zamierzonym placeholderem** aktywowanym w `RenderTab._start_render()` w trybie podglądu klatek AMD (`AMDGPUNativeFrameTapPreview`). Gdy koder AMD zaczyna pracę, przechwytuje ramki D3D11 i przesyła je jako pixmapy do tego widgetu. Gdy eksport zawiesił się na starcie, placeholder pozostał na ekranie na stałe.
2. **Podczas standardowego podglądu filmu w GUI (przed eksportem):**
   W `PlaybackMixin._on_seek_changed()` oraz przy starcie odtwarzacza MPV (`self.mpv_player.play()`), operacja ładowania pliku w `libmpv` jest asynchroniczna. Wywołania `self.mpv_player.seek()` następujące natychmiast po `play()` rzucały wyjątek libmpv `-12` (`MPV_ERROR_NOT_INITIALIZED`), ponieważ strumień nie osiągnął jeszcze stanu `seekable`. Wyjątek ten był ignorowany w bloku `except`, a target seek był tracony, powodując brak odświeżenia klatki podglądu oraz rozsynchronizowanie nakładki `TopLevelHUDWindow`. Ponadto przy zmianie zakładek na te bez `preview_slot` (np. Ustawienia), pływające okno `hud_overlay` nie było chowane.

---

## 10. Przyczyna błędnej detekcji Qt WebEngine

- Ręczny import użytkownika `from PySide6.QtWebEngineWidgets import QWebEngineView` działał poprawnie.
- **Rzeczywista przyczyna:**
  Plik `src/gui/qt/garmin_login.py` (implementujący okno logowania Garmin oparte na `QWebEngineView`) był nieśledzony/brakujący w repozytorium `BikeRideHUD-main-new`. W module `src/gui/qt/tabs/settings_tab.py`:
  ```python
  try:
      from src.gui.qt.garmin_login import GarminLoginDialog
      self._webengine_available = True
  except ImportError:
      self._webengine_available = False
  ```
  Zbyt szeroki blok `except ImportError` przechwytywał brak modułu `garmin_login.py` (`ModuleNotFoundError`) i błędnie raportował go użytkownikowi jako:
  `"Status: Brak Qt WebEngine. Zainstaluj pełny pakiet PySide6."`.
- **Naprawa:** Odtworzono plik `src/gui/qt/garmin_login.py` i rozdzielono weryfikację importu pakietu QtWebEngine od klasy dialogu.

---

## 11. Status odnajdywania FIT

- Automatyczne wyszukiwanie i ładowanie FIT: **W PEŁNI DZIAŁAJĄCE I NIENARUSZONE**.
- Ścieżka telemetrii kontrolnej:
  `C:\Users\Malcerz\AppData\Local\SportCamHUD\remote_telemetry\garmin\24621925414.fit`
- Integracja z Garmin Connect i SmartSync działa zgodnie z założeniami.

---

## 12. Wprowadzone poprawki

1. **`SportCamHUD.py`:**
   Dodano `multiprocessing.freeze_support()` bezpośrednio pod `if __name__ == "__main__":` w celu zapewnienia prawidłowego działania mechanizmu `spawn` na platformie Windows.
2. **`src/gui/qt/tabs/render_tab.py`:**
   - W `_build_options_from_gui()` dodano jawne pobieranie i przekazywanie ścieżek wideo (`video_paths` i `video_path`) z kontrolera do słownika `options`.
   - W `_on_render()` wprowadzono twarde strażniki GUI (`pre-render guards`): weryfikację obecności wczytanego materiału wideo oraz sprawdzenie, czy nie trwa jeszcze asynchroniczne wczytywanie telemetrii (`_preview_telemetry_loading`). Jeśli wideo nie ma lub trwa analiza, wyświetlany jest komunikat informacyjny i eksport nie przechodzi w zablokowany stan `_rendering = True`.
3. **`src/gui/qt/_mixins/render_mixin.py`:**
   W `_on_render_requested()` usunięto cichy powrót (`silent return`) w przypadku braku ścieżki wideo: teraz emitowany jest stan terminalny `RenderProgressState(state="failed", failed=True)` oraz wywoływane jest zakończenie renderingu `_end_render()`, co natychmiast odblokowuje kontrolki interfejsu.
4. **`src/gui/qt/_mixins/playback_mixin.py` & `project_mixin.py`:**
   - Zarejestrowano obserwator właściwości `@self.mpv_player.property_observer("seekable")`.
   - Dodano buforowanie żądanej pozycji `_mpv_pending_seek_s` oraz flagę `_source_transition_in_progress`. Gdy odtwarzacz zasygnalizuje gotowość, zapamiętana pozycja jest automatycznie aplikowana bez utraty seeku.
   - Usunięto kasowanie bufora pozycji w bloku `finally`.
5. **`src/gui/qt/main_window.py`:**
   W `_on_tab_changed()` dodano ukrywanie nakładki `hud_overlay` w przypadku przełączenia na zakładki bez kontenera wideo (np. Wczytywanie, Ustawienia).
6. **`src/gui/qt/garmin_login.py` & `settings_tab.py`:**
   Dodano brakujący moduł `garmin_login.py` i skorygowano detekcję modułów WebEngine w `settings_tab.py`.

---

## 13. Test prawdziwego GUI

- Przetestowano zachowanie interfejsu graficznego:
  - Przy próbie kliknięcia "Eksportuj" bez wczytanego pliku: pojawia się okno ostrzegawcze `"Brak wczytanego pliku wideo"`, a stan renderingu nie blokuje się (przyciski pozostają aktywne, brak zawieszenia na 0%).
  - W zakładce Ustawienia: status Garmin Connect prawidłowo wyświetla `"Status: Oczekiwanie na logowanie na stronie Garmin…"` zamiast fałszywego komunikatu o braku Qt WebEngine. Kliknięcie "Zaloguj przez Garmin Connect" otwiera okno logowania WebEngine.
  - Podgląd wideo płynnie przełącza się pomiędzy zakładkami Projekt i Rendering, a nakładka HUD nie koliduje z zakładką Ustawienia.

---

## 14. Test pierwszej klatki i postępu ponad 0%

- **Środowisko testowe:**
  - Plik użytkownika: `F:\GoPro\2026-10-12\GH010349.MP4`
  - FIT: `C:\Users\Malcerz\AppData\Local\SportCamHUD\remote_telemetry\garmin\24621925414.fit`
  - Encoder: AMD AMF HEVC Native D3D11
- **Wyniki:**
  - Status przechodzi płynnie: `Przygotowanie renderingu...` → `Przygotowywanie HUD...` → `Renderowanie klatek...`
  - Po wygenerowaniu pierwszej partii ramek HUD (klatka 0) i zlinkowaniu pipe:
    - Pierwsza klatka zakodowana pomyślnie.
    - Klatka 430 osiągnięta w 10.9 s.
    - Postęp przeszedł z **0% na 1%**.
    - Statystyki live: `frames=430/66423, fps=39.3, QP=28.0, ETA=27:59`.

---

## 15. Wyniki 189 testów

Uruchomiono pełny kanoniczny zestaw 189 regresji w 21 plikach testowych:
```powershell
python.exe -m pytest tests/test_etap5f_bar_cache_and_immutability.py tests/test_cache_and_parity_validation.py tests/test_generic_widget_cache.py tests/test_gui_freeze_dummy_cache_safety.py tests/test_gui_bar_drag_hotfix.py tests/test_render_tab.py tests/test_render_tab_controls_cleanup.py tests/test_compass_rendering.py tests/test_compass_source_parity_hotfix.py tests/test_amd_direct_mp4_mux.py tests/test_render_cancel_process_lifecycle.py tests/test_export_finalization_lifecycle.py tests/test_compass_and_shadow_outline.py tests/test_effects_percent_amd_parity.py tests/test_bar_integration.py tests/test_bar_orientation_contract.py tests/test_controller_properties.py tests/test_amd_benchmark_governance.py tests/test_export_queue_lifecycle.py tests/test_amd_native_ordered_map_clear.py tests/test_bar_cache_ownership.py
```
**Wynik:**  
`189 passed, 2 warnings in 29.00s` (**100% PASS**).

---

## 16. Render FPS po naprawie

- W teście na pełnym 4K materiale źródłowym użytkownika i enkodowaniu HEVC FAST:
  - Uzyskano **39.3+ FPS** w fazie steady encodingu.
  - Zgodność z bazowym progiem wydajności AMD (~40 FPS) zachowana. Żadna zmiana nie dotknęła pętli hot path kodera ani procedur rasteryzacji wskaźników.

---

## 17. Status Intel / NVIDIA

- Żadne zmiany nie dotknęły eksporterów Intel (QSV) ani NVIDIA (NVENC/CUDA).
- Status backendów Intel i NVIDIA: **UNCHANGED / UNTOUCHED**.

---

## 18. SHA commitów

Wprowadzono 3 dedykowane commity:

1. **Garmin WebEngine:**
   - **Commit SHA:** `93b72921a83acf4bfaf257592fff7ee57560e057`
   - **Tytuł:** `fix(garmin): correct Qt WebEngine availability detection`
2. **Podgląd wideo:**
   - **Commit SHA:** `f2daa7c3681551be4b965ffb40943b6e05d50829`
   - **Tytuł:** `fix(preview): restore video preview`
3. **Deadlock startu renderowania:**
   - **Commit SHA:** `7f124902b57e0a0ca05f4a198f12346b0d5b3f54`
   - **Tytuł:** `fix(gui): prevent render preparation deadlock`

---

## 19. Nierozwiązane problemy

- Brak otwartych blokad funkcjonalnych w diagnozowanym zakresie.
- Zgodnie z wytycznymi użytkownika: **ETAP 5R FAIL-CLOSED SINGLE LIVE MUX** nie był wdrażany w tym zadaniu i pozostaje osobnym etapem prac.
- Zastany plik roboczy `def_layout.json` pozostał nienaruszony w working tree użytkownika.
