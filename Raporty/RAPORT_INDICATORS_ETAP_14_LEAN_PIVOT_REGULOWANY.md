# RAPORT — Przechył: regulowany pivot / oś obrotu grafiki

**Etap:** 14 (LEAN PIVOT)
**Data:** 2026-08-23
**Baseline:** ETAP 12/13 (`RAPORT_INDICATORS_ETAP_12_...`, `RAPORT_INDICATORS_ETAP_13_...`).
**Zakres:** wyłącznie punkt obrotu grafiki wskaźnika `Przechył`. **Bez zmian** algorytmu kąta Lean, fuzji IMU, offset/invert/sensitivity/clamp, innych wskaźników, pipeline'ów AMD/NVIDIA/Intel, FFmpeg, SmartSync.

---

## 1. Gdzie wcześniej wyliczany był pivot

W `src/indicators/lean.py::_render_lean_indicator` grafika była obracana:

```python
rotated = graphic.rotate(angle, resample=..., expand=True)   # PIL: center = środek obrazka
img.alpha_composite(rotated, (raster_w/2 - rotated.w/2, center_y - rotated.h/2))
```

PIL `Image.rotate` bez parametru `center` obraca **wokół środka grafiki** (`w/2, h/2`), a wynik był wklejany wyśrodkowany w rastrze.

## 2. Dlaczego grafika obracała się wokół środka

- Brak jakiegokolwiek pola pivot w configu — jedynym dostępnym (domyślnym) punktem był środek obrazka PIL.
- Paste był symetryczny (`raster_w/2 - w/2, center_y - h/2`), więc środek grafiki pokrywał się ze środkiem rastra.
- Dla roweru oznaczało to „zawieszenie" w powietrzu i obrót wokół środka zamiast „osadzenia" przy podłożu.

## 3. Jakie pola dodano do configu wskaźnika

- `pivot_x` (float, 0.0–1.0, krok 0.01) — „Punkt obrotu X" (0 = lewo, 1 = prawo).
- `pivot_y` (float, 0.0–1.0, krok 0.01) — „Punkt obrotu Y" (0 = góra, 1 = dół).
- Wartości znormalizowane względem grafiki: `pivot_px = graphic.width * pivot_x`, `pivot_py = graphic.height * pivot_y`.

## 4. Jaki jest nowy domyślny pivot

```
pivot_x = 0.5
pivot_y = 1.0
```
czyli **dolny środek grafiki** — naturalny punkt „kontaktu kół z podłożem" dla roweru. Stare configi bez pól dostają ten default (kompatybilność wsteczna).

## 5. Jak działa transformacja obrotu po zmianie

Bezpieczny model „pad + rotate wokół środka padu" (pivot nigdy się nie przesuwa):

```
pivot_px = gw * pivot_x ; pivot_py = gh * pivot_y
pad = 2*max(gw, gh) + 4                        (kwadrat, brak clippingu dla każdego kąta)
pad_img = transparent(pad, pad)
pad_img.alpha_composite(graphic, (pad/2 - pivot_px, pad/2 - pivot_py))   # pivot na środku padu
rotated = pad_img.rotate(angle)                # obrót wokół środka padu == pivotu
# pozycja ekranowa pivotu = tam, gdzie był przy wyśrodkowanej grafice (angle=0):
screen_pivot_x = raster_w/2 + (pivot_px - gw/2)
screen_pivot_y = center_y    + (pivot_py - gh/2)
img.alpha_composite(rotated, (screen_pivot_x - pad/2, screen_pivot_y - pad/2))
```

Kolejność: **translate pivotu na środek padu → rotate → paste z powrotem**. Pivot pozostaje w stałej pozycji ekranowej dla każdego kąta; pozycja całego wskaźnika w layout nie zmienia się (przesuwany jest tylko punkt obrotu wewnątrz rastra). Dla `pivot = (0.5, 0.5)` zachowanie jest identyczne z poprzednim (obrót wokół środka).

## 6. Jak rozwiązano kompatybilność wsteczną

- `_graphic_pivot(cfg, gw, gh)` używa `cfg.get("pivot_x", 0.5)` / `cfg.get("pivot_y", 1.0)` — brak pól = domyślne (0.5/1.0).
- Stare layouty bez `pivot_x/pivot_y` renderują się bez zmian (poza nowym, naturalnym domyślnym pivotem — zgodnie z założeniem zadania: „stare configi bez pivotu dostają default 0.5/1.0").
- Brak mutacji configu, brak zapisu do pliku.

## 7. Jakie pliki i funkcje zmieniono

| Plik | Zmiana |
|---|---|
| `src/indicators/lean.py` | `_graphic_pivot(cfg, gw, gh)` (normalizacja pivotu), `_rotate_paste_params(...)` (pad-rotate, zwraca też ekranowy pivot), `_render_lean_indicator` używa pad-rotate zamiast `graphic.rotate(...)` wokół środka. |
| `src/gui/qt/models.py` | `lean_indicator_fields()`: pola `pivot_x` (default 0.5), `pivot_y` (default 1.0) w zakładce Data. |
| `src/gui/qt/_mixins/indicator_mixin.py` | defaulty tworzenia wskaźnika: `pivot_x=0.5`, `pivot_y=1.0`. |
| `tests/test_lean_pivot_contract.py` (NOWY) | TEST 1–5 (9 testów). |

## 8. Jakie testy dodano

`tests/test_lean_pivot_contract.py` (9 testów):
- **TEST 1** — default pivot: nowo tworzony wskaźnik ma `pivot_x=0.5`, `pivot_y=1.0` (canonical defaults); `_graphic_pivot` zwraca defaulty, gdy pól brak.
- **TEST 2** — center vs bottom: math `_rotate_paste_params` daje inny ekranowy pivot; render center vs bottom przy tym samym kącie różni się; pivot-środek zachowuje środek bboxa grafiki niezmienny przy zmianie kąta; pivot-dół przesuwa środek bboxa (rzeczywiste użycie innego pivotu).
- **TEST 3** — preview/final parity: ten sam pivot/kąt → identyczny widget (compose_overlay fast_preview True/False).
- **TEST 4** — legacy config bez `pivot_x/pivot_y`: nie crashuje, dostaje defaulty, renderuje się.
- **TEST 5** — zmiana `pivot_x/pivot_y` nie psuje pozycji wskaźnika, skali grafiki ani wartości tekstowych (identyczny rozmiar i wiersz wartości).

## 9. Wyniki testów

- Nowe `test_lean_pivot_contract.py` → **9 passed**.
- Zestaw dotkniętych (pivot + lean IMU + lean indicator + orientation + slope + tick + pixel + parity) → **162 passed**.
- **Pełny test suite** → **963 passed, 17 skipped, 9 failed**.
- **9 failures = wszystkie pre-existing** (identyczne jak w ETAP 11B/12/13, potwierdzone stash-em): `test_amd_native_etap5b`, `test_etap5e1` (2), `test_etap5e3`, `test_etap8m7`, `test_etap8q`, `test_etap8s`, `test_etap8t_b`, `test_static_indicator_cache::test_slope_dynamic_marker_and_static_style_miss`.
- `get_errors` na zmienionych plikach → brak błędów.

## 10. Co sprawdzić ręcznie w GUI

1. Dodaj `Przechył` → grafika (rower) powinna obracać się **wokół dolnego środka** (koła „osadzone" przy podłożu), a nie wokół środka obrazka.
2. W Property Editor (zakładka Data) zmień **Punkt obrotu X / Y** (0.0–1.0, krok 0.01):
   - `0.5 / 1.0` = dół-środek (default),
   - `0.5 / 0.5` = środek (stare zachowanie),
   - `0.25 / 0.9`, `0.5 / 0.0` itd. → obrót wokół wybranego punktu.
3. Przy pochyleniu (zakręt) kółka pozostają mniej więcej „przy ziemi", góra roweru wychyla się.
4. **Preview vs Render** — ten sam punkt obrotu dla tej samej chwili.
5. Otwórz stary projekt bez `pivot_x/pivot_y` → nadal się renderuje (dostaje default 0.5/1.0).
6. Pozycja wskaźnika, skala grafiki i odczyt liczbowy pozostają bez zmian przy zmianie pivotu.

---

## Podsumowanie (AGENTS.md)

### Changed
`src/indicators/lean.py` (pivot: `_graphic_pivot`, `_rotate_paste_params`, pad-rotate), `src/gui/qt/models.py` (pola `pivot_x`/`pivot_y`), `src/gui/qt/_mixins/indicator_mixin.py` (defaulty), nowy `tests/test_lean_pivot_contract.py`.

### Preserved
- Algorytm kąta Lean, fuzja IMU, offset/invert/sensitivity/clamp — bez zmian.
- BAR/Ruler, pipeline'y AMD/NVIDIA/Intel, FFmpeg, SmartSync, mapy — bez zmian.
- Kompatybilność wsteczna configów (defaulty 0.5/1.0).

### Tested
9 (nowe pivot) + 162 (dotknięte) + pełny suite 963 passed / 17 skipped. 9 failures — wszystkie pre-existing.

### Not tested
- Runtime GPU eksportu — ścieżka wspólna, nie uruchamiana. NVIDIA preserved statically.

### Risks / Remaining issues
- Domyślny pivot (0.5/1.0) zmienia wygląd istniejących configów Lean (celowo — nowe naturalne zachowanie); użytkownik może wrócić do środka przez `0.5/0.5`.
- Pre-existing failures: 9 (lista w pkt. 9).
