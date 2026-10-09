# Raport: Tymczasowe Usunięcie / Ukrycie Uploadu do YouTube z GUI

## 1. Kontekst i Cel Zadania

W BikeRideHUD istniała opcjonalna funkcja automatycznego uploadu wyrenderowanego materiału wideo do YouTube bezpośrednio po zakończeniu renderingu. Ponieważ upload do YouTube wymaga zewnętrznej konfiguracji konta Google Cloud Console oraz autoryzacji OAuth 2.0 (pliki `youtube_client_secret.json` i `youtube_token.json`), na obecnym etapie rozwoju funkcja ta wprowadzała niepotrzebne komplikacje dla użytkowników końcowych.

**Cele wdrożenia:**
1. Całkowite ukrycie kontrolek YouTube w zakładce Rendering / Eksport w GUI.
2. Zachowanie całego kodu backendu (`YouTubeUploader`, OAuth, obsługa chunków, tokenów) bez usuwania modułów.
3. Architektura pojedynczego przełącznika (feature flag `ENABLE_YOUTUBE_UPLOAD_UI = False`) umożliwiająca natychmiastowe przywrócenie funkcji w przyszłości.
4. Poprawa układu okna — przestrzeń zwolniona po usunięciu ramki YouTube została naturalnie wykorzystana przez powiększoną listę kolejki (`queue_list`).
5. Brak jakichkolwiek skutków ubocznych: brak wyjątków `AttributeError`, brak zapytań o credentiale, brak wyzwalania uploadera w tle, pełna funkcjonalność normalnego eksportu bezpośredniego (Direct) i kolejkowego (Queue).
6. 100% parytet skrótów SHA-256 (`FIXED_SOURCE_HASH_PARITY=YES`) pomiędzy `BikeRideHUD-main-new` i `BikeRideHUD-portable`.

---

## 2. Wdrożone Zmiany w Kodzie

### 2.1. Feature Flag w `src/gui/export_queue.py`
W module zarządzania kolejką wprowadzono centralną flagę z czytelnym komentarzem architektonicznym oraz opcjonalnym przełącznikiem zmiennej środowiskowej:

```python
# ==============================================================================
# YouTube upload feature flag
# Set to True to re-enable YouTube upload configuration in GUI and processing.
# YouTube upload UI temporarily disabled.
# Backend retained for future re-enable.
# ==============================================================================
ENABLE_YOUTUBE_UPLOAD_UI: bool = os.getenv("TELEM_ENABLE_YOUTUBE_UPLOAD", "0").strip().lower() in ("1", "true", "yes", "on")
ENABLE_YOUTUBE_UPLOAD: bool = ENABLE_YOUTUBE_UPLOAD_UI
YOUTUBE_UPLOAD_FEATURE_ENABLED: bool = ENABLE_YOUTUBE_UPLOAD_UI
```

W metodach uploadera w kolejce dodano twarde strażniki (guard clauses):
- `_try_start_upload()`: zwraca natychmiast `None` jeśli `not ENABLE_YOUTUBE_UPLOAD`.
- `_next_waiting_upload()`: zwraca `None` jeśli `not ENABLE_YOUTUBE_UPLOAD`.
- `ExportJob` oraz `YouTubeUploader` pozostają w pełni zaimplementowane i gotowe do pracy w momencie przestawienia flagi.

### 2.2. Panel Kolejki i Layout w `src/gui/qt/tabs/render_tab.py`
W module interfejsu renderowania:
1. **Import flagi:** `ENABLE_YOUTUBE_UPLOAD_UI` zaimportowane bezpośrednio z `src.gui.export_queue`.
2. **Warunkowe budowanie UI w `_build_queue_panel()`:**
   - Gdy `ENABLE_YOUTUBE_UPLOAD_UI == False`:
     - Ramka `yt_frame` nie jest tworzona ani dodawana do layoutu `vbox`.
     - Atrybuty `self.chk_yt_enabled = None`, `self.edit_yt_title = None`, `self.cmb_yt_privacy = None`, `self.edit_yt_desc = None`.
     - Wysokość `queue_list` została zwiększona z domyślnego maksimum 180 px do 260 px (`minimumHeight(80)`, `maximumHeight(260)`), dzięki czemu lista zadań estetycznie wypełnia prawy panel i pozwala na wygodny podgląd wielu zadań bez pustych przestrzeni w układzie.
   - Gdy `ENABLE_YOUTUBE_UPLOAD_UI == True`:
     - Cała ramka `yt_frame` (checkbox „Upload YouTube po renderze”, tytuł, prywatność, opis, automatyczne odblokowywanie po zaznaczeniu) jest tworzona dokładnie tak jak dotychczas.
3. **Bezpieczne dodawanie do kolejki w `_on_add_to_queue()`:**
   - Odczyt wartości z kontrolek zabezpieczono bezpiecznymi wartościami fallback:
     ```python
     yt_enabled = bool(self.chk_yt_enabled and self.chk_yt_enabled.isChecked())
     yt_title = self.edit_yt_title.text().strip() if self.edit_yt_title is not None else ""
     yt_privacy = (self.cmb_yt_privacy.currentData() or "private") if self.cmb_yt_privacy is not None else "private"
     yt_desc = self.edit_yt_desc.text().strip() if self.edit_yt_desc is not None else ""
     ```
   - Każde nowe zadanie otrzymuje `yt_enabled=False`.
4. **Odświeżanie listy kolejki w `_refresh_queue_ui()`:**
   - Wyświetlanie etykiety uploadu (`| YT: ...`) jest aktywne wyłącznie, gdy `job.yt_enabled and ENABLE_YOUTUBE_UPLOAD_UI`.

---

## 3. Instrukcja Ponownego Włączenia Funkcji (Future Re-enable)

Aby w przyszłości ponownie aktywować interfejs i proces uploadu YouTube, wystarczy w jednym miejscu:
1. W pliku `src/gui/export_queue.py` zmienić:
   ```python
   ENABLE_YOUTUBE_UPLOAD_UI: bool = True
   ```
   **LUB**
2. Uruchomić aplikację ze zmienną środowiskową:
   ```cmd
   set TELEM_ENABLE_YOUTUBE_UPLOAD=1
   ```

Po przestawieniu tej flagi kontrolki natychmiast pojawią się w GUI, powrócą do wcześniejszych rozmiarów, a zadania z zaznaczoną opcją będą po wyrenderowaniu przekazywane do `YouTubeUploader`.

---

## 4. Wyniki Testów

Stworzono dedykowany zestaw testów jednostkowych: `tests/test_youtube_upload_ui_disabled.py`.

```
tests/test_youtube_upload_ui_disabled.py::test_feature_flag_defaults PASSED
tests/test_youtube_upload_ui_disabled.py::test_youtube_ui_hidden_when_disabled PASSED
tests/test_youtube_upload_ui_disabled.py::test_add_to_queue_without_youtube_controls PASSED
tests/test_youtube_upload_ui_disabled.py::test_upload_not_triggered_when_feature_disabled PASSED
tests/test_youtube_upload_ui_disabled.py::test_youtube_ui_re_enabled_with_flag PASSED
```

Testy zweryfikowały:
- Domyślne wartości flag (`False`).
- Brak kontrolek i etykiet YouTube w drzewie Qt przy wyłączonej fladze.
- Poprawny rozmiar `queue_list` (max 260 px).
- Poprawne tworzenie `ExportJob` w GUI z `yt_enabled=False`.
- Brak uruchomienia uploadera przy zakończeniu renderowania.
- Prawidłowe pojawienie się kontrolek przy włączeniu flagi w środowisku testowym (`monkeypatch`).

Dodatkowo uruchomiono pełną baterię testów regresyjnych (kolejka eksportu, startup, parametry sterujące):
```
collected 50 items
tests/test_youtube_upload_ui_disabled.py .....                           [ 10%]
tests/test_render_tab_controls_cleanup.py .........                      [ 28%]
tests/test_export_queue_basic.py ........................                [ 76%]
tests/test_queue_requeue_pending.py ............                         [100%]
============================= 50 passed in 4.39s ==============================
```

---

## 5. Status Parytetu Źródeł

Wszystkie zmodyfikowane pliki oraz nowy plik testów i raport zostały zsynchronizowane pomiędzy:
- `C:\_DEV\BikeRideHUD-main-new`
- `C:\_DEV\BikeRideHUD-portable`

Skrypt weryfikacyjny `scripts/check_parity.py` potwierdza:
`FIXED_SOURCE_HASH_PARITY=YES`.
