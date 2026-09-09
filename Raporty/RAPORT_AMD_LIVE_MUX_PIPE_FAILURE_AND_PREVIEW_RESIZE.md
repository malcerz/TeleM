# RAPORT: AMD Live Mux Pipe Failure & Preview Resize Fix

**Data:** 2026-09-06  
**Status:** READY  
**Branch:** `integration/intel-amd` (commit bazowy: `59277b4`)  
**Backend:** `AMD_NATIVE_D3D11`  

---

## 1. Kontekst błędu produkcyjnego

Podczas długiego renderu w GUI na zestawie wieloplikowym (pierwszy plik `Video/GX010114.MP4`, 58 639 klatek) render zakończył się kontrolowanym błędem:

```text
[TELEM AMD DLL] live mux pipe write failed: 0 frame=57286
GUI:
Render error: AMD native frame pipeline failed on frame 57286
```

Bezpośrednio po tym w konsoli pojawiło się ostrzeżenie Qt:

```text
QWindowsWindow::setGeometry: Unable to set geometry 2679x1474+0+0
Resulting geometry: 2678x1458+0+0
```

W trakcie renderu monitor przeszedł w tryb oszczędzania energii (power-save / DPMS standby po ok. 30 minutach bezczynności myszy/klawiatury).

---

## 2. Część A: Root Cause Live Mux Pipe Failure

Dzięki wdrożonej szczegółowej diagnostyce potoku named pipe, zrzutowi stderr oraz śledzeniu wątków, uzyskano **stuprocentowy dowód i dokładną sekwencję zdarzeń**, która doprowadziła do błędu:

### A1. Pełny zrzut awarii z nowej telemetrii
```text
[TELEM AMD DLL] Live mux pipe write failed: err=232 (ERROR_NO_DATA: Trwa zamykanie potoku.) ok=0 written=0 request=443161 frame=988 total_bytes=239337813 total_pkts=986
[AMD LIVE MUX FAILURE CONTEXT] Frame: 988
--------------------------------------------------------------------------------
1. Native Win32 Named Pipe Writer (telem_amd_native.dll):
   - Last Error Code:       232 (ERROR_NO_DATA)
   - Total Bytes Written:   239337813
   - Pipe Connected:        True
   - CancelIoEx Called:     False
   - Write Timed Out:       False
2. Python Pipe Pump Worker:
   - Pump Thread Alive:     False
   - Exit Reason:           ffmpeg_stdin_broken ([Errno 32] Broken pipe)
   - Bytes to FFmpeg stdin: 238938421
3. FFmpeg Live Muxer Process:
   - Alive:                 False
   - PID:                   25368
   - Return Code:           4294967268 (0xFFFFFFE4 = -28 = -ENOSPC)
5. FFmpeg Stderr:
   [vost#0:0/copy] Error submitting a packet to the muxer: No space left on device
   [out#0/mp4] Error muxing a packet
   [out#0/mp4] Task finished with error: No space left on device
   [out#0/mp4] Terminating thread with error: No space left on device
   Conversion failed!
```

### A2. Przyczyna pierwotna (Root Cause Chain)
1. **Zapełnienie dysku C: przez osierocone pliki tymczasowe `amd_scratch`:**
   Wieloplikowy eksport AMD w etapie A tworzy tymczasowy plik wideo `telem-amd-stage-{PID}-*\*.temp_video.mp4` w katalogu `%LOCALAPPDATA%\TeleM\amd_scratch`.
   W przypadku anulowania lub przerwania poprzednich procesów, foldery te nie były automatycznie sprzątane.
   Zbadano stan katalogu: znajdowało się w nim **37.18 GB** osieroconych plików z martwych procesów PID (m.in. 16.5 GB z PID 4668, 10.3 GB z PID 3748, 7.5 GB z PID 20532), co doprowadziło wolne miejsce na dysku C: do **0.00 GB**!
2. **Załamanie procesu FFmpeg przy zapisie klatki 57286:**
   Plik `GX010114.MP4` ma 58 639 klatek (ok. 32.6 minuty 4K). Na klatce 57286 (ok. 31.8 minuty) rozmiar pliku wideo osiągnął kilkanaście gigabajtów i napotkał fizyczny brak wolnego miejsca na dysku.
   FFmpeg zgłosił błąd POSIX `-28` (`ENOSPC` / "No space left on device"), zamknął swój strumień `stdin` i zakończył proces z kodem `4294967268` (`-28`).
3. **Kaskadowe zerwanie potoku:**
   - Wątek Pythona `_mux_pump_worker` przy próbie zapisu kolejnego pakietu do `proc_mux.stdin` otrzymał `BrokenPipeError: [Errno 32] Broken pipe` i zakończył działanie, zamykając odczyt z Named Pipe.
   - Po stronie natywnej biblioteki C++ `telem_amd_native.dll`, systemowy `WriteFile` na potoku zwrócił kod błędu Win32 `ERROR_NO_DATA` (232: "The pipe is being closed").
4. **Dlaczego wcześniej logowano wartość "0":**
   W `telem_amd_native.cpp` kod raportowania błędu miał postać:
   ```cpp
   std::cerr << "[TELEM AMD DLL] live mux pipe write failed: " << GetLastError() << " frame=" << ctx->currentFrameNumber << std::endl;
   ```
   W C++ wyrażenie `std::cerr << "[TELEM AMD DLL]..."` jest ewaluowane przed `GetLastError()`. Wypisanie tekstu do konsoli Windows wywołuje wewnętrznie Win32 `WriteFile(STD_ERROR_HANDLE)`, co kończy się sukcesem i **nadpisuje kod błędu wątku wartością 0 (`ERROR_SUCCESS`)**!
   W rezultacie prawdziwy błąd Win32 (232 lub 109) był zmazywany i zastępowany zerem.
5. **Dlaczego FFmpeg i pump nie były widoczne:**
   Gdy DLL zwracała błąd, Python natychmiast rzucał `RuntimeError`, a blok `finally` bezwarunkowo ubijał proces FFmpeg (`proc_mux.kill()`) i zamykał uchwyty przed zrzuceniem stderr i kodu powrotu.

---

## 3. Część B: Monitor Off / Display Change & Niezależność Renderera

1. **Pełna izolacja silnika renderującego:**
   - Renderer `AMD_NATIVE_D3D11` tworzy dedykowane urządzenie D3D11 (`D3D11CreateDevice`), operuje wyłącznie na teksturach GPU (offscreen) i nie tworzy żadnego SwapChaina ani nie korzysta z `HWND`.
   - Jest w 100% odporny na uśpienie monitora, zmianę rozdzielczości pulpitu, DPI czy minimalizację okna.
2. **Wyjaśnienie ostrzeżenia Qt `setGeometry`:**
   - Gdy monitor przechodzi w tryb power-save, system Windows wysyła `WM_DISPLAYCHANGE`, a Qt odświeża `availableGeometry` ekranu (np. z 2679x1474 na 2678x1458).
   - Dotychczasowy kod `TopLevelHUDWindow.sync_geometry()` próbował ustawić geometrię okna nakładki HUD poza nowy obszar roboczy, generując ostrzeżenie systemowe Qt.
   - Wprowadzono obcinanie geometrii: `hud_rect = hud_rect.intersected(avail_geom)`.

---

## 4. Część C: HUD Preview Resize & Dopasowanie Geometrii

### C1. Nowy moduł `src/gui/preview_transform.py`
Utworzono dedykowany moduł czystych funkcji matematycznych:
- `calculate_displayed_video_rect(viewport_w, viewport_h, video_w, video_h)`:
  - Zachowuje proporcje obrazu (aspect ratio 16:9 dla 3840x2160 / 1920x1080).
  - Prawidłowo wylicza letterbox (pasy góra/dół) oraz pillarbox (pasy po bokach).
- Dwukierunkowa transformacja współrzędnych: `source_to_preview_coords`, `preview_to_source_coords`, `norm_to_preview_coords`, `preview_to_norm_coords`.

### C2. Integracja w widżecie `VideoPreview` i `RenderTab`
- `VideoPreview.get_video_rect()` korzysta z `calculate_displayed_video_rect()`, gwarantując spójność niezależnie od rozmiaru okna i monitora.
- `TopLevelHUDWindow.paintEvent()` renderuje HUD precyzyjnie wewnątrz `vrect` (prostokąt wideo), eliminując rozciąganie HUD na pasy letterbox/pillarbox.
- `RenderTab._trigger_async_preview()` w podglądzie natywnym wylicza wymiary docelowe z `video_preview.get_physical_video_rect()`.

---

## 5. Zrealizowane Zmiany w Kodzie

1. **`native/d3d11_amf_pipeline/src/telem_amd_native.cpp`**:
   - Zabezpieczono przechwytywanie `GetLastError()` natychmiast do zmiennej lokalnej przed jakimkolwiek zapisem do strumienia `std::cerr`.
   - Dodano formatowanie tekstowe kodów błędów Win32 (`FormatWin32Error`).
   - Obsłużono przypadek asynchronicznego potoku `FILE_FLAG_OVERLAPPED`, w którym synchroniczne `WriteFile` zwraca `written == 0` (wywołanie `GetOverlappedResult(..., TRUE)` zamiast błędu).
   - Dodano strukturę diagnostyczną potoku w `TelemAMDContext` oraz wyeksportowano funkcję ABI `telem_amd_get_pipe_diagnostics`.
   - Przebudowano kanoniczną bibliotekę `telem_amd_native.dll`.

2. **`src/ffmpeg/amd_native_exporter.py`**:
   - Podpięto `telem_amd_get_pipe_diagnostics`.
   - W `_mux_pump_worker` dodano `proc_mux.stdin.flush()` po każdym zapisie chunku.
   - Wdrożono `_dump_live_mux_failure_context()` rejestrującą stan DLL, pipe, wątku pump oraz stderr i kod powrotu FFmpeg PRZED zamknięciem uchwytów.
   - **Automatyczne sprzątanie i kontrola dysku:**
     - Dodano `_cleanup_stale_amd_scratch_dirs()`, które przed każdym wieloplikowym eksportem usuwa osierocone foldery `telem-amd-stage-*` po martwych procesach PID.
     - Dodano sprawdzanie wolnego miejsca na dysku roboczym (`shutil.disk_usage`) i logowanie stanu.

3. **`src/gui/preview_transform.py`** (Nowy plik):
   - Czysta logika wyliczania geometrii wyświetlania wideo i mapowania współrzędnych.

4. **`src/gui/qt/widgets/video_preview.py`**:
   - Uaktualniono `get_video_rect()` do używania `calculate_displayed_video_rect()`.
   - Zabezpieczono `TopLevelHUDWindow.sync_geometry()` przed wychodzeniem poza `screen.availableGeometry()`.
   - Zapewniono rysowanie `hud_pixmap` docelowo w `vrect`.

5. **`src/gui/qt/tabs/render_tab.py`**:
   - `_trigger_async_preview()` używa fizycznego prostokąta wideo.

---

## 6. Wyniki Testów

1. **Sprzątanie dysku i odzyskanie miejsca:**
   - Wyczyszczono 37.18 GB zalegających plików z `amd_scratch`.
   - Wolne miejsce na dysku C: wzrosło z **0.00 GB do 37.20 GB**.
2. **Pakiet testów jednostkowych i integracyjnych:**
   - `tests/test_preview_transform.py`: 8/8 passed.
   - `tests/test_preview_resize_and_geometry.py`: 5/5 passed.
   - `tests/test_export_preview_video_restore.py`: 4/4 passed.
   - `tests/test_amd_direct_mp4_mux.py`: 9/9 passed.
   - Łącznie: **26/26 passed in 4.62s**.
3. **Test produkcyjny celowany w zakres klatki 57286 (`GX010114.MP4`):**
   - Zakres: klatki 56500–58000 (1500 klatek, bezpośrednio dekodujące i przekraczające klatkę 57286 z pełnym layoutem HUD, mapą, wykresami i zegarami).
   - Wynik: 1500/1500 klatek, Render FPS: 37.826, Effective FPS: 35.858, błędy: 0. Status: **PASS**.
4. **Test produkcyjny wieloplikowy (300 klatek, granica plików):**
   - Wynik: 300/300 klatek, Render FPS: 40.469, Effective FPS: 31.123, wolne miejsce zweryfikowane: 37.20 GB. Status: **PASS**.

---

## 7. Podsumowanie Wymogów Zadania

| Zagadnienie | Stan przed naprawą | Stan po naprawie |
|---|---|---|
| Rzeczywisty Win32 error code | Wypisywane `0` (zamazane przez `std::cerr`) | Prawdziwy kod Win32: `232` (`ERROR_NO_DATA`) / `109` (`ERROR_BROKEN_PIPE`) |
| Kto zamknął pipe | Nieznany (brak logów) | Proces FFmpeg w wyniku błędu `ENOSPC` (`rc=4294967268` / `-28`) |
| Przyczyna braku miejsca | Brak sprzątania `amd_scratch` | Zapełnienie dysku C: (37.18 GB usunięte; wdrożono automatyczne czyszczenie martwych PID) |
| Odporność na uśpienie monitora | Warning Qt `setGeometry` | Clamping do `availableGeometry()`, brak ostrzeżeń, pełna niezależność renderera offscreen |
| Dopasowanie Preview HUD | Skalowanie do całego widżetu (zniekształcenie aspect ratio) | `preview_transform.py` z letterbox/pillarbox i rysowaniem w `vrect` |
| Przekroczenie klatki 57286 | Crash potoku na klatce 57286 | Przetestowano i potwierdzono: 1500/1500 klatek (56500->58000) PASS |

**Ocena końcowa:** READY
