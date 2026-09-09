# RAPORT — REAL 12.FIT DISTANCE FINAL VALIDATION

## TASK

Końcowa walidacja rzeczywistego, sklejonego FIT przez produkcyjną ścieżkę
TeleM, potwierdzenie parity Edit Preview / Export Preview / final preparation,
krótki render na jawnie wskazanych plikach wideo, finalizacja kontraktu markera
BAR min/mid/max oraz sprawdzenie lifecycle przyciemnienia Export Preview.

## INITIAL STATE

- Branch: `integration/intel-amd`
- HEAD: `59277b4`
- Working tree był i pozostaje dirty. Wszystkie wcześniejsze zmiany użytkownika
  zachowano.
- Nie wykonano `reset`, `restore`, `clean`, rebase, commita ani push.
- Implementacja normalizacji i preview lifecycle pochodzi z poprzedniego etapu,
  opisanego w `Raporty/RAPORT_FIT_MERGED_DISTANCE_PREVIEW_PARITY_DIM_FIX.md`.
- W tym etapie nie zmieniono kodu produkcyjnego ani wyglądu HUD. Dodano realny
  test integracyjny i poprawiono błędne, historycznie zahardkodowane oczekiwania
  testów geometrii markera.

## REAL FILES

Po doprecyzowaniu przez użytkownika użyto bez kopiowania do repozytorium:

```text
D:\GoPro\2026-09-01\12.fit
D:\GoPro\2026-09-01\12_naprawiony.fit
```

SHA-256:

```text
12.fit:
5D69B51F816F7A8E2AAD06A43AC2931FAEBF8A411DAB0505BEBC09E1920F2B19

12_naprawiony.fit:
DD31BDB6D0C845A2729564CBC13B3481C8C3D803723EEE1A29F78AB0BC18E1DE
```

## REAL 12.FIT — RAW BINARY DATA

Odczyt bezpośrednio z binarnego FIT przez `fitparse`, bez synthetic substitute:

```text
session count:            1
lap count:                2
record.distance samples:  2775

session.total_distance:   14148.73 m
lap 1 total_distance:      6371.32 m
lap 2 total_distance:      7777.41 m
lap sum:                  14148.73 m

lap 1 start: 2026-09-01 13:07:12 UTC
lap 2 start: 2026-09-01 13:30:24 UTC

first record.distance: 2026-09-01 13:07:12, 0.00 m
last record.distance:  2026-09-01 13:55:46, 7777.41 m
```

Jedyny rzeczywisty spadek/reset:

```text
segment 1 end:   2026-09-01 13:28:03, 6371.32 m
segment 2 start: 2026-09-01 13:30:24,    0.00 m raw
gap:             141 s
reset:           6371.32 -> 0.00 m
```

Wcześniejsze wartości zostały w całości potwierdzone przez realny plik.

## PRODUCTION PARSER / NORMALIZATION / RESOLVER

Rzeczywisty plik przeszedł przez:

```text
12.fit binary
-> telemetry_fit.parse_fit()
-> telemetry_fit.sync_fit_to_video() / FitDataset
-> normalize_fit_recorded_distance()
-> resolve_distance_samples("fit")
```

Wynik diagnostyki produkcyjnej:

```text
[FIT DISTANCE NORMALIZE]
segments=2
resets=1
segment_ends=[6371.32,7777.41]
normalized_final=14148.73
session_total=14148.73
match=True
```

- `segment_start_indices = (1252,)`
- normalized stream ma 2775 próbek.
- Stream resolvera jest tym samym kanonicznym obiektem co
  `FitDataset["distance"]`; GPS-derived `track` nie zastąpił recorded distance.
- Monotonicity: PASS dla wszystkich kolejnych próbek.

`12_naprawiony.fit` ma te same timestampy i już naprawiony recorded stream:

```text
segments=1
resets=0
normalized_final=14148.73
session_total=14148.73
match=True
```

Porównanie kanonicznego wyniku oryginału z `12_naprawiony.fit`:

```text
samples:          2775 / 2775
same timestamps:  True
max abs diff:     1.8189894035458565e-12 m
different >1e-9: 0
```

## REAL GAP PROBES

Wartości z `interpolate_distance()` na kanonicznym streamie oryginalnego
`12.fit`:

| Probe UTC | Znaczenie | Distance |
|---|---|---:|
| 13:28:02 | tuż przed końcem segmentu 1 | 6371.32 m |
| 13:29:13.500 | środek gapu | 6371.32 m |
| 13:30:23.999999 | tuż przed segmentem 2 | 6371.32 m |
| 13:30:24 | pierwszy raw record segmentu 2 | 6371.32 m |
| 13:30:29 | 5 s po starcie segmentu 2 | 6371.32 m |
| 13:30:45 | pierwszy późniejszy ruch (`raw=1.17`) | 6372.49 m |

Scalar interpolation i vectorized final precompute zwróciły identyczne
wartości. Dla środka gapu GPS-derived FIT track dawał `6162.512092640667 m`,
podczas gdy resolver poprawnie utrzymał `6371.32 m`, co potwierdza brak skoku
na alternatywny track.

## EDIT / EXPORT / FINAL PREPARATION PARITY

Test realnego datasetu zbudował niezależne cache dokładnie sposobami używanymi
przez:

- Edit Preview: `PreviewMixin._build_prepare_cache()`;
- Export Preview: `RenderTab._build_hud_prepare_cache()`;
- final render preparation: `build_activity_range_cache()` + wspólne
  `prepare_overlay_frame_data()`.

Porównano początek, gap, dokładną granicę segmentu 2, pierwszy ruch po granicy
i koniec aktywności. Dla wszystkich timestampów trzy ścieżki miały identyczne:

```text
current_distance
max_distance_m = 14148.73 m
min_val        = 0.0 km
max_val        = 14.14873 km
marker fraction
```

Nie wystąpił zakres rzędu tysięcy kilometrów. Konwersja metr -> km odbywa się
raz na granicy display/auto-range.

## SHORT REAL VIDEO BOUNDARY RENDER

Użytkownik jawnie wskazał pairing, więc nie był on zgadywany:

```text
D:\GoPro\2026-09-01\GX010244.MP4
D:\GoPro\2026-09-01\GX010245.MP4
D:\GoPro\2026-09-01\12.fit
```

Czasy źródeł:

```text
GX010244 start: 2026-09-01 13:07:20.504363 UTC
duration:       1383.849133 s
end:            2026-09-01 13:30:24.353496 UTC

GX010245 start: 2026-09-01 13:31:20.714923 UTC
duration:       1471.470000 s
```

Smoke obejmował ostatnie 2 s klipu 244 i pierwsze 2 s klipu 245. Użyto widgetu
`fit_distance_text` z realnego `GX010244.layout.json`, 1920x1080,
30000/1001 fps, produkcyjnego AMD D3D11VA/native HUD/AMF oraz jawnych
production-defaults z `BENCHMARKS.md`.

```text
RENDER PATH: AMD_NATIVE_D3D11
decode:      D3D11VA GPU
HUD:         amd_native
encode:      AMF
fallback:    none
source switch: frame 60
frames:      120 / 120
duration:    4.004 s
codec:       HEVC 1920x1080 30000/1001
file size:   6,944,845 bytes
```

Artefakt:

```text
scratch/real12_boundary_validation/real12_boundary_244_245_4s.mp4
```

Klatki kontrolne przed/po source switch pokazały odpowiednio `6.4 km` i
`6.5 km`, stały zakres `0.0 / 7.1 / 14.1 km` oraz marker bez cofnięcia do zera.
`DISTANCE | KM` pozostało bez zmian; użyty font powoduje, że pionowa kreska może
wizualnie przypominać cyfrę `1`, ale tekst i separator są prawidłowe.

Nie wykonano pełnego 85574-frame renderu.

## BAR MARKER ROOT CAUSE AND FINAL CONTRACT

Renderer nie miał błędnego przesunięcia markera. Błąd był w testach z
zahardkodowanym `pad_x=10`:

- test powstał 2026-08-23;
- responsywna formuła `pad_x` weszła później, 2026-08-29 w `7e4e34e`;
- aktualny `pad_x` zależy od rozdzielczości, `marker_size` i supersamplingu.

Dla testu zgłoszonego w zadaniu (1280x720, `marker_size=7`, SS=1):

```text
scale:               720 / 1080 = 0.6666667
track width:         358 px
marker radius:       5 px
marker border width: 1 px
pad_x:               max(5 + round(4*0.6667), round(8*0.6667)) = 8 px
marker min/mid/max:  8 / 187 / 366 px
useful scale pixels: 8 .. 367 (końcowy stroke ma 1 px szerokości poza centrum)
```

Dla produkcyjnego v10 (`marker_size=6`):

```text
marker radius:       4 px
pad_x:               7 px
marker min/mid/max:  7 / 186 / 365 px
useful scale pixels: 7 .. 366
```

Border i shadow są rysowane wokół obliczonego centrum i nie zmieniają centroidu
koloru fill markera. Crop/raster zachowuje centrum oraz pełny użyteczny span.
Testy sprawdzają teraz bezpośrednio piksele osi, min, midpoint, max, clamp,
compositor crop oraz SS=1/2/3. Usunięto stałą `10`; nie przesunięto całego bara.

Geometria produkcyjna przed/po etapie jest identyczna. Ponieważ w tym etapie
nie zmieniono kodu produkcyjnego renderera, nie ma zmiany pikseli HUD do
porównania; poprawiony został kontrakt testowy, a nie obraz.

## DIMMING LIFECYCLE

`EXPORT_PREVIEW_DIM_ALPHA` pozostało dokładnie `24`:

```text
24 / 255 = 0.0941176471 = 9.41176471%
```

Test QImage potwierdza:

- Edit Preview (`render_active=False`): 0% export dimming;
- rendering (`render_active=True`): dokładnie alpha 24 na owned copy;
- wejście `(200,100,50,255)` -> Export Preview `(181,91,45,255)`;
- źródłowy QImage pozostaje `(200,100,50,255)`;
- complete / failed / cancelled: `_rendering=False`, pixmap Export Preview
  wyczyszczony, powrót do Edit Preview bez export dimming.

## CHANGED FILES — THIS FINAL VALIDATION STAGE

- `tests/test_real_12fit_distance.py` — opt-in real-binary integration suite;
- `tests/test_distance_bar_scale_contract.py` — pikselowy kontrakt osi i
  min/mid/max + supersampling;
- `tests/test_etap10n2_distance_marker.py` — usunięcie starego `pad_x=10`;
- `tests/test_etap10n3_distance_marker.py` — usunięcie starego `pad_x=10`;
- `tests/test_export_preview_video_restore.py` — dokładne alpha/RGB dimming;
- `Raporty/RAPORT_REAL_12FIT_DISTANCE_FINAL_VALIDATION.md`.

Artefakty testowe:

- `scratch/real12_boundary_validation/real12_boundary_244_245_4s.mp4`;
- `scratch/real12_boundary_validation/real12_boundary_244_245_4s.mp4.amd_profile.json`;
- `scratch/real12_boundary_validation/before_switch.png`;
- `scratch/real12_boundary_validation/after_switch.png`.

## TESTS

### PASS

- Real FIT opt-in suite: `5 passed`.
- Focused real FIT + distance + marker + dim + title suite: `64 passed`.
- Wszystkie distance marker suites: `34 passed`.
- Dimming + `DISTANCE | KM`: `20 passed`.
- Intel/NVIDIA isolation suite: `26 passed`.
- Rozszerzony telemetry/bar/preview suite: `194 passed, 2 skipped`; wszystkie
  testy w zakresie tego zadania przeszły.
- `py_compile` zmienionych/istotnych modułów i testów: PASS.
- `git diff --check` dla zmienionych plików: PASS; tylko informacyjne
  ostrzeżenia Git o przyszłej konwersji LF/CRLF.
- Krótki realny AMD boundary render: `120/120`, ffprobe PASS, wizualny smoke PASS.

### EXISTING OUT-OF-SCOPE FAILURES

Rozszerzony zestaw ujawnia 5 niezwiązanych failów istniejącego dirty tree:

```text
tests/test_bar_orientation_contract.py: 4 FAIL
tests/test_preview_range_markers_removal.py: 1 FAIL
```

Dotyczą orientation/slope layout i historycznego napisu cut-region, nie FIT
distance, poziomego markera dystansu ani dim lifecycle. Nie zostały naprawione,
zgodnie z zakazem rozszerzania zakresu i wykonywania nowych optymalizacji.

Ponadto `tests/test_fit_registration.py` ma niezależny błąd kolekcji, ponieważ
importuje nieistniejący `src.gui.hud_tuner_app`. Został wyłączony z powtórzonego
zestawu po udokumentowaniu błędu.

### NOT TESTED / NOT PROVEN

- Pełny 85574-frame render: świadomie NOT TESTED zgodnie z wymaganiem.
- Formalne pixel-reference A/B finalnego HEVC: NOT PROVEN — brak wskazanego
  golden reference dla tych klipów; wykonano realny visual boundary smoke.
- Cały dirty repository suite nie jest green z powodu pięciu powyższych,
  niezwiązanych failów oraz jednego błędu kolekcji.

## PERFORMANCE

To był correctness smoke, nie porównawczy benchmark:

```text
HUD prepare:   0.722 s
video encode:  1.799 s
finalize:      0.110 s
total:         2.751 s
Render FPS:    66.690
Effective FPS: 43.622
```

Nie należy porównywać tych liczb z kanonicznym pełnym layoutem/4K workloadem.

## REGRESSIONS / RISKS

- Normalizacja wykrywa jednoznaczne duże resety; nietypowy merge zaczynający
  kolejny segment od wysokiej wartości nadal może wymagać dodatkowych reguł.
- Opt-in test realnego FIT wymaga ustawienia `TELEM_REAL_12_FIT`; opcjonalne
  porównanie pliku naprawionego wymaga `TELEM_REAL_12_FIXED_FIT`.
- Pięć niezwiązanych regresji dirty tree pozostaje do osobnego zadania.

## BACKEND ISOLATION

- Nie zmieniono Intel/QSV, NVIDIA/NVENC/CUDA ani AMD native production code.
- AMD GPU map/charts/gauge defaults nie zostały ruszone.
- Intel/NVIDIA tests: `26 passed`.
- Krótki render użył AMD Native D3D11 bez fallbacku.

## FINAL SUMMARY

```text
REAL 12.fit PARSER:                 PASS
REAL NORMALIZATION:                PASS
REAL FINAL / SESSION MATCH:        PASS
REAL MONOTONICITY:                 PASS
REAL GAP HOLD-LAST:                PASS
EDIT / EXPORT / FINAL DATA PARITY: PASS
REAL MAX BAR RANGE:                PASS (0.0 .. 14.14873 km)
BAR MARKER MIN / MID / MAX:        PASS
EDIT / EXPORT DIM LIFECYCLE:       PASS
SHORT REAL BOUNDARY RENDER:        PASS (120/120)
BACKEND ISOLATION:                 PASS

TASK STATUS: READY
WHOLE DIRTY TREE: NOT FULLY GREEN (documented out-of-scope failures)
```
