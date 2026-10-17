# SPORTCAMHUD — mapa z pochyleniem respektuje wybrany kształt

Data: 2026-10-16. **STATUS: PASS**

## 1. Repo
- Gałąź `fix/gui-freeze-hud-composite`, HEAD na starcie `1404441`. Zastane zmiany (Intel/NVIDIA, `def_layout.json`, `live_av_mux.py`) nietknięte.
- Commit: `939137636dc87790f4673de679f6c768abb69d28` — fix(map): keep the selected map shape when pitch is applied.

## 2. Diagnoza
Problem był w **Pythonie** (`src/indicators`), nie w DLL AMD.
- Pochylenie liczy `apply_map_pitch` (helpers.py): homografia źródłowego kwadratu na trapez z `compute_map_pitch_quad`, z przezroczystym tłem poza trapezem.
- W każdej ścieżce CPU/podglądu (`moving_map.py` ×3, `static_map.py` ×2) kolejność była: render mapy → orientacja → **kształt + obramowanie** → przezroczystość → **pitch**. Kształt był więc docinany *przed* warpem, a warp zamieniał docięty kwadrat (z ramką) w trapez z pustymi rogami. Wynik: „trapez w kwadratowej ramce” (stary eksport Kwadrat + pitch 45: `map_shapes_compare.png`, pierwszy kafel).
- Ścieżka AMD GPU (`_render_track_map_gpu_tile`): przy pitch > 0 eksporter wyłącza obrót GPU, a pitch nakładany jest w Pythonie. Kształt i obramowanie nakłada natywny shader stylu mapy (5W) na końcu, w przestrzeni docelowej. Tam kolejność była poprawna, ale wejściem był już trapez z przezroczystymi rogami.
- Sama zamiana kolejności nie wystarczała: przycięcie trapezu kwadratem zostawiłoby puste rogi.

## 3. Naprawa
- `apply_map_pitch` (`_get_map_pitch_transforms`): homografia jest złożona ze skalowaniem tak, aby **największy prostokąt wpisany w trapez (wąska dalsza krawędź × pełna głębia) wypełniał całe pole mapy**. Perspektywa działa na zawartość (zbieżność, marker jako elipsa), a pole jest w pełni pokryte. To jedna homografia (bez podwójnego przepróbkowania), z brzegiem `BORDER_REPLICATE` zamiast przezroczystego.
- Kolejność we wszystkich ścieżkach CPU/podglądu: render → orientacja/track-up → **pitch** → **kształt + obramowanie** (na końcowym obrazie) → przezroczystość → kompozycja.
- Ścieżka AMD GPU: bez zmian kodu natywnego — finalny kształt i obramowanie z shadera stylu działają teraz na w pełni pokrytym polu.
- pitch = 0: identyczne zachowanie (funkcja zwraca ten sam obiekt).

Zmienione pliki:
- `src/indicators/helpers.py`;
- `src/indicators/moving_map.py`;
- `src/indicators/static_map.py`;
- `tests/test_map_pitch_keeps_shape.py` (nowy);
- `tests/test_map_perspective.py` (oczekiwane współrzędne uwzględniają skalowanie wypełnienia; test zgodności markera i trasy w perspektywie zostaje).

## 4. Kolejność etapów
| przed | po |
|---|---|
| tekstura → track-up → kształt/ramka → przezroczystość → pitch (trapez) → kompozycja | tekstura → track-up → pitch (wypełnia pole) → kształt/ramka → przezroczystość → kompozycja |
| AMD GPU: tekstura (CPU) → pitch (trapez) → GPU: kształt/ramka w przestrzeni docelowej → HUD | AMD GPU: tekstura (CPU) → pitch (wypełnia pole) → GPU: kształt/ramka → HUD |

## 5. Wyniki
**Test regresyjny** (`tests/test_map_pitch_keeps_shape.py`):
- dla Kwadrat / Prostokąt / Zaokrąglony / Koło × pitch 30/45/70 sylwetka (alfa) wyniku jest identyczna jak przy pitch 0, rogi Kwadratu i Prostokąta są wypełnione, a zawartość ma perspektywę;
- obramowanie biegnie po kształcie;
- pitch 0 bez zmian;
- **14/14 PASS**. Ten sam test na starym kodzie: **13/14 FAIL** (wykrywa trapez).

Pozostałe testy mapy: `test_map_perspective.py` 11/11, `test_map_style_5w.py` 15/15, `test_map_sync.py` 38/38.

**Eksport** (harness `--test-amd-export`, GX020079 + FIT, 300 kl., HLG→SDR, FAST 40M). Kopie layoutu 5Y z `track_map`: `track_up`, pitch 0/45, kształty — `Raporty/map_pitch_shape_artifacts/layout_*.json`. Mapa z klatki 150: `map_shapes_compare.png` (kafle: stary Kwadrat 45 | nowy Kwadrat 0 | nowy Kwadrat 45 | nowy Zaokrąglony 45 | nowy Koło 45).

| przypadek | wynik |
|---|---|
| A. Kwadrat, pitch 0 | kwadrat z ramką, bez zmian — PASS |
| B. Kwadrat, pitch 45 | **pełny kwadrat** z mapą w perspektywie (wcześniej spłaszczony trapez) — PASS |
| C. Zaokrąglony, pitch 45 | zaokrąglony prostokąt z ramką po kształcie — PASS |
| D. Koło, pitch 45 | koło z ramką po kształcie — PASS |
| E. Eksport | jw. — PASS |
| F. Podgląd GUI | podgląd edytora używa tych samych funkcji (`moving_map`/`static_map`), więc kolejność i pitch są identyczne; pokryte testem jednostkowym. Interaktywnie w oknie — NOT TESTED |
| G. pitch 0 | bez zmian (test + eksport) — PASS |

## 6. FPS (Render FPS, te same ustawienia, kolejno nowy/stary)
| wariant | wynik |
|---|---|
| Kwadrat 45, nowy kod | 41,62 / 41,18 |
| Kwadrat 45, stary kod (portable `gui-fixed`, ta sama DLL) | 41,53 / 42,25 |
| Kwadrat 0, nowy kod | 41,84 |
| layout bazowy 5Y | 41,24 |

**Wpływ: brak** (w granicach rozrzutu). Pierwsze przebiegi z nowymi layoutami testowymi dały ~22 FPS dla wszystkich wariantów, także starego kodu i pitch 0. W powtórce, po rozgrzaniu cache kafelków, wszystkie mają ~41–42 FPS. Nie jest to skutek poprawki.

## 7. Ochrona
- `def_layout.json` (Twój): `65fa8390d1cda70ed8d115631a75e35559b24b9990e1ca15f944f0fb371606f4` przed i po. Testy używały kopii layoutu 5Y, harness raportował `def_layout_unchanged True`. Pitch, kształt, pozycja i rozmiar mapy w Twoim pliku nie są zmieniane.
- **DLL nie była przebudowywana**: `e359d7784d2ff3d2b1aefb6cf56dc1ba3c38a67260fd8d87e27851ef0d55ee89` przed i po (także w nowym portable).
- Audio, HDR, QP/VBR, kolejka, inne wskaźniki: bez zmian.

## 8. Portable
`C:\_DEV\BikeRideHUD-main-new\dist\portable-hdr-map-shape-fix` — z commita `9391376`, 6320 plików, 1,71 GB. Zawiera poprawkę (`helpers.py`). Eksport z pakietu (Kwadrat, pitch 45): success, **42,08 FPS**, mapa zgodna z dev (MAE wycinka 5,1 — kompresja i font szablonu). Poprzednie pakiety nienadpisane.

## 9. Otwarte
- Przy dużym pitch perspektywa jest łagodniejsza niż wcześniej w obrębie pola, bo trapez jest skalowany, żeby wypełnić kształt; dalsza część mapy jest bardziej widoczna. To zamierzony efekt wymagania „kształt końcowy = wybrany kształt”.
- Interaktywny test podglądu w oknie GUI nie był wykonywany.

ntfy: wysłane po zapisaniu raportu, "id":"oaJAppd3PGmX", HTTP 200.
