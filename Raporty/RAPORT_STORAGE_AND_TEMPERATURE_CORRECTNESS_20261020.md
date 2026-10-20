# Storage Preflight + Temperature Resolver Correctness — 2026-10-20

## Wynik i stan początkowy

Implementacja na `main`, bez push. Wejściowy HEAD: `189ec8113aebd8924313519f15a9492f39afb7bf`. Prywatny `def_layout.json`, wcześniejsze nieśledzone pliki, DLL i manifesty zachowane. Bez nowych gałęzi, worktree, kopii projektu, stash/reset/clean.

**Wynik: poprawki wdrożone i sprawdzone testami; pełna walidacja sprzętowa AMD i fizycznego udziału UNC — NOT TESTED.** Nie deklaruję pełnego PASS wszystkich kryteriów sprzętowych.

## Etap A — Storage

### Potwierdzona przyczyna i reprodukcja

Uruchomienie aktualnego bloku preflight z dwoma źródłami po 2047.4454 s przekazało do kontroli tylko **2047.4454 s**, zamiast **4094.8908 s**. `ffprobe_stream_info` wybierał wyłącznie `v:0`, nie dostarczał bitrate kopiowanego audio. Wyjątki probe i parsowania były ignorowane. Monitor nie otrzymywał wyliczonej rezerwy zadania; utrata katalogu lub błąd zapytania ustawiał flagę bez callbacku zatrzymującego dopływ klatek.

### Zmienione miejsca

- `src/ffmpeg/render_errors.py`: `probe_export_storage_media`, `preflight_export_storage`, `estimate_required_export_space`, `check_preflight_storage`, `RuntimeStorageMonitor`.
- `src/gui/qt/_mixins/render_mixin.py`: wspólny `_render_pipeline` dla direct/queue, callback storage, przyczyna końcowego stanu failed, walidacja także docelowego MP4.
- `src/render_progress.py`: osobne powody `STORAGE_LOW_SPACE` i `STORAGE_UNAVAILABLE`.
- `src/ffmpeg/amd_native_exporter.py`: wyłącznie przekierowanie storage-stop z destrukcyjnej ścieżki user cancel do istniejącego flush/drain; oczekiwanie na live mux nie zabija go natychmiast z powodu tej flagi.
- `tests/test_storage_export_correctness.py`, rozszerzenie `tests/test_amd_live_mux_audio_finalization.py`.

### Kontrakt i dowód multi-file

Oba wejścia GUI korzystają z jednej kontroli przed przygotowaniem HUD, inline GPMF i cache renderera. Wszystkie źródła są odpytywane; kanoniczny `VideoTimeline.output_frame_count(target_fps) / target_fps` wyznacza czas. `subset_excluding` uwzględnia zakresy źródłowe i wycięcia, bez liczenia całych źródłowych plików przy eksporcie fragmentów. Brak timeline powoduje zbudowanie planu klipów z probe wszystkich plików. Nieudane oszacowanie, nieprawidłowy FPS/bitrate, nieistniejący katalog i nieudane `disk_usage` blokują eksport jako `StorageError`, bez ogólnego ignorowania błędu.

Przypadek obowiązkowy: `GX010381.MP4` + `GX010382.MP4`, po **2047.4454 s**, **30000/1001 FPS**, target **60 Mb/s**, budżet peak **90 Mb/s**. Kanoniczny wynik to dokładnie **4094.8908 s**. Mockowane **24 GiB** pozwala na jeden klip, lecz kontrola całego projektu blokuje kodowanie. Osobne testy rzeczywistej metody GUI dla direct i queue kończą się `ENOSPC` przed uruchomieniem monitora i kosztownych etapów. Nie zapełniano dysku.

Estymacja jest konserwatywna: peak 1.5 × target, suma bitrate obecnych strumieni audio (384 kb/s fallback dla strumienia bez bitrate), 30% marginesu i rezerwa max(512 MiB, 5% szacowanego pliku). Komunikat podaje dysk, rozmiar pliku, wymagane miejsce, dostępne miejsce i brakujące GB. Rozmiar w komunikacie jest budżetem przy peak, a nie obietnicą rzeczywistego rozmiaru VBR.

Aktualna aplikacja nie ma eksportowego mnożnika prędkości. `update_rate_step` zmienia częstość HUD, a `charts_skip_pauses` dotyczy wykresów; nie skracają filmu i nie zmniejszają estymacji. Nie dodano funkcji przyspieszania. Gdy zakresy są już reprezentowane w timeline, używany jest ten plan. Domyślne/fallbackowe parsowanie wadliwego FPS zostało dodatkowo zastąpione ścisłym parsowaniem ułamka.

Kontrola używa katalogu ostatecznie rozwiązanego wyniku; wcześniejsza istniejąca polityka wyboru/fallbacku folderu nie została zmieniona. `disk_usage` nie jest wykonywane dla dysku aplikacji. Fizyczny odłączany nośnik/UNC: NOT TESTED; błędy dostępu i zapytań symulowano.

### Runtime i częściowy materiał

Monitor co 1.5 s otrzymuje rezerwę danego zadania. Low-space zatrzymuje nowe klatki; utrata dysku/błąd query daje osobny typowany queue blocker i również wywołuje callback. Powód storage jest zachowany przy stanie failed, nie `NONE`. AMD przechodzi przez już istniejące flush/drain/live mux. Nie dodano remuksowania ani nowego sposobu finalizacji. Zwykłe anulowanie zachowuje swoją dotychczasową ścieżkę.

Po zatrzymaniu GUI waliduje istniejący finalny plik oraz `.part` / `.part.mp4`, raportuje `partial_valid`, `partial_invalid` albo `unverified`; nie zgłasza pełnego sukcesu. Poprawny częściowy materiał nie jest kasowany. Niewalidowalny plik może pozostać artefaktem diagnostycznym, ale nie jest przedstawiany jako poprawny film. Kolejka otrzymuje błąd blokujący.

Test z mockiem AMD potwierdził wywołanie flush, brak kill live mux i zachowanie wyniku. Osobna walidacja rzeczywistego MP4 harnessu potwierdziła 2.002 s oraz niezmieniony SHA256; niepoprawny plik bez moov został odrzucony. Dowód: `storage_temperature_20261020/partial_validation.json`. Realne przerwanie produkcyjnego AMD podczas ENOSPC i możliwość finalizacji z taką rezerwą: **NOT PROVEN sprzętowo**.

## Etap B — Temperature

### Przyczyny i wyniki przed poprawką

Nowe testy na kodzie wejściowym: **8 FAIL, 12 PASS**. Poprzednie testy plateau badały pomocniczy interpolator, a nie główny resolver.

1. `presentation_value` wybierał plan `quantized_reconstruct`, ale `NumericPresentationPlan.value_at` używał zwykłych sąsiadujących próbek. W t=30 wynik plateau wynosił 19.0.
2. Wybór tego planu ignorował jawne `step`; próbki 59=19, 60=20 dawały w t=59.5 błędne 19.5.
3. Rejestr narzucał temperaturze `native_resolution=1.0`; helper grupował ułamkowe TMPC w całkowite buckety. Odtworzono m.in. 19.6/19.7 → 19.5.
4. `render_overlay_job` miał bezwarunkowy fallback FIT → surowe próbki kamery. Worker nie realizował AUTO temperatury tak jak manager Preview.
5. Starszy `interpolate_temperature` po kanonicznym wyniku None cofał się do `_interpolate_step(...allow_pre_first=True)`, ujawniając przyszły odczyt przed pierwszą próbką.

### Zmienione miejsca

- `src/telemetry_resolver.py`: semantyka temperatury z detekcją natywnej rozdzielczości; `_presentation_meta` uwzględnia również ułamkową część samych odczytów (np. 19.2 → 20.2); `_uses_quantized_events`; `_quantized_change_timeline`; binarny lookup segmentu i zdarzeń; `numeric_presentation_plan`, `NumericPresentationPlan.value_at`, `presentation_value`.
- `src/ffmpeg/worker_cache.py`: AUTO temperatury korzysta z istniejącego `resolve_samples_from_sources` i jego kolejności preferencji.
- `src/ffmpeg/frame_renderer.py`: usunięcie niejawnego fallbacku do temperatury kamery w starszym rendererze.
- `src/indicators/frame_data.py`: wspólny resolver także dla fallbacku bez callbacku; kanoniczne None nie jest nadpisywane przyszłą próbką.
- `src/telemetry_extract.py`: wyłącznie helper prezentacyjny `interpolate_temperature`; parser RAW niezmieniony.
- `tests/test_temperature_presentation_parity.py`: **38 testów** po rozszerzeniu.

Nie utworzono drugiego silnika. Plan i główny resolver korzystają z istniejącego interpolatora i cache osi zmian. Jawne `step` wygrywa z auto/reconstruction. Dla rzeczywiście całkowitych danych auto z decimals=0 trzyma krok; decimals=1/2 rekonstruują plateau. Jawne linear pozostaje aktywne także przy zerowej precyzji tekstu. Ułamkowe źródła nie są grupowane w pełne stopnie; auto respektuje obserwowaną precyzję, a linear interpoluje sąsiednie rzeczywiste wartości.

### Dowody kontraktu

- Plateau 0..59=19, 60=20: **19 / 19.25 / 19.5 / 19.75 / 20** w t=0/15/30/45/60, zarówno canonical, jak plan.
- Explicit step, decimals=1, t=59.5: **19.0**.
- Surowe **19.2, 19.3, 19.4, 19.5, 19.6, 19.7, 19.8**, a także **16.910156, 21.029297, 40.904297** zachowane na timestampach źródłowych.
- FIT bez temperatury i GPMF z temperaturą: explicit FIT = **None**, GPMF = kamera, AUTO = kamera; przy obecności FIT AUTO preferuje FIT. Preview manager i Final worker zwracają identyczne wartości.
- Test starszego renderera przechwytuje wartość przekazaną do compositor dla FIT/GPMF/AUTO. Test pełnej klatki z prędkością i temperaturą potwierdza 19.5 w compositorze.
- Długa luka, jawne granice segmentów, brakująca próbka, rzeczywista luka klipów/wycięcie i obszar przed pierwszą próbką nie są rampowane. Stałe źródło pozostaje stałe. RAW nie jest modyfikowane, sztuczne próbki nie są dopisywane do cache.
- Istniejące testy BAR pełnego float, gauge, integer-only i geometrii pozostają w zestawie. Nie zmieniano funkcji geometrii, rozmiarów ani projektu HUD.

## Walidacja i harness

Główny zestaw po poprawkach: **253 PASS, 4 SKIP, 2 DESELECTED** w 6.81 s; po końcowym uszczelnieniu parsowania FPS dodatkowy zestaw Storage: **21 PASS** (3 nowe testy błędnych FPS). Log: `storage_temperature_20261020/pytest_scoped_final.log`.

Dwa wyłączone testy były uruchomione, zawiodły także na wejściowym kodzie 189ec81 odtworzonym wyłącznie w pamięci procesu, bez modyfikacji checkoutu:
- `test_gauge_schema_exposes_only_used_fields` — brak oczekiwanego thickness w schemacie;
- `test_render_tab_preview_target_size_uses_video_rect_for_native` — brak oczekiwanego wywołania resize.

Dowód: `baseline_unrelated_failures.log`; pełny wcześniejszy przebieg: `pytest_final.log` (250 PASS, 4 SKIP, 2 FAIL, przed trzema kolejnymi testami). Nie poprawiano tych niezależnych problemów. `py_compile` i `git diff --check` zmienionych plików PASS. Pełny lint nie jest PASS; `pyflakes.log` obejmuje m.in. wcześniejsze nieużywane importy i Any w innej części render_mixin.

Dane BENCHMARKS `Video/GX020079.MP4` + `Video/GX020079.fit` niedostępne. Przed użyciem jawnie ogłoszono istniejącą parę harnessu Intel: **C:/GoPro/GX010378.MP4 + C:/GoPro/2026-10-15_15-03-50.fit**, layout `Raporty/intel_vbr_qp_20261017/layout.json`.

Kanoniczna aplikacja `SportCamHUD.py --test-intel-export --intel-path native --codec hevc --profile fast --frames 60 --bitrate 40M`:
- direct: poprawny MP4, 60 klatek 4K HEVC, AAC, 2.002 s, 3.29 s / 18.23 effective FPS (`intel_smoke.json`);
- queue + `--preview-hud`, końcowy zweryfikowany przebieg: **60 klatek**, poprawny HEVC/AAC, **2.002 s**, live audio mux=true, brak pozostawionych pipe forwarders, **3.06 s / 19.58 effective FPS** (`intel_queue_verified.json`). Log nie zawiera tracebacku/exception_type błędu HUD.

Pierwszy przebieg queue (`intel_queue_final`) odrzucono jako dowód pełnego sukcesu: JSON success=true nie ujawniał wyjątku UnboundLocalError w podglądzie. Przyczyną był dodany warunkowy import zasłaniający wcześniejszy globalny resolver. Import usunięto, dodano test pełnej klatki z prędkością + temperaturą i powtórzono harness. Nie oparto wyniku wyłącznie na fladze success.

Test helperów nie zastąpił harnessu. Krótkie wyniki direct/queue nie służą do porównania wydajności backendów. Sprzętowy AMD HUD/QP i NVIDIA: NOT TESTED w tym środowisku.

## Wydajność

`performance.json`: ta sama seria 100000 próbek i pełny przebieg 108000 lookupów (1 h przy 30 FPS), baseline z 189ec81 załadowany w pamięci. Przygotowanie 33.3 ms → 85.0 ms; lookup **10.11 → 14.33 µs**. Różne checksumy wynikają z naprawionej rekonstrukcji plateau. Dodatkowy pełny przebieg 1800 klatek HUD 320×180: **0.494 s**. Nie jest to pomiar kodowania AMD/4K.

Koszt dodatkowy około **4.22 µs/klatkę**, jednorazowy cache indeksu zdarzeń, bez kopiowania/skanowania całej serii per-frame. Wyszukiwanie segmentu i zdarzenia binarne. Test dużej serii potwierdza ponowne użycie tego samego indeksu cache. Istotny spadek sprzętowego FPS AMD: **NOT PROVEN / nie zmierzono na AMD**.

## Izolacja i pozostałe ograniczenia

Nie zmieniono żadnej DLL, manifestu, C++, presetów, VBR/VBV/HRD, sprzętowego feedbacku AMF QP, Intel QSV, NVIDIA NVENC, GPU Pitch, mapy, kompasu, SmartSync, HDR/HLG ani geometrii HUD. AMD po pracy ma SHA256 **BBCA75FBD0DFC5D7CBB61922E92F8D5F049B4305DD18335315667E6E5E54CA5F**. Live mux nadal single-pass, audio bezpośrednio z MP4; nie dodano ensure_audio_cache, audio pre-extraction ani końcowego remuksowania.

Warstwa storage-stop używa istniejącej finalizacji, lecz realne zachowanie AMD przy utracie nośnika wymaga sprzętowej próby. Fizyczne UNC, długi eksport 4094.8908 s, wszystkie kodeki/presety i sprzętowa regresja AMD/NVIDIA nie były renderowane. Estymacja VBR jest celowo konserwatywna i może blokować zadanie, którego rzeczywisty plik byłby mniejszy od budżetu peak.

## Commity lokalne

- **2d35d75** — Etap A: preflight całego projektu, rezerwa zadania, runtime/queue diagnostics i test drain AMD.
- **f6251ff** — Etap B: wspólny resolver, precyzja źródła, step, source selection, testy.
- **22f4d6f** — uszczelnienie Etapu A: wadliwe FPS nie mogą przejść przez fallback 30 FPS.
- Osobny commit dokumentacyjny zapisuje ten raport i wybrane małe dowody; bez push.

## Git status

Po commitach implementacyjnych jedynym zmodyfikowanym śledzonym plikiem użytkownika pozostaje `def_layout.json`. Wcześniejsze nieśledzone pliki C, raporty Intel, katalogi C_r31..C_r36, log hang_repro, kopie DLL oraz font Digital-7 Mono PL.ttf zachowane. Nowe dowody i renderowane MP4 są w `Raporty/storage_temperature_20261020/`; MP4 nie są dodawane do commitów. Końcowy surowy status znajduje się w `storage_temperature_20261020/git_status_final.txt` (zapis przed commitem dokumentacyjnym).
