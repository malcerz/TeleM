# RAPORT — FIT MERGED DISTANCE / PREVIEW PARITY / DIM FIX

## TASK

Naprawa sklejonego pola FIT `record.distance`, zatrzymanie interpolacji dystansu
na przerwie między segmentami, ujednolicenie danych dystansu pomiędzy Edit
Preview / Export Preview / final render oraz usunięcie ściemnienia z Edit
Preview bez zmiany wyglądu HUD.

## INITIAL STATE

- Branch: `integration/intel-amd`
- HEAD przed zmianami: `59277b4`
- Working tree był i pozostaje dirty. Istniejące zmiany użytkownika zostały
  zachowane; nie wykonano resetu, restore, clean, commita ani push.
- `src/telemetry_resolver.py` uznawał każde większe cofnięcie recorded FIT
  distance za stream nieużyteczny i przechodził w całości na GPS-derived FIT
  `track`.
- `PreviewMixin._build_prepare_cache()` wyliczał FIT `max_distance_m` bezpośrednio
  z `fit_data["track"]`, nawet gdy bieżąca wartość pochodziła z recorded
  `distance`. To było bezpośrednią przyczyną niespójnej/absurdalnej skali Preview.
- `render_preview()` oraz awaryjne ścieżki Edit Preview ściemniały obraz wideo
  niezależnie od aktywnego renderingu. Top-level HUD nad MPV również nakładał
  ciemny prostokąt w zwykłym trybie edycji.

## STRUKTURA 12.fit

Poniższe dane pochodzą z dostarczonej przez użytkownika analizy binarnej. Sam
plik `12.fit` nie był obecny w katalogu załącznika, workspace, `C:\_DEV\TeleM\Video`,
ani przeszukanych katalogach Desktop/Documents/Downloads/Videos, dlatego nie
zostały niezależnie odczytane w tym etapie.

- session: 1
- laps: 2
- LAP 1 start: `2026-09-01 13:07:12 UTC`
- LAP 1 total_distance: `6371.32 m`
- LAP 2 start: `2026-09-01 13:30:24 UTC`
- LAP 2 total_distance: `7777.41 m`
- SESSION total_distance: `14148.73 m`
- suma lapów: `6371.32 + 7777.41 = 14148.73 m`
- ostatni record segmentu 1: `2026-09-01 13:28:03 UTC`, `6371.32 m`
- pierwszy record segmentu 2: `2026-09-01 13:30:24 UTC`, `0.00 m`
- reset recorded distance: `6371.32 -> 0.00 m`
- gap bez rekordów: `141 s`

## ROOT CAUSE

### Cofanie dystansu

Raw cumulative `record.distance` zawiera dwa poprawne lokalnie monotoniczne
segmenty, lecz drugi zaczyna się ponownie od zera. Interpolowanie raw wartości
przez granicę tworzyło sztuczny ruch `6371.32 -> 0.00`. Odrzucenie całego pola
po wykryciu niemonotoniczności usuwało dokładny recorded distance zamiast
naprawić granicę merge.

### Zła skala Preview

Current distance był rozwiązywany przez wspólny resolver, natomiast Edit
Preview pobierał maksimum bezpośrednio z GPS-derived `fit_data["track"]`.
Oznaczało to dwa źródła prawdy (recorded current i track max), a przy błędnej
jednostce/tracku dawało absurdalny zakres oraz marker fraction.

## IMPLEMENTATION

### Kanoniczna normalizacja FIT recorded distance

W `src/telemetry_resolver.py` dodano jedną funkcję
`normalize_fit_recorded_distance()` (linia 105 po zmianie) oraz typ
`NormalizedFitDistance` (linia 56).

Algorytm:

1. Waliduje strukturę, timestampy, liczby finite i nieujemne.
2. Wyraźny reset (`current` dużo mniejsze od `previous`) rozpoczyna nowy segment.
3. Offset zwiększa się o końcową/peak wartość poprzedniego segmentu.
4. Drobne regresje float są zaciskane do poprzedniej wartości i nie tworzą
   resetu.
5. GPS-derived FIT `track` nie jest sumowany z recorded distance; pozostaje
   tylko fallbackiem dla strukturalnie nieużytecznego recorded streamu.

Dla danych 12.fit wynik kontraktowy to:

```text
segment 1: 0.00 -> 6371.32
segment 2: 6371.32 -> 14148.73
normalized_final = 14148.73 m = 14.14873 km
```

Parser zachowuje obecnie `session.total_distance`, lap start/distance oraz
summary normalizacji w `FitRecords` / `FitDataset`. `sync_fit_to_video()`
normalizuje recorded distance raz przy materializacji datasetu i emituje
jednorazową diagnostykę (nigdy per-frame):

```text
[FIT DISTANCE NORMALIZE]
segments=2
resets=1
segment_ends=[6371.32,7777.41]
normalized_final=14148.73
session_total=14148.73
match=True
```

### Gap / interpolacja

Kanoniczny stream przechowuje indeksy początków segmentów.
`src/telemetry_extract.py:1075` oraz vectorized precompute
`src/telemetry_precompute.py:300` używają tych samych granic. Pomiędzy ostatnim
rekordem segmentu 1 a pierwszym rekordem segmentu 2 zwracane jest HOLD LAST
VALUE. Na pierwszym rekordzie segmentu 2 obowiązuje już wartość po dodaniu
offsetu.

Dla testu `6300 -> 6371.32`, gap 141 s, `0 -> 100`:

```text
przed t2: 6371.32
t2:       6371.32
t3:       6471.32
```

Stream i interpolowane wartości nie maleją.

### Jeden distance stream / parity

Kanoniczny resolver jest używany przez:

- wartość bieżącą i dynamiczne FIT indicators,
- Edit Preview range cache,
- Export Preview range cache,
- final renderer i streaming,
- worker cache,
- telemetry precompute (również vectorized),
- auto-range / `max_distance_m`,
- chart/history source tuple w `TelemetryDataManager`,
- slope input tworzony przy ładowaniu FIT.

Test parity celowo dostarcza recorded distance kończący się na `14148.73 m`
oraz absurdalnie inny FIT track. Edit Preview i final-render preparation zwracają
ten sam current distance, ten sam max, ten sam auto min/max i ten sam marker
fraction. Track nie przecieka do skali.

### Edit Preview / Export Preview dim lifecycle

- `render_active=False`: `render_preview()` kopiuje normalny obraz źródłowy i
  nie ściemnia RGB; awaryjne/cut-region ścieżki Edit Preview robią to samo.
- MPV top-level HUD nie nakłada już globalnego ciemnego prostokąta podczas
  zwykłej edycji.
- `render_active=True`: Export Preview nadal może być ściemniony. PIL export
  copy używa dotychczasowego `PREVIEW_VIDEO_BRIGHTNESS = 0.55`; AMD GPU frame
  tap używa własnej kopii `QImage`.
- complete/error/cancel przechodzą przez jedno `_end_render()`: najpierw
  wyłączają render-active (odrzucając queued export frames), czyszczą Export
  Preview pixmap/HUD i przywracają normalny Edit Preview.
- Nie są modyfikowane w miejscu piksele współdzielonego Edit Preview ani klatki
  wejściowej enkodera.

Dokładna wartość QImage dimming (niezmieniona):

```text
plik:     src/gui/qt/tabs/render_tab.py
funkcja:  dim_export_preview_qimage
linia:    54 — EXPORT_PREVIEW_DIM_ALPHA = 24
użycie:   linia 68 — QColor(0, 0, 0, int(alpha))
alpha:    24
percent:  24 / 255 * 100 = 9.4117647% (około 9.41%)
```

PIL Export Preview zachowuje osobny istniejący współczynnik brightness `0.55`
w `src/indicators/helpers.py:28`, czyli redukcję jasności o 45%. Żadna z tych
wartości nie została zwiększona ani zmniejszona.

## „DISTANCE 1 KM”

To nie jest druga wartość telemetryczna. Znak odczytany jako `1` jest pionowym
separatorem `|`. Rzeczywisty title to `DISTANCE | KM`, budowany przez:

```python
title = f"{title} | {unit_title}" if title else unit_title
```

w `src/indicators/bar.py:385` i analogicznej ścieżce `:676`. Separator ani
wygląd HUD nie zostały zmienione. Test `test_distance_retains_title_with_unit_km`
przechodzi.

## CHANGED FILES

- `src/telemetry_resolver.py`
- `src/telemetry_extract.py`
- `telemetry_fit.py`
- `src/gui/telemetry_manager.py`
- `src/gui/qt/_mixins/preview_mixin.py`
- `src/indicators/compositor.py`
- `src/gui/qt/widgets/video_preview.py`
- `src/gui/qt/tabs/render_tab.py`
- `src/telemetry_precompute.py`
- `src/ffmpeg/worker_cache.py`
- `src/ffmpeg/streaming.py`
- `tests/test_fit_merged_distance_preview_parity.py`
- `tests/test_distance_bar_scale_contract.py`
- `tests/test_chart_decimals_preview_dim.py`
- `tests/test_export_preview_video_restore.py`
- `Raporty/RAPORT_FIT_MERGED_DISTANCE_PREVIEW_PARITY_DIM_FIX.md`

Repozytorium zawierało przed zadaniem inne zmiany w części tych plików. Lista
powyżej oznacza pliki dotknięte tym etapem, nie autorstwo całego ich diffu.

## TESTS

### PASS

- Synthetic exact 12.fit contract: 2 segmenty, 1 reset, final `14148.73 m`,
  session match True.
- Monotonicity assertion.
- Gap 141 s HOLD LAST VALUE; scalar i vectorized precompute parity.
- Preview/render: current, max, auto min/max i marker fraction parity.
- Edit Preview bez dimming.
- Export Preview z dimming na owned copy; input QImage/PIL bez mutacji.
- Restore Edit Preview po complete/error/cancel.
- `DISTANCE | KM` title.
- `python -m py_compile` wszystkich zmienionych modułów: PASS.
- Focused suite: `22 passed`.
- Rozszerzony telemetry/cache/GUI suite: `96 passed, 1 skipped`.
- Intel/NVIDIA/backend-neutral regression suite: `18 passed`.
- Dostępny realny `Video/GX010114_116.fit`: 4303 rekordy, recorded distance
  monotonic, final `24231.54 m`, session `24231.54 m`, `match=True`: PASS.
- `git diff --check` dla dotkniętych plików: PASS (wyłącznie ostrzeżenia o
  planowanej konwersji LF/CRLF).

### NOT TESTED

- Bezpośredni parser/normalizacja na realnym `12.fit`: **NOT TESTED — pliku nie
  dostarczono ani nie znaleziono**.
- Krótki realny render obejmujący granicę 12.fit: **NOT TESTED — brak pliku i
  odpowiadającego mu jawnie wskazanego VIDEO/FIT pairing**.
- Pixel comparison final compositor surface: NOT TESTED; etap nie zmienia
  wyglądu HUD, ale nie wykonano realnego renderu 12.fit.
- Długi 85574-frame render: świadomie niewykonany zgodnie z wymaganiem.

### EXISTING OUT-OF-SCOPE FAILURE

`tests/test_distance_bar_scale_contract.py::test_marker_0_percent_at_scale_start`
oczekuje marker x `10 +/- 1`, a istniejący dirty renderer bar zwraca `8`.
Pozostałe 18 testów tego pliku przechodzą. Ten błąd geometrii istniał w
już-zmodyfikowanym `src/indicators/bar.py`, nie wynika z normalizacji ani dim
lifecycle i nie został oportunistycznie naprawiony.

## PERFORMANCE

Nie wykonywano benchmarku ani długiego renderu. Normalizacja wykonywana jest
jednorazowo przy materializacji FIT datasetu; ścieżki per-frame dostają gotowy
kanoniczny stream. Brak zmian w AMD native compositor/encode, NVIDIA i Intel.

## REGRESSIONS / RISKS

- Realne wartości i dokładna struktura `12.fit` nadal wymagają bezpośredniego
  potwierdzenia na pliku użytkownika.
- Reset jest rozpoznawany tylko jako wyraźny spadek do co najwyżej połowy
  poprzedniej wartości, z tolerancją na szum `max(1 m, 0.1%)`. Nietypowy merged
  FIT zaczynający nowy segment od wysokiej wartości może wymagać rozszerzenia
  metadanymi lap/event po uzyskaniu przykładu.
- Istniejący out-of-scope test pozycji markera pozostaje czerwony.

## BACKEND ISOLATION

- Nie zmieniono plików Intel/QSV ani NVIDIA/NVENC/CUDA.
- Zmiany są wyłącznie wspólną warstwą danych FIT i GUI preview lifecycle.
- Testy Intel/NVIDIA: `18 passed`.
- Nie zmieniono AMD native D3D11 compositing, map, charts, gauge ani AMF encode.

## FINAL SUMMARY

```text
IMPLEMENTATION: PASS
SYNTHETIC 12.fit CONTRACT: PASS
AVAILABLE REAL FIT PARSER TEST: PASS
REAL 12.fit TEST: NOT TESTED / BLOCKED — FILE NOT AVAILABLE
PREVIEW/RENDER DISTANCE PARITY: PASS
EDIT/EXPORT DIM LIFECYCLE: PASS
OVERALL: NOT READY (pending real 12.fit validation and existing bar marker failure)
```
