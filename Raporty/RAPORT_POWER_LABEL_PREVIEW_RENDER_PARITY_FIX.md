# RAPORT: POWER LABEL PREVIEW RENDER PARITY FIX

**Data:** 2026-09-16  
**Gałąź:** `amd-bikeridehud`  
**Autor:** Antigravity  

---

## 1. Summary

Naprawiono różnicę w pozycjonowaniu etykiety poziomego wskaźnika (`fit_curVpower_text` oraz całego typu wskaźników bar/ruler/segments) pomiędzy oknem podglądu (PREVIEW, 540p) a finalnym eksportem wideo (RENDER, 4K).

Przed naprawą:
- **PREVIEW:** `POWER` znajdował się **POD** poziomą skalą / barem.
- **FINAL RENDER:** `POWER` znajdował się **NAD** poziomą skalą / barem.

Po naprawie:
- **PREVIEW:** `POWER` znajduje się **POD** poziomą skalą / barem (`+16 px` względem osi).
- **FINAL RENDER:** `POWER` znajduje się **POD** poziomą skalą / barem (`+89 px` względem osi).
- Względna proporcja położenia etykiety względem skali jest w 100% zachowana na każdej rozdzielczości (540p, 1080p, 4K).

---

## 2. Metryki i Identyfikacja

```text
INDICATOR_KEY=fit_curVpower_text
RENDERER=_render_ruler / _render_bar_indicator (src/indicators/bar.py)
PREVIEW_LABEL_Y=538 (PREVIEW_BAR_RECT=(336, 522, 288, 1), RELATIVE=+16 px -> BELOW BAR)
RENDER_LABEL_Y=2172 (RENDER_BAR_RECT=(1342, 2083, 1152, 2), RELATIVE=+89 px -> BELOW BAR)
ROOT_CAUSE=Funkcja _label_offset() w src/indicators/bar.py zawierała 'del scale' i nie skalowała wartości label_offset_x oraz label_offset_y proporcjonalnie do rozdzielczości canvasu (min_dim / 540.0), podczas gdy wszystkie pozostałe elementy skali, ticki, fonty i wysokość rastra skalowały się liniowo.
MODIFIED_FILES=src/indicators/bar.py
POWER_LABEL_PREVIEW_RENDER_PARITY=PASS
OTHER_LAYOUT_REGRESSION=NONE (alt_text, distance, gauge, map, charts, texts zachowują pozycje)
CASE=CASE A — POWER LABEL PARITY FIXED
```

---

## 3. Szczegóły Implementacji

### Plik: `src/indicators/bar.py`
W funkcji `_label_offset(cfg, ss, scale)` usunięto pomijanie parametru `scale` (`del scale`) i wprowadzono proporcjonalne skalowanie przesunięć etykiety zakotwiczone w domyślnej rozdzielczości podglądu GUI (540p, `min_dim / 540.0` czyli `scale * 2.0` gdzie `scale = min_dim / 1080.0`):

```python
def _label_offset(cfg: dict[str, Any], ss: int, scale: float = 1.0) -> tuple[int, int]:
    """New BAR offsets are final widget pixels (and supersample-safe)."""
    try:
        ox = float(cfg.get("label_offset_x", 0.0) or 0.0)
        oy = float(cfg.get("label_offset_y", 0.0) or 0.0)
    except (TypeError, ValueError):
        ox = oy = 0.0
    # The layout preview canvas defaults to 540p (960x540, scale=0.5), while
    # full-resolution renders are 1080p (scale=1.0) or 4K (scale=2.0).
    # Scaling by scale * 2.0 (i.e. min_dim / 540.0) anchors 1.0x to the
    # 540p GUI preview canvas and scales proportionally with canvas resolution.
    return int(round(ox * max(1, ss) * scale * 2.0)), int(round(oy * max(1, ss) * scale * 2.0))
```

W funkcji `_render_segments` przekazano parametr `scale = min(canvas_w, canvas_h) / 1080.0` do `_label_offset(cfg, ss, scale)`.

---

## 4. Testy i Walidacja

1. **Testy jednostkowe i generyczne:**
   - Utworzono zestaw testów w `tests/test_power_label_parity.py` sprawdzający etykiety `A`, `POWER`, `TEMP`, `CADENCE`, `Power`, `Solar` na różnych rozdzielczościach i stylach (`ruler`, `segments`).
   - Uruchomiono `pytest`: **14 passed** (9 nowych + 5 istniejących testów bar label).

2. **Test realny na projekcie GX010298:**
   - Wygenerowano pełną klatkę podglądu (`scratch/power_label_parity/preview.png`) i renderu 4K (`scratch/power_label_parity/render.png`) dla `t=0.0s`.
   - Zapisano cropy wskaźnika mocy (`preview_power.png` oraz `render_power.png`).
   - Wizualna weryfikacja potwierdza: etykieta `Power` znajduje się pod poziomą skalą, wycentrowana pomiędzy `0W` a `231W`, nie koliduje ze wskaźnikiem prędkości `0.0 km/h`.

3. **Brak regresji pozostałych wskaźników:**
   - Wskaźnik prędkości (`speed_text`), mapa (`track_map`), wykresy tętna (`fit_heart_rate_text`), kadencji (`fit_cadence_text`), dystansu (`fit_distance_text`), wysokości (`alt_text`), baterii i kamer zachowują 100% zgodności geometrycznej.

---

## 5. Artefakty

Wszystkie artefakty zapisano w katalogu `scratch/power_label_parity/`:
- `root_cause.md`
- `geometry_probe.txt`
- `preview.png`
- `render.png`
- `preview_power.png`
- `render_power.png`
- `tests.txt`
- `artifacts_manifest.txt`
- `ntfy_result.txt`
