# SPORTCAMHUD — ETAP 5O: Bar cache ownership i kontrakt ROSE

Data: 2026-10-13, Europe/Warsaw. Repo: `C:\_DEV\BikeRideHUD-main-new`.

**STATUS: PARTIAL / PERFORMANCE NOT PROVEN.** Naprawiono izolację publicznych obrazów Bar i zaktualizowano test finalnego rastra ROSE. Pierwotna grupa 5N: **186 passed, 0 failed, 0 skipped**; końcowy zestaw z trzema nowymi testami: **189 passed, 0 failed, 0 skipped**. Bramka „bez regresji FPS” nie została zamknięta. Nie powstały commity 5O ani push. Nie deklarujemy utrzymania 40 FPS ani pełnego bezpieczeństwa produkcyjnego.

## 1. Git i ochrona stanu

- Przeczytano AGENTS.md, BENCHMARKS.md, raporty 5M/5N i aktualne źródła. Jawna gałąź oraz VIDEO/FIT użytkownika mają pierwszeństwo przed historycznymi domyślnymi benchmarkami.
- Gałąź `fix/gui-freeze-hud-composite`; HEAD przed i po: `8465744675c5e75b1ce19a6edde7792ee6da7adc`.
- Tag `amd-known-good-40fps-20261012` pozostaje przy e7582d8e2c212990987380ee10e5980f2dfd5867. Annotated tag object: `8feaa2f78af38ac60fa9713eabe2090564ec4fde`.
- Zastana zmiana `def_layout.json` oraz nieśledzone raporty/artifacts zachowane. Nie wykonano reset/clean/stash/rebase/merge/push ani synchronizacji portable. Nie dodawano plików do indexu.
- SHA256 `def_layout.json`: `8375ca40ba3670dd52de765eb91642082c9097a8fbc12dbe7fa1d1203ffa4440` — bez zmiany.
- SHA256 `src/indicators/gauge.py`: `2d8b408aa80a5ff98cfe1f44afd4a9b4730bd5f70153849bfa8c4f6142e55fca` — bez zmiany.
- SHA256 eksportera AMD: `0598bc640b6ba46ae261dc08fb444461791820e0a32777a83c2a0aea99c7dd43` — bez zmiany.
- DLL AMD ABI9 SHA256 `7f93c483404f970ea4e2110dcfe12535429b25b11df7415b688c07cef508752f` — bez zmiany. Nie zmieniono kodeka, QP, bitrate, konfiguracji AMD ani natywnych ścieżek.

## 2. Przyczyna defektu i miejsca współdzielenia

`_render_bar_indicator` zwracał Image znajdujący się w `_BAR_INDICATOR_CACHE`; zmiana pikseli przez caller uszkadzała przyszły hit. Dodatkowa warstwa `WidgetRenderCache.get_or_render` przechowywała i zwracała ten sam wynik wraz z metadanymi, również bez izolacji producer/caller. Kopiowanie tylko pierwszej warstwy nie chroniłoby publicznego wyniku po efekcie: `apply_indicator_effects` potrafi zwrócić własny cached raster.

| Konsument / operacja | Własność i weryfikacja |
|---|---|
| Publiczny Bar; re-eksport `src.overlay_renderer` i `src.indicators`; segment_bar adapter | Caller-owned mały tile. Mutacja wyniku nie wpływa na cache. |
| Publiczny dispatcher / autoplacement / command_builder | Bar po wszystkich efektach jest caller-owned. Obsłużony także pozycyjny cfg_override. |
| Publiczny WidgetRenderCache | Snapshot wejścia przy miss oraz osobny wynik przy miss/hit; głęboka kopia metadata i Image.info. |
| Compositor / render_preview / HUD editor przez compositor | Jawny borrowed Bar; źródło czytane. Oddzielny canvas HUD jest celem paste. |
| Effects | Czyta getchannel/np.array ze źródła, buduje oddzielny destination; cached styled tile tylko read-only w compositorze. |
| rotated_paste, crop, resize, rotate | Zmienia base_img (canvas); przekształcenia źródła tworzą wynik, nie edytują cached Bar. |
| AMD producer/consumer i capture | Utrzymywane Python references do tile; cache eviction/clear nie unieważnia Image. Kolejne wartości nie malują w poprzednim cached tile. |
| Intel/NVIDIA wspólny compositor | To samo read-only użycie; backendy/FFmpeg/QSV/NVENC niezmienione. Hardware eksportów Intel/NVIDIA: NOT TESTED. |
| Testy i skrypty | Wszystkie dotychczasowe publiczne importy zachowane. Nowe testy celowo mutują wyłącznie owned wyniki. |

W ruler dynamic canvas powstaje przez copy statycznej bazy; segmenty również tworzą odrębny out_img. `Image.paste`/putalpha po publicznej granicy są dozwolone; te same operacje na borrowed źródle są zabronione kontraktem. Borrowed nie jest runtime-enforced immutable typem — zaufanie ograniczono do audytowanych wewnętrznych konsumentów.

## 3. Wprowadzony kontrakt ownership

- `bar.py`: pierwotny renderer zachowany jako `_render_bar_indicator_borrowed`; publiczna oryginalna sygnatura `_render_bar_indicator` tworzy owned tile. Logika rasteryzacji bez zmian.
- `raster_ownership.py`: mała granica kopii Image, głęboka kopia Image.info/metadata i licznik payloadu kopii. Publiczna kopia nie zachowuje `_dynamic_key`, aby edycja Image nie dawała starego cache hit efektów po podpisie immutable źródła.
- `widget_cache.py`: publiczne `get_or_render` izoluje producer i caller; jawne `get_or_render_borrowed` dla immutable producerów bez kopiowania. Domyślny AMD_CPU_WIDGET_CACHE=1, supported renderers i sesyjny getter bez zmian.
- `dispatcher.py`: publiczny Bar owned także po efektach; osobne `render_value_indicator_borrowed` dla compositora. Inne formy zachowują dotychczasową własność. Nie wyłączono cache.
- `compositor.py`: używa jawnego borrowed wejścia. Brak nowej kopii całego HUD 4K.

## 4. Testy Bar i parity

Nowy `tests/test_bar_cache_ownership.py`: trzy testy, rozbudowane macierze wewnątrz testów:

1. 24 konfiguracje: 960x540/3840x2160 × horizontal ruler/vertical ruler/segments × ss1/ss2 × Arial/Consolas. A25→B75→A25, mutacje output miss/hit i Image.info, zachowanie input cfg. Bit-exact porównanie z rzeczywistym Bar z HEAD 5N (`git show`) przed i po shadow/fade/outline. To test repozytoryjny wymagający historii Git i dostępnych fontów Windows.
2. Widget cache: mutacja producer Image, nested Image.info, input/output metadata, miss/hit, dwóch niezależnych consumers. 2 hits / 1 miss; cache pozostaje czysty.
3. Dispatcher: owned final styled Bar; dwa kolory i obie formy; output putalpha nie narusza borrowed; dwie kolejne kompozycje HUD 4K identyczne; licznik kopii nie zmienia się podczas compose. Held borrowed raster nie zmienia się po innej wartości i cache clear/reset. Pozycyjny cfg_override również izolowany.

Dla porównywanych rastrów Bar raw/styled: **max_diff=0, MAE=0, different_pixels=0**. A→B→A PASS; brak pozostawania B w ponownym A. Istniejące GUI/cache/shadow/outline/parity/cancel/finalization testy pozostają aktywne. Nie usunięto testów, nie dodano skip/xfail ani osłabionych sprawdzeń rastera.

## 5. Kontrakt testu ROSE

Stary test obserwował ImageDraw.text podczas budowania tarczy 0°, przed OpenCV transformacją, i wymagał upright letters. Zgodnie z decyzją użytkownika cała tarcza oraz N/E/S/W obracają się; wskazówka jest nieruchoma. **gauge.py nie zmieniono.**

`test_rose_final_raster_rotates_cardinals_and_keeps_needle_fixed` zastępuje glyphy parami nierównych, niesymetrycznych znaczników o unikalnych kolorach. Pozycję i oś każdego znacznika mierzy wyłącznie na finalnym rasterze. Sprawdza analityczny obrót dla 0/30/90/180/270/359/1/360°, fixed needle mask bit-exact, identyczne 0/360 i ciągłość przejścia. Tolerancja 1.1px dotyczy środka znacznika po interpolacji rastra, nie globalnej dopuszczalnej różnicy obrazu. Brak OCR. Finalny test ROSE izoluje geometrię bez cieni; cienie pokrywa istniejąca grupa oraz pełne eksporty.

## 6. Pełna grupa regresyjna

- Pierwotna grupa 20 plików 5N: **186 passed in 28.53s**, log `etap5o_artifacts/suite186.log`.
- Nowe ownership testy początkowo: **3 passed in 1.41s**, log `ownership_tests.log`.
- Po uzupełnieniu pozycyjnego override / held raster: dokładnie te same 20 plików + ownership file, **189 passed in 33.72s**, 0 failed/0 skipped, `final_suite189.log`.
- `git diff --check`: PASS. Nie uruchamiano całego dowolnego zbioru tests/; wynik 189 dotyczy jawnej grupy 5N+5O.

Lista 20 plików: test_etap5f_bar_cache_and_immutability, test_cache_and_parity_validation, test_generic_widget_cache, test_gui_freeze_dummy_cache_safety, test_gui_bar_drag_hotfix, test_render_tab, test_render_tab_controls_cleanup, test_compass_rendering, test_compass_source_parity_hotfix, test_amd_direct_mp4_mux, test_render_cancel_process_lifecycle, test_export_finalization_lifecycle, test_compass_and_shadow_outline, test_effects_percent_amd_parity, test_bar_integration, test_bar_orientation_contract, test_controller_properties, test_amd_benchmark_governance, test_export_queue_lifecycle, test_amd_native_ordered_map_clear (wszystkie w tests/, rozszerzenie .py).

## 7. Dokładny workload A/B

Kanoniczny CLI `SportCamHUD.py --test-amd-export --mode direct`; VIDEO `D:\Comparator\GX010345.MP4`, jawnie wskazany FIT `C:\Users\Malcerz\AppData\Local\SportCamHUD\remote_telemetry\garmin\24621925414.fit`. 1500 klatek od120s, 3840x2160, pełny HUD i cienie, HEVC FAST QP28, bitrate45M, Single Live Mux. Identyczne pliki `Raporty/etap5m_artifacts/layout_needle.json` / `layout_rose.json` jak 5N. Brak AMD_* override; QT_QPA_PLATFORM=offscreen. Testy/mikrobenchmark nie działały jednocześnie z eksportami.

Pierwsze BEFORE wykonano na HEAD przed jakąkolwiek poprawką. Następnie AFTER. Ponieważ wynik FPS się obniżył, wykonano naprzemienne A/B: AFTER NEEDLE, BEFORE NEEDLE, BEFORE ROSE, AFTER ROSE. Izolowany BEFORE używa import findera w lokalnym `etap5o_artifacts/ab_hook/sitecustomize.py`, wyłącznie dla czterech zmienionych modułów Bar/widget_cache/dispatcher/compositor odczytanych z git show HEAD. Brak cofania working tree. Exit-only observer zbiera cache stats/copy bytes poza pętlą renderowania, identycznie dla obu wersji. Nie zmienia DLL/mux/eksportera. AFTER ROSE zawiera także poprawkę pozycyjnego cfg_override, niewykonywaną w gorącej ścieżce tych eksportów.

## 8. Render i Process Effective FPS oraz czasy

| Run | Render FPS | Process Effective FPS | Bar ms | producer_prepare ms | compose_overlay ms | above_compose ms |
|---|---:|---:|---:|---:|---:|---:|
| before_needle | 40.72010 | 35.20000 | 2.40548 | 21.15435 | 0.45823 | 11.24868 |
| after_needle | 37.20307 | 32.21000 | 3.34491 | 25.67018 | 0.55588 | 14.20137 |
| before_rose | 40.76487 | 35.06000 | 2.42700 | 22.21613 | 0.42846 | 12.48598 |
| after_rose | 35.70989 | 31.27000 | 3.39232 | 26.76148 | 0.53945 | 15.70451 |
| repeat_after_needle | 36.28634 | 31.49000 | 3.45509 | 26.27259 | 0.57101 | 14.58672 |
| repeat_before_needle | 36.72626 | 31.93000 | 3.35724 | 25.95136 | 0.55766 | 14.35543 |
| repeat_before_rose | 35.13481 | 30.90000 | 3.39682 | 27.18393 | 0.55820 | 15.83031 |
| repeat_after_rose | 35.29550 | 30.99000 | 3.37380 | 27.07392 | 0.55082 | 15.83282 |

Process Effective FPS pochodzi z harnessu (czas od uruchomienia eksportu z przygotowaniem), Render FPS z job native_fps. Nie utożsamiano ich. Pełne statystyki per-stage w JSON / `.amd_profile.json`; `final_summary.json` zbiera wskazane metryki.

Pierwszy pomiar wyglądał jak duża regresja: NEEDLE40.72→37.20, ROSE40.76→35.71. Powtórzony HEAD również spadł do36.73/35.13; zmieniły się czasy niezmienionych rendererów text/compass oraz całego prepare. Naprzemienne A/B: NEEDLE36.72626→36.28634 (**-1.20% Render**, Process31.93→31.49), ROSE35.13481→35.29550 (**+0.46% Render**, Process30.90→30.99). Nie ustalono jednoznacznie przyczyny zmiany warunków hosta; nie wolno ogłaszać, że całość jest tylko szumem ani przyjmować nieuzgodnionej tolerancji. **40 FPS i brak regresji end-to-end: NOT PROVEN.** Nie wprowadzano zmian potoku AMD dla odzyskania wyniku ani nie zatwierdzono poprawki commitami.

## 9. Kopie, alokacje i cache hit/miss

W obu powtórzonych eksportach AFTER exit observer w procesie eksportu: **0 owned Image copies, 0 owned payload bytes**. To nie oznacza braku wszystkich historycznych alokacji Pillow/NumPy/rendererów; dotyczy wyłącznie nowych granic ownership. BEFORE/AFTER cache counts identyczne:

- Bar: hits3660 / misses3854, entries64/max64, hit rate48.7091%.
- Widget cache: hits1492 / misses9, hit ratio99.4004%, instance fit_garmin_battery_percent_text, segment_bar. Raw changes1500, visual changes9.

Mikropomiar 160 identycznych żądań/style (159hits/1miss):

| Tile | BEFORE hit ms | AFTER borrowed hit ms | AFTER public owned hit ms | Owned copies / payload |
|---|---:|---:|---:|---:|
| horizontal ruler1044x153 | .0255 | .0231 | .0627 | 160 /102228480B |
| vertical ruler230x1050 | .0235 | .0228 | .0682 | 160 /154560000B |
| segments1008x157 | .0261 | .0249 | .0586 | 160 /101283840B |

`ownership_cost.json`: publiczne kopie samych tile kosztują około0.03–0.05ms/hit w tym pomiarze; borrowed zero nowych kopii. Cold miss czasy nie są porównaniem optymalizacji (nieparowane font/cache warmup). Peak tracemalloc5.1–7.7MB zawiera NumPy snapshots, nie mierzy natywnego allocator Pillow ani pamięci GPU.

Dodatkowy losowo przeplatany pomiar dispatchera w jednym procesie, 100bloków×100żądań/wersję: mean BEFORE .037903ms, AFTER borrowed .040445ms (różnica **.002542ms/żądanie**), AFTER public z pełnymi efektami1.889186ms. Median odpowiednio .033383/.040516/1.804937ms. Ten koszt publicznego finalnego tile zależy od rozmiaru warstw efektów; nie należy go zastępować kosztem raw tile. Artefakt `paired_dispatch_cost.json`. Żaden z tych małych pomiarów nie dowodzi pełnej bramki FPS.

Alternatywą dla kosztownego kopiowania finalnych styled tile na każdej klatce jest zastosowany audited borrowed compositor. Publiczne granice zachowują kopie wymagane do realnej izolacji. Nie wdrażano niepotrzebnych pełnych kopii 4K. Nie wyłączono cache i nie zmieniono jego sygnatur rasteryzacji.

## 10. RAM / CPU

Sampler psutil co0.2s obejmuje root+children. Peak RSS sumuje pamięć procesów (może liczyć shared pages więcej niż raz); observed CPU sumuje ostatnie zaobserwowane user+system dla każdego(pid,creation time), może nie uchwycić końcowego krótkiego procesu. CPU seconds to nie średni procent CPU. To porównanie orientacyjne, nie analiza native allocations.

| Run | Wall całego procesu s | Peak tree RSS MiB | Observed tree CPU s |
|---|---:|---:|---:|
| before_needle | 47.730 | 1725.0 | 53.234 |
| after_needle | 52.630 | 1660.9 | 68.062 |
| before_rose | 47.768 | 1731.4 | 72.656 |
| after_rose | 53.623 | 1672.7 | 83.219 |
| repeat_after_needle | 53.645 | 1664.5 | 69.656 |
| repeat_before_needle | 52.901 | 1661.0 | 67.859 |
| repeat_before_rose | 54.476 | 1671.3 | 81.156 |
| repeat_after_rose | 54.144 | 1666.8 | 89.047 |

## 11. Parity eksportów, ghosting, audio i zakończenie

Wszystkie osiem eksportów zakończyło się poprawnie: success=true,1500klatek, child_exitcode0, valid output, audio obecne, czas około50.069333s. Produkcyjny Single Live Mux zachowany (profile single_pass_av_mux=true); żadnego M4A/ADTS/audio_cache/pośredniego MP4/dodatkowego remuxingu. Każdy MP4 w artifacts jest samodzielnym końcowym wynikiem osobnego A/B, nie pośrednim plikiem pipeline.

W każdym trybie wszystkie cztery końcowe MP4 mają identyczny SHA256:

- NEEDLE: `0bcc2b261e622f4959168772a823e306c50b09a7b5a3d8c4ddd8d331ec93f55d`.
- ROSE: `0d27c2270781fbb24e5065ae8fd90612ad19a2dd8d600c9792be007787923087`.

Bitowo identyczne kompletne pliki dowodzą identycznej treści eksportu dla całych1500klatek wraz z audio. Brak nowego ghostingu/zmiany cieni/pozycji/kolorów względem BEFORE. Bar raw/styled porównano dodatkowo przed kodowaniem (max_diff0/MAE0/different_pixels0). Nie wykonywano nowego przechwytywania natywnego pre-encode HUD surface ani niezależnej ręcznej oceny wszystkich istniejących artefaktów obrazu; nie deklarujemy, że test eliminuje dawny defekt występujący identycznie w obu wersjach.

## 12. Intel/NVIDIA oraz otwarte ryzyka

Nie zmieniono kodu backendów Intel/NVIDIA, ustawień eksportu, singleton enable policy ani natywnych powierzchni. Wspólne testy cache/GUI/kompozycji PASS; borrowed output czytany przez wspólny compositor bez kopii. **Rzeczywiste eksporty Intel/NVIDIA hardware: NOT TESTED**, brak gwarancji ich FPS.

**MEMORY SAFETY — ACTIVE RISK.** Prywatne ABI Pillow, map GPU, transfery Gauge GPU i wskaźniki produkcyjne bez zmian. Nie dereferencjonowano eksperymentalnie adresów. Owned Bar nie oznacza naprawy tych ryzyk.

**FILE MUX FALLBACK — ACTIVE RISK.** Nie zmieniono fallbacku ani startup mux lifecycle. Zielone testy nie dowodzą wyeliminowania zakazanej historycznej gałęzi. Badane eksporty używały Single Live Mux.

## 13. Zmienione pliki, SHA i decyzja o commitach

- `src/indicators/bar.py` — SHA256 `b491f512f12f892604cfa8d89b52889cda157afe9f4e70412178964e1cdbc6d5`.
- `src/indicators/dispatcher.py` — SHA256 `8db8d56922817e9ab5695185c0e5fe29314c03da1f60ed5371c825d50958450b`.
- `src/indicators/compositor.py` — SHA256 `f077a945359a0ba42dc8c63af08cff78618922f28e1d42818d33ed50ead08781`.
- `src/indicators/widget_cache.py` — SHA256 `7dbaa1f060d81536440b3b3d117c2d67392bbccbf8315512ce5b9ce7eba658b7`.
- `src/indicators/raster_ownership.py` — SHA256 `2122390aac2d9b9f4580f236866789cd76cf8d8ad55bc6e713870ad2df8beaf8`.
- `tests/test_bar_cache_ownership.py` — SHA256 `5210701981945a1529ede8fc06d9172e7990c6444957b82bd706e41e437b7ca5`.
- `tests/test_compass_source_parity_hotfix.py` — SHA256 `101d6ec7ebf2e84292b8ba24a8e7bc70776e3b788f910f5ed7a8e099051e58f5`.

Raport i artifacts pozostają lokalne. Nie zmieniono gauge/exporter/DLL/def_layout, brak nowych bibliotek/shaderów i dużego refaktoru. SHA nowych commitów 5O: **brak**. Użytkownik uzależnił osobne commity Bar/ROSE od pozytywnego wyniku testów i pomiarów; bramka wydajności nie została dowiedziona. Przy przyszłym spełnieniu tej bramki zakres jest gotowy do dwóch osobnych commitów: (1) pięć modułów ownership+Bar testy; (2) wyłącznie test finalnego ROSE. Nie wykonano takiej operacji teraz.

Wynik końcowy: testy i parity PASS, zachowanie audio/finalizacji dla badanych eksportów PASS, pełna bramka FPS NOT PROVEN. Poprawki pozostają reviewable w working tree. Nie rozpoczęto kolejnego etapu.
