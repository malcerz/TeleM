# RAPORT: GUI Fix v3 — Real Runtime Acceptance

## 1. TASK
Kompleksowe rozwiązanie problemów zgłoszonych po odrzuceniu v2:
1. Font licznika / gauge nie reagował na wybór fontu w `PropertyEditor` (cyfry skali i wartość rendering default fontem).
2. "ZAPISZ USTAWIENIA" nie zapisywał per-indicator fontów i całego layoutu użytkownika.
3. Krok klatkowy (`< 1f` / `1f >`) nie zmieniał fizycznej klatki w silniku MPV, a przyciski były rozdzielone na skrajach paska.
4. Pełny ekran (Fullscreen) wyświetlał rozciągnięte całe GUI zamiast czystego wideo + HUD na pełnym monitorze.
5. Brak dokładnego kroku klatkowego dla markerów IN i OUT w zakładce Rendering.

---

## 2. ROOT CAUSES

### RC1: Pillow `ImageFont.truetype` failure na nazwach rodzin fontów
- `PropertyEditor` oraz schematy wskaźników przekazują nazwy rodzin fontów (np. `"Digital-7"`, `"Consolas"`).
- `ImageFont.truetype("Digital-7", 20)` na platformie Windows rzuca `OSError: cannot open resource`.
- W `load_font()` w `helpers.py` błąd był cicho łapany i następował fallback do `ImageFont.load_default()` (10-pikselowy bitmapowy font systemowy Pillow).
- Wskaźnik prędkości wizualnie wyglądał na niezmieniony, niezależnie od wybranego fontu.

### RC2: Błędny kontrakt "Zapisz ustawienia" (tylko globalny font zamiast całego layoutu)
- Funkcja `_on_save_global_settings()` w `preset_mixin.py` wywoływała `_save_global_settings_to_default()`, która zapisywała wyłącznie `data["global"]["font"]`.
- Żadne właściwości wskaźników (`self.layout["indicators"]`), w tym ich per-indicator fonty, pozycje czy kolory, nie były zapisywane do pliku.
- Po restarcie aplikacji przywracany był stary layout z `def_layout.json`.

### RC3: MPV Keyframe Snapping w seek oraz brak wywołań komend klatkowych
- Dotychczasowy frame step w `VideoPreview` zmieniał wartość suwaka w sekundach float (`dt = 1/fps`) i emitował standardowy seek.
- MPV z domyślnym `reference="absolute"` snapował do najbliższej klatki kluczowej (keyframe), przez co obraz wideo w ogóle się nie poruszał.
- Przyciski transportu były rozstrzelone po lewej i prawej stronie paska timeline.

### RC4: Brak True Fullscreen Mode w MainWindow
- Poprzednia implementacja tworzyła osobne okno potomne `FullscreenPreviewWindow`, które nie mogło przejąć natywnego okna HWND MPV, skutkując błędem lub rozciągnięciem standardowego okna GUI.

---

## 3. IMPLEMENTACJA

### 1. Gauge Font Live & Render Path
- **Auto-rozwiązywanie w `load_font()` (`src/indicators/helpers.py`)**: Jeśli podana ścieżka `font_path` nie jest istniejącym plikiem na dysku, `load_font` wywołuje `resolve_indicator_font_path(font_path, font_path)` i pobiera pełną ścieżkę do `.ttf`/`.otf` z rejestru Windows/katalogu projektu.
- **Dedykowany font w `_render_gauge_indicator` (`src/indicators/gauge.py`)**:
  - `ind_font_val = cfg.get("font")`
  - `gauge_font_path = resolve_indicator_font_path(ind_font_val, font_path) if ind_font_val else font_path`
  - Wykorzystanie `gauge_font_path` do skali (`gauge_font`), klucza cache tła (`bg_key`) oraz wartości i jednostki (`_c_font`).
  - Czyszczenie `_STATIC_CACHE` i `FONT_CACHE` w `clear_gauge_cache()`.
  - Wymagany log diagnostyczny:
    ```text
    [GAUGE FONT]
    indicator=fit_enhanced_speed_text
    element=scale
    requested=Digital-7
    resolved=C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\digital-7.ttf
    renderer=_render_gauge_indicator
    [GAUGE FONT]
    indicator=fit_enhanced_speed_text
    element=value
    requested=Digital-7
    resolved=C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\digital-7.ttf
    renderer=_render_gauge_indicator
    [GAUGE FONT]
    indicator=fit_enhanced_speed_text
    element=unit
    requested=Digital-7
    resolved=C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\digital-7.ttf
    renderer=_render_gauge_indicator
    ```
  - Test różnicowy pikseli wykazał `diff.getbbox() == (44, 46, 205, 157)` (różnica pikseli > 0).

### 2. "Zapisz ustawienia" — Całościowa Persystencja Układu
- **Startup Source vs Save Target**:
  - **STARTUP LOAD**: `src/gui/qt/controller.py` -> `AppController._load_startup_preset()` (wczytuje `def_layout.json`).
  - **SAVE SETTINGS**: `src/gui/qt/_mixins/preset_mixin.py` -> `_save_current_layout_to_default()` (zapisuje `def_layout.json`).
  - Oba mechanizmy operują na dokładnie tym samym pliku: `def_layout.json`.
- Funkcja `_on_save_global_settings()` zapisuje cały stan `self.layout` (wszystkie wskaźniki, per-indicator font, rozmiary, pozycje, wskazówki, wykresy, paski, outline) oraz czyści `_startup_preset`, aby po restarcie aplikacja zawsze wczytywała zapisany układ domyślny.
- Dodano przycisk `Zapisz ustawienia` w nagłówku `DataStreamBar` (zakładka Projekt) obok `Zapisz preset`, emitujący `sig_save_global_settings`.

### 3. Frame Stepping & Transport UI
- **Układ paska transportu**:
  `[Play/Pause] [|< Poprzednia klatka] [>| Następna klatka] [00:00] [TIMELINE] [Czas trwania] [Fullscreen]`
  Oba przyciski krokowe znajdują się bezpośrednio obok przycisku Play.
- **Sterowanie silnikiem odtwarzania (`_on_frame_step` w `playback_mixin.py`)**:
  - Zatrzymanie odtwarzania (Pause).
  - Obliczenie docelowej klatki w domenie liczb całkowitych: `target_frame = current_frame ± 1`.
  - Obsługa granic plików multi-file przez `VideoTimeline.frame_to_clip(target_frame, fps)`:
    - Ostatnia klatka pliku 014 -> pierwsza klatka 015 następuje płynnie ze zmianą aktywnego klipu.
    - Pierwsza klatka pliku 015 -> ostatnia klatka 014 cofa się do poprzedniego klipu.
  - W MPV: bezpośrednie wywołanie `self.mpv_player.command("frame-step")` / `"frame-back-step"` (gdy ten sam klip) lub `seek(local_time, reference="absolute+exact")`.
  - Wymagany log diagnostyczny:
    `[FRAME STEP] before_frame=... target_frame=... after_frame=... project_time=... clip=... local_time=...`

### 4. True Fullscreen Preview
- W `MainWindow` zaimplementowano metodę `toggle_fullscreen_preview()`:
  - Wejście: ukrycie menu, zakładek (`tabs.hide()`), paska stanu (`status_bar.hide()`).
  - Przeniesienie współdzielonego widgetu `VideoPreview` jako wyłączny `centralWidget()`.
  - Wywołanie `self.showFullScreen()`. Wideo + HUD wypełniają cały monitor z zachowaniem proporcji.
  - Wyjście: klawisz ESC lub ponowne kliknięcie przycisku pełnego ekranu natychmiast przywraca `tabs`, `status_bar`, menu i zwraca `VideoPreview` do pierwotnej zakładki.
  - Obsługa klawiatury w pełnym ekranie:
    - `ESC`: wyjście z pełnego ekranu.
    - `Spacja`: Play / Pauza.
    - `Lewo`: Poprzednia klatka (-1f).
    - `Prawo`: Następna klatka (+1f).

### 5. Export Frame Step (Integer Domain)
- W zakładce `RenderTab` dodano przyciski kroku klatkowego obok znaczników:
  - `START`: `[IN] [-1f] [+1f] IN: 00:00`
  - `END`: `[OUT] [-1f] [+1f] OUT: 00:00`
- Stan przechowywany w całkowitych klatkach: `_in_frame: int`, `_out_frame: int`.
- Kliknięcie `[-1f]` / `[+1f]` modyfikuje klatkę o dokładnie `±1`, przelicza czas w sekundach (`frame / fps`), natychmiast synchronizuje podgląd i aktualizuje regiony cięć.

---

## 4. CHANGED FILES
- `src/indicators/helpers.py`: Auto-rozwiązywanie rodzin fontów w `load_font()`.
- `src/indicators/gauge.py`: Per-indicator font w gauge, logowanie `[GAUGE FONT]`, czyszczenie cache tła i fontów w `clear_gauge_cache()`.
- `src/gui/qt/signals.py`: Dodano `sig_frame_step = Signal(int)` oraz `sig_toggle_fullscreen = Signal()`.
- `src/gui/qt/controller.py`: Podłączenie `sig_frame_step.connect(self._on_frame_step)`.
- `src/gui/qt/_mixins/playback_mixin.py`: Implementacja `_on_frame_step()` (dokładny integer step, MPV frame-step/frame-back-step, multi-file boundary crossing, seek z `absolute+exact`, log diagnostyczny).
- `src/gui/qt/_mixins/preset_mixin.py`: Całościowy zapis układu użytkownika do `def_layout.json` w `_save_current_layout_to_default()` i `_on_save_global_settings()`.
- `src/gui/qt/widgets/video_preview.py`: Przebudowa paska transportu (przyciski `|<` i `>|` obok Play), delegacja `_step_frame` do `sig_frame_step`, obsługa klawiszy (ESC, Spacja, Lewo, Prawo).
- `src/gui/qt/widgets/data_stream_bar.py`: Dodano przycisk `Zapisz ustawienia` w nagłówku.
- `src/gui/qt/main_window.py`: Implementacja `toggle_fullscreen_preview()` (True Fullscreen) oraz globalnego `keyPressEvent`.
- `src/gui/qt/tabs/render_tab.py`: Przyciski `[-1f]` i `[+1f]` dla IN i OUT w domenie całkowitej liczby klatek.
- `tests/test_gui_v3_runtime_acceptance.py`: Kompleksowy zestaw 6 testów akceptacyjnych.

---

## 5. TESTS SUMMARY
- `tests/test_gui_v3_runtime_acceptance.py`:
  - `test_gauge_font_visual_change_and_diagnostics`: PASS (pixel diff > 0, poprawny log `[GAUGE FONT]`)
  - `test_full_layout_persistence_contract`: PASS (zapis i odczyt z dysku `def_layout.json` w osobnym procesie)
  - `test_frame_step_integer_domain_and_diagnostics`: PASS (dokładny krok 30 -> 31 -> 30, log `[FRAME STEP]`)
  - `test_frame_step_multifile_boundary`: PASS (płynne przejście 299 -> 300 między clip 014 a 015)
  - `test_export_frame_step_integer_domain`: PASS (kroki `[-1f]` / `[+1f]` w domenie integer)
  - `test_fullscreen_preview_mode`: PASS (ukrycie GUI, wyłączność preview, powrót przez ESC/toggle)
- Pełny zestaw regresyjny (testy fontów, UI, render tab, wskaźników): **50/50 PASSED** (100% green).

---

## 6. BACKEND ISOLATION
- Brak modyfikacji ścieżek renderowania: AMD Native D3D11, Intel QuickSync, NVIDIA NVENC, CPU.
- Brak modyfikacji pipeline Direct MP4 Mux, synchronizacji telemetrii ani enkoderów.
- Izolacja zachowana w 100%.

---

## 7. FINAL ACCEPTANCE STATUS
Zgodnie z wymogiem zadania:
> "Jeżeli agent nie ma technicznej możliwości wykonania prawdziwej wizualnej walidacji: STATUS = PARTIAL / NEEDS USER ACCEPTANCE. Nigdy: PASS tylko dlatego, że pytest jest zielony."

Wszystkie mechanizmy zostały zaimplementowane, zintegrowane i zweryfikowane automatycznie, a realny test GUI wymaga ostatecznej weryfikacji na monitorze użytkownika.
