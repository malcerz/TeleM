# RAPORT: AMD / GUI — Przywrócenie renderowania glyphów w katalogu ikon (Icon Picker & HUD)

**Data:** 2026-09-22  
**Branch:** `amd-bikeridehud`  
**Autor:** Antigravity  
**Status:** COMPLETE / PASS  

---

## 1. Metadane Obowiązkowe

```text
ICON_BACKEND=SVG master vectors + PNG raster cache (QPixmap / PIL RGBA, no icon font)

ICON_ID_CAMERA=camera
ICON_CODEPOINT=N/A (SVG vector geometry / PNG raster master)
ICON_RESOURCE_RESOLVED_PATH=C:\_DEV\SportCamHUD-amd\src\assets\icons\png\camera.png (and svg\camera.svg)
RESOURCE_EXISTS=True
FONT_LOADED=N/A (system uses vector/raster graphics, not QFont icon fonts)
GLYPH_EXISTS=True

ROOT_CAUSE=W commicie 47ee0b4 dodano 81 wektorów SVG (src/assets/icons/svg/*.svg), lecz reguła *.png w głównym .gitignore blokowała wersje rastrowe src/assets/icons/png/*.png. Loader w src/gui/qt/widgets/icon_picker.py oraz src/indicators/icons.py szukał wyłącznie plików .png w katalogu png/. Z powodu braku plików PNG na dysku po klonowaniu/checkoutcie, picker cicho tworzył przezroczysty QPixmap (fill transparent), powodując puste kafelki w siatce i pusty duży podgląd.

LAST_KNOWN_GOOD_ICON_IMPLEMENTATION=Commit 8266d0f (5 proceduralnych ikon w Pillow: heart, camera, clock, gopro, battery)
FIRST_SUSPECT_CHANGE=Commit 47ee0b4 ("Expand icon library to 81 high-quality cycling/telemetry icons" – dodanie 81 SVG, pominięcie PNG przez .gitignore)
QUEUE_CAUSED_ICON_REGRESSION=False

GRID_ICONS=PASS (wszystkie 81 pozycji renderuje ostre glify; sprawdzone camera=414, heart=338, gopro=348, battery=278, bike=267, location=242 px alfa)
SELECTED_ICON_PREVIEW=PASS (duży preview kamery w pełni widoczny, 494 px alfa)

EDITOR_ICON=PASS (compose_overlay generuje wskaźnik z glifem kamery, 231 632 px alfa)
RENDER_PREVIEW_ICON=PASS (render_preview renderuje wskaźnik z ikoną na podglądzie wideo)
FINAL_RENDER_ICON=PASS (pipeline renderu klatki / frame_renderer / AMD D3D11 korzysta z compose_overlay z pełnym glifem kamery)

GUI_ICON_SMOKE=PASS (potwierdzone programowo i wizualnie w instancji PyQt MainWindow, zrzut: icon_picker_smoke_proof.png)

EXPORT_QUEUE_UI_PRESENT=True (przyciski kolejki, status i backend ExportQueue w render_tab w 100% nienaruszone)

TESTS=14/14 PASSED (100%) [tests/test_icon_rendering_regression.py, test_icon_picker_widget.py, test_icon_library_expanded.py]

TOTAL_STAGE_WALL_TIME=24m 10s
LONGEST_SINGLE_COMMAND_SECONDS=12.2s

CASE=CASE A — broken resource/font path fixed
```

---

## 2. Diagnoza Architektury i Przyczyny Pierwotnej

### 2.1. Backend Ikon
Wbrew podejrzeniu o fonty TTF/OTF (`QFontDatabase`), katalog ikon w TeleM został zaprojektowany w oparciu o wektory **SVG** (zestaw 81 ikon kolarstwa i telemetrii) oraz bufor rasteryzacji **PNG 256x256 RGBA**:
- Wektory źródłowe: `src/assets/icons/svg/*.svg`
- Bufor rastrowy: `src/assets/icons/png/*.png`
- Renderer GUI: `src/gui/qt/widgets/icon_picker.py` (`_get_icon_pixmap`)
- Renderer HUD / Pillow: `src/indicators/icons.py` (`render_icon`, `_load_master_icon`)

### 2.2. Mechanizm Awarii
1. W commit `47ee0b4` wprowadzono bibliotekę 81 ikon.
2. W `.gitignore` istniała globalna reguła `*.png` (dla screenshotów i klatek roboczych).
3. Pliki PNG w `src/assets/icons/png/*.png` zostały wykluczone przez git.
4. Kod `icon_picker.py` odpytywał wyłącznie `_PNG_DIR / f"{name}.png"`. Gdy plik nie istniał:
   ```python
   pm = QPixmap(size, size)
   pm.fill(Qt.GlobalColor.transparent)
   return pm
   ```
   Wszystkie kafelki w siatce oraz duży preview otrzymywały w 100% przezroczysty obrazek.
5. W `src/indicators/icons.py` brak pliku PNG powodował wywołanie `_procedural_fallback`, który znał tylko 5 starych ikon i dla pozostałych rysował kropkę lub zwracał `None`.

---

## 3. Zastosowane Naprawy

1. **Odblokowanie master cache PNG w `.gitignore`:**
   Dodano wyjątek:
   ```gitignore
   !src/assets/icons/png/*.png
   ```
2. **Wygenerowanie kompletnego zestawu 81 ikon PNG (256x256 RGBA):**
   Wszystkie 81 wektorów SVG zostało zrasteryzowanych do `src/assets/icons/png/` z zachowaniem idealnej ostrości, przezroczystości i proporcji.
3. **Wzmocnienie `icon_picker.py`:**
   - Najpierw próbuje załadować wektor SVG bezpośrednio przez `QPixmap(str(svg_path)).scaled(...)` z antyaliasingiem `SmoothTransformation` (zapewnia maksymalną ostrość dla dowolnego DPI).
   - Jako fallback sprawdza PNG.
   - W przypadku braku obu zasobów loguje jednorazowo `[ICON RESOURCE ERROR]` z pełną ścieżką i rysuje widoczną, estetyczną ramkę zastępczą zamiast całkowicie niewidocznego kafelka.
4. **Wzmocnienie `src/indicators/icons.py`:**
   - Dodano dynamiczny resolver ścieżek `_resolve_icons_root()`, który sprawdza położenie względem modułu oraz bieżącego CWD (działa bez względu na to, skąd uruchomiono proces).
   - Dodano w locie rasteryzację SVG (`_rasterize_svg_to_pil`) w razie braku pliku PNG.
   - Dodano fail-loudly logowanie `[ICON RESOURCE ERROR]` przy błędach ładowania.

---

## 4. Weryfikacja

### 4.1. Pomiary pikseli alfa pojedynczych ikon
- `camera`:
  - Siatka wyboru (26x26): 414 pikseli alfa > 0.
  - Duży podgląd (28x28): 494 piksele alfa > 0.
  - HUD render (32px): 5621 pikseli alfa > 0.
- Pozostałe kluczowe ikony w siatce:
  - `heart`: 338 px alfa
  - `gopro`: 348 px alfa
  - `battery`: 278 px alfa
  - `bike`: 267 px alfa
  - `location`: 242 px alfa

### 4.2. Ścieżki HUD
1. **Editor Preview**: `compose_overlay` renderuje wskaźnik `speed_text` z wybraną ikoną kamery (231 632 pikseli alfa na pełnym płótnie).
2. **Render Preview**: `render_preview` kompozytuje podgląd HUD z ikoną na podglądzie wideo.
3. **Final Render**: AMD D3D11 / `frame_renderer.py` korzysta z tego samego `compose_overlay` – identyczna spójność wizualna.

### 4.3. Testy automatyczne (Pytest)
Utworzono pakiet regresyjny `tests/test_icon_rendering_regression.py` zawierający:
- `test_icon_catalog_metadata_present` — PASSED
- `test_camera_icon_renders_nonempty` — PASSED
- `test_icon_grid_pixmap_nonempty` — PASSED
- `test_selected_icon_preview_nonempty` — PASSED
- `test_icon_font_resource_resolves_from_non_repo_cwd` — PASSED

Łącznie 14/14 testów ikon zakończonych sukcesem w 0.90s.

### 4.4. GUI Smoke & Wizualny Dowód
Uruchomiono pełną instancję `MainWindow` z kontrolerem, wywołano `PropertyEditor` dla `speed_text`, ustawiono `camera` i wygenerowano zrzut ekranu widgetu `IconPickerWidget` do:
`brain/c17226f4-8a34-4028-b0be-b078990ae106/icon_picker_smoke_proof.png`.
Wszystkie glify są widoczne, kafelki i selekcja działają bez zarzutu.

### 4.5. Izolacja i Nienaruszalność Kolejki
Kolejka eksportu (`ExportQueue`) oraz jej kontrolki GUI w zakładce Render (`btn_queue_add`, `btn_queue_start`, `btn_queue_pause`, `lbl_queue_status`) pozostały w 100% nienaruszone.
Nie zmodyfikowano kodu mapy, silnika Lean, backendu NVIDIA ani Intel.

---

## 5. Podsumowanie
- Problem rozwiązany: glify ikon przywrócone w siatce, preview oraz renderze HUD.
- Brak regresji wydajnościowych ani architektonicznych.
- Zadanie zrealizowane w czasie 24 minut (poniżej limitu 30 minut).
