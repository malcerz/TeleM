# Raport: AMD ETAP 3Q — LEAN VISIBLE GLYPH GAP FIX

## 1. Cel i zakres etapu

- **Zadanie**: Wyeliminować nachodzenie dynamicznego napisu stopni (np. `-9°`) na grafikę rowerka / obszar pivotu w finalnym renderze AMD Native D3D11.
- **Kryteria pomiarowe**:
  - Pomiar bezpośrednich pikseli widocznych (**Visible Pixels**):
    - `bike_visible_bottom_y` — najniższy nieprzezroczysty piksel grafiki rowerka / obszaru pivotu.
    - `text_visible_top_y` — najwyższy nieprzezroczysty piksel faktycznie wyrenderowanego glifu wartości (np. `-9°`).
    - `visible_gap_y = text_visible_top_y - bike_visible_bottom_y`.
  - Tolerancja: `delta_gap <= 2 px` oraz `visible_gap_y > 0` (brak overlapu).
- **Zasady nadrzędne**:
  - Brak zmian rozmiaru rowerka, pivotu, kąta obrotu ani ogólnego położenia widgetu na ekranie.
  - MAP, horizontal BAR, vertical BAR, NVIDIA, Intel, optymalizacje 3L — nienaruszone.

---

## 2. Root Cause Analysis — Dlaczego ETAP 3P dał fałszywy PASS?

W ETAPIE 3P wskaźnik `lean_indicator` w `def_layout.json` posiadał pusty ciąg `label: ""` (brak napisu tytułowego "LEAN", jedynie dynamiczny napis wartości `-9°` na dole).

1. **Fałszywy fallback w wyznaczaniu tytułu**:
   - W `src/indicators/lean.py` (`get_lean_gpu_transform_info` w wersji 3P) linia wyznaczająca tytuł miała postać:
     `raw_title = str(cfg.get("title_text", label or cfg.get("label", "") or "Lean")).strip()`
   - Ponieważ `label` oraz `cfg["label"]` były pustymi ciągami `""`, ewaluacja `"" or "" or "Lean"` zwracała `"Lean"`.
   - W rezultacie `get_lean_gpu_transform_info` zakładało, że widget posiada nagłówek "LEAN" (`title_h = 51 px`), co zwiększało wysokość kafelka `raster_h` z 374 px do 430 px.
2. **Rozbieżność między warstwą GPU a CPU ABOVE**:
   - Warstwa **CPU ABOVE** (`_render_lean_indicator`) używała właściwej formuły: `raw_title = str(cfg.get("title_text", label or "")).strip()`, dając `raw_title = ""` i `raster_h = 374 px`.
   - CPU ABOVE umieszczało kafelek wyżej na ekranie (`screen_y = ry - 374 // 2 = 171 px`), a napis `-9°` był rysowany od pozycji `screen_y + 319 = 490 px`.
   - Tymczasem transformacja GPU liczyła pozycję pivotu w oparciu o kafelek 430 px (`screen_y = ry - 430 // 2 = 143 px`), co przesuwało pivot GPU rowerka w dół na `screen_pivot_y = 514 px`.
   - **Skutek**: Dół rowerka (GPU) lądował na `Y = 514 px`, podczas gdy napis (CPU) zaczynał się na `Y = 490 px` — napis zachodził na rowerek o 24 piksele!
3. **Błąd w metryce w 3P**:
   - W 3P testowano izolowane wywołania funkcji `_render_lean_indicator` podając sztuczny parametr `label="Lean"`, co maskowało błąd na poziomie konfiguracji produkcyjnej `def_layout.json`.

---

## 3. Zastosowany Minimal Fix

1. **`src/indicators/lean.py`**:
   - W `get_lean_gpu_transform_info` ujednolicono wyznaczanie `raw_title` dokładnie 1:1 z `_render_lean_indicator`:
     ```python
     raw_title = str(cfg.get("title_text", label or "")).strip()
     ```
2. **`src/ffmpeg/amd_native_exporter.py`**:
   - Wywołanie `get_lean_gpu_transform_info` przekazuje rzeczywistą wartość z konfiguracji: `label=lean_cfg.get("label", "")`.

---

## 4. Wyniki pomiarów — Widoczny odstęp (Visible Gap)

Pomiar na klatce 150 (4K UHD 3840x2160, `GX030120.MP4` + `def_layout.json`):

```text
LEAN_VISIBLE_GAP:
  preview:
    bike_visible_bottom_y=513.0
    text_visible_top_y=520.0
    visible_gap_y=7.0
  final_amd:
    bike_visible_bottom_y=513.0
    text_visible_top_y=520.0
    visible_gap_y=7.0
  delta_gap=0.0
```

### Tabela podsumowująca

| Metryka | Preview (CPU Reference) | Final AMD Render | Delta | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Bike visible bottom Y** | 513.0 px | 513.0 px | **0.0 px** | **PASS** |
| **Text visible top Y** | 520.0 px | 520.0 px | **0.0 px** | **PASS** |
| **Visible gap Y** | 7.0 px | 7.0 px | **0.0 px** | **PASS** (brak overlapu, $gap > 0$) |

---

## 5. Weryfikacja wizualna i testy

1. **Pliki kadrów i cropów**:
   - `scratch/preview_lean_crop_etap3q.png` (podgląd referencyjny)
   - `scratch/final_amd_lean_crop_etap3q.png` (finalny zdekodowany MP4 AMD)
   - Na obu cropach napis `-9°` znajduje się w czytelnym, 7-pikselowym odstępie pod dolnym kołem/pivotem rowerka. Overlap został całkowicie wyeliminowany.
2. **Eksport i wydajność**:
   - Plik wideo: `scratch/test_amd_etap3q_smoke.mp4` (300 klatek, 4K UHD @ 29.97 fps).
   - Render FPS: 23.92 fps (brak wpływu na wydajność).
3. **Testy jednostkowe**:
   - `pytest tests/test_lean_gpu_bridge.py tests/test_lean_tight_rotation.py`: **23 passed** (100%).

---

## 6. Podsumowanie

- Nachodzenie napisu na rowerek zostało całkowicie usunięte u źródła.
- Widoczny odstęp między dolną krawędzią rowerka a górną krawędzią glifu wartości wynosi dokładnie `7.0 px` w obu potokach (`delta = 0.0 px`).
- **ETAP 3Q zakończony sukcesem (PASS)**.
