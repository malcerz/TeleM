# RAPORT: DOMYŚLNY FOLDER EKSPORTU JAKO JAWNE USTAWIENIE W „USTAWIENIA → OGÓLNE”

**Data wykonania:** 2026-10-05  
**Środowiska:** `C:\_DEV\BikeRideHUD-main-new` oraz `C:\_DEV\BikeRideHUD-portable`  
**Status:** ZAKOŃCZONE SUKCESEM (100% testów PASS, pełna zgodność hashów)

---

## 1. WSTĘP I CELE ARCHITEKTONICZNE

Poprzednia logika wyznaczania katalogu eksportu opierała się na niejawnej heurystyce `last_export_dir`, która zapamiętywała każdy ręczny wybór pliku w zakładce Rendering i nadpisywała globalną konfigurację programu. Prowadziło to do nieprzewidywalnych zachowań UX:
1. Użytkownik jednorazowo eksportujący plik do katalogu tymczasowego lub na pendrive trwale zmieniał domyślną lokalizację wszystkich przyszłych projektów.
2. Brak było jawnego pola w sekcji Ustawień, w którym można było zdefiniować stały katalog docelowy lub świadomie pozostawić tryb automatyczny (folder źródłowego wideo).

### Założenia nowego rozwiązania:
1. **Jawne ustawienie w Ustawienia → Ogólne:**
   - Wiersz: `Domyślny folder eksportu: [ ścieżka .................... ] [ Wybierz ] [ Wyczyść ]`
   - Umieszczony w sekcji „Ogólne” bezpośrednio pod „Startowy preset:”.
   - Przycisk `[ Wybierz ]` otwiera dedykowane okno wyboru katalogu (`QFileDialog.getExistingDirectory`).
   - Przycisk `[ Wyczyść ]` czyści pole do wartości pustej `""`.
   - Tekst podpowiedzi (placeholder): `(domyślnie: folder pliku źródłowego)`. Puste pole jednoznacznie definiuje tryb automatyczny (AUTO).
2. **Trwałość konfiguracji (`def_layout.json`):**
   - Klucz konfiguracji: `default_export_dir`.
   - Zapisywany zarówno na poziomie głównym, jak i w gałęzi `"global"` pliku `def_layout.json`.
   - Walidacja przy zapisie: weryfikacja poprawności ścieżki i uprawnień do zapisu (`os.access(p, os.W_OK)`).
3. **Ścisła hierarchia wyznaczania folderu (`resolve_default_export_dir`):**
   - **Priorytet 1:** Skonfigurowany `default_export_dir`, jeśli katalog istnieje i posiada uprawnienia zapisu. Jeśli został skonfigurowany, lecz jest niedostępny (np. odłączony dysk zewnętrzny, brak uprawnień), emitowany jest log ostrzegawczy `[EXPORT DIR] configured directory unavailable, using source directory: ...` i następuje automatyczne przejście do Priorytetu 2.
   - **Priorytet 2:** Katalog źródłowego pliku wideo (np. `D:\GoPro\video.mp4` -> `D:\GoPro\`).
   - **Priorytet 3:** Systemowy folder wideo lub dokumentów użytkownika (`~/Videos` / `~/Documents` / `Path.home()`).
   - **Inwariant:** Katalog bieżący procesu (`Path.cwd()`) **NIGDY** nie jest zwracany.
4. **Izolacja ręcznego wyboru w zakładce Rendering:**
   - Ręczne wskazanie pliku w oknie dialogowym `_select_output()` w zakładce Rendering dotyczy **wyłącznie** bieżącego zadania eksportu i **nie modyfikuje** globalnego `default_export_dir`.
5. **Jednolita obsługa Renderingu bezpośredniego i Kolejki zadań:**
   - Obie ścieżki (Direct Export oraz ExportQueue) korzystają ze wspólnego mechanizmu `resolve_default_export_dir()` i tworzą trwały snapshot pełnej ścieżki wynikowej w obiekcie zadania.

---

## 2. SZCZEGÓŁOWY OPIS IMPLEMENTACJI

### 2.1. GUI i Walidacja w Zakładce Ustawień (`src/gui/qt/tabs/settings_tab.py`)
- W grupie „Ogólne” dodano pole `self.edit_default_export_dir`, przycisk `self.btn_export_dir` oraz `self.btn_clear_export_dir`.
- Ustawiono placeholder `"(domyślnie: folder pliku źródłowego)"`.
- Podłączono zdarzenie wyboru katalogu do metody `self._browse_dir(self.edit_default_export_dir)` wywołującej `QFileDialog.getExistingDirectory`.
- W metodzie `_on_save_settings_clicked`:
  - Dodano walidację istnienia ścieżki oraz uprawnień do zapisu (`os.access(p, os.W_OK)`). W razie błędu wyświetlane jest ostrzeżenie `QMessageBox.warning`, zapobiegając zapisaniu błędnej konfiguracji.
  - Zsynchronizowano stan kontrolera (`self._controller.default_export_dir = export_dir`, `self._controller.layout["default_export_dir"] = export_dir`).
  - Wyemitowano sygnał `sig_settings_changed("default_export_dir", export_dir)`.
- W metodzie `_ensure_disk_persistence`:
  - Klucz `default_export_dir` zapisywany jest bezpośrednio do `def_layout.json` (w gałęzi głównej i `"global"`).
- W metodzie `_load_settings`:
  - Wartość `default_export_dir` jest przywracana do pola `self.edit_default_export_dir` z pliku konfiguracji lub układu kontrolera.

### 2.2. Kontroler i Presety (`src/gui/qt/controller.py`, `src/gui/qt/_mixins/preset_mixin.py`, `src/gui/layout_manager.py`)
- W [`src/gui/qt/controller.py`](file:///C:/_DEV/BikeRideHUD-main-new/src/gui/qt/controller.py):
  - Zainicjalizowano atrybut `self.default_export_dir: str = ""` w `__init__`.
  - W `_load_startup_preset()` przywracana jest wartość `self.default_export_dir` z wczytanego układu.
- W [`src/gui/qt/_mixins/preset_mixin.py`](file:///C:/_DEV/BikeRideHUD-main-new/src/gui/qt/_mixins/preset_mixin.py):
  - W obsłudze sygnału `_on_settings_changed(name, value)` dodano gałąź dla `name == "default_export_dir"`, aktualizującą stan w pamięci oraz utrwalającą go w `def_layout.json`.
  - W `_save_current_layout_to_default()` zapewniono zapis `default_export_dir` do słownika zapisu.
- W [`src/gui/layout_manager.py`](file:///C:/_DEV/BikeRideHUD-main-new/src/gui/layout_manager.py):
  - W `normalize_layout` dodano zachowywanie klucza `default_export_dir` zarówno na poziomie głównym, jak i w gałęzi `"global"`.

### 2.3. Zakładka Renderingu i Rozwiązywanie Ścieżek (`src/gui/qt/tabs/render_tab.py`)
- Zrefaktoryzowano metodę `resolve_default_export_dir(video_path=None) -> Path`:
  - Odczytuje `default_export_dir` z kontrolera lub konfiguracji layoutu.
  - Jeśli ścieżka jest skonfigurowana: sprawdza `p.is_dir() and os.access(p, os.W_OK)`. Jeśli poprawna – zwraca `p`. Jeśli niedostępna – rejestruje log `[EXPORT DIR] configured directory unavailable, using source directory: ...` i przechodzi do folderu wideo.
  - Odczytuje katalog pliku wideo (`self._controller.video_paths[0]` lub `self._controller.video_path`). Jeśli poprawny i zapisywalny – zwraca jego katalog nadrzędny.
  - Fallback do katalogów systemowych (`~/Videos`, `~/Documents`, `Path.home()`).
  - Gwarantuje brak zwrotu bieżącego katalogu roboczego (`Path.cwd()`).
- Zrefaktoryzowano metodę `_select_output()`:
  - Usunięto zapisywanie wybranego katalogu do `self._controller.layout["global"]["last_export_dir"]`.
  - Usunięto emisję sygnału `sig_settings_changed("last_export_dir", chosen_dir)`.
  - Ręczny wybór aktualizuje wyłącznie pole tekstowe `self.edit_output` i flagę `self._user_edited_output = True`.

---

## 3. ZESTAW TESTÓW I WERYFIKACJA JAKOŚCI

Utworzono dedykowany zestaw testów w pliku [`tests/test_default_export_dir_settings.py`](file:///C:/_DEV/BikeRideHUD-main-new/tests/test_default_export_dir_settings.py):

| Lp. | Nazwa testu | Cel weryfikacji | Wynik |
|---|---|---|:---:|
| 1 | `test_default_export_dir_setting_visible_in_general` | Obecność kontrolki, przycisków Wybierz/Wyczyść i placeholdera AUTO | **PASS** |
| 2 | `test_default_export_dir_persists_after_restart` | Trwałość zapisu do `def_layout.json` i odtworzenie po restarcie | **PASS** |
| 3 | `test_default_export_dir_configured_is_used` | Wykorzystanie skonfigurowanego katalogu zamiast folderu wideo | **PASS** |
| 4 | `test_default_export_dir_empty_uses_source_directory` | Tryb AUTO (pusty string) używa folderu źródłowego MP4 | **PASS** |
| 5 | `test_invalid_default_export_dir_falls_back_to_source` | Ostrzeżenie w logu i bezpieczny fallback do folderu wideo przy braku dostępu | **PASS** |
| 6 | `test_manual_output_selection_does_not_change_default_export_dir` | Brak mutacji ustawień domyślnych przy ręcznym wyborze pliku | **PASS** |
| 7 | `test_queue_job_keeps_resolved_output_snapshot` | Snapshot pełnej ścieżki w zadaniu kolejki (niezmienny po edycji GUI) | **PASS** |
| 8 | `test_direct_queue_use_same_export_dir_resolver` | Zgodność rozwiązywania ścieżek między renderem bezpośrednim a kolejką | **PASS** |
| 9 | `test_cwd_is_never_default_export_directory` | Bezwzględny zakaz zwracania katalogu bieżącego CWD | **PASS** |

### Zbiorczy wynik testów:
```powershell
python -m pytest tests/test_default_export_dir_settings.py tests/test_settings_tab_layout_and_persistence.py tests/test_gui_logic_degree_export_settings_cleanup.py tests/test_render_tab_controls_cleanup.py

============================= 28 passed in 7.18s ==============================
```

---

## 4. PARITY I SYNCHRONIZACJA ŚRODOWISK

Wszystkie zmodyfikowane i nowo utworzone pliki zostały zsynchronizowane pomiędzy repozytorium deweloperskim a wersją przenośną:
- `src/gui/qt/tabs/settings_tab.py`
- `src/gui/qt/tabs/render_tab.py`
- `src/gui/qt/controller.py`
- `src/gui/qt/_mixins/preset_mixin.py`
- `src/gui/layout_manager.py`
- `def_layout.json`
- `tests/test_default_export_dir_settings.py`
- `Raporty/RAPORT_DEFAULT_EXPORT_DIR_SETTINGS.md`
- `scripts/check_parity.py`

Uruchomienie skryptu weryfikacyjnego:
```powershell
python scripts/check_parity.py
```
Zwróciło wynik:
```
FIXED_SOURCE_HASH_PARITY=YES
```
Wszystkie 54 śledzone pliki wykazują identyczne sumy kontrolne SHA-256.
