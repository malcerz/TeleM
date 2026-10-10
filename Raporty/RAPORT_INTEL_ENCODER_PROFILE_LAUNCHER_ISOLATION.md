# RAPORT: Diagnoza i rozwiązanie problemu braku pola "Profil enkodera" w GUI (Izolacja Launchera)

**Data:** 2026-09-28  
**Środowisko:** Intel Core Ultra 7 255U / Intel Graphics (PC Intel)  
**Kanon:** `C:\_DEV\SportCamHUD-main`  
**Autor:** Antigravity / Gemini High  

---

## 1. Zadanie (TASK)

Zdiagnozowanie i usunięcie przyczyny braku widoczności pola **"Profil enkodera"** w zakładce Rendering po wybraniu kodera Intel (`Encoder = intel`) w uruchamianej aplikacji kanonicznej `C:\_DEV\SportCamHUD-main`.

---

## 2. Stan początkowy (INITIAL STATE)

- W gałęzi `main` repozytorium `C:\_DEV\SportCamHUD-main` kod widżetu profilu enkodera Intel znajdował się w pliku `src/gui/qt/tabs/render_tab.py`:
  - `self.cmb_intel_profile = QComboBox()` (linie 458-471)
  - `layout_intel.addRow("Profil enkodera:", self.cmb_intel_profile)`
  - Opcje: Szybki (`TU7`), Zbalansowany (`TU4`), Jakość (`TU1`)
- Mimo obecności w repozytorium `main`, użytkownik zgłosił, że po uruchomieniu aplikacji widoczne są wiersze:
  - *Koder wideo*
  - *Rozdzielczość*
  - *Rotacja*
  a pole *Profil enkodera* nie pojawia się w GUI.

---

## 3. Przyczyna źródłowa (ROOT CAUSE)

Przeprowadzona analiza środowiska runtime i ścieżek importu wykazała:

1. **Zanieczyszczenie globalnego środowiska Python (`C:\Python\Lib\site-packages\`):**
   - Wykryto plik `__editable__.telem-0.16.9.pth` oraz metadane `bikeridehud-0.16.9.dist-info` zarejestrowane przez dawny `pip install -e`.
   - Plik `.pth` kierował bezwarunkowo do `C:\_Dev\SportCamHUD-intel\src`.
2. **Rozbieżność między gałęziami:**
   - W gałęzi roboczej `c:\_Dev\SportCamHUD-intel` profil enkodera Intel **nigdy nie został zaimplementowany** (rozwój profili nastąpił w commitach na `main`).
3. **Brak izolacji w skryptach startowych:**
   - [Start_SportCamHUD.cmd](file:///C:/_DEV/SportCamHUD-main/Start_SportCamHUD.cmd) nie wymuszał lokalnej zmiennej `PYTHONPATH` na bieżący katalog roboczy, przez co importy mogły preferować ścieżki zdefiniowane w globalnym Pythonie lub zewnętrznych zmiennych środowiskowych.
   - [Start_SportCamHUD.cmd](file:///C:/_DEV/SportCamHUD-main/Start_SportCamHUD.cmd) został zapisany z prefiksem UTF-8 BOM, co powodowało błąd powłoki `cmd.exe` przy parsowaniu pierwszej linii (`'@echo' is not recognized...`).

---

## 4. Wprowadzone zmiany (CHANGED FILES)

### 1. `Start_SportCamHUD.cmd`
- Zapisano plik w czystym kodowaniu ASCII (bez BOM), eliminując błąd powłoki Windows.
- Dodano jawną definicję zmiennej `set "PYTHONPATH=%~dp0"`, gwarantując, że katalog kanoniczny `C:\_DEV\SportCamHUD-main` ma bezwzględny priorytet.

### 2. `SportCamHUD.py`
- Zabezpieczono kolejność w `sys.path`:
  - Usunięto wszelkie wcześniejsze wystąpienia korzenia i wstawiono `_root` na indeks `0`.
  - Dodano filtr oczyszczający `sys.path` z obcych drzew (m.in. `bikeridehud-intel` dodawanego automatycznie przez pliki `.pth` w `site-packages`).
- Dodano diagnostykę startupową wypisującą do logu/konsoli:
  - `RUNNING_PYTHON_EXE`
  - `RUNNING_ENTRYPOINT`
  - `RUNNING_CWD`
  - `RUNNING_RENDER_TAB_FILE`
  - `RUNNING_SOURCE_IS_CANONICAL`

---

## 5. Przeprowadzone testy (TESTED)

1. **Weryfikacja ścieżki importu z poziomu launchera:**
   - `cmd.exe /c "where python && python -c ""import src.gui.qt.tabs.render_tab as r; print(r.__file__)"""`
   - Wynik: `C:\_Dev\SportCamHUD-main\src\gui\qt\tabs\render_tab.py` (`LAUNCHER_IMPORT_PATH_PASS=YES`).
2. **Weryfikacja startupu z parametrem `--version` / `--help`:**
   - Potwierdzono poprawne uruchomienie bez błędów BOM:
     - `RUNNING_PYTHON_EXE=C:\Python\python.exe`
     - `RUNNING_ENTRYPOINT=C:\_Dev\SportCamHUD-main\SportCamHUD.py`
     - `RUNNING_CWD=C:\_Dev\SportCamHUD-main`
     - `RUNNING_RENDER_TAB_FILE=C:\_Dev\SportCamHUD-main\src\gui\qt\tabs\render_tab.py`
     - `RUNNING_SOURCE_IS_CANONICAL=YES`
3. **Inspekcja runtime widżetów Qt (`Encoder = intel`):**
   - Zweryfikowano właściwości obiektów Qt:
     - `widget_intel_options.isVisible() == True`
     - `cmb_intel_profile.isVisible() == True`
     - `cmb_intel_profile.geometry() == QRect(198, 41, 382, 22)`
     - Wybory: `['Szybki', 'Zbalansowany', 'Jakość']`
   - Widoczne wiersze w formularzu w dokładnej kolejności:
     1. `Koder wideo:`
     2. `Profil enkodera:`
     3. `Rozdzielczość:`
   - Wynik: `INTEL_PROFILE_SELECTOR_VISIBLE=YES`.

---

## 6. Izolacja backendów i brak regresji

- Zmiany ograniczyły się wyłącznie do skryptów uruchomieniowych (`Start_SportCamHUD.cmd`, `SportCamHUD.py`).
- Żaden kod backendu renderingu (Intel, AMD, NVIDIA, CPU) nie był modyfikowany.
- Plik `def_layout.json` pozostał nienaruszony.

---

## 7. Podsumowanie (SUMMARY)

| Kryterium akceptacji | Wymaganie | Stan rzeczywisty | Werdykt |
|---|---|---|---|
| Czystość gałęzi `main` | `git status --short` clean | Tracked files clean | **PASS** |
| Priorytet importu kanonicznego | `render_tab` z `SportCamHUD-main` | Potwierdzone runtime | **PASS** |
| Usunięcie kolizji `.pth` | Wykluczenie `SportCamHUD-intel` | Filtrowanie w `SportCamHUD.py` | **PASS** |
| Poprawka launchera batch | ASCII bez BOM | `Start_SportCamHUD.cmd` działa | **PASS** |
| Widoczność profilu enkodera | Widoczny pod koderem wideo | `INTEL_PROFILE_SELECTOR_VISIBLE=YES` | **PASS** |

**Status końcowy: PASS**
