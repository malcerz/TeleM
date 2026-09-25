# Raport: Wyłączenie markera kierunkowego (strzałki) i wymuszenie kropki (DOT) na mapie

**Data:** 2026-09-24  
**Zadanie:** Całkowite wyłączenie z produkcyjnego GUI markera kierunkowego / strzałki mapy i pozostawienie wyłącznie zwykłego markera pozycji w formie kropki (`dot`).  
**Status:** **COMPLETE / PASS**

---

## 1. Wymagania i cele

1. **GUI PropertyEditor**:
   - Usunięcie / ukrycie opcji `directional` ze schematu `map_marker_style`.
   - Pozostawienie wyłącznie wyboru `dot` ("Kropka").
2. **Kompatybilność wsteczna layoutów**:
   - Stare layouty zawierające `map_marker_style = "directional"` lub `arrow_marker = True` muszą ładować się bez żadnych błędów.
   - W trakcie normalizacji i ładowania wartość ta jest automatycznie mapowana do `map_marker_style = "dot"` oraz `arrow_marker = False` bez modyfikacji pozostałych ustawień użytkownika.
3. **Preview i Final Render (Hard Gates)**:
   - W obu trybach (North-Up oraz Track-Up) znacznik pozycji jest renderowany wyłącznie jako kropka (`dot` – 2D puck dome sprite z miękkim cieniem i gradientowym rozbłyskiem).
   - Kod strzałki kierunkowej pozostawiony jako uśpiony (dormant) w `build_static_map_marker_tile` na wypadek przyszłych prac, bez niepotrzebnych ryzykownych refaktorów.
   - Nienaruszone pozostałe parametry mapy: smoothing, Track-Up, North-Up, pitch, zoom, GPS, trasa, backend AMD, kolejka eksportu.

---

## 2. Kluczowe wskaźniki i weryfikacja (Hard Gates)

```text
DIRECTIONAL_OPTION_VISIBLE_IN_GUI=NO
OLD_DIRECTIONAL_LAYOUT_FALLBACK=PASS
PREVIEW_DOT=PASS
FINAL_DOT=PASS
PREVIEW_DIRECTIONAL_ARROW_VISIBLE=False
FINAL_DIRECTIONAL_ARROW_VISIBLE=False
PREVIEW_DOT_VISIBLE=True
FINAL_DOT_VISIBLE=True
OTHER_MAP_BEHAVIOR_CHANGED=NO
```

---

## 3. Zmodyfikowane pliki

1. **`src/gui/qt/models.py`**:
   - W `_map_gauge_tab_fields()`: ograniczono pole wyboru `map_marker_style` wyłącznie do `choices=[("dot", "Kropka")]` z domyślną wartością `"dot"`.
   - W `normalize_indicator_decimal_defaults()`: dodano automatyczne mapowanie wartości `directional`, `arrow`, `strzałka`, `strzalka` do `"dot"` oraz `arrow_marker = False`.
2. **`src/gui/layout_manager.py`**:
   - W `normalize_layout()`: dodano explicite sanitizację wskaźników mapy przy wczytywaniu layoutu z pliku JSON – `map_marker_style` jest przekształcane na `"dot"`, a flaga `arrow_marker` na `False`.
3. **`src/indicators/moving_map.py`**:
   - W `_render_moving_map_indicator()`, `render_map_working_image()`, `render_map_unrotated_working_image()`: dodano twardą normalizację stylu markera do `"dot"` przed procesem renderowania.
   - W `build_static_map_marker_tile()`: zmieniono domyślny parametr `marker_style` z `"directional"` na `"dot"`. Kod generowania trójkątnej strzałki kierunkowej pozostał nienaruszony (dormant).
4. **`src/ffmpeg/amd_native_exporter.py`**:
   - W inicjalizacji GPU mapy (linia 3820): wymuszono styl `marker_style = "dot"`.
   - W pętli klatek (linia 5773): warunek `if marker_style == "directional":` jest nieaktywny, dzięki czemu DLL GPU nie aktualizuje dynamicznie obróconej strzałki per-frame, lecz korzysta z jednorazowo wgranego statycznego markera D3D11 (`m_mapMarkerSRV` – kropka).
5. **`tests/test_indicator_control_surface_ab.py`**:
   - Zaktualizowano test regresji A/B dla mapy, aby testować `marker_size` zamiast wyłączonej opcji `directional`.

---

## 4. Wyniki testów weryfikacyjnych

Uruchomiono dedykowane skrypty weryfikacyjne:
- `scratch/verify_map_marker_dot.py`
- `scratch/test_gui_map_marker_property.py`
- `tests/test_indicator_control_surface_ab.py`

### Test 1: GUI Schema & PropertyEditor
- Przetestowano uruchomienie rzeczywistego okna GUI Qt i kliknięcie wskaźnika `track_map`.
- Pole `Styl znacznika` w PropertyEditor zawiera wyłącznie element `['Kropka']` (`data: 'dot'`).
- Opcja `Strzałka kierunkowa` (`directional`) została w 100% usunięta z interfejsu.
- **Wynik:** `PASS`

### Test 2: Fallback starego layoutu (Backward Compatibility)
- Wczytano syntetyczny plik layoutu JSON zawierający `"map_marker_style": "directional"` oraz `"arrow_marker": true`.
- Funkcja `normalize_layout` przetworzyła layout bez żadnego wyjątku czy błędu:
  - `map_marker_style` -> `"dot"`
  - `arrow_marker` -> `False`
- Żadne inne parametry (pitch, zoom, x, y, size, kolory) nie zostały zmienione.
- **Wynik:** `PASS`

### Test 3: Preview North-Up
- Wyrenderowano klatkę preview w trybie `map_orientation="north_up"` z podanym `"map_marker_style": "dot"` oraz ze starym `"map_marker_style": "directional"`.
- W obu przypadkach marker jest rysowany jako kropka na środku mapy (`Alpha=255`).
- Różnica pikselowa pomiędzy wersjami: `max_diff = 0` (idealna tożsamość).
- **Wynik:** `PASS`

### Test 4: Preview Track-Up
- Wyrenderowano klatkę preview w trybie `map_orientation="track_up"` z kątem 45.0°.
- Różnica pikselowa pomiędzy wersjami: `max_diff = 0` (idealna tożsamość).
- Znacznik pozycji na środku mapy to kropka (`dot`), brak obracającej się strzałki kierunkowej.
- **Wynik:** `PASS`

### Test 5: Krótki render finalny AMD (D3D11 / AMF HEVC)
- Wykonano eksport 10 klatek 1080p z procesem potomnym AMD (`run_amd_render_child`).
- Eksport zakończył się sukcesem (`exitcode=0`, czas trwania 3.96 s).
- Wyodrębniono klatkę wideo za pomocą `ffmpeg` i zweryfikowano obszar markera mapy.
- Kropka jest poprawnie nałożona przez shader GPU (`m_mapMarkerSRV`), brak strzałki.
- **Wynik:** `PASS`

---

## 5. Metryki czasowe zadania

- `AUDIT_TIME`: ~10 min
- `IMPLEMENTATION_TIME`: ~12 min
- `VALIDATION_TIME`: ~15 min
- `TOTAL_STAGE_WALL_TIME`: ~37 min (poniżej budżetu 60 min)
- `LONGEST_SINGLE_COMMAND_SECONDS`: ~12 s

---

## 6. Wnioski i podsumowanie

Strzałka kierunkowa mapy została całkowicie usunięta z produkcyjnego GUI oraz runtime aplikacji. Wszelkie odwołania w starych layoutach automatycznie degradują się do kropki (`dot`). Preview oraz eksport finalny generują identyczny, spójny znacznik pozycji.
Kod i architektura innych modułów mapy, telemetrii oraz renderera GPU pozostały w 100% nienaruszone.
Zgodnie z poleceniem: brak commitów i pushy, stan gotowy do inspekcji.
