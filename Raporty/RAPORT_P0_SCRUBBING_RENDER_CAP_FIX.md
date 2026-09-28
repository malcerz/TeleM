# RAPORT P0 — SCRUBBING REGRESSION + RENDER 10s CAP FIX

## TASK
Przywrócić swobodne przewijanie timeline (scrubbing) i poprawić limit
renderowania z ~10 s (300 klatek) do pełnego czasu trwania projektu
dla `Video/GX010298.MP4` (~23:18, ~1398 s).

---

## ROOT CAUSE

### Bezpośrednia przyczyna (danych)
`Video/GX010298.layout.json` zawierał:
```json
"cut_regions": [[10.0, 1398.6639333333333]]
```
Pochodzi z wcześniejszej sesji — użytkownik ustawił IN=10s,
`_save_project_layout()` zapisał tymczasowe granice IN/OUT
do trwałego sidecar layoutu projektu.

### Architektoniczna przyczyna (kodu)
`preset_mixin.py` → `_save_project_layout()` serialized `self._cut_regions`
(runtime IN/OUT state) do pliku layoutu — co zatruwa kolejne sesje.

### Łańcuch skutków
```
layout.cut_regions = [(10.0, 1398.664)]
  → project_mixin: self._cut_regions = [(10.0, 1398.664)]
  → SeekBar.effective_duration_s = 10.0 s
  → render capped at ~300 frames (~10 s)
```

---

## ZMIENIONE PLIKI

| Plik | Zmiana |
|------|--------|
| `Video/GX010298.layout.json` | Usunięto klucz `cut_regions` |
| `src/gui/qt/_mixins/project_mixin.py` L518–L526 | Nie ładuj `cut_regions` z layoutu — zawsze `self._cut_regions = []` |
| `src/gui/qt/_mixins/preset_mixin.py` L178–L184, L219–L224 | `_save_project_layout` i `_save_current_layout_to_default` nie zapisują `_cut_regions` |

---

## TESTY

```
scratch/p0_timeline_duration/test_p0_fix_static.py

PASS  layout JSON: no cut_regions
PASS  project_mixin: cut_regions not loaded from layout
PASS  preset_mixin: sidecar functions do not serialize cut_regions

ALL CHECKS PASSED (3/3)
```

### Wymagane testy GUI (użytkownik)
1. Wczytać `GX010298.MP4 + GX010298.fit`
2. Scrubbing 0%/25%/50%/75%/100% — `duration_label` ~23:18
3. EKSPORTUJ bez IN/OUT → ~41918 klatek
4. EKSPORTUJ z IN=30s OUT=60s → ~30s; po anulowaniu zakresu → pełny

---

## SUMMARY

```
TASK:        P0 Scrubbing + Render Cap regression fix
STATUS:      IMPLEMENTED / STATIC TEST PASSED (3/3)

CHANGED:
  Video/GX010298.layout.json           — usunięto zatrute cut_regions
  src/gui/qt/_mixins/project_mixin.py  — nie ładuj cut_regions z layoutu
  src/gui/qt/_mixins/preset_mixin.py   — nie serializuj cut_regions do sidecar

TESTED:       Static structure test — PASS
NOT TESTED:   GUI scrubbing / pełny render — wymaga GUI

PERFORMANCE:  nie dotyczy (fix funkcjonalny)
RISKS:        NISKIE — czysto GUI layer, render paths niezmienione
```
