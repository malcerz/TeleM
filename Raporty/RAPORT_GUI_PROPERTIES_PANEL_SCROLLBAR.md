# RAPORT: PIONOWY SCROLLBAR DLA PANELU WŁAŚCIWOŚCI WSKAŹNIKA (GUI)

## METADATA
- **Data**: 2026-09-16
- **Workspace**: `C:\_DEV\BikeRideHUD`
- **Gałąź**: `amd-bikeridehud`
- **Status końcowy**: `CASE A — PROPERTIES PANEL SCROLLBAR FIXED`

---

## 1. PODSUMOWANIE METRYK (WYMAGANE POLA)

```text
PROPERTIES_PANEL_WIDGET=src.gui.qt.widgets.property_editor.PropertyEditor
SCROLL_CONTAINER=PySide6.QtWidgets.QScrollArea (wrap wokół self.form_container wewnątrz PropertyEditor)
VERTICAL_SCROLLBAR=Qt.ScrollBarAsNeeded (automatyczny, włącza się wyłącznie przy przepełnieniu)
HORIZONTAL_SCROLLBAR=Qt.ScrollBarAlwaysOff (zablokowany, brak poziomego przesuwania)
1080P_TEST=PASS (wysokość panelu ~520px przy 1080p, naturalna wysokość formularza 1312px, scrollbar 0..878, brak ściskania kontrolek)
SMALL_WINDOW_TEST=PASS (wysokość 350px, scrollbar 0..1048, pełny scroll i dostępność wszystkich kontrolek)
CONTROL_COMPRESSION_FIXED=PASS (wiersze w zakładkach Text, Segments, Colors, Marker itd. zachowują naturalne wysokości ~24-28px, spacing=8px)
MODIFIED_FILES=src/gui/qt/widgets/property_editor.py, tests/test_property_editor_scroll.py
CASE=CASE A — PROPERTIES PANEL SCROLLBAR FIXED
```

---

## 2. ARCHITEKTURA I IMPLEMENTACJA

1. **Identyfikacja widgetu**:
   - Odpowiedzialny widget: [PropertyEditor](file:///C:/_DEV/BikeRideHUD/src/gui/qt/widgets/property_editor.py#L24) w `src/gui/qt/widgets/property_editor.py`, osadzony w prawej części [ProjectTab](file:///C:/_DEV/BikeRideHUD/src/gui/qt/tabs/project_tab.py#L75) (`src/gui/qt/tabs/project_tab.py`).
2. **Dodanie `QScrollArea`**:
   - Utworzono `self.scroll_area = QScrollArea()`.
   - Skonfigurowano:
     - `self.scroll_area.setWidgetResizable(True)`
     - `self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)`
     - `self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)`
     - `self.scroll_area.setFrameShape(QScrollArea.NoFrame)`
   - `self.scroll_area.setWidget(self.form_container)` obejmuje wyłącznie formularz właściwości.
   - Podgląd wideo (`VideoPreview`), oś czasu (`SeekBar`), przyciski strumieni (`DataStreamBar`) i okno główne pozostały w 100% nienaruszone.
3. **Eliminacja kompresji kontrolek**:
   - W `_build_form` usunięto wymuszony stretch `outer.addWidget(tabs, 1)` na rzecz naturalnego rozmiaru `outer.addWidget(tabs)` z elastycznym `QSpacerItem` na samym dole formularza.
   - Wszystkie kontrolki w `QTabWidget` (w tym zakładki `Text`, `Segments`, `Colors`, `Marker`) oraz dolny wiersz `Wygładzanie` zachowują swoje naturalne wysokości i odstępy.

---

## 3. WYNIKI TESTÓW I DOWODY DZIAŁANIA

- **Test 1080p (wysokość 520px)**:
  - Naturalna wysokość formularza: **1312 px**
  - Zakres suwaka: `0 .. 878`
  - Zjazd na sam dół: `pos = 878`, odczyt kontrolki `Wygładzanie` = `3 okno` (pełna dostępność).
  - Powrót na samą górę: `pos = 0`.
- **Test małego okna (wysokość 350px)**:
  - Zakres suwaka: `0 .. 1048`.
  - Naturalna wysokość formularza nienaruszona.
- **Test dopasowanego okna (wysokość 800px przy krótkim formularzu Text 707px)**:
  - Zakres suwaka: `0 .. 0` (`isVisible() == False` — automatyczne ukrywanie).
- **Testy jednostkowe pytest**:
  - `tests/test_property_editor_scroll.py`: 4/4 **PASSED** (0.59s).
- **Zrzut ekranu**:
  - `scratch/properties_panel_scroll/after_1080p.png`

---

## 4. ARTEFAKTY W `scratch/properties_panel_scroll/`

- `before_structure.md` — analiza hierarchii przed modyfikacją
- `after_structure.md` — hierarchia i konfiguracja po dodaniu `QScrollArea`
- `gui_test.txt` — pełny log testów geometrii, przewijania i integracji
- `git_diff_before.patch` — stan diffa przed zadaniem
- `git_diff_after.patch` — stan diffa po zadaniu
- `after_1080p.png` — zrzut ekranu panelu przy symulacji 1080p
- `test_properties_scroll.py` — skrypt testowy
- `artifacts_manifest.txt` — sumy kontrolne SHA256
- `ntfy_result.txt` — potwierdzenie wysłania notyfikacji bramki
