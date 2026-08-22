# TeleM — ETAP 10H: BUGFIX wyboru fontów Windows — Digital-7 / Iona-u1

## Status i decyzja

**WINDOWS FONT SELECTION: FIXED**

---

## 1. Current font contract

Właściwość `font` (per-widget oraz globalnie) obsługuje:
- **A. Pełną ścieżkę absolutną** do pliku fontu (`.ttf`, `.otf`, `.ttc`).
- **B. Ścieżkę względną** do katalogu projektu TeleM.
- **C. Nazwę zainstalowanej rodziny fontów Windows** (np. `Digital-7`, `IONA-U1`, `Comic Sans MS`, `Arial`, `Consolas`).

Wartość pusta lub `None` oznacza użycie domyślnego fontu systemowego HUD. W przypadku nieodnalezienia lub uszkodzenia pliku, system bezpiecznie przechodzi do fallbacku z jednorazową diagnostyką (brak crasha, brak log-spamu na klatkę).

---

## 2. Reproduction

Przetestowano bezpośrednio na widgetach (`speed_text`, `speed_visual`):
- `default`
- `Comic Sans`
- `Digital-7`
- `Iona-u1`
- `__FONT_DOES_NOT_EXIST__` (test fallbacku)

### Wyniki diagnostyki:
- **`default`**: `property=None` -> `resolved=""` -> `fallback=True` -> `FreeTypeFont (domyślny HUD)`.
- **`Comic Sans`**: `property="Comic Sans"` -> `resolved="C:\Windows\Fonts\comic.ttf"` -> plik istnieje (`.ttf`) -> `Pillow ImageFont.truetype SUCCESS ('Comic Sans MS', 'Regular')` -> `fallback=False`.
- **`Digital-7`**: `property="Digital-7"` -> `resolved="C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\digital-7.ttf"` -> plik istnieje (`.ttf`) -> `Pillow ImageFont.truetype SUCCESS ('Digital-7', 'Regular')` -> `fallback=False`.
- **`Iona-u1`**: `property="Iona-u1"` -> `resolved="C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\IONA-U1.otf"` -> plik istnieje (`.otf`) -> `Pillow ImageFont.truetype SUCCESS ('IONA-U1', 'Regular')` -> `fallback=False`.
- **`__FONT_DOES_NOT_EXIST__`**: `property="__FONT_DOES_NOT_EXIST__"` -> `resolved=""` -> `fallback=True (reason: font '__FONT_DOES_NOT_EXIST__' not found)` -> brak crasha.

---

## 3. Digital-7 discovery
- **Nazwa rodziny**: `Digital-7` oraz `Digital-7 Mono`
- **Pliki na dysku**:
  - `C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\digital-7.ttf` (34 360 bajtów)
  - `C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\digital-7 (mono).ttf` (34 404 bajty)
- **Lokalizacja**: Per-user Windows Fonts (`%LOCALAPPDATA%\Microsoft\Windows\Fonts`)
- **Format**: TrueType (`.ttf`)
- **Pillow**: Załadowany bezbłędnie przez `ImageFont.truetype` -> `('Digital-7', 'Regular')`.

---

## 4. Iona-u1 discovery
- **Nazwa rodziny**: `IONA-U1`
- **Plik na dysku**: `C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\IONA-U1.otf` (6 296 bajtów)
- **Lokalizacja**: Per-user Windows Fonts (`%LOCALAPPDATA%\Microsoft\Windows\Fonts`)
- **Format**: OpenType (`.otf`)
- **Pillow**: Załadowany bezbłędnie przez `ImageFont.truetype` -> `('IONA-U1', 'Regular')`.

---

## 5. Comic Sans control
- **Nazwa rodziny**: `Comic Sans MS`
- **Pliki na dysku**: `C:\Windows\Fonts\comic.ttf` (272 612 bajtów)
- **Lokalizacja**: System Fonts (`C:\Windows\Fonts`)
- **Rejestr**: `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts`
- **Format**: TrueType (`.ttf`)
- **Pillow**: Załadowany bezbłędnie -> `('Comic Sans MS', 'Regular')`.

---

## 6. Windows font locations
Na Windows fonty są instalowane w dwóch niezależnych miejscach:
1. **System Fonts (dla wszystkich użytkowników, instalacja jako Administrator)**:
   `C:\Windows\Fonts` (rejestr w `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts`)
2. **User Fonts (instalacja per-user, domyślna w nowszych wersjach Windows 10/11 bez uprawnień admina)**:
   `C:\Users\<User>\AppData\Local\Microsoft\Windows\Fonts` (rejestr w `HKCU\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts`)

---

## 7. Registry / QFontDatabase findings
- W `HKLM`: 145 wpisów fontów (w tym `Comic Sans MS (TrueType) -> comic.ttf`).
- W `HKCU`: 3 wpisy zainstalowanych fontów użytkownika:
  - `Digital-7 (TrueType)` -> `C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\digital-7.ttf`
  - `Digital-7 Mono (TrueType)` -> `C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\digital-7 (mono).ttf`
  - `IONA-U1 (TrueType)` -> `C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\IONA-U1.otf`
- `QFontDatabase.families()` zwraca 148 rodzin, w tym: `'Comic Sans MS'`, `'Digital-7'`, `'Digital-7 Mono'`, `'IONA-U1'`.

---

## 8. Exact root cause

Wcześniejsza implementacja w TeleM miała 3 kluczowe błędy:
1. **Brak obsługi nazw rodzin w per-widget resolverze**:
   - `resolve_indicator_font_path()` w `src/indicators/helpers.py` sprawdzał jedynie `(root / raw).is_file()`. Wpisanie nazwy rodziny (np. `"Digital-7"` lub `"Iona-u1"`) natychmiast uznawał za brak pliku i cicho cofał się do defaultu.
2. **Brak skanowania rejestru użytkownika (`HKCU`)**:
   - `resolve_font_path()` w `src/gui/layout_manager.py` odpytywał wyłącznie klucz `HKLM`. Fonty zainstalowane w `HKCU` były całkowicie ignorowane.
3. **Błędne łączenie ścieżek bezwzględnych z rejestru**:
   - Wpisy w `HKCU` zawierają pełną ścieżkę bezwzględną `C:\Users\...\font.ttf`. Kod w `layout_manager.py` łączył to naiwnie: `fonts_dir / value`, co dawało `C:\Windows\Fonts\C:\Users\...` i kończyło się błędem `exists() == False`.

---

## 9. Minimal fix

1. **`src/indicators/helpers.py`**:
   - Dodano funkcję `_build_windows_font_map()`, która skanuje rejestry `HKCU` i `HKLM` oraz foldery `%LOCALAPPDATA%\Microsoft\Windows\Fonts` i `C:\Windows\Fonts`.
   - Zaimplementowano uniwersalną funkcję `resolve_font_file()`, która:
     - Rozpoznaje ścieżki bezwzględne oraz względne w projekcie (`.ttf`, `.otf`, `.ttc`).
     - Rozpoznaje nazwy rodzin, nazwy rejestrowe oraz nazwy plików (case-insensitive, z usuwaniem sufixów stylu typu `(TrueType)`).
     - Weryfikuje poprawność przez `ImageFont.truetype(path, size=8)`.
     - Rejestruje czytelny komunikat diagnostyczny przy pierwszym rozwiązaniu/fallbacku.
   - `resolve_indicator_font_path()` korzysta z `resolve_font_file()` oraz buforuje wynik w `_FONT_PATH_CACHE`.
   - Dodano obsługę formatu `.ttc` obok `.ttf` i `.otf`.
2. **`src/gui/layout_manager.py`**:
   - Zunifikowano `resolve_font_path(family_name)` tak, aby delegował do `resolve_indicator_font_path()`.
3. **`src/gui/qt/widgets/property_editor.py`**:
   - Dodano `QCompleter` podpięty pod `QFontDatabase.families()`, ułatwiający autouzupełnianie zainstalowanych w systemie rodzin fontów bezpośrednio w polu `font`.
   - Rozszerzono filtr wyboru pliku do `Fonty (*.ttf *.otf *.ttc)`.

---

## 10. Family → file resolution

| Wpis w GUI / layout | Ścieżka rozwiązania | Format | Typ rejestru / katalogu |
|---|---|:---:|---|
| `Digital-7` | `C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\digital-7.ttf` | `.ttf` | `HKCU` / User Fonts |
| `digital-7` | `C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\digital-7.ttf` | `.ttf` | `HKCU` / User Fonts |
| `Digital-7 Mono` | `C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\digital-7 (mono).ttf` | `.ttf` | `HKCU` / User Fonts |
| `Iona-u1` | `C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\IONA-U1.otf` | `.otf` | `HKCU` / User Fonts |
| `IONA-U1` | `C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\IONA-U1.otf` | `.otf` | `HKCU` / User Fonts |
| `Comic Sans` | `C:\Windows\Fonts\comic.ttf` | `.ttf` | `HKLM` / System Fonts |
| `Comic Sans MS` | `C:\Windows\Fonts\comic.ttf` | `.ttf` | `HKLM` / System Fonts |
| `Arial` | `C:\Windows\Fonts\arial.ttf` | `.ttf` | `HKLM` / System Fonts |

---

## 11. Pillow load results

Wszystkie znalezione fonty zostały załadowane bezpośrednio przez bibliotekę Pillow (`ImageFont.truetype`):
- `C:\Windows\Fonts\comic.ttf`: **SUCCESS** (`Comic Sans MS`, `Regular`)
- `C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\digital-7.ttf`: **SUCCESS** (`Digital-7`, `Regular`)
- `C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\digital-7 (mono).ttf`: **SUCCESS** (`Digital-7 Mono`, `Mono`)
- `C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\IONA-U1.otf`: **SUCCESS** (`IONA-U1`, `Regular`)

---

## 12. Fallback diagnostics

Przy rozwiązywaniu fontu emitowany jest pojedynczy wpis diagnostyczny (tylko przy cache miss):
```text
[FONT RESOLVER] requested='Comic Sans' -> resolved='C:\Windows\Fonts\comic.ttf'
[FONT RESOLVER] requested='Digital-7' -> resolved='C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\digital-7.ttf'
[FONT RESOLVER] requested='Iona-u1' -> resolved='C:\Users\Malcerz\AppData\Local\Microsoft\Windows\Fonts\IONA-U1.otf'
[FONT RESOLVER] requested='__FONT_DOES_NOT_EXIST__' -> fallback='' reason='font '__FONT_DOES_NOT_EXIST__' not found'
```
Brak logowania per-frame — kolejne zapytania o ten sam font trafiają w `_FONT_PATH_CACHE` oraz `FONT_CACHE`.

---

## 13. Cache behavior

- `_FONT_PATH_CACHE`: buforuje mapowanie `(font_property_value, default|root) -> resolved_path`.
- `FONT_CACHE`: buforuje instancje fontów Pillow pod kluczem `(resolved_path, size_px)`.
- Zmiana fontu z `Arial` na `Digital-7`, następnie `Iona-u1` i powrót do `Arial`:
  - `diff(Arial_1, Arial_2) = 0` (100% deterministyczny powrót do pierwotnego stanu).
  - Brak zanieczyszczenia cache ani kolizji kluczy.

---

## 14. GUI behavior

- W `PropertyEditor` pole `font` posiada `QCompleter` zintegrowany z `QFontDatabase.families()`.
- Wpisanie `"Dig"` podpowiada `Digital-7` i `Digital-7 Mono`.
- Wpisanie `"Ion"` podpowiada `IONA-U1`.
- Przycisk `"Wybierz plik…"` otwiera dialog z filtrem `Fonty (*.ttf *.otf *.ttc)` i wstawia bezwzględną ścieżkę do pliku.

---

## 15. Visual raster comparison

Wyrenderowano widget `speed_text` oraz `speed_visual` z wartością `SPEED 28.6 km/h` pod różnymi fontami:
- Pliki wygenerowane w `Raporty/`:
  - `WIDGET_TEST_default.png`
  - `WIDGET_TEST_Comic_Sans.png`
  - `WIDGET_TEST_Digital-7.png`
  - `WIDGET_TEST_Iona-u1.png`
  - `GAUGE_TEST_default.png`
  - `GAUGE_TEST_Digital-7.png`
  - `GAUGE_TEST_Iona-u1.png`

### Wyniki porównania rastra:
- `Digital-7 != default`: **Max pixel diff = 255 (Distinct)**
- `Iona-u1 != default`: **Max pixel diff = 255 (Distinct)**
- `Comic Sans != default`: **Max pixel diff = 255 (Distinct)**
- `Digital-7 != Iona-u1`: **Max pixel diff = 255 (Distinct)**

---

## 16. Targeted tests

Uruchomiono zestaw 54 targetowanych testów automatycznych:
- `tests/test_font_selection.py` (9 testów: system font family resolution, user fonts, invalid paths, fallback, cache, JSON roundtrip, raster comparison)
- `tests/test_gauge_rendering.py` (12 testów)
- `tests/test_slope_rendering.py` (16 testów)
- `tests/test_compass_rendering.py` (9 testów)
- `tests/test_chart_rendering.py` (8 testów)

**Wynik: 54 passed (100%)**

---

## 17. Changed files

- [src/indicators/helpers.py](file:///c:/_DEV/TeleM/src/indicators/helpers.py) — rozszerzenie resolvera fontów o rejestr Windows (`HKLM` + `HKCU`), foldery per-user, dopasowywanie rodzin i diagnostykę.
- [src/gui/layout_manager.py](file:///c:/_DEV/TeleM/src/gui/layout_manager.py) — zunifikowanie `resolve_font_path` z `src/indicators/helpers.py`.
- [src/gui/qt/widgets/property_editor.py](file:///c:/_DEV/TeleM/src/gui/qt/widgets/property_editor.py) — dodanie autouzupełniania rodzin fontów przez `QCompleter` oraz obsługa `.ttc`.
- [tests/test_font_selection.py](file:///c:/_DEV/TeleM/tests/test_font_selection.py) — testy regresyjne i walidacyjne dla fontów systemowych, fallbacku i determinizmu.
