# RAPORT: ETAP 10K3 — BUGFIX: Brak FIT Speed / Enhanced Speed w GUI

**Data wykonania:** 2026-08-22  
**Autor:** Antigravity  
**Stan:** **FIT SPEED DISCOVERY: FIXED**

---

## 1. Root Cause Analysis

### Przyczyna źródłowa (Root Cause)
W module `telemetry_fit.py` wewnątrz pętli parsowania pól komunikatów `record`:
1. Pola `enhanced_speed` oraz `enhanced_altitude` były przechwytywane przez gałąź:
   ```python
   elif fname in ("enhanced_speed", "speed") and speed_ms is None:
       speed_ms = f.value
   elif fname in ("enhanced_altitude", "altitude") and alt is None:
       alt = f.value
   ```
2. Ponieważ dopasowanie następowało w gałęzi `elif`, wykonanie **nie przechodziło** do ogólnej gałęzi `elif fname not in _EXCLUDED_FIELDS:`.
3. W rezultacie:
   - `enhanced_speed` i `enhanced_altitude` **nie były dodawane** do słownika `scalar_fields` ani do `field_metadata`.
   - Pola te nie trafiały do `FitRecords.field_catalog` ani do `FitDataset.field_catalog`.
   - Zbudowany rekord `rec` posiadał jedynie legacy klucze `rec["speed"]` i `rec["alt"]`.
4. W warstwie GUI (`src/gui/qt/_mixins/indicator_mixin.py` w metodzie `_discover_data_streams()`):
   Pętla dynamicznego odkrywania pól FIT celowo pomijała klucze `("speed", "alt", ...)`, zakładając, że są one obsługiwane osobno. Ponieważ `enhanced_speed` nie istniało w `tm.fit_data`, a `speed` było pomijane, użytkownik nie widział żadnego przycisku prędkości ani wysokości z pliku FIT.

---

## 2. Identyfikowalność w całym potoku (Full Pipeline Trace)

| Stage | enhanced_speed present? | Stan po naprawie |
|---|---|---|
| **FIT record parser** | **TAK** (4293 rekordy w pliku FIT) | **TAK** (4293 rekordy `enhanced_speed`, 12.69 m/s max) |
| **FitRecords** | **NIE** (pomijane przez gałąź `elif`) | **TAK** (`records.field_catalog["enhanced_speed"]` obecne) |
| **FitDataset** | **NIE** (brak w `field_keys`) | **TAK** (`fit_data["enhanced_speed"]` zsynchronizowane) |
| **field_catalog** | **NIE** (brak metadanych) | **TAK** (`display_name="Speed (FIT)"`, `unit="km/h"`) |
| **resolve_samples** | **NIE** (`fit_data.get("enhanced_speed")` brak) | **TAK** (zwraca próbki z `source="fit"`) |
| **GUI discovery** | **NIE** (brak w liście strumieni) | **TAK** (`DataStream(key="fit_enhanced_speed_text", ...)`) |
| **GUI button** | **NIE** (przycisk nie generował się) | **TAK** (widoczny przycisk `Speed (FIT)`) |
| **created indicator** | **NIE** (tworzenie uszkodzone) | **TAK** (`source="fit"`, `field="enhanced_speed"`, `form="gauge"`) |
| **rendered value** | **NIE** / fallback | **TAK** (prawidłowo interpolowana prędkość w km/h) |

---

## 3. Statystyki parsera dla `enhanced_speed`

Bezpośredni odczyt z `telemetry_fit.parse_fit("Video/Jazda_na_rowerze_w_porze_lunchu.fit")`:
- **Nazwa pola FIT:** `enhanced_speed`
- **Liczba próbek:** `4293`
- **Jednostka w pliku FIT:** `m/s`
- **Wartość minimalna:** `0.0 m/s` (`0.0 km/h`)
- **Wartość maksymalna:** `12.69 m/s` (`45.684 km/h`)
- **Skalowanie w TeleM:** Przeliczane automatycznie przez mnożnik `3.6` na `km/h`.
  - Przykład testowy: `4.5 m/s` $\times 3.6 =$ `16.2 km/h`.

---

## 4. Inwentaryzacja standardowych pól FIT w pliku testowym

Wszystkie standardowe pola liczbowe z komunikatów `record` w badanym pliku FIT:

| Pole FIT | Typ pola | Liczba próbek | Jednostka surowa | Jednostka TeleM | GUI Discovery Status |
|---|---|---:|---|---|---|
| **`enhanced_speed`** | Standard | 4293 | `m/s` | `km/h` | **Eksponowane jako `Speed (FIT)` (`gauge`)** |
| **`enhanced_altitude`** | Standard | 4299 | `m` | `m` | **Eksponowane jako `Altitude (FIT)` (`bar`)** |
| **`distance`** | Standard | 4299 | `m` | `m` | **Eksponowane jako `Distance (FIT)` (`bar`)** |
| **`heart_rate`** | Standard | 4299 | `bpm` | `bpm` | **Eksponowane jako `Heart Rate (FIT)` (`chart`)** |
| **`cadence`** | Standard | 4273 | `rpm` | `rpm` | **Eksponowane jako `Cadence (FIT)` (`chart`)** |
| **`fractional_cadence`** | Standard | 4273 | `rpm` | `rpm` | **Eksponowane jako `Fractional Cadence (FIT)` (`chart`)** |
| **`temperature`** | Standard | 4299 | `C` | `°C` | **Eksponowane jako `Temperature (FIT)` (`text`)** |
| `position_lat` | Standard | 4287 | `semicircles` | `deg` | Celowo mapowane na GPS Track / Mapę |
| `position_long` | Standard | 4287 | `semicircles` | `deg` | Celowo mapowane na GPS Track / Mapę |
| `timestamp` | Standard | 4299 | `datetime` | `datetime` | Celowo używane jako oś czasu |
| `unknown_107..144` | Standard | 2971–4299 | `None` | - | Wykluczone (`_EXCLUDED_FIELDS`) — pola diagnostyczne Garmina |

---

## 5. Czy `enhanced_altitude` również było dotknięte?

**TAK.** `enhanced_altitude` było traktowane identycznie w module `telemetry_fit.py` (wartość wpisywana do `rec["alt"]`, ale pole `enhanced_altitude` nie trafiało do `scalar_fields` ani `field_metadata`).

Zastosowana poprawka generic pipeline naprawiła **zarówno `enhanced_speed`, jak i `enhanced_altitude`**.

---

## 6. Wprowadzone zmiany (Minimal Fix)

1. **`telemetry_fit.py`**:
   - W gałęzi `elif fname in ("enhanced_speed", "speed"):` oraz `elif fname in ("enhanced_altitude", "altitude"):` dodano rejestrację do `scalar_fields` oraz utworzenie metadanych w `field_metadata`.
   - `enhanced_speed` i `speed` otrzymują jednostkę `km/h` oraz etykietę `Speed (FIT)`.
   - `enhanced_altitude` i `altitude` otrzymują jednostkę `m` oraz etykietę `Altitude (FIT)`.
2. **`src/gui/qt/_mixins/indicator_mixin.py`**:
   - W `_discover_data_streams()` odblokowano strumienie `enhanced_speed` i `enhanced_altitude`.
   - Dodano deduplikację aliasów: jeśli obecne jest `enhanced_speed`, pomijany jest redundantny surowy alias `speed`; jeśli obecne jest `enhanced_altitude`, pomijany jest surowy `alt`.
   - W `_create_indicator()` zapewniono czytelne domyślne etykiety (`label="Speed"`, `label="Altitude"`) oraz jednostki.

---

## 7. Testy i weryfikacja

### A. Jednoczesne współistnienie FIT + GPMF (Simultaneous Coexistence)
- **GPMF Speed:** `key="speed_text"`, `source="gpmf"`, `field="speed"`.
- **FIT Speed:** `key="fit_enhanced_speed_text"`, `source="fit"`, `field="enhanced_speed"`.
- Oba wskaźniki mogą znajdować się jednocześnie na jednym layoutcie, każdy pobiera i interpoluje dane ze swojego niezależnego strumienia.
- Zapis i odczyt z pliku JSON (`Save / Reload`) w 100% zachowuje ich odrębne tożsamości źródłowe.

### B. Wyniki automatycznych testów regresyjnych
Uruchomiono zestaw testów:
```bash
python -m pytest tests/test_etap10k3_fit_speed.py tests/test_etap10k2_acceptance.py tests/test_etap10k_fit_gui.py
```
**Wynik:** **`21 passed in 32.73s`** (100% PASS):
- `tests/test_etap10k3_fit_speed.py`: 6 passed
- `tests/test_etap10k2_acceptance.py`: 8 passed
- `tests/test_etap10k_fit_gui.py`: 7 passed

---

## 8. Zmienione pliki

- [telemetry_fit.py](file:///c:/_DEV/TeleM/telemetry_fit.py) — włączenie `enhanced_speed`, `speed`, `enhanced_altitude`, `altitude` do katalogu pól FIT i słownika skalarnych próbek.
- [src/gui/qt/_mixins/indicator_mixin.py](file:///c:/_DEV/TeleM/src/gui/qt/_mixins/indicator_mixin.py) — ekspozycja strumieni `enhanced_speed` i `enhanced_altitude` w odkrywaniu strumieni GUI oraz domyślne konfiguracje wskaźników.
- [tests/test_etap10k3_fit_speed.py](file:///c:/_DEV/TeleM/tests/test_etap10k3_fit_speed.py) — dedykowany zestaw testów regresyjnych dla inwentaryzacji standardowych pól FIT, współistnienia GPMF+FIT oraz serializacji layoutu.
