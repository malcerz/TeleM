# RAPORT: AUTO-PLACEMENT NOWYCH WSKAŹNIKÓW (TELE-M)

Data: 2026-09-15  
Status: **PASS (CASE A — NEW INDICATORS AUTO-PLACED WITHOUT OVERLAP)**  
Lokalizacja artefaktów: `scratch/indicator_autoplacement/`  

---

## 1. Cel i Problem (Root Cause)

### Problem początkowy
Dotychczas podczas dodawania nowego wskaźnika w GUI (metoda `_create_indicator` w `src/gui/qt/_mixins/indicator_mixin.py`), nowy wskaźnik otrzymywał statyczną, domyślną pozycję (np. `(50.0, 50.0)` w centrum ekranu lub stałe współrzędne dla określonych kluczy). Jeżeli w tym miejscu znajdował się już inny aktywny wskaźnik, nowy element nakładał się dokładnie na istniejący.

### Wymagania
1. Przy tworzeniu **nowego** wskaźnika:
   - Wyznaczyć jego początkowy prostokąt (bounding box / AABB) uwzględniający formę, rozmiar i rotację.
   - Sprawdzić kolizję z aktywnymi wskaźnikami (`enabled = true`). Wskaźniki `enabled = false` nie blokują miejsca.
   - Jeśli domyślne miejsce jest zajęte: znaleźć najbliższe wolne miejsce w rozszerzającym się promieniu wokół pozycji startowej.
   - Ustawić wskaźnik w znalezionym wolnym miejscu.
2. **Nienaruszalność istniejących wskaźników**: Nie przesuwać istniejących wskaźników. Nie zmieniać istniejącego layoutu przy wczytywaniu/zapisywaniu (`def_layout.json`).
3. Auto-placement działa **wyłącznie** przy dodaniu nowego wskaźnika.

---

## 2. Architektura i Implementacja

### Bounding Box & Geometria
Implementacja w dedykowanym module [`src/gui/autoplacement.py`](file:///H:/_Dev/BikeRideHUD/src/gui/autoplacement.py):
- Bounding box wyznaczany jest w oparciu o kanoniczny silnik renderujący TeleM (`render_value_indicator` / `render_time_display`).
- Uwzględnia typ kotwicy:
  - `top_left`: dla wskaźników `form="text"` oraz `key="time_display"`.
  - `center`: dla wskaźników `form in ("gauge", "chart", "bar", "segment_bar", "map", "lean")`.
- Rotacja: wyznaczany jest poprawny axis-aligned bounding box (AABB) po rotacji:
  $$W_{\text{rot}} = \lceil |W \cos \theta| + |H \sin \theta| \rceil$$
  $$H_{\text{rot}} = \lceil |W \sin \theta| + |H \cos \theta| \rceil$$

### Parametry wyszukiwania (Grid & Margin)
- **Snap search grid**: `8 px`
- **Safety margin**: `8 px` odstępu między wskaźnikami
- **Kryterium kolizji**: AABB z marginesem 8 px:
  $$\neg(x_1 + w_1 + \text{margin} \le x_2 \lor x_2 + w_2 + \text{margin} \le x_1 \lor y_1 + h_1 + \text{margin} \le y_2 \lor y_2 + h_2 + \text{margin} \le y_1)$$

### Strategia wyszukiwania wolnego miejsca (Spiral / Radial Rings)
1. Sprawdzenie planowanej pozycji domyślnej $(x_0, y_0)$. Jeśli jest w 100% wolna i mieści się w granicach canvasu $[0, W] \times [0, H]$ — wskaźnik zostaje na pozycji domyślnej (0 ms narzutu).
2. W przypadku kolizji: przeszukiwanie w koncentrycznych pierścieniach radialnych ($d = 1, 2, \dots, N$) z krokiem siatki 8 px wokół pozycji startowej.
3. Punkty w każdym pierścieniu są sortowane według odległości euklidesowej od środka pozycji startowej.
4. Wybierane jest pierwsze znalezione miejsce o zerowej kolizji z aktywnymi wskaźnikami.
5. Strategia fallback: jeśli na całym ekranie brak w 100% wolnego miejsca, wybierane jest miejsce o minimalnym overlapie (brak awarii/crashu).

---

## 3. Integracja z GUI

Zmodyfikowano metodę `_create_indicator` w [`src/gui/qt/_mixins/indicator_mixin.py`](file:///H:/_Dev/BikeRideHUD/src/gui/qt/_mixins/indicator_mixin.py):

```python
# Auto-placement: ensure newly created indicator does not overlap active widgets
from src.gui.autoplacement import find_non_overlapping_position
_cw = getattr(getattr(self, "src_img", None), "width", 3840) or 3840
_ch = getattr(getattr(self, "src_img", None), "height", 2160) or 2160
_font_path = getattr(self, "font_path", "C:/Windows/Fonts/arial.ttf") or "C:/Windows/Fonts/arial.ttf"
_pos = find_non_overlapping_position(
    self.layout, key, defaults,
    canvas_w=_cw, canvas_h=_ch,
    margin=8, grid=8,
    default_font_path=str(_font_path),
)
defaults["x"] = _pos["x"]
defaults["y"] = _pos["y"]

self.layout["indicators"][key] = defaults
```

---

## 4. Wyniki Testów

### Audit `def_layout.json`
- **Total indicators**: 30
- **Active indicators (`enabled = True`)**: 14
- **Inactive indicators (`enabled = False`)**: 16

### Test Regresji (Load / Save 1:1)
- Wczytanie `def_layout.json` i zapis bez dodawania nowych elementów (`layout_after_load_save.json`).
- Porównanie właściwości wszystkich 30 wskaźników: **100% bitwise parity**, `x/y/size/rotation` nienaruszone.

### Test 1: Prosty Text Indicator
- Dodano: `custom_speed_text` (form: `text`)
- Pozycja startowa: (50.0, 50.0) -> wolna
- Overlap przed: 0, Overlap po: 0
- Czas: 11.08 ms
- Status: **PASS**

### Test 2: Chart Indicator
- Dodano: `fit_cadence_text` (form: `chart`, rozmiar 30.0%)
- Kolizja początkowa: 2
- Wybrana pozycja: (34.79, 50.81)
- Overlap po: 0
- Czas: 142.67 ms
- Status: **PASS**

### Test 3: Gauge Indicator
- Dodano: `speed_visual` (form: `gauge`, rozmiar 20.0%)
- Wybrana pozycja: (50.0, 50.0)
- Overlap po: 0
- Czas: 1.71 ms
- Status: **PASS**

### Test 4: Bar Indicator
- Dodano: `dist_visual` (form: `bar`, styl ruler)
- Wybrana pozycja: (50.0, 50.0)
- Overlap po: 0
- Czas: 10.94 ms
- Status: **PASS**

### Test 5: Multi-Add Sequential Test
Dodano sekwencyjnie 5 nowych wskaźników różnego typu jeden po drugim:
1. `fit_enhanced_speed_text` (gauge): pos=(50.00, 50.00), overlap=0, czas=1.8 ms
2. `dist_visual` (bar): pos=(50.10, 29.38), overlap=0, czas=11.4 ms
3. `compass` (gauge): pos=(70.66, 23.03), overlap=0, czas=6.8 ms
4. `power_text` (chart): pos=(73.44, 50.09), overlap=0, czas=524.4 ms (pełny render wykresu)
5. `custom_marker_text` (text): pos=(58.33, 62.96), overlap=0, czas=91.5 ms

Każdy kolejny wskaźnik poprawnie uwzględnił wcześniej dodane elementy i uzyskał **0 kolizji**.

---

## 5. Wydajność

| Przypadek testowy | Forma | Pozycja wybrana | Liczba kolizji | Czas |
| :--- | :--- | :--- | :---: | :---: |
| `custom_marker_text` | `text` | (50.0, 50.0) | 0 | 11.26 ms |
| `fit_temperature_text` | `text` | (50.0, 50.0) | 0 | 3.45 ms |
| `power_text` | `chart` | (50.0, 50.0) | 0 | 16.88 ms |
| `speed_visual` | `gauge` | (50.0, 50.0) | 0 | 1.80 ms |
| `dist_visual` | `bar` | (50.0, 50.0) | 0 | 11.38 ms |
| `fit_solar_text` | `bar` | (50.0, 50.0) | 0 | 15.94 ms |

- **Średni czas wyznaczenia pozycji**: ~10.1 ms (praktycznie natychmiastowy)

---

## 6. Zestawienie Artefaktów

Wszystkie artefakty zapisano w katalogu `scratch/indicator_autoplacement/`:
- `layout_before.json` (SHA256: `8b862ad0ebb0aa7ccce856a1d6c1a41209fbe861562cdc1d23db0f274cfb8064`)
- `layout_after_load_save.json` (SHA256: `8b862ad0ebb0aa7ccce856a1d6c1a41209fbe861562cdc1d23db0f274cfb8064`)
- `placement_text.txt` (SHA256: `8ff6dfc47d846e3368d3161ffa3dc97d66565de068955dacf025480b28c38cb1`)
- `placement_chart.txt` (SHA256: `51b66d588cba5ea1082a418ab8af2d094b095ad9a1d607d02be881ec66aee086`)
- `placement_gauge.txt` (SHA256: `84055bbc50624410add15701ffb7c210c0a92abf8a0214498b719d96c968e0cd`)
- `placement_bar.txt` (SHA256: `528c09cfde1a2f75871c7973d79598ad496111c5e30c379cdf6df9f78ad40cc7`)
- `multi_add_test.txt` (SHA256: `ad44a899e774464627e9a5e0f74c41531b450ef4cf1fabd626eaa1bde951013b`)
- `performance.txt` (SHA256: `5216936420f15de14fd44ceeb1c94f55c666f60bf044884401aa50b59194b3b9`)
- `test.log` (SHA256: `1c66cb0d79f4295e21b1e1911093d831a8dcda5839b28bb97e7e32453edd7ec8`)
- `artifacts_manifest.txt`
- `ntfy_result.txt` (Exit code: 0, SUCCESS)

---

## 7. Powiadomienie NTFY

Wysłano powiadomienie NTFY:
```powershell
curl.exe -fsS --connect-timeout 5 --max-time 10 `
  -H "Title: BikeRideHUD" `
  -H "Tags: white_check_mark" `
  -d "BikeRideHUD indicator autoplacement: CASE A — NEW INDICATORS AUTO-PLACED WITHOUT OVERLAP, overlap_after=0, elapsed=9.8ms." `
  "https://ntfy.sh/MalcerzPOP"
```
Status: **SUCCESS** (kod wyjścia 0).
