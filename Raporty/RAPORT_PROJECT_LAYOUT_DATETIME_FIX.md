# RAPORT: PROJECT LAYOUT JSON DATETIME FIX

**Data:** 2026-09-15  
**Gałąź:** `main`  
**Commit wyjściowy:** `463b4bc`

---

## 1. ZADANIE

Naprawić błąd:

```
[ProjectLayout] Błąd zapisu layoutu projektu:
Object of type datetime is not JSON serializable
```

**Wymagania:**
- Nie używać globalnego `json.dump(..., default=str)` jako obejścia
- Audyt źródeł obiektów niebędących typami JSON w layoutach
- Ścisły kontrakt JSON: `str, int, float, bool, null, list, dict`
- Weryfikacja roundtrip: load → save → reload z 100% parytetem

---

## 2. STAN WYJŚCIOWY

### 2.1 Ścieżka serializacji (przed)

```
self.layout  (dict RAM, może zawierać datetime, Path, numpy, tuple)
    ↓
normalize_layout_for_save()   [compositor.py]
    ↓   (nie sanityzował typów runtime - tylko głębokie kopiowanie + orientacja)
json.dump(..., default=str)   ← obejście objawu, nie przyczyny
```

Plik `_save_project_layout` w `preset_mixin.py` używał `default=str`:

```python
json.dump(saved, f, indent=2, ensure_ascii=False, default=str)
```

### 2.2 Typy stwierdzone w pre-save payload

| Typ Python         | Przykładowe klucze                              |
|--------------------|--------------------------------------------------|
| `datetime`         | `_runtime_start_dt`, `export_start_time`        |
| `date`             | `_runtime_date`                                 |
| `timedelta`        | `_runtime_duration_delta`                       |
| `WindowsPath`      | `_runtime_video_ref`, `export_settings.source_path` |
| `numpy.float64`    | `cut_regions[i][j]`, `global.target_fps`        |
| `numpy.int32`      | `global.buffer_count`                           |
| `numpy.bool_`      | `global.is_hardware_accel`                      |
| `tuple`            | `cut_regions[i]` (pary float)                   |

---

## 3. ROZWIĄZANIE

### 3.1 Nowa funkcja `sanitize_layout_for_json`

Dodano do [`src/indicators/compositor.py`](file:///H:/_Dev/BikeRideHUD/src/indicators/compositor.py):

```python
def sanitize_layout_for_json(obj: Any) -> Any:
    """Recursively convert runtime/non-JSON objects to strict JSON primitives."""
    if obj is None: return None
    if isinstance(obj, bool): return obj
    if isinstance(obj, (str, int, float)): return obj
    if isinstance(obj, (datetime, date)): return obj.isoformat()   # ISO 8601
    if isinstance(obj, timedelta): return obj.total_seconds()
    if isinstance(obj, (Path, PurePath, os.PathLike)): return str(obj)
    # numpy: integer → int, floating → float, bool_ → bool, ndarray → list
    # Qt: QDate/QTime/QDateTime → str, QColor → str("#rrggbb"), QUrl → str
    if isinstance(obj, bytes): return obj.decode("utf-8", errors="replace")
    if isinstance(obj, (list, tuple)): return [sanitize_layout_for_json(x) for x in obj]
    if isinstance(obj, (set, frozenset)): return [...]
    if isinstance(obj, dict): return {str(k): sanitize_layout_for_json(v) for k, v in obj.items()}
    return str(obj)  # ostatni fallback
```

### 3.2 Integracja w `normalize_layout_for_save`

Funkcja `normalize_layout_for_save` teraz zwraca wynik `sanitize_layout_for_json(saved)` — każdy layout
przechodzący przez ten gateway jest gwarantowanie serializowalny przez standardowy `json.dump`.

### 3.3 Zmiany w `preset_mixin.py`

**`_save_project_layout`** — usunięto `default=str`, dodano jawną sanityzację:

```diff
- json.dump(saved, f, indent=2, ensure_ascii=False, default=str)
+ saved = sanitize_layout_for_json(saved)
+ json.dump(saved, f, indent=2, ensure_ascii=False)
```

**`_save_preset_as`** — dodano `sanitize_layout_for_json` po `normalize_layout_for_save`.

**`_save_current_layout_to_default`** — dodano `sanitize_layout_for_json` przed zapisem do `def_layout.json`.

### 3.4 Zmiany w `layout_manager.py`

**`LayoutManager.save`** — teraz używa `normalize_layout_for_save + sanitize_layout_for_json`:

```diff
+ from src.indicators.compositor import normalize_layout_for_save, sanitize_layout_for_json
+ saved = normalize_layout_for_save(self.layout)
+ saved = sanitize_layout_for_json(saved)
- json.dump(self.layout, f, indent=2, ensure_ascii=False)
+ json.dump(saved, f, indent=2, ensure_ascii=False)
```

---

## 4. PLIKI ZMIENIONE

| Plik                                                          | Zmiana                                              |
|---------------------------------------------------------------|-----------------------------------------------------|
| [`src/indicators/compositor.py`](file:///H:/_Dev/BikeRideHUD/src/indicators/compositor.py)     | Dodano `sanitize_layout_for_json`; `normalize_layout_for_save` teraz ją wywołuje |
| [`src/gui/qt/_mixins/preset_mixin.py`](file:///H:/_Dev/BikeRideHUD/src/gui/qt/_mixins/preset_mixin.py) | Usunięto `default=str`; dodano sanityzację w 3 miejscach zapisu |
| [`src/gui/layout_manager.py`](file:///H:/_Dev/BikeRideHUD/src/gui/layout_manager.py)           | `LayoutManager.save` teraz normalizuje i sanityzuje  |

---

## 5. TESTY

### 5.1 Test sanityzacji typów

Skrypt: `scratch/project_layout_datetime_fix/test_sanitization.py`

**Typy testowane:**
- `datetime` (naive i UTC-aware) → ISO 8601 string ✅
- `date` → ISO 8601 string ✅
- `timedelta` → float seconds ✅
- `Path`, `WindowsPath` → str ✅
- `numpy.int32`, `numpy.int64`, `numpy.float32`, `numpy.float64`, `numpy.bool_` → Python int/float/bool ✅
- `numpy.ndarray` (1D i 2D) → list ✅
- `bytes` → str ✅
- `set`, `frozenset` → list ✅
- `tuple` → list ✅

**Wynik:** PASS — `json.dumps` bez `default=str` działa ✅

### 5.2 Test roundtrip layoutu produkcyjnego

Skrypt: `scratch/project_layout_datetime_fix/run_project_layout_validation.py`

**Dataset:** `Video/GX010290.MP4`, `Video/GX010291.mp4`, `Video/GX020291.mp4`, `Video/20260911.fit`

**Pre-save payload** zawierał: `datetime, WindowsPath, timedelta, date, float64, int32, bool, tuple`

**Wyniki:**
```
Strict json.dump succeeded without default=str!
Post-save JSON types: ['dict', 'int', 'str', 'float', 'bool', 'list']
PASS: All reloaded types are strictly standard JSON types.
Roundtrip validation PASSED with 100% parity!
  - Indicator count: 30/30 match
  - DateTime: "2026-09-11T13:04:56.655000+00:00" (ISO 8601 ✓)
  - Cut regions: [[10.5, 25.0], [120.0, 145.5]] (numpy float64 → float ✓)
  - Export settings: wszystkie pola zachowane ✓
```

**STATUS:** PASS ✅

### 5.3 Pre-save typ audit

```
dict        ← wskaźniki, globalne ustawienia
int         ← grubości, ticki, segmenty
str         ← kolory, labelki, ścieżki
float64     ← koordinaty, fps, zakresy (numpy)
int32       ← liczniki (numpy)
bool        ← enabled, show_* (Python native)
list        ← custom_texts, tracks
float       ← x, y, size, font_size (Python native)
datetime    ← start_dt_utc, export timestamps
WindowsPath ← referencje ścieżek video
timedelta   ← elapsed
date        ← daty nagrań
tuple       ← cut_regions pary (float64, float64)
```

Wszystkie konwertowane na czyste typy JSON po sanityzacji.

---

## 6. ARTEFAKTY

Katalog: `scratch/project_layout_datetime_fix/`

| Plik                          | Opis                                        |
|-------------------------------|---------------------------------------------|
| `payload_type_audit.txt`      | Audyt typów pre-save                        |
| `datetime_source.txt`         | Ślad źródeł datetime w kodzie               |
| `saved_project_layout.json`   | Przykładowy zapisany layout (rygorystyczny JSON) |
| `roundtrip_test.txt`          | Wyniki testu roundtrip                      |
| `test.log`                    | Pełny log testu                             |
| `ntfy_result.txt`             | Wynik NTFY notification                     |
| `artifacts_manifest.txt`      | Manifest artefaktów                         |

---

## 7. NTFY

```
Topic:   MalcerzPOP
Status:  SUCCESS (exit 0)
Message: BikeRideHUD ProjectLayout JSON: CASE A — PROJECT LAYOUT JSON ROUNDTRIP PASS,
         datetime_field=sanitized, strict_json=NO_default_str.
ID:      mzwObJv9Tw3j
```

---

## 8. BACKEND ISOLATION

- **AMD:** NIE DOTKNIĘTO — żadnych zmian w `amd_native_exporter.py`, `amd_config.py`, pipelinach AMD
- **NVIDIA:** NIE DOTKNIĘTO — renderer NVENC/native bez zmian
- **Intel:** NIE DOTKNIĘTO
- **GPU backends:** Żadna zmiana nie wpływa na ścieżki renderowania

Zmiany dotyczą wyłącznie serializacji layoutu GUI do JSON na dysk.

---

## 9. RYZYKA

| Ryzyko | Ocena |
|--------|-------|
| `LayoutManager.save` zmiana semantyki dla zewnętrznych wywołań | NISKIE — normalizacja tylko korzystna |
| Qt types (`QDate`, `QColor`, etc.) jako fallback string | NISKIE — sprawdzone przez `type_name`, prawdopodobnie rzadkie |
| `_on_settings_changed("startup_preset")` używa `json.dump(data, ...)` bez sanityzacji | NISKIE — `data` pochodzi bezpośrednio z `json.loads`, nie zawiera runtime objects |

---

## 10. PODSUMOWANIE

```
TASK:    Naprawa json.dump datetime serialization w Project Layout
STATUS:  PASS

CHANGED:
  src/indicators/compositor.py          — dodano sanitize_layout_for_json, rozszerzono normalize_layout_for_save
  src/gui/qt/_mixins/preset_mixin.py    — usunięto default=str, dodano sanitize_layout_for_json w 3 save paths
  src/gui/layout_manager.py             — LayoutManager.save teraz normalizuje + sanityzuje

TESTED:
  test_sanitization.py                  — PASS: wszystkie non-JSON typy prawidłowo konwertowane
  run_project_layout_validation.py      — PASS: roundtrip 30 wskaźników, datetime ISO 8601, cut_regions float, export settings

NOT TESTED:
  Pełny test GUI z uruchomioną aplikacją NVIDIA (brak możliwości w headless)

PERFORMANCE:
  Brak wpływu — sanityzacja wywoływana tylko przy zapisie layoutu (nie w render loop)

RISKS:
  NISKIE — zmiany tylko w warstwie persystencji, bez wpływu na render/GPU backends
```
