# RAPORT: STRICT JSON PERSISTENCE FINAL GATE

**Data:** 2026-09-15  
**Gałąź:** `main`  
**Commit wyjściowy:** `463b4bc`  
**Status zadania:** CASE A — STRICT JSON PASS + UNKNOWN TYPES FAIL LOUDLY  

---

## 1. CEL ZADANIA

Domknięcie kontraktu persystencji JSON w `BikeRideHUD`:
1. **Usunięcie cichego fallbacku `return str(obj)`** z `sanitize_layout_for_json` — nieznane/nieobsługiwane typy obiektów środowiskowych (runtime objects) mają głośno zgłaszać `TypeError` zamiast być po cichu zamieniane na bezużyteczny string.
2. **Wprowadzenie path-aware diagnostics** w rekursji (`path="root"`), umożliwiające precyzyjne namierzenie ścieżki w strukturze JSON (np. `root.export_settings.foo.bar`, `root.indicators.speed_text.custom_runtime`, `root.cut_regions[1][1]`).
3. **Zachowanie pełnego wsparcia dla znanych typów:**
   - `None`, `bool`, `str`, `int`, `float`
   - `datetime`, `date` → format ISO 8601
   - `timedelta` → sekundy jako `float`
   - `Path`, `PurePath`, `os.PathLike` → `str`
   - `numpy` skalary (`np.integer`, `np.floating`, `np.bool_`) → Python native
   - `numpy.ndarray` (1D, 2D) → nested `list`
   - `bytes` → UTF-8 decoded `str`
   - `set`, `frozenset` → deterministycznie posortowana lista
   - `tuple`, `list` → `list`
   - Qt typy (`QDate`, `QTime`, `QDateTime`, `QColor`, `QUrl`, `QPoint/QPointF`, `QSize/QSizeF`, `QRect/QRectF`) → jawne prymitywy
   - `dict` → `dict` ze znormalizowanymi kluczami `str` i przesanityzowanymi wartościami
4. **Testy negatywne** wstrzykniętych obiektów nieobsługiwanych (`DummyRuntimeObject`, socket/uchwyty) z weryfikacją rzucenia `TypeError` i poprawności ścieżki.
5. **Pozytywny roundtrip test** na realnym projekcie (`def_layout.json`, 30 wskaźników, pliki `GX010290.MP4 + GX010291.mp4 + GX020291.mp4 + 20260911.fit`).

---

## 2. STAN WYJŚCIOWY

W poprzednim etapie funkcja `sanitize_layout_for_json` posiadała na końcu:
```python
return str(obj)  # ostatni fallback
```
Mogło to maskować błędy w przypadku przypadkowego wstawienia do drzewa layoutu obiektów runtime (np. procesów, socketów, uchwytów wątków, dynamicznych obiektów Qt bez metody `toString`).

---

## 3. IMPLEMENTACJA

W pliku [`src/indicators/compositor.py`](file:///H:/_Dev/BikeRideHUD/src/indicators/compositor.py):

### 3.1 Nowa sygnatura i logika `sanitize_layout_for_json`
```python
def sanitize_layout_for_json(obj: Any, path: str = "root") -> Any:
    """Recursively convert runtime/non-JSON objects to strict JSON primitives.

    - None -> None
    - bool -> bool
    - str, int, float -> primitive values
    - datetime / date -> ISO 8601 formatted string
    - timedelta -> float seconds
    - Path / os.PathLike -> str
    - numpy scalars/arrays -> Python int/float/bool/list
    - bytes -> str
    - set / frozenset -> deterministic sorted list
    - tuple / list -> list
    - Qt types (QDate, QTime, QDateTime, QColor, QUrl, QPoint, QSize, QRect) -> primitives
    - dict -> dict with string keys and sanitized values

    Raises TypeError with exact structure path if an unsupported runtime type is encountered.
    """
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (str, int, float)):
        return obj
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, timedelta):
        return obj.total_seconds()
    if isinstance(obj, (Path, PurePath, os.PathLike)):
        return str(obj)
    try:
        import numpy as np
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return [sanitize_layout_for_json(x, f"{path}[{i}]") for i, x in enumerate(obj.tolist())]
    except ImportError:
        pass
    type_name = type(obj).__name__
    if type_name in ("QDate", "QTime", "QDateTime") and hasattr(obj, "toString"):
        return str(obj.toString("yyyy-MM-ddTHH:mm:ss.zzz"))
    if type_name == "QColor" and hasattr(obj, "name"):
        return str(obj.name())
    if type_name == "QUrl" and hasattr(obj, "toString"):
        return str(obj.toString())
    if type_name in ("QPoint", "QPointF") and hasattr(obj, "x") and hasattr(obj, "y"):
        return [sanitize_layout_for_json(obj.x(), f"{path}[0]"), sanitize_layout_for_json(obj.y(), f"{path}[1]")]
    if type_name in ("QSize", "QSizeF") and hasattr(obj, "width") and hasattr(obj, "height"):
        return [sanitize_layout_for_json(obj.width(), f"{path}[0]"), sanitize_layout_for_json(obj.height(), f"{path}[1]")]
    if type_name in ("QRect", "QRectF") and hasattr(obj, "x") and hasattr(obj, "width"):
        return [
            sanitize_layout_for_json(obj.x(), f"{path}[0]"),
            sanitize_layout_for_json(obj.y(), f"{path}[1]"),
            sanitize_layout_for_json(obj.width(), f"{path}[2]"),
            sanitize_layout_for_json(obj.height(), f"{path}[3]"),
        ]
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, (list, tuple)):
        return [sanitize_layout_for_json(x, f"{path}[{idx}]") for idx, x in enumerate(obj)]
    if isinstance(obj, (set, frozenset)):
        def _set_sort_key(item: Any) -> tuple[str, str]:
            return (type(item).__name__, str(item))
        try:
            sorted_items = sorted(obj)
        except TypeError:
            sorted_items = sorted(obj, key=_set_sort_key)
        return [sanitize_layout_for_json(x, f"{path}[{idx}]") for idx, x in enumerate(sorted_items)]
    if isinstance(obj, dict):
        return {str(k): sanitize_layout_for_json(v, f"{path}.{k}") for k, v in obj.items()}

    safe_repr = repr(obj)
    if len(safe_repr) > 80:
        safe_repr = safe_repr[:77] + "..."
    raise TypeError(
        f"Unsupported layout JSON type at {path}: {type(obj).__name__} (value: {safe_repr})"
    )
```

---

## 4. WYNIKI TESTÓW

### 4.1 Testy obsługiwanych typów (Supported Types)
Plik: `scratch/strict_json_final_gate/supported_types.txt`
- Sprawdzono: `NoneType`, `bool`, `int`, `float`, `str`, `datetime` (naive i UTC), `date`, `timedelta`, `Path`, `np.int32`, `np.int64`, `np.float32`, `np.float64`, `np.bool_`, `np.ndarray` (1D i 2D), `bytes`, `set`, `frozenset`, `tuple`, `list`, typy Qt (`QColor`, `QDateTime`, `QUrl`, `QPointF`, `QRectF`), nested `dict`.
- Wynik: **PASS** — deterministyczne sortowanie zbiorów, bezbłędna serializacja rygorystycznym `json.dumps` bez `default=str`.

### 4.2 Testy negatywne (Negative Tests / Fail Loudly)
Plik: `scratch/strict_json_final_gate/unsupported_type_test.txt`

| Przypadek testowy | Wstrzyknięty typ | Ścieżka oczekiwana | Zgłoszony wyjątek i komunikat | Wynik |
|---|---|---|---|---|
| Root dummy object | `DummyRuntimeObject` | `root.invalid_root` | `TypeError: Unsupported layout JSON type at root.invalid_root: DummyRuntimeObject` | **PASS** |
| Deep nested export settings | `DummyRuntimeObject` | `root.export_settings.foo.bar` | `TypeError: Unsupported layout JSON type at root.export_settings.foo.bar: DummyRuntimeObject` | **PASS** |
| Custom indicator property | `ArbitrarySocket` | `root.indicators.speed_text.custom_runtime` | `TypeError: Unsupported layout JSON type at root.indicators.speed_text.custom_runtime: ArbitrarySocket` | **PASS** |
| Element w `cut_regions` | `DummyRuntimeObject` | `root.cut_regions[1][1]` | `TypeError: Unsupported layout JSON type at root.cut_regions[1][1]: DummyRuntimeObject` | **PASS** |
| Element w `set` | `DummyRuntimeObject` | `root.active_objects[0]` | `TypeError: Unsupported layout JSON type at root.active_objects[0]: DummyRuntimeObject` | **PASS** |

Wszystkie przypadki negatywne natychmiast rzucają `TypeError` z precyzyjną ścieżką w strukturze danych.

### 4.3 Test roundtrip na realnym projekcie
Plik: `scratch/strict_json_final_gate/roundtrip_test.txt`
- Materiał: `GX010290.MP4`, `GX010291.mp4`, `GX020291.mp4`, `20260911.fit`
- Layout bazowy: `def_layout.json` (30 wskaźników)
- Wstrzyknięte metadane GUI: `_runtime_start_dt`, `_runtime_video_path`, `_runtime_duration_delta`, `_runtime_date`, numpy `target_fps`/`buffer_count`/`is_hardware_accel`, `cut_regions` z krotkami numpy `float64`, `export_settings`.
- Zapis: `normalize_layout_for_save` + `sanitize_layout_for_json` → standardowy `json.dump` bez `default=str`.
- Wynik:
  - Zapis zakończony sukcesem bez błędów.
  - Przeładowany JSON zawiera wyłącznie typy standardowe JSON (`dict`, `int`, `str`, `float`, `bool`, `list`).
  - Zgodność 30/30 wskaźników: **100% parytetu** (współrzędne, formularze, rotacje, czcionki, grubości, min/max, ticks, decimals, show_value, źródła danych).
  - Datetime w formacie ISO 8601 (`"2026-09-11T13:04:56.655000+00:00"`).
  - Regiony cięć jako czyste listy float (`[[10.5, 25.0], [120.0, 145.5]]`).
  - Ustawienia eksportu zachowane w 100%.

---

## 5. ARTEFAKTY

Katalog: `H:\_Dev\BikeRideHUD\scratch\strict_json_final_gate\`

- `supported_types.txt` — matryca obsługiwanych typów i potwierdzenie kontraktu
- `unsupported_type_test.txt` — log testów negatywnych (TypeError z dokładną ścieżką)
- `roundtrip_test.txt` — szczegółowy raport z weryfikacji 30 wskaźników
- `test.log` — pełny log wykonania zestawu testów
- `artifacts_manifest.txt` — manifest artefaktów wraz z rozmiarami plików
- `ntfy_result.txt` — wynik wysłania notyfikacji NTFY

---

## 6. NTFY NOTIFICATION

- **Komenda:** `curl.exe -fsS --connect-timeout 5 --max-time 10 -H "Title: BikeRideHUD" -H "Tags: white_check_mark" -d "BikeRideHUD strict JSON final gate: CASE A — STRICT JSON PASS + UNKNOWN TYPES FAIL LOUDLY." "https://ntfy.sh/MalcerzPOP"`
- **Status:** Exit code 0 (sukces w próbie 1)
- **ID wiadomości:** `vKo3IkUBWuA3`
- **Topic:** `MalcerzPOP`

---

## 7. IZOLACJA BACKENDÓW

- **NVIDIA:** Nie zmieniono żadnych plików renderera, enkoderów ani pipelinów NVIDIA.
- **AMD:** Nie dotknięto AMD native D3D11 compositora ani enkoderów AMF.
- **Intel:** Brak zmian.
- **Audio / Telemetria / Mapy:** Bez zmian w mechanizmach obliczeniowych — zmiany dotyczą wyłącznie serializacji JSON w warstwie persystencji.

---

## 8. PODSUMOWANIE KOŃCOWE

```text
TASK:        Domknięcie kontraktu persystencji JSON (usunięcie cichego fallbacku, path-aware TypeError, testy supported/unsupported/roundtrip)
STATUS:      PASS (CASE A — STRICT JSON PASS + UNKNOWN TYPES FAIL LOUDLY)

CHANGED:
  src/indicators/compositor.py           — usunięto cichy fallback str(obj), dodano path-aware TypeError, deterministyczne sortowanie setów, rozszerzono obsługę Qt typów

TESTED:
  scratch/strict_json_final_gate/run_strict_json_final_gate.py — PASS (wszystkie 3 etapy)
  - Supported types (prymitywy, daty, numpy, kolekcje, Qt)
  - Negative tests (TypeError z dokładną ścieżką dla 5 scenariuszy)
  - Real roundtrip (30/30 wskaźników, strict json.dump)

NOT TESTED:
  Interaktywny start GUI z renderowaniem w oknie (środowisko headless)

PERFORMANCE:
  Brak wpływu na wydajność renderera / render loop (funkcja wywoływana tylko przy zapisie projektu/presetu na dysk).

RISKS:
  Brak. Każdy nieobsługiwany typ runtime w payloadzie layoutu jest natychmiast wykrywany ze wskazaniem dokładnej ścieżki w strukturze.

REPORT:
  Raporty/RAPORT_STRICT_JSON_FINAL_GATE.md
```
