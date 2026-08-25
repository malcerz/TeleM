# RAPORT — BAR Ruler: tick contract + property/preview parity

**Etap:** 10Y (BAR RULER TICK CONTRACT + PREVIEW PARITY)
**Data:** 2026-08-23
**Baseline:** ETAP 10X (`RAPORT_INDICATORS_ETAP_10X_BAR_DISTANCE_SCALE_FIX.md`) — naprawa `auto_scale` NIE cofnięta, matematyka markera NIE zmieniona.
**Zakres:** kontrakt ticków BAR Ruler (`major_ticks`/`major_step`/`minor_ticks`/legacy `ticks`) + spójność jednostek i effective range w preview/render. **Bez zmian** pipeline'ów AMD/NVIDIA/Intel, FFmpeg, synchronizacji, telemetrii, map, GPU compositing.

---

## 1. Skąd pochodził `major_step`

`major_step` pojawiał się z **dwóch źródeł**:
1. **Ukryta imputacja w rendererze** — `src/indicators/bar.py::_render_ruler`:
   ```python
   major_step = cfg.get("major_step")
   if major_step is None:
       if unit_str == "km" or "distance" in lbl_str or "dist" in lbl_str:
           major_step = 1.0
       elif unit_str in ("°c","c","degc") or "temperature" in lbl_str or "temp" in lbl_str:
           major_step = 1.0
   ```
   Czyli dla każdego BAR-a o jednostce km/temp renderer **sam dokładał** `major_step=1.0`, nawet jeśli nie było go w configu.
2. **Tworzenie wskaźnika** — `indicator_mixin._create_indicator` ustawiał `defaults["major_step"] = 1.0` dla pól FIT temp/dystans.

W Property Editor BAR Ruler **nie ma pola `major_step`** (schema `_bar_ruler_fields` pokazuje tylko `major_ticks`/`minor_ticks`/`ticks`) — był to **ukryty, aktywny parametr**.

## 2. Dlaczego `major_ticks` z GUI było ignorowane

Renderer:
```python
if major_step is not None and float(major_step) > 0 and abs(val_max - val_min) > 0:
    major_divisions = max(1, int(round(range / major_step)))   # tryb STEP
else:
    major_divisions = max(1, int(cfg.get("major_ticks", ticks if ticks > 0 else 8)))  # tryb COUNT
```
Ponieważ `major_step=1.0` było albo imputowane, albo zapisane przy tworzeniu, tryb STEP był aktywny i `major_ticks` **nigdy** nie było brane pod uwagę (GUI edytuje pole, które jest ignorowane).

## 3. Dokładny kontrakt ticków (po zmianie)

| Parametr | Warunek | Znaczenie |
|---|---|---|
| `major_step` | `> 0`, JAWNIE w configu | **Tryb STEP** — główna podziałka co `major_step` jednostek (`major_divisions = round(range/major_step)`); `major_ticks` ignorowane. |
| `major_step` | `<= 0` lub brak | **Tryb COUNT** — `major_ticks` = liczba głównych przedziałów na całej skali. |
| `major_ticks` | zawsze (w COUNT) | liczba głównych podziałek (fallback `ticks if ticks > 0 else 8`). |
| `minor_ticks` | zawsze | liczba drobnych podziałek między głównymi (`total = major * minor`; główny co `minor`-ty tick). |
| `ticks` | legacy | nadal wspierany jako fallback `major_ticks` w trybie COUNT (stare projekty). |

Przykłady (testy): `major_ticks=8, minor_ticks=4` → 33 ticki, 9 głównych; `major_step=2` (zakres 0–24) → podziałka co 2 km niezależnie od `major_ticks`.

## 4. Czy zmieniono canonical defaults

- `major_step` w `models.py` ma nadal `default=0.0` (tryb COUNT) — **bez zmiany**.
- `major_ticks` default `8`, `minor_ticks` default `5` — **bez zmiany**.
- `_create_indicator` **przestał** wpisywać `major_step=1.0` do configu (usunięte) — nowy Ruler nie ma ukrytego STEP.
- Renderer **przestał imputować** `major_step` dla km/temp — `major_ticks` działa od razu.

## 5. Jak zachowano stare projekty z `major_step`

Stare projekty, które **jawnie zapisały** `major_step > 0` (świadomy tryb STEP), zachowują tryb STEP — renderer nadal honoruje jawny `major_step`. Stare projekty **bez** `major_step` (dotąd w trybie STEP przez imputację) przechodzą na tryb COUNT z `major_ticks`/`ticks` — to celowa zmiana zgodna z kontraktem GUI (migracja bez masowego zapisu; nic nie jest nadpisywane w pliku).

## 6. Dlaczego „Property Preview" pokazywał np. 10129 km

Przyczyna: `src/gui/telemetry_manager.py::register_fit_fields` tworzył konfigurację dynamicznego pola FIT `fit_distance_text` z:
```python
max_val = max(vals)   # metry! np. 10129.14
unit   = meta.get("unit") or ""   # "m"
```
Czyli zakres zapisywany był w **metrach** bez konwersji `/1000`. Gdy taki wskaźnik był renderowany (a jednostka ustawiona na „km" lub przez natywny „m" wyświetlany obok wartości w km), etykiety zakresu pokazywały `0 km / 5065 km / 10129 km`, a marker stał przy 0% (wartość `11.9 km` na skali `10129`). W „głównym preview" (compose_overlay z `auto_scale`) skala była poprawna (km), stąd rozjazd dwóch podglądów.

## 7. Gdzie następował błąd jednostek m → km

- `register_fit_fields` (telemetry_manager.py) — `max_val`/`min_val` w metrach bez `/1000` (główne źródło).
- `_create_indicator` — dla `fit_distance_text` ustawiał `unit="m"` (z katalogu FIT) przy skali liczonej w km → niespójność jednostki i zakresu.
- `dist_visual`/`dist_text` (GPMF) — brak wymuszenia `unit="km"` (etykiety bez jednostki).

## 8. Jak teraz liczony jest effective range

- **AUTO** (`auto_scale=True`): `effective max = max_distance_m / 1000.0` (compose_overlay) — 10129.14 m → **10.129 km**, nigdy 10129 km.
- **MANUAL**: `effective max = config max_val` (w km dzięki poprawce rejestracji/creation).
- Dystans FIT/GPMF: konfiguracja tworzona/uzupełniana z `unit="km"` i zakresem w km.

## 9. Czy Property Preview korzysta ze wspólnej logiki z Main Preview

W GUI **nie istnieje osobny widget „Property Preview"** — jedynym podglądem jest wspólny main preview (`preview_mixin._render_preview`) oraz HUD preview Render (oba przez ten sam `compose_overlay`). Rozjazd „10129 vs 24 km" pochodził z **złego stanu konfiguracji** (metry w `max_val`), a nie z drugiego algorytmu. Po poprawce configu wszystkie ścieżki (main preview, HUD preview, final render, bbox measure) widzą ten sam zakres w km. Nie duplikowano logiki AUTO — poprawiono źródło danych (config).

## 10. Czy `auto_scale` wpływa teraz wyłącznie na zakres

Tak. `auto_scale` (ETAP 10X) nadal steruje tylko `min_val/max_val`. Konfiguracja ticków (`major_ticks`/`minor_ticks`) jest niezależna i działa zarówno przy manual, jak i przy auto (test TEST 5: `auto_scale=True` + `major_ticks` 8→16 zmienia ticki, nie zmienia zakresu).

## 11. Live editing major/minor ticks

- Zmiana `major_ticks` N→N+1 zmienia **tylko liczbę głównych podziałek** (raster ticków), nie zmienia `min/max/unit/source` ani pozycji markera (TEST 9).
- Zmiana `minor_ticks` M→M+1 zmienia liczbę drobnych podziałek (TEST 4).
- `_on_property_changed` zapisuje tylko zmienione pole; `_render_preview` odświeża; brak „przeskoków" innych właściwości.

## 12. Zmienione pliki i funkcje

| Plik | Funkcja / miejsce | Zmiana |
|---|---|---|
| `src/indicators/bar.py` | `_render_ruler` | Usunięta imputacja `major_step` dla km/temp; jednoznaczny kontrakt COUNT/STEP. |
| `src/gui/telemetry_manager.py` | `register_fit_fields` | Dystans FIT: `max/min /1000` + `unit="km"`. |
| `src/gui/qt/_mixins/indicator_mixin.py` | `_create_indicator`, `_get_indicator_range` | Usunięty ukryty `major_step`; `unit="km"` dla dystansu FIT i GPMF; obsługa `dist_visual` w zakresie. |
| `tests/test_bar_ruler_tick_contract.py` | nowy plik | Testy 1–9 (12 testów). |

## 13. Dodane testy

`tests/test_bar_ruler_tick_contract.py`:
- TEST 1 — COUNT: `major_ticks=8` → 33 ticki / 9 głównych; 16 → 65.
- TEST 2 — STEP: jawny `major_step` (2 vs 3) zmienia ticki; `major_step=2` ignoruje `major_ticks`; `major_step=0` ≡ brak.
- TEST 3 — brak ukrytego `major_step` w nowych Rulerach; `major_ticks` działa bez `major_step`.
- TEST 4 — `minor_ticks` (4→8) zmienia ticki.
- TEST 5 — `auto_scale` zmienia zakres, nie ticki.
- TEST 6 — manual + ticki (0–3, 6 podziałów, marker 50%).
- TEST 7 — konwersja m→km (10129.14 m → 10.129 km; marker na końcu dla pełnego dystansu).
- TEST 8 — parity preview/render (ten sam config → ten sam marker; config nie mutowany).
- TEST 9 — live change `major_ticks` zmienia ticki, marker bez zmian.

## 14. Wyniki wszystkich testów

- `test_bar_ruler_tick_contract.py` → **12 passed**.
- `test_etap10n3`/`test_etap10n2`/`test_distance_optimization`/`test_bar_integration`/`test_distance_bar_scale_contract`/`test_etap10k_fit_gui`/`test_etap10k3_fit_speed`/`test_pixel_indicator_style`/`test_slope_rendering`/`test_etap10t2_segment_gui_hardening`/`test_indicator_config_parity` → **171 passed**.
- `test_render_tab`/`mp4_inspector`/`qp_analyzer`/`indicator_drag`/`font_selection`/`text_size_compatibility`/`track_up_map`/`etap10m2`/`solar_pct`/`etap6b` → **98 passed**.
- `get_errors` na zmienionych plikach → brak błędów.
- Pre-existing (niezwiązane, potwierdzone wcześniej): `test_fit_registration.py` (brak modułu), `test_static_indicator_cache` slope, `test_etap8m3`/`test_etap8m7`.

## 15. Czy ETAP 10X nadal przechodzi bez regresji

Tak — `auto_scale` gating w `compositor.py` niezmieniony; `test_distance_bar_scale_contract.py` (TEST 1–8 z 10X) przechodzi w całości (11 testów), a `test_etap10n3_distance_marker.py` (6) także.

## 16. Czy preview/final rendering mają parity

Tak. Preview (main i HUD) oraz final render (CPU/AMD/NVIDIA/Intel) przechodzą przez ten sam `compose_overlay` z tym samym configiem. Poprawka dotyczy źródła configu (km), więc wszystkie ścieżki widzą identyczny effective range, jednostki i ticki (TEST 8).

## 17. Czy dotknięto AMD/NVIDIA/Intel

**Nie.** Zmiany w `src/indicators/bar.py` (wspólny renderer), `telemetry_manager.py` i `indicator_mixin.py` — żadnego z pipeline'ów GPU ani `command_builder` (bbox/regions NVIDIA/AMD) nie ruszano. NVIDIA path preserved statically; runtime validation nie była możliwa na tej maszynie (AMD).

## 18. Co sprawdzić ręcznie w GUI

1. Dodaj BAR dystansu → zakładka **Ticks**: zmiana `major_ticks` (np. 8→16) natychmiast zmienia liczbę głównych podziałek; `minor_ticks` (4→8) zmienia drobne.
2. Włącz **Auto skala** → zakres zmienia się do pełnego dystansu, ale `major_ticks`/`minor_ticks` nadal działają.
3. `fit_distance_text` → jednostka **km** i zakres w km (nie „10129 km").
4. `dist_visual`/`dist_text` (GPMF) → jednostka **km**.
5. Stary projekt z jawnym `major_step` → nadal tryb STEP (krok); bez `major_step` → COUNT z `major_ticks`.
6. Marker zgodny z effective scale (0–3 manual, pełny dystans auto) — bez zmian względem 10X.

---

## Podsumowanie (AGENTS.md)

### Changed
`src/indicators/bar.py` (kontrakt ticków), `src/gui/telemetry_manager.py` (rejestracja FIT w km), `src/gui/qt/_mixins/indicator_mixin.py` (unit km + brak ukrytego major_step + zakres dist_visual), nowy `tests/test_bar_ruler_tick_contract.py`.

### Preserved
- `auto_scale` gating (10X), matematyka markera, min/max w kompozytorze — bez zmian.
- Pipeline'y AMD/NVIDIA/Intel, `command_builder` (bbox/regions), FFmpeg, telemetria, mapy, GPU compositing — bez zmian.
- Legacy `ticks`, stary `major_step>0` (tryb STEP) — zachowane.

### Tested
12 (nowe) + 171 + 98 passed; brak regresji 10X (test_distance_bar_scale_contract + test_etap10n3).

### Not tested
Pełny eksport GPU na sprzęcie; NVIDIA preserved statically (maszyna AMD).

### Risks / Remaining issues
- Stare projekty z dystansowym `max_val` zapisanym w **metrach** (sprzed 10Y/10X) przy `auto_scale=False` pokażą złą skalę — wymagają `auto_scale=True` lub poprawy `max_val` (odnotowano też w 10X).
- `major_step` pozostaje w schemacie gauge/chart (`_ticks_tab_fields`, default 0) — ich renderery go nie używają (osobny, poza zakresem).
- Pre-existing failures: `test_fit_registration.py`, `test_static_indicator_cache` (slope), `test_etap8m3`, `test_etap8m7`.
