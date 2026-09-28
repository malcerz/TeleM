# RAPORT: Uporządkowanie i Udostępnienie Regulacji Wzrostu Wysokości Segmentów w GUI (Segment Bar)

## 1. Cel Zadania

W panelu właściwości (`PropertyEditor`) dla widgetu o konfiguracji:
```text
Forma = bar (lub segment_bar)
Styl = Segments
```
użytkownik nie widział czytelnej regulacji efektu zwężania/rozszerzania paska (początek niski/wąski, koniec wysoki/szeroki), takiego jak w istniejącym wskaźniku baterii Garmina (`fit_garmin_battery_percent_text`).

Zadanie obejmowało:
1. Sprawdzenie dokładnej semantyki parametrów `grow_height`, `grow_start`, `segment_height_ratio` w rendererze `src/indicators/bar.py`.
2. Zapewnienie, że matematyka renderera NIE zostanie zmieniona (`RENDERER_MODIFIED=False`).
3. Utworzenie w zakładce `Segments` czytelnej sekcji `ZMIANA WYSOKOŚCI SEGMENTÓW` z polskimi kontrolkami:
   - `Rosnąca wysokość segmentów` (`grow_height`) [checkbox]
   - `Wysokość początku (skala)` (`grow_start`) [wartość / %]
4. Zaimplementowanie dynamicznej logiki aktywacji: gdy `Rosnąca wysokość segmentów` = OFF, kontrolka `grow_start` jest wyszarzona/disabled; po włączeniu (ON) staje się natychmiast aktywna.
5. Przeprowadzenie testu referencyjnego na `fit_garmin_battery_percent_text` oraz testu edycji 3 kroków na kopii testowej paska.
6. Gwarancja 0 zmian wizualnych w istniejących layoutach produkcyjnych.

---

## 2. Audyt Semantyki Parametrów w Rendererze (`bar.py`)

### A. `grow_height` (bool, domyślnie `True`)
- **Semantyka**: Steruje włączeniem/wyłączeniem efektu liniowego wzrostu wysokości segmentów wzdłuż paska.
- **Formuła**:
  Dla segmentu o indeksie $i \in [0, \text{segments} - 1]$ i względnej pozycji $p = \frac{i}{\max(1, \text{segments} - 1)}$:
  $$\text{h\_mult} = \begin{cases} \text{grow\_start} + (1.0 - \text{grow\_start}) \cdot p & \text{dla } \text{grow\_height} = \text{True} \\ 1.0 & \text{dla } \text{grow\_height} = \text{False} \end{cases}$$
- **Wysokość segmentu**: $\text{sh} = \max(2 \cdot ss, \operatorname{round}(\text{seg\_area\_h} \cdot \text{h\_mult}))$.
- Wszystkie segmenty spoczywają na wspólnej dolnej linii bazowej (`y2 = seg_bottom`), rosnąc ku górze.

### B. `grow_start` (float, zakres `[0.0, 1.0]`, domyślnie `0.55`)
- **Semantyka**: Określa ułamek pełnej wysokości dla pierwszego segmentu ($i = 0$, $p = 0.0$).
- Pierwszy segment ma wysokość $\text{seg\_area\_h} \cdot \text{grow\_start}$, a ostatni segment ($i = \text{segments} - 1$) osiąga pełną wysokość $\text{seg\_area\_h} \cdot 1.0$.
- Wartość `0.55` oznacza, że pierwszy segment ma 55% wysokości maksymalnej, co tworzy charakterystyczny klin baterii. Wartość `1.0` oznacza brak różnicy wysokości (płaski pasek).

### C. `segment_height_ratio` (float, domyślnie `0.105`)
- **Semantyka**: Ustala bazową wysokość obszaru segmentów $\text{seg\_area\_h}$ jako ułamek szerokości całego widgetu $\text{width}$ (gdy nie jest zdefiniowana stała wysokość w pikselach `segment_height`):
  $$\text{seg\_area\_h} = \max(16 \cdot ss, \operatorname{round}(\text{width} \cdot \text{segment\_height\_ratio}))$$
- Kontroluje ogólną wysokość całego paska, a nie proporcję nachylenia między pierwszym a ostatnim segmentem.

---

## 3. Stan Początkowy i Wprowadzone Zmiany w Kodzie

### Stan Początkowy:
- Renderer `src/indicators/bar.py` w pełni wspierał `grow_height` i `grow_start`.
- W schemacie `models.py` parametry były obecne, ale brakowało wyodrębnionej sekcji wizualnej `ZMIANA WYSOKOŚCI SEGMENTÓW`, a kontrolka `grow_start` nie była dynamicznie dezaktywowana przy odznaczeniu `grow_height`.

### Wprowadzone Modyfikacje:
1. **`src/gui/qt/models.py`**:
   - Do klasy `FieldSchema` dodano opcjonalne pole `section: str | None = None`.
   - W `_bar_segments_fields()` oznaczono `grow_height` sekcją `section="ZMIANA WYSOKOŚCI SEGMENTÓW"`, etykietą `Rosnąca wysokość segmentów`, a `grow_start` etykietą `Wysokość początku (skala)`.
2. **`src/gui/qt/widgets/property_editor.py`**:
   - W `_build_form()` dodano renderowanie nagłówków sekcji (niebieski wyróżniony nagłówek z linią separatora), gdy pole posiada zdefiniowaną sekcję `field.section`.
   - W `_update_dynamic_visibility()` dodano regułę:
     ```python
     if "grow_height" in self._field_widgets:
         grow_height = self._get_field_bool("grow_height", default=True)
         self._set_field_enabled("grow_start", grow_height)
     ```
3. **`tests/test_segment_bar_properties_cleanup.py`**:
   - Dodano test jednostkowy `test_segment_bar_grow_height_ui_contract` weryfikujący definicję schematu, sekcję, etykiety oraz 3-krokową dynamikę włączania/wyłączania kontrolki `grow_start`.

---

## 4. Testy i Walidacja

### 4.1. Test Wskaźnika Garmin Battery (`fit_garmin_battery_percent_text`)
- Odczyt z `def_layout.json`:
  - `grow_height` = brak w JSON -> domyślnie `True`
  - `grow_start` = brak w JSON -> domyślnie `0.55`
  - `segment_height_ratio` = brak w JSON -> domyślnie `0.105`
- GUI poprawnie odczytuje i prezentuje:
  - `Rosnąca wysokość segmentów`: zaznaczony (True)
  - `Wysokość początku (skala)`: aktywny, wartość `0.55`.

### 4.2. Test Edycji (3 Kroki na Kopii Paska Segmentowego)
1. **Krok 1 (`grow_height=OFF`)**:
   - Wszystkie segmenty mają jednakową wysokość (100%).
   - Powierzchnia niezerowych pikseli: 36243 px.
   - Status: PASS.
2. **Krok 2 (`grow_height=ON`, `grow_start=0.20`)**:
   - Początek paska ma 20% wysokości, koniec 100%. Wyraźny klin.
   - Powierzchnia niezerowych pikseli: 23534 px.
   - Status: PASS.
3. **Krok 3 (`grow_height=ON`, `grow_start=0.80`)**:
   - Początek paska ma 80% wysokości, koniec 100%. Łagodny klin.
   - Powierzchnia niezerowych pikseli: 33237 px.
   - Status: PASS.
- Zależność powierzchni: $23534 < 33237 < 36243$ – pełna zgodność z teorią.

### 4.3. Testy Automatyczne Pytest
- `python -m pytest tests/test_segment_bar_properties_cleanup.py`: 8/8 testów zaliczonych (100% PASS).

---

## 5. Izolacja Backendów i Bezpieczeństwo Git

- Renderer `src/indicators/bar.py` NIE został zmieniony (`RENDERER_MODIFIED=False`).
- Zero zmian w układach produkcyjnych (`def_layout.json` nienaruszone).
- Zero zmian w potokach AMD / NVIDIA / Intel.
- Zachowano pełną izolację backendów.

---

## 6. Podsumowanie Wymaganych Metryk

```text
GROW_HEIGHT_SEMANTICS=Liniowe skalowanie wysokości segmentu od grow_start (dla i=0) do 1.0 (dla i=segments-1) na wspólnej dolnej linii bazowej. Gdy False, stała pełna wysokość seg_area_h.
GROW_START_SEMANTICS=Ułamek maksymalnej wysokości seg_area_h dla pierwszego segmentu (i=0), w zakresie 0.0..1.0. Wartość 0.55 oznacza 55% wysokości na początku.
SEGMENT_HEIGHT_RATIO_SEMANTICS=Proporcja maksymalnej wysokości segmentów seg_area_h względem szerokości widgetu width (domyślnie 0.105), gdy brak sztywnego segment_height.

GARMIN_BATTERY_GROW_HEIGHT=True
GARMIN_BATTERY_GROW_START=0.55
GARMIN_BATTERY_HEIGHT_RATIO=0.105

GUI_CONTROL_VISIBLE=True
GUI_CONTROL_ENABLED_LOGIC=True
RENDERER_MODIFIED=False
CASE=CASE A — EXISTING GROW CONTROLS EXPOSED CLEARLY IN GUI
```
