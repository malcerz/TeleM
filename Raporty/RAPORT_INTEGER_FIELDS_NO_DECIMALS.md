# RAPORT: Prezentacja Całkowitoliczbowa (Integer Fields, No Decimals)

## 1. Cel zadania
Wymuszenie stałej prezentacji całkowitoliczbowej (0 miejsc po przecinku, brak separatora dziesiętnego `.` lub `,`) dla semantycznych pól telemetrycznych:
- `heart_rate` (np. `87.0 -> 87`, `87.4 -> 87`, `87.6 -> 88`)
- `cadence` (np. `81.0 -> 81`, `81.7 -> 82`)
- `power` / `curVpower` (np. `254.0 -> 254`, `254.6 -> 255`)
- `ISO` (np. `100.0 -> 100`)
- `exposure` (np. `247.0 -> 247` prezentowane w czasie naświetlania jako `1/247`)

Oraz:
- Usunięcie / ukrycie kontrolki miejsc po przecinku (`decimals` / `decimal_places`) w GUI Property Editor dla wskaźników tych pól.
- Zachowanie pełnej precyzji zmiennoprzecinkowej (`float`) wewnątrz silnika (dane RAW, `telemetry_resolver`, interpolacja, plany telemetryczne).
- Zapewnienie wstecznej kompatybilności layoutów (stare wartości `decimals: 1` lub `2` są ignorowane/normalizowane do 0, a nowe zapisy layoutu nie zawierają zbędnego klucza `decimals` dla tych wskaźników).
- Zachowanie kontroli precyzji dla pozostałych pól: Garmin Battery (2 miejsca), temperatura (1 miejsce), prędkość/dystans/wysokość (0..2 konfigurowalne).

---

## 2. Stan początkowy
- Niektóre wskaźniki (np. `hr_text`, `cad_text`, `power_text`, `iso_text`) posiadały w schemacie formularza GUI kontrolkę `decimals`, co pozwalało użytkownikowi ustawić wartości `1` lub `2`.
- W starych plikach layoutu mogły znajdować się klucze `"decimals": 1` lub `2`.
- Wskaźnik `exposure_text` stosował obcięcie `int(value)` zamiast standardowego zaokrąglenia `int(round(float(value)))`.

---

## 3. Zmodyfikowane pliki
1. `src/telemetry_resolver.py`:
   - Zdefiniowano zbiór `INTEGER_ONLY_FIELDS = frozenset({"heart_rate", "hr", "cadence", "cad", "power", "curvpower", "iso", "exposure"})`.
   - Wprowadzono funkcję semantycznej detekcji `is_integer_only_field(field_or_key, cfg=None) -> bool`.
   - Zaktualizowano `presentation_default_precision(field, cfg)` oraz `resolve_presentation_precision(config, default=0, field=None)` aby bezwzględnie zwracały `0` dla pól integer-only.
2. `src/indicators/helpers.py`:
   - Przekazano parametr `field=field` do `resolve_presentation_precision`.
3. `src/indicators/compositor.py`:
   - Przekazano `field=key` do `resolve_presentation_precision(current_cfg, default_decimals, field=key)`.
   - Poprawiono formatowanie `exposure_text` na bezpieczne zaokrąglanie `int(round(float(value)))`.
4. `src/indicators/chart.py`:
   - Przekazano `field=key` do `resolve_decimal_places(cfg, legacy_decimal_default, field=key)`.
5. `src/gui/qt/models.py`:
   - `indicator_default_decimals`: zwraca `0` dla pól integer.
   - `get_schema_for_indicator`: filtruje i pomija pola `decimals` oraz `decimal_places` dla pól integer-only.
   - `normalize_indicator_decimal_defaults`: usuwa zbędne klucze `decimals` i `decimal_places` ze wskaźników integer-only w zapisywanych layoutach.
6. `src/gui/qt/_mixins/indicator_mixin.py` & `src/gui/qt/_mixins/preset_mixin.py`:
   - Przekazywanie `cfg=cfg` do `get_schema_for_indicator` oraz aktualizacja schematu GUI przy zmianie właściwości `field`.
7. `tests/test_gopro_battery_iso_decimal_ui.py`:
   - Zaktualizowano asercje dla integer ISO schema i normalizacji layoutu.
8. `tests/test_integer_fields_presentation.py`:
   - Nowy kompletny zestaw testów automatycznych (33 testy) weryfikujący wszystkie wymagania.

---

## 4. Dokładna implementacja
- **Zasada działania:** Funkcja `is_integer_only_field` sprawdza zarówno nazwę klucza wskaźnika (`hr_text`, `iso_text`), postać kanoniczną (`hr`, `cad`, `power`, `iso`, `exposure`), jak i atrybut konfiguracji `cfg.get("field")`. Dzięki temu dowolny nowo utworzony wskaźnik przypisany do danego pola semantycznego automatycznie staje się integer-only.
- **Precyzja wewnętrzna:** Żadne obliczenia interpolacyjne ani próbki źródłowe nie zostały przekonwertowane na `int`. Formatowanie do wartości całkowitej następuje wyłącznie na granicy prezentacji / renderingu tekstu HUD.

---

## 5. Wyniki testów

### 5.1. Testy jednostkowe i regresyjne
Uruchomiono pakiety testów:
- `tests/test_integer_fields_presentation.py` (33 passed)
- `tests/test_gopro_battery_iso_decimal_ui.py` (10 passed)
- `tests/test_presentation_architecture.py` (34 passed)
- `tests/test_chart_decimals_preview_dim.py` (9 passed)

Łącznie: **86 passed, 0 failed**.

### 5.2. Zweryfikowane przypadki brzegowe
1. **Prezentacja wartości (Exact Rounding):**
   - HR: `87.0 -> 87`, `87.4 -> 87`, `87.6 -> 88` (PASS, brak kropki/przecinka)
   - Cadence: `81.0 -> 81`, `81.7 -> 82` (PASS)
   - Power: `254.0 -> 254`, `254.6 -> 255` (PASS)
   - ISO: `100.0 -> 100` (PASS)
   - Exposure: `247.0 -> 1/247` (PASS)
2. **GUI Property Editor:**
   - Wskaźniki HR, Cadence, Power, ISO, Exposure nie posiadają pola `decimals` w schemacie (PASS).
   - Pola Garmin Battery (2), Temperature (1), Speed (0..2), Distance (0..2), Altitude (0..2) zachowują kontrolkę `decimals` (PASS).
3. **Kompatybilność wsteczna layoutów:**
   - Stary JSON z `"decimals": 1` dla HR/Cadence/Power/ISO/Exposure jest interpretowany jako integer (PASS).
   - `normalize_indicator_decimal_defaults` usuwa zbędny klucz przy zapisie (PASS).

---

## 6. Izolacja backendów i brak regresji
- Zmiany są w 100% backend-neutralne (warstwa `telemetry_resolver`, `gui/qt/models`, `compositor`).
- Żadne elementy potoków kodowania AMD AMF, NVIDIA NVENC ani Intel QSV nie zostały zmodyfikowane.
- Geometria HUD, model baterii, oś czasu oraz renderer nie uległy zmianom.

---

## 7. Artefakty zadania
Katalog: `scratch/integer_fields_no_decimals/`
- `field_policy.txt` (SHA256: `e909f5f93dede2aad595caa480337882b2b482c86897e21e00bc7f1077a72a7a`)
- `gui_test.txt` (SHA256: `8fb441db7729b5239f4686ed2dcd57502593af7f262caade38961d51abb79978`)
- `layout_compatibility_test.txt` (SHA256: `a94978312cb21359a78f85cfe6dc15b89dffe1dc136782cc867cde680ef8de07`)
- `presentation_test.txt` (SHA256: `a32deb2070c197a1780f1fd5b65048bce01d649700d137ae94614ad06869be86`)
- `test.log` (SHA256: `7b933a0640f9bef759400fd29cd23e141ca8e8386d39606135bdc9acdcdd0b13`)
- `artifacts_manifest.txt`
- `ntfy_result.txt` (id: `E7OPXys0Ryz5`)

---

## 8. Podsumowanie i kwalifikacja wyniku
Wynik: **CASE A — INTEGER FIELDS + GUI CLEANUP PASS**
- Wartości prezentowane dla HR, Cadence, Power, ISO i Exposure są zawsze całkowite bez separatora dziesiętnego.
- Kontrolki precyzji w GUI dla tych pól zostały usunięte.
- Pozostałe pola zachowują wsparcie dla miejsc po przecinku.
- Pełna kompatybilność wsteczna ze starymi layoutami została zachowana.
