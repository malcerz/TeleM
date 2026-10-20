# AMD Preview/Final parity + Intel telemetry freeze — 2026-10-20

## Zadanie i stan początkowy

- Repozytorium `C:\_DEV\SportCamHUD`, gałąź `main`, HEAD wejściowy `f7e8ca7`. Bez nowych gałęzi/worktree, bez push.
- Zmiany użytkownika zachowane: zmodyfikowany `def_layout.json` (nie commitowany) i wszystkie wcześniejsze pliki nieśledzone (C, raporty Intel, katalogi `C_r31..C_r36`, kopie DLL `*.bak_*`, font).
- Produkcyjna DLL AMD `runtime/amd/bin/telem_amd_native.dll` SHA-256 **BBCA75FBD0DFC5D7CBB61922E92F8D5F049B4305DD18335315667E6E5E54CA5F** — przed pracą, po pracy i w logach każdego smoke (`sha256=` w `[RUNTIME]`). Nie przebudowywana, nie podmieniana.
- Pomocniczo: kopia HEAD przez `git archive` w scratchpadzie (nie worktree) do porównań testów; baseline wydajności AMD uruchomiono w repo, tymczasowo przywracając wyłącznie moje 2 pliki do wersji HEAD (kopie zapasowe, przywrócone po przebiegu, sprawdzone `git diff --stat`).

### Dane (jawnie zadeklarowane pary VIDEO/FIT)

`Video/GX020079.*` z `BENCHMARKS.md` nie istnieje na tej maszynie (jak w poprzednim raporcie). Użyto materiałów użytkownika, którymi zgłoszono błąd — faktyczne finalne eksporty AMD z dzisiaj:

| Scena | Źródło | FIT | Finalny eksport użytkownika | Dowód parowania |
|---|---|---|---|---|
| noc (06:20, HLG) | `F:\GoPro\2026-10-16\GX010380.MP4` (4K) | `2026-10-16_06-22-14.fit` | `D:\GoPro\SCH\20261016-0620.mp4` (14:28, aktualny kod) | kolumna FIT temperatury z cache tego eksportu = STEP tego FIT w **663/663** próbkach |
| dzień (15:30, HLG) | `F:\GoPro\2026-10-12\GX010368.MP4` (8K) | `Afternoon_Ride.fit` | `D:\GoPro\SCH\20261012-1530.mp4` | zgodność **460/479** (reszta: przesunięcie sync) |

Parowanie nie było zgadywane z nazw — potwierdzone danymi z cache render-prep faktycznego eksportu.

---

## CZĘŚĆ A — AMD

### 1. Przyczyna braku części dziesiętnej temperatury w AMD Final

Final AMD nie korzysta z `telemetry_precompute` ani z workera — HUD czyta kolumny z **`RenderPreparationService.build_telemetry_cache_vectorized`** (`src/render_preparation.py`, ścieżka `PRECOMPUTED`, cache dyskowy memmap). Poprzednie poprawki temperatury (f6251ff, c17503e, 03a8603) zmieniły resolver, worker i frame_data, ale **nie ten builder**, a testy parity nie obejmowały go wcale:

1. Pola FIT o strategii `quantized_reconstruct` (temperatura, `garmin_temperature`, napięcie baterii) wpadały w gałąź `else: _vectorize_step(...)` → surowy STEP pełnych stopni Garmina (np. 19.0, 9.0, 15.0), mimo `decimals=1`. Preview (`TelemetryDataManager.resolve_value` → `resolve_current_presentation`) rekonstruuje plateau (19.0 → 18.97, 8.55 …).
2. `columns["temp"]` (`temp_text`) = STEP próbek GPMF niezależnie od skonfigurowanego `source` (FIT/AUTO ignorowane) i bez kanonicznej prezentacji.
3. `std_atemp` = liniowa interpolacja „FIT albo GPX” zamiast kontraktu źródła `atemp_text`.
4. Klucz cache render-prep nie zależał od kontraktu prezentacji → stare kolumny STEP byłyby trafiane (HIT) również po poprawce.
5. (wykryte podczas smoke) Dla eksportu zakresu In/Out builder dostaje oś czasu przyciętą do zakresu (`subset_excluding`). `_interpolate_quantized_change_events` z takim mapperem nie mapuje zdarzeń zmian poza zakresem → wraca do STEP. Preview używa pełnej osi projektu.

Formatowanie nie było winne: `compositor` formatuje `f"{value:.{decimals}f}"` — stąd „15.0”, „9.0” (decimals=1 zachowane, wartość już zaokrąglona do pełnego stopnia). Serializacja do int nie występuje.

**Reprodukcja na eksportach użytkownika** (`repro_fit_temperature.py`, kolumna z cache finalu vs resolver Preview, 400 klatek):

| | rozbieżny tekst | max |diff| | przykład Preview → Final |
|---|---|---|---|
| noc, przed | **381/402** | 0.999 | 13.7 → 14.0, 8.5 → 9.0, 8.9 → 8.0 |
| dzień, przed | **305/401** | 0.993 | 22.9 → 23.0, 19.7 → 20.0 |
| noc, po | **0/402** | 0.0 | — |
| dzień, po | **0/401** | 0.0 | — |

### 2. Przyczyna różnicy jasności/koloru Preview vs Final

**Zakodowany obraz nie jest ciemniejszy.** Różnicę daje interpretacja HLG przez odtwarzacz.

- Preview = libmpv z opcjami SportCamHUD (`mpv_hwdec.build_mpv_options`): HLG→SDR `tone_mapping=bt.2390`, `hdr_compute_peak=no`, `gamut_mapping_mode=relative`, `hdr_contrast_recovery=0`, cel BT.709/gamma2.2, biel 203 cd/m². Zweryfikowane przez `video-target-params` libmpv: wejście `bt.2020 / hlg / full`, wyjście `bt.709 / gamma2.2 / max-luma 203`.
- Final w trybie `preserve_hlg` zostaje HLG (zamierzone, ETAP 5Z.2). Odtwarzacz na ekranie SDR musi sam zrobić tone mapping; stockowe ustawienia (dynamiczna detekcja piku itd.) dają ciemniejszy obraz.

### 3. Dowód: obraz zakodowany vs interpretacja odtwarzacza

**(a) Metadane** — finalny MP4 = źródło:

| | profil | pix_fmt | primaries/transfer/matrix | range | `colr` w kontenerze |
|---|---|---|---|---|---|
| GX010380 źródło | Main 10 | yuv420p10le | bt2020 / arib-std-b67 / bt2020nc | pc | brak (tylko VUI) |
| 20261016-0620 final | Main 10 | yuv420p10le | bt2020 / arib-std-b67 / bt2020nc | pc | `nclx 9/18/9 full_range=1` |
| 20261012-1530 final | Main 10 | yuv420p10le | jw. | pc | `nclx 9/18/9 full_range=1` |

Log AMF: `HEVC Main10 HLG primaries=BT2020 transfer=ARIB_STD_B67 matrix=BT2020NC range=FULL`, `pipeline=HLG_PRESERVE`.

**(b) Wartości kodowe przed wyświetleniem** (`compare_yuv.py`, klatka t=600.6 s, 10-bit Y, obszar bez HUD = bloki 64×64 o średniej |diff| < 12; final jest fizycznie obrócony 180° względem surowego źródła — orientacja wykryta automatycznie, mediana |diff| 3 vs 307):

| scena | pokrycie bez HUD | średnia Y src / fin | śr. różnica (fin−src) | MAE | p1/p50/p99 src | p1/p50/p99 fin |
|---|---|---|---|---|---|---|
| noc | 71.8% | 357.11 / 357.14 | **+0.03** | 4.77 | 66/296/825 | 66/297/823 |
| dzień (8K→4K area) | 73.3% | 464.51 / 464.23 | **−0.27** | 4.35 | 65/432/940 | 65/432/939 |

Pełny zakres 0..1023 zachowany. MAE ~4.5 kodu to szum kompresji HEVC, bez przesunięcia tonalnego. `max_diff` 648/854 to piksele na krawędziach bloków z HUD (bloki maski 64×64) — nie dowód zmiany jasności.

**(c) Ta sama ścieżka wyświetlania** (`display_compare.py`, luminancja 8-bit, ten sam obszar bez HUD, odniesienie = Preview źródła):

| rendering | noc: śr. Y | noc: MAE | dzień: śr. Y | dzień: MAE |
|---|---|---|---|---|
| Preview (libmpv + opcje aplikacji) — **źródło** | 93.98 | 0 | 127.14 | 0 |
| Preview (te same opcje) — **finalny MP4** | **94.03** | **1.55** | **126.72** | **1.31** |
| libplacebo bt.2390 bez detekcji piku (≈ Preview) — final | 99.51 | 7.77 | 128.81 | 8.22 |
| **libplacebo domyślne (typowy odtwarzacz HDR-aware)** — final | **82.20 (−12.5%)** | 12.04 | **106.88 (−15.9%)** | 20.29 |
| final odczytany jako limited range | 94.93 | 6.26 | 127.08 | 6.00 |
| final bez tone mappingu (HLG jako SDR) | 90.33 | 8.13 | 116.78 | 11.68 |

Wniosek: odtworzony tą samą ścieżką co Preview, finalny MP4 jest wizualnie równy Preview (MAE 1.3–1.6 na 255). „Ciemniejszy final” powtarza się dopiero przy innym tone mappingu HLG→SDR (stockowy libplacebo/mpv: −12.5% noc, −16% dzień, p90 180→145 / 244→202). Błąd range (full↔limited) i P010/NV12 wykluczone pomiarem.

**Decyzja:** brak zmian w eksporcie HDR. Psucie HLG lub podbijanie gammy „na oko” byłoby sprzeczne z wymaganiem. Jeśli materiał ma wyglądać jak Preview w dowolnym odtwarzaczu SDR, właściwa jest istniejąca opcja GUI „Konwertuj do SDR (tone mapping)” (`tonemap_sdr`, statyczny BT.2390 HLG→SDR, do którego dostrojono opcje Preview w ETAP 5Z.4). Tej ścieżki nie zmieniano.

Ograniczenie: konkretny odtwarzacz użytkownika (np. Filmy i TV / VLC, ekran HDR/SDR) nie był znany ani mierzony — „libplacebo domyślne” to reprezentatywny model, nie pomiar tego odtwarzacza.

### 4. Poprawka AMD (`src/render_preparation.py`)

- `_vectorize_presentation(...)` — nowy helper: per-klatkowy wywołuje istniejący kanoniczny `resolve_current_presentation` (bez drugiego silnika).
- `build_telemetry_cache_vectorized`:
  - `temp_text` i `atemp_text` (gdy włączone): próbki przez `resolve_samples_from_sources` z tym samym domyślnym `source` co Preview (`frame_data.configured_source`, AUTO) + kanoniczna prezentacja z `decimals` wskaźnika;
  - pola FIT o strategii `quantized_reconstruct` i włączonym wskaźniku → kanoniczna prezentacja zamiast STEP;
  - mapper osi czasu = ten sam co Preview (`telemetry.timeline` / `telemetry.video_timeline`, pełna oś projektu); bez obiektu telemetry (np. MISS w procesie potomnym) — dotychczasowy kontrakt workera;
  - wyłączone wskaźniki zachowują dotychczasowe tanie kolumny (brak konsumenta).
- `compute_cache_key`: `presentation_contract = "quantized_reconstruct_preview_timeline_v2"` — stare cache STEP nie są już trafiane (jednorazowa przebudowa).
- Pola integer-only (HR, kadencja, …), liniowe, bateria monotoniczna, heading, lean, mapa: bez zmian.

### 5. Testy AMD

Nowy `tests/test_amd_final_temperature_parity.py` (11 testów + 2 dowodowe HDR):
- FIT temp final == resolver Preview per klatka i ma część dziesiętną; `decimals=0` → natywny STEP;
- `temp_text` dla `gpmf/fit/auto`: final == Preview, właściwe źródło; zachowany ułamek TMPC;
- integer-only (HR) bez ułamków;
- klucz cache unieważnia stary kontrakt;
- eksport zakresu In/Out: final == Preview z pełną osią projektu (bez poprawki: jedna wartość 18.00);
- final HLG użytkownika: Main10 / arib-std-b67 / bt2020 / bt2020nc / pc (pomijany, gdy plików brak).

Na kodzie HEAD (`git archive`): **9 z nowych testów FAIL** (5 AMD + 4 Intel), po poprawce **wszystkie PASS**.

Kanoniczny harness `SportCamHUD.py --test-amd-export` (direct, HEVC, FAST, 40M, `preserve_hlg`, `def_layout.json` użytkownika, start 600 s):

| przebieg | klatki | render FPS | effective | QP (AMF feedback) | live mux | HLG | finalizacja |
|---|---|---|---|---|---|---|---|
| noc baseline (HEAD) | 1800 | 41.29 | 40.14 | 26.89 (180 próbek) | single_pass_av | HLG_PRESERVE | OK |
| **noc po poprawce** | 1800 | **41.42** | **40.37** | **26.88** (180) | single_pass_av | HLG_PRESERVE | OK |
| dzień baseline (HEAD), źródło 8K | 900 | 19.25 | 18.66 | 27.02 | single_pass_av | HLG_PRESERVE | OK |
| **dzień po poprawce**, źródło 8K | 900 | **19.16** | **18.70** | **27.03** | single_pass_av | HLG_PRESERVE | OK |

Wyniki: MP4 Main10 HLG pc + `colr` nclx, wideo 1800/900 klatek, AAC, A/V 60.060/60.053 s i 30.030/30.037 s.

Uwaga: pierwszy przebieg po poprawce (klucz `v1`) dał plik **bajtowo identyczny** z baseline — tak wykryto problem osi czasu przy eksporcie zakresu (pkt 1.5). Po poprawce v2:
- **Geometria HUD / regresje pikselowe**: porównanie klatek finalu baseline vs poprawka (`hud_diff_regions.py`). Jedyny zmieniony region: noc x 3584–3808, y 1920–1984; dzień y 1792–1856 = wskaźnik `fit_temperature_text`. Reszta HUD i wideo bez zmian: Y MAE całej klatki 0.18–1.12, czyli szum ponownego kodowania VBR.
- Treść: noc t=40 s „9.0 C” → **„8.5 C”** (Preview 8.547); dzień t=20 s „15.0 C” → **„14.8 C”**. Wycinki: `amd_smoke/temp_widget_baseline_vs_patched_t40.png`, `amd_smoke/day_temp_widget_baseline_vs_patched_t20.png` (lokalnie, `*.png` w `.gitignore`).

### 6. AMD QP / VBR / finalizacja

Nie zmieniono: DLL, C++, AMF/QP, VBR/VBV/HRD (`rc=VBR target=40M peak=60M` w logu identyczne), presetów, HEVC/HLG, live mux (`aac_pipe_copy`, single pass, audio z oryginalnego MP4), finalizacji, GPU Pitch, mapy. Nie dodano `ensure_audio_cache` ani końcowego muxowania. QP feedback działa (`[AMF QP] statistics feedback ... surface_flag=ON`, QP avg 26.88 vs 26.89).

---

## CZĘŚĆ B — Intel

### 7. Przyczyna freeze kompasu i przechyłu

`export_intel_native_d3d11` działa **w procesie GUI** i buduje cache klatek przez `telemetry_precompute.build_telemetry_cache` **przed** startem workerów HUD. Ten builder pobiera heading (kompas) przez `_resolve_cache_samples("heading", src)`, a roll IMU (przechył) przez `_worker_lean_roll` — oba czytają globalny `WORKER_CACHE`. Eksporter Intel nie inicjalizował `WORKER_CACHE` w swoim procesie (AMD robi to przez `init_worker` przed buildem). Skutek:
- w świeżym procesie `field_samples` puste → kompas = `None`, przechył = `None` dla **każdej** klatki → widżety stoją; workery dostają ten gotowy cache (`lookup`) i nie liczą wartości same;
- w długo żyjącym GUI `WORKER_CACHE` mógł zawierać dane poprzedniego projektu (np. po `RenderPreparationService`, które ustawia `WORKER_CACHE["field_samples"]`), a `_worker_lean_roll` cache'ował oś roll (także pustą) bez powiązania ze źródłem → stary przechył z innego projektu lub trwale pusty.

Dowód sprzętowy z wcześniejszych logów Intel (`storage_temperature_20261020/intel_queue_verified.log`): `[HUD PREP LEAN] stage=lean_vectorize ... frames=60 elapsed_ms=0.32` — za szybko na obliczenie osi roll z 200 Hz IMU całego klipu, zgodne z pustym źródłem. Test logiczny: `test_uninitialised_worker_cache_freezes_compass_and_lean` — wszystkie klatki `None`.

### 8. Przyczyna błędnej skali wysokości

`alt_text` w layoucie: `form=bar`, `auto_scale=True`, `source=fit`, ręczne `0..1000 m`. Intel używa pełnego płótna (`hud_regions=None`) → gałąź `else` w `frame_renderer.render_overlay_frame`, która **jako jedyna nie przekazywała `auto_ranges`** do `compose_overlay`. Pozostałe ścieżki i Preview przekazują. Bez `auto_ranges` i przy `min_alt/max_alt=None` (Intel `_range_cache` ma tylko dystans) compositor zostawia ręczną skalę 0..1000 m. Stąd „okolice 1000 m” / zła skala na Intelu. Cache zawiera poprawne `auto_ranges` (na AMD np. `alt_text (11.6, 96.8)`).

### 9. Poprawka Intel

- `src/ffmpeg/intel_native_exporter.py`: `_hud_init_args(telemetry_cache)` (jedna definicja argumentów), a **przed** `build_telemetry_cache`: `init_worker(*_hud_init_args(None), skip_chart_build=True)` — ten sam wzorzec co AMD. Workery dostają `init_args = _hud_init_args(telemetry_cache)` — identyczna krotka jak wcześniej.
- `src/ffmpeg/worker_cache.py`: `_worker_lean_roll` wiąże cache osi roll z bieżącym obiektem `field_samples` (zmiana obiektu = nowe obliczenie); `init_worker` usuwa stan poprzedniego eksportu (`_lean_roll`, `_lean_roll_source`, `_prev_frame_data`, `_prev_atlas_img`).
- `src/ffmpeg/frame_renderer.py`: gałąź pełnego płótna przekazuje `auto_ranges=data.get("auto_ranges")`.

Nie zmieniono: Intel QSV/flush, QP, VBR, dekodera, wyboru urządzenia, DLL Intel, NVIDIA, audio.

### 10. Testy/walidacja Intel (bez sprzętu Intel)

`tests/test_intel_telemetry_freeze.py` (6 testów, PASS; na HEAD 4 FAIL):
- reprodukcja: niezainicjowany `WORKER_CACHE` → kompas i lean `None` we wszystkich klatkach;
- po inicjalizacji: >100 różnych wartości kompasu i przechyłu na 300 klatek, sąsiednie klatki różne;
- kontrakt kolejności w eksporterze: `init_worker` przed `build_telemetry_cache`;
- cache roll związany z `field_samples` (pusty pierwszy wynik nie zatruwa kolejnych; inny projekt = inna oś);
- `init_worker` czyści stan poprzedniego eksportu;
- gałąź pełnego płótna przekazuje `auto_ranges['alt_text'] = (100.0, 109.5)` zamiast 0..1000.

### 11. Co wymaga realnego testu na Intelu (NOT TESTED)

- `--test-intel-export --intel-path native` na Core Ultra, scena dzienna: kompas i przechył zmieniają się klatka po klatce w MP4; skala wysokości = zakres aktywności;
- czas `[HUD PREP LEAN]` (powinien wzrosnąć do realnego obliczenia osi roll) i ewentualny wpływ na start eksportu;
- dwa kolejne eksporty różnych projektów w jednym GUI (brak przenoszenia danych);
- wydajność Intel FPS przed/po. Wywołanie `init_worker` w procesie GUI jest jednorazowe (bez budowy wykresów), ale nie było mierzone na Intelu.

**Status Intel: poprawka przygotowana i zwalidowana logicznie — pełny PASS NOT PROVEN bez sprzętu Intel.**

---

## Wymagania ogólne

### Harness

`--test-amd-export` był zepsuty na HEAD: `AttributeError: 'RenderTab' object has no attribute 'chk_compression_analysis'` (checkbox usunięty w 98848d7), a harness zawisał z otwartym GUI (`harness_chk_compression_analysis_hang.log`). Minimalna poprawka tylko w gałęzi testowej `application.py` (guard `hasattr`), osobny commit. Dwa inne miejsca z tym atrybutem (harnessy `--test-b/-c` i startup) nie były używane i zostały bez zmian — do późniejszego zadania.

### 12. Wydajność

- Render AMD (pętla klatek): bez zmian — kolumny są nadal czytane z memmap. Noc 41.29 → 41.42 FPS, dzień (8K) 19.25 → 19.16 FPS (szum pomiaru).
- Przygotowanie render-prep (jednorazowe, w tle GUI, potem HIT z dysku): pełny film 64 288 klatek z osią projektu **0.70 s → 4.36 s** (+3.7 s; ok. 0.2% czasu 30-minutowego eksportu). Koszt to kanoniczny resolver per klatka dla 2 włączonych wskaźników temperatury. Nie optymalizowano resolvera — to współdzielony kod Preview, poza zakresem.
- Intel: NOT MEASURED.

### Testy zbiorcze

Jednoprocesowy `pytest tests` zawiesza się na wcześniej istniejących testach (`test_export_lifecycle_p1_fixes.py`, `test_render_progress_single_source.py` — TIMEOUT także na HEAD), a `test_auto_telemetry_source_order.py` ma błąd kolekcji (`TelemetryOrchestrator` nie istnieje). Dlatego uruchomiono każdy z 319 plików osobno (limit 90 s), na kodzie po poprawce i na HEAD (`git archive`):

| | passed | failed | errors | skipped |
|---|---|---|---|---|
| po poprawce | 2523 | 140 | 9 | 83 |
| HEAD (kopia archiwum + 2 nowe pliki testów) | 2498 | 153 | 18 | 86 |

Plików testów z większą liczbą FAIL/ERROR po poprawce niż na HEAD: **0** (`pytest_per_file_patched.tsv`, `pytest_per_file_head_archive.tsv`). 140 wcześniej istniejących FAIL dotyczy obszarów niezmienianych (GUI, NVIDIA/Intel etap testy, solar, DJI…). Nie były naprawiane (zakres). Różnice na korzyść poprawki wynikają z nowych testów oraz braku nieśledzonych zasobów w kopii archiwum (np. `test_text_unit_offsets`), nie z regresji.

`pyflakes` zmienionych plików: tylko wcześniej istniejące ostrzeżenia (nieużywane importy, `Sequence` w `render_preparation`). `git diff --check` PASS.

### Izolacja backendów i ryzyka

- `render_preparation.py` jest używany wyłącznie przez AMD (`render_mixin` dla `amd`, `amd_native_exporter`).
- `worker_cache.init_worker`/`_worker_lean_roll`: wspólne. AMD/NVIDIA wołają `init_worker` w świeżych procesach potomnych, więc czyszczenie stanu jest dla nich no-op; regresja AMD sprawdzona smoke.
- `frame_renderer` gałąź `else` (pełne płótno): Intel native i ogólna ścieżka FFmpeg/CPU bez atlasu. Gałąź direct-region NVIDIA (`_nvidia_direct_region`) **nie** została zmieniona, choć również nie przekazuje `auto_ranges` — do osobnego zadania NVIDIA.
- Ryzyka:
  - jeśli cache AMD zostanie zbudowany w procesie potomnym (MISS bez obiektu telemetry), mapper wraca do osi zakresu (stary kontrakt workera): poprawna precyzja, ale możliwy STEP przy zdarzeniach poza zakresem In/Out. Normalnie cache buduje GUI (rodzic), a child trafia HIT (potwierdzone w logach smoke);
  - ten sam problem osi zakresu istnieje w `telemetry_precompute`/workerze (Intel/CPU) dla eksportów In/Out — udokumentowany, nie zmieniany.

## Commity i git status

- `74ec340` fix(amd): render final temperature through the Preview presentation contract
- `e1d45fa` fix(intel): resolve compass, lean and altitude scale per export
- `7700407` test(harness): tolerate removed QP diagnostics checkbox in AMD export harness
- commit dokumentacyjny z tym raportem i dowodami `Raporty/amd_parity_intel_freeze_20261020/` (skrypty, JSON, logi; MP4/PNG lokalnie, wykluczone `.gitignore`)

Bez push. `git status` po commitach: zmodyfikowany tylko `def_layout.json` użytkownika. Wszystkie wcześniejsze pliki nieśledzone zachowane.

## Podsumowanie PASS/FAIL

| kryterium | status |
|---|---|
| AMD: temperatura Final = Preview (wartość + decimals), noc i dzień | **PASS** (0/402, 0/401 rozbieżności; smoke: 8.5 C / 14.8 C) |
| AMD: wybór źródła FIT/GPMF/AUTO zgodny z Preview | **PASS** (testy) |
| AMD: jasność — przyczyna ustalona, zakodowany obraz = źródło | **PASS** (diagnoza); zmiana eksportu nie była potrzebna |
| AMD: QP, VBR, live mux, finalizacja, HLG, DLL SHA | **PASS** (smoke noc+dzień) |
| AMD: wydajność render | **PASS** (41.29 → 41.42 / 19.25 → 19.16 FPS); prep +3.7 s jednorazowo |
| AMD: geometria HUD | **PASS** (jedyny zmieniony region = wskaźnik temperatury) |
| Intel: przyczyna freeze kompasu/lean i skali wysokości | ustalona, poprawka + testy logiczne **PASS** |
| Intel: sprzęt (Core Ultra) | **NOT TESTED** — pełny PASS Intela NOT PROVEN |
| Konkretny zewnętrzny odtwarzacz użytkownika | **NOT TESTED** (model libplacebo) |
