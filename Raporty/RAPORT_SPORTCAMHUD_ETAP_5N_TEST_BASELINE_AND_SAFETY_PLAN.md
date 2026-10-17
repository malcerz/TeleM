# SPORTCAMHUD — ETAP 5N: baza testowa i plan bezpieczeństwa

Data: 2026-10-13, Europe/Warsaw. Repozytorium: `C:\_DEV\BikeRideHUD-main-new`.

**Status: PARTIAL, nie FULL PASS.** Wyjaśniono wszystkie 18 zastanych błędów; 16 naprawiono wyłącznie w testach/fixture. Pozostały jawny defekt cache Bar i nierozstrzygnięty kontrakt ROSE. Pełny zestaw wskazany w 5M wraz z jednym nowym testem: **184 passed, 2 failed**, bez skip/xfail. Prywatne ABI Pillow i automatyczny file mux fallback pozostają aktywne; nie deklarujemy MEMORY SAFETY PASS ani gotowości do refaktoru.

## 1. HEAD i working tree

- Przeczytano `AGENTS.md`, `BENCHMARKS.md` oraz raport 5M; sprawdzono rzeczywisty diff i odtworzono 18 błędów, nie przyjęto raportu jako jedynego dowodu.
- Gałąź: `fix/gui-freeze-hud-composite`.
- HEAD początkowy: `4587b657f2a678fda2b869b08b91d1eaeb4a530a`.
- HEAD końcowy: `8465744675c5e75b1ce19a6edde7792ee6da7adc`.
- Tag `amd-known-good-40fps-20261012` pozostaje przy `e7582d8e2c212990987380ee10e5980f2dfd5867`.
- Zastane: zmodyfikowany def_layout, zmiana Bar z 5M, dwa nowe pliki tools z 5M, nieśledzone raporty użytkownika/5M i artifacts. Zachowano całość; commitowano tylko jawne listy plików.
- `def_layout.json` SHA256 nadal `8375ca40ba3670dd52de765eb91642082c9097a8fbc12dbe7fa1d1203ffa4440`; nie dodano go do commitów.
- DLL AMD SHA256 nadal `7f93c483404f970ea4e2110dcfe12535429b25b11df7415b688c07cef508752f`, ABI 9. Nie zmieniono DLL/ABI/D3D11/AMF ani flag AMD.
- Nie wykonano reset/clean/stash/rebase/merge/push/synchronizacji portable. Raport 5N i surowe artifacts pozostają lokalne, poza commitami. Working tree ma zastaną zmianę def_layout i nieśledzone raporty/artefakty; brak niezacommitowanych zmian testów lub kodu aplikacji.

## 2. Zatwierdzenie porządków 5M

Commit **`8a0c67fc416997557e72a58d288f72b3be0a227d`**:

- `src/indicators/bar.py`: tylko usunięcie pierwszej, przesłoniętej definicji clear_bar_cache (-9 wierszy), druga pozostaje identyczna.
- `tools/create_source_archive.py`: aktualna zawartość Git-tracked files, wykluczenie pycache/pyc/pyo, brak nadpisania ZIP, zachowanie śledzonych native binaries.
- `tools/SOURCE_ARCHIVES.md`: reguły i ograniczenia source snapshot.

Zweryfikowano SHA256 tych trzech plików względem evidence 5M. AST Bar po usunięciu pierwszej definicji z AST HEAD identyczny z working tree. Testy Etap5F Bar + generic widget cache: **13 passed**. Functional archive fixture i bit-exact rastery Bar były zaliczone w 5M; kod jest dokładnie tym samym kodem. Nie dołączono wielkich MP4, artifacts, def_layout ani niezwiązanych raportów do commita.

## 3. Klasyfikacja wszystkich 18 błędów

Kategorie: **A** rzeczywisty defekt produktu; **B** historyczne oczekiwanie sprzeczne z aktualnym kontraktem; **C** fixture/mock lub sposób pomiaru; **D** niedeterministyczność; **E** osobna decyzja architektoniczna/semantyczna. Żaden z odtworzonych błędów nie wymagał klasyfikacji D: prewarm miał niekompletny klucz, a nie potwierdzony race.

W tabeli skróty plików oznaczają dokładne pliki w `tests/`:

- CACHE = `test_cache_and_parity_validation.py`
- PREWARM = `test_gui_freeze_dummy_cache_safety.py`
- GUI = `test_render_tab_controls_cleanup.py`
- SCHEMA = `test_compass_rendering.py`
- ROSE = `test_compass_source_parity_hotfix.py`
- MUX = `test_amd_direct_mp4_mux.py`
- BAR = `test_bar_orientation_contract.py`
- CLEAR = `test_amd_native_ordered_map_clear.py`

| # | Dokładna nazwa testu / plik | Klasa i dokładna przyczyna | Oczekiwane → rzeczywiste zachowanie | Defekt produktu / minimalna poprawka i status |
|---:|---|---|---|---|
| 1 | test_2_value_change_repeating_previous_key / CACHE | C: trzy referencje wskazują ten sam wielokrotnie modyfikowany canvas Gauge. Pomiary były wykonywane po trzecim renderze. **Korekta 5M: to test Gauge, nie Bar.** | A→B→A powinno dać różne obrazy A/B i identyczne A; późne np.asarray pokazywało już A dla wszystkich, diff_val=0. | Nie dowodzi błędu pikseli produktu; test musi snapshotować wynik przed kolejnym renderem. Dodano dwie .copy() w teście, zachowano oba warunki parytetu. PASS. Ownership samego Gauge nadal wymaga jawnego kontraktu, patrz pkt 6/8. |
| 2 | test_7_8_input_and_output_mutation_safety / CACHE | A: `_BAR_INDICATOR_CACHE` zwraca dokładnie obraz przechowywany w cache; caller maluje na nim niebieski prostokąt. | Kolejne renderowanie tych samych danych powinno być wolne od mutacji callera → piksel nadal (0,0,255,255). | **Potwierdzony defekt ochrony cache.** Test bez zmian, FAIL. Minimalna naprawa to kopia przy granicy publicznego zwrotu lub jawna polityka owned/borrowed z bezpiecznym API. Nie wdrożono wspólnej zmiany renderera bez oceny wydajności/ownership. |
| 3 | test_complete_cache_after_prewarm / PREWARM | C: lookup liczył klucz bez start_dt_utc, choć prepare zawiera start telemetryczny; start_ts=0 zamiast czasu projektu. | Po zakończeniu prewarm ten sam klucz → READY; rzeczywiście pytano o inny klucz i dostawano None. | Brak wykazanego defektu prewarm. Do klucza dodano base_dt/layout, join potwierdza zakończenie wątku. PASS. |
| 4 | test_render_tab_controls_integration / GUI | B: aktualne etykiety to Jakość/Szybki, test oczekiwał Quality/Fast. | Kanoniczne currentData QUALITY/FAST i poprawne widoczne etykiety → dane były poprawne, język inny. | Produkt zgodny z lokalizowanym GUI. Uaktualniono tylko teksty oczekiwane, zachowano asercje danych i klas kontrolek. PASS. |
| 5 | test_output_dialog_prefill_logic / GUI | B/C: historyczny last-dialog-dir zastąpiono globalnym default export dir; goły RenderTab bez kontrolera nie ma źródła/default i fallback daje samą nazwę. | Absolute path ma być zachowany; filename-only ma trafić do saved global dir → test oczekiwał starego C:\Videos. | Aktualny kontrakt potwierdzają `export_paths`/test_default_export_dir_settings i commit `4b52155` Restore global default export directory. Fixture jawnie daje C:\Exports przez resolver; oba scenariusze i last_output_dir po wyborze nadal testowane. PASS. |
| 6 | test_compass_gui_schema_exposes_common_and_compass_specific_controls / SCHEMA | B: field/gauge_style nie są obecnymi edytowalnymi polami Compass; schema eksponuje form/source/compass_rotation_mode. | Kontrolki wspólne i kompasowe → brak 'field' w zbiorze nazw. | Aktualna schema i wybór formy są świadomą granicą UI, renderer nie został zmieniony. Zamieniono dwa historyczne pola na form/compass_rotation_mode, zachowano pozostałe wymagania. PASS. |
| 7 | test_rose_cardinals_follow_course_and_remain_upright / ROSE | C + E: spy ImageDraw.text obserwuje budowę tarczy bazowej 0°, a nie wynik cv2.warpAffine. Przy heading90 w spy nadal N jest u góry. Upright glyphs dodatkowo są historyczną semantyką wymagającą decyzji wobec obracania całej tarczy. | Końcowe pozycje liter mają podążać za kursem, litery być upright → observer mierzy bazę, a szybki renderer obraca także glyphs. | Sama asercja nie dowodzi złych końcowych pozycji. Potencjalny rozdźwięk semantyki upright = E. **Nie zmieniono renderera ani testu; pozostaje FAIL**, nie używa się go jako dowodu GPU defect. Potrzebny test finalnego rastra oraz decyzja użytkownika o upright, bez automatycznego powrotu do wolnej wersji. |
| 8 | test_direct_mp4_mux_lifecycle_single_file[False] / MUX | C: globalny fake Popen tworzył .part także przy capability probe przed preflight. Ponadto mock native próbował otwierać prawdziwy named pipe. | Jeden live mux → PARTIAL_OUTPUT_EXISTS jeszcze przed native create. | Fixture ograniczono do właściwej komendy mux; Win32 pipe jest mockiem, probe dummy media kontrolowane. Usunięto otwieranie pipe w fake_create. Wszystkie asercje pipe/no raw/final rename zachowano. PASS. |
| 9 | test_direct_mp4_mux_lifecycle_single_file[True] / MUX | C: ta sama kolizja probe/mux, wariant Inline GPMF. | Live mux z mapowaniem GPMF w jednej komendzie → wcześniejszy fake .part. | Te same poprawki fixture; zachowane asercje liczby inputs, gpmd, stream index i codec data. PASS. |
| 10 | test_direct_mp4_mux_with_range_start_offset / MUX | C: globalny Popen jak wyżej; po odsłonięciu tego błędu dodatkowo MagicMock global_start/global_end/project_duration nie obsługiwał formatu .3f przy cache key. | Jeden mux + concat z zakresem źródłowym → najpierw stale .part, później TypeError fixture. | Dodano numeryczne global_start=0/global_end=60/project_duration=60; pozostała prawdziwa ścieżka przygotowania i asercje concat/copyts/make_zero. PASS. |
| 11 | test_direct_mp4_mux_single_file_legacy_fallback_ss_offset / MUX | C: identyczne problemy mocków Popen i niepełnego timeline. | Jawne single_pass=0 dla single-file, -ss120 -i source i jeden live mux → preflight/TypeError. | Fixture poprawiony jak #10. Nie zmieniono flag produkcyjnych; ta próba nadal testuje jawny compatibility mode. PASS. |
| 12 | test_direct_mp4_mux_failure_propagation / MUX | C + B: stale .part maskował dalsze historyczne oczekiwanie False i usunięcia partial. Kod zgłasza typed MuxError i preserve_partial_output=True. | Failure musi wyjść do GUI z recovery context i ochronić final → FFMPEG_EXIT_1/live_mux, final intact, partial zachowane. | Produkt zgodny z istniejącym kontraktem recovery; zmieniono test na typed code/stage i zawartość zachowanego partial. Nie pomylono error z explicit cancel. PASS. Startup fallback pozostaje osobnym defektem kontraktu (#9 raportu). |
| 13 | test_direct_mp4_mux_user_cancellation / MUX | C: globalny fake Popen tworzył .part zanim test dochodził do cancel. | Explicit cancel kończy się False, bez final i partial → preflight stale .part. | Poprawiono tylko platform/process fixtures; asercje cancel/cleanup bez osłabiania. PASS. |
| 14 | test_slope_render_still_works_and_is_vertical / BAR | C: helper używał font size 20% wysokości (144 px) zamiast cfg.font_size=1.2% (~9 px). Teksty rozszerzały raster. | Vertical slope i widoczne dane → raster 722×365, width>height przez nadmiarowe teksty. | Geometria osi nie była dowodem błędu produktu. Helper liczy font z config tak jak compositor. Bez zmiany asercji vertical. PASS. |
| 15 | test_horizontal_ruler_renders_scale_and_marker / BAR | C: ta sama nadmierna czcionka zakrywała mały marker/obszar obserwacji. | Widoczny marker wartości50% → _marker=None. | Poprawiono parametr font helpera, test nadal szuka rzeczywistych żółtych pikseli i położenia markera. PASS. |
| 16 | test_vertical_uses_same_fraction_contract_only_geometry_changes / BAR | C: nadmierne napisy zmieniały względne marginesy rastra, marker y=269 przekraczał 65% height402. | Równa skala/fraction50% i marker w środkowym paśmie → tekst rozciągał bbox. | Wyłącznie poprawa fixture font. Wszystkie asercje plan/fraction/marker pozostały. PASS. |
| 17 | test_vertical_text_is_never_rotated / BAR | C: fixture144 px dawał glyph bbox h81 przy height264, przekraczając 20%. | Tekst poziomy i kompaktowy → w>1.5h było prawdziwe, ale font był niewłaściwy. | Poprawiono font parametr; nie zmieniono progów ani crop/renderera. PASS. |
| 18 | test_etap2a_fix_exporter_runs_clears_before_hud_upload / CLEAR | B: test wycinał źródło od wrappera _consume_prepared_frame (:6717); implementacja z clears znajduje się wcześniej w _consume_prepared_frame_impl (:6049). | Clears przed HUD upload przed process → substring nie znaleziony przez zły początek wycinka. | Zmieniono granicę wycinka na _impl, zachowano kolejność wszystkich trzech wywołań i warunek AFTER-MAP. Analogicznie skorygowano koniec prepare slice w sąsiednim teście. PASS. |

Wpływ poprawek #1,3–6,8–18 na AMD/Intel/NVIDIA: **brak zmian produkcyjnych**, poprawiono tylko testy/fixture. Wspólne testy potwierdzają obecne zachowanie bez zmiany backendów. Defekt #2 dotyczy wszystkich konsumentów CPU Bar, więc jego naprawa wymaga backend-neutral proof. #7 dotyczy wspólnego Compass renderer CPU, także preview/editor, a AMD GPU compositing wymaga osobnego dowodu parytetu. Nie zmieniono Intel/NVIDIA.

## 4. Wyniki i zakres stabilizacji

- Odtworzenie 18 błędów w ośmiu plikach: **18 failed, 72 passed**, 10.80 s (`baseline.log`).
- Po poprawkach, pełna połączona grupa 5M: **2 failed, 184 passed**, 26.81 s (`final_suite.log`). Oryginalne 185 przypadków plus jeden nowy.
- Nowy `test_preexisting_partial_is_preserved_before_native_create`: typed PARTIAL_OUTPUT_EXISTS/preflight_output, zachowana zawartość wcześniejszego partial, brak final, native create niewywołany. PASS.
- Mux/Bar orientation/early-clears podczas walidacji: **48 passed**, 7.62 s (przed dodaniem nowego testu).
- Cache Etap5F + generic widget cache: **13 passed**, 0.40 s.
- Nie usunięto żadnego failing test, nie dodano skip ani xfail, nie zmniejszono progów pixel/marker. Bar mutation i ROSE pozostają czerwone.
- QT_QPA_PLATFORM=offscreen. Pełna suite repo poza grupą 5M **NOT TESTED**, ręczne GUI **NOT TESTED**. Zaliczone mock lifecycle tests nie dowodzą realnego multi-file/cancel/error GPU.

## 5. Poprawione testy i commity

Oddzielny commit testowy **`8465744675c5e75b1ce19a6edde7792ee6da7adc`**, wyłącznie siedem plików:

`tests/test_amd_direct_mp4_mux.py`, `tests/test_amd_native_ordered_map_clear.py`, `tests/test_bar_orientation_contract.py`, `tests/test_cache_and_parity_validation.py`, `tests/test_compass_rendering.py`, `tests/test_gui_freeze_dummy_cache_safety.py`, `tests/test_render_tab_controls_cleanup.py`.

Mock Popen routuje wyłącznie komendę z stdin=PIPE oraz formatem hevc/h264/obu do fake muxera; pomocnicze probes nie tworzą partial. Mock Win32 odłącza unit tests od rzeczywistych handles/pipe dereferences. Osobny istniejący legacy multi-file fixture zachowuje własne mocks; nie jest pomijany. Testy używają dummy bytes w plikach, nie generują rzeczywistego audio-cache/M4A/ADTS/remuxowanego materiału. Fixtures EOF/probe count służą lifecycle, nie dowodzą zgodności liczby kodowanych klatek realnego GPU.

Zmiana dotyczy także rzeczywiście obowiązującego error handling: test wymaga ochrony final i recovery partial; nie zmieniono produkcyjnego błędu na False, aby przejść test.

## 6. Rzeczywiste defekty i cache safety

**Cache safety nie otrzymuje PASS.**

1. Bar mutacja: confirmed A i failing regression test. Hit i miss zwracają obraz cache bez kopii. Kopia na granicy publicznego API to mała funkcjonalnie zmiana, ale może zwiększyć koszt każdej klatki wspólnego renderera. Etap5N zachowuje production. Następny etap musi określić owners (compositor, effects, consumers), testować zarówno hit jak miss i downscaled shared entries, a potem mierzyć oba FPS.
2. Generic widget cache: lokalny bezpieczny reproducer na własnym Image.new potwierdził, że singleton jest jednym obiektem, `get_widget_cache(enabled=False)` wyłącza go także dla wcześniejszego callera, mutacja obrazu oraz metadata jest widoczna przy następnej identycznej sygnaturze. Dane w `cache_ownership.json`. To A dla ochrony zwracanych danych oraz E dla izolacji sesji/polityki; nie twierdzimy, że toggle występuje dziś w normalnym eksporcie. Child AMD ma własny proces, co nie izoluje dwóch sesji w procesie GUI.
3. Gauge zwraca reusable canvas; snapshot historycznej klatki musi nastąpić przed następnym renderem. Poprawka #1 potwierdza prawidłowe różnice A/B oraz powrót do A. Nie dowodzi bezpiecznego asynchronous ownership; bez tego kontraktu nie uznajemy całej pamięci rendererów za bezpieczną.
4. Produkcyjne prywatne ABI mapy/Gauge i automatyczny startup file fallback to aktywne ryzyka/defekty kontraktu niezależnie od naprawionych mocks.

Projekt cache: jawny RenderCacheContext z session/backend/policy, legacy singleton jako adapter bez zmiany domyślnego AMD ON ani nieprzeanalizowanych defaults Intel/NVIDIA. Osobno ownership obrazów/metadata (kopie publiczne albo verified readonly views), osobno session registry i lifecycle. Testy: mutacja hit/miss, dwa consumers i dwa identyczne indicator keys, niezależny enable/clear, cfg/font/resolution/source invalidation, A→B→A, concurrent producer/consumer. Nie wdrożono.

## 7. NEEDLE / ROSE i granice visual parity

Aktualny szybki renderer jest bez zmian. 5L-B vs 5L-C ma różnice rasteryzacji ROSE opisane w 5L-D; nie cofano warpAffine, cieni, fontów, kolorów, geometrii ani antyaliasingu.

Pozostały test ROSE wymaga osobnej decyzji o upright glyphs. ImageDraw spy nie jest poprawnym observerem końcowego transformowanego obrazu. Następny test powinien identyfikować litery w finalnym rastrze (lub testować transformację warstw z deterministycznym wzorcem) i osobno badać ich orientację. Nie wolno zastąpić tego samym spy bazowej tarczy ani zadeklarować zmiany wyglądu jako naprawy testu.

PASS testów CPU preview/final w zaliczonej grupie nie oznacza PASS pixel parity wynikowej klatki GPU. Pełny pre-encode readback NEEDLE/ROSE/GPU z pixel metrics **NOT TESTED** w 5N. Poprzedni 5M test powrotu kąta wykazał brak ghostingu lokalnego rastera; nie zastępuje GPU dirty regions proof.

## 8. Memory safety: warunki, dereferencje, ownership

Nie wykonywano eksperymentów z adresami, nie uruchamiano prywatnego pointer testu, nie podmieniono implementacji. Realne harnessy użyły istniejącego eksportera. **MEMORY SAFETY: FAIL / ACTIVE RISK.**

| Ścieżka | Wejście i niebezpieczne odczyty | Ownership/lifetime |
|---|---|---|
| `_pillow_rgba_contiguous_pointer` :96–133 | RGBA map_img, GPU map enabled i valid map_dst; wywołanie :5748 bez AMD_DIRECT_ROW_TABLE. PyCapsule→raw_ptr; from_address raw_ptr+40, row_table, row_table+(height-1)*sizeof(void*) | `map_data` trzyma silną referencję do map_img, pointer/stride i dimensions. PreparedFrame utrzymuje ją do consumer upload. To dowód referencji, nie poprawnego ABI ani braku mutacji. |
| `_pillow_rgba_row_table` :136–181 | target_addr oraz AMD_DIRECT_ROW_TABLE=1; default0 blokuje tylko tę ścieżkę. from_address raw_ptr+16/+20/+40; tablica `(c_void_p*height).from_address`, odczyty r0/r1/r_last | Własny hud_backing_ring przyjmuje memmove, slot event jest zwalniany po consume. Source Pillow pozostaje przy życiu podczas kopiowania. |
| GPU Gauge :5493–5597 | gauge_gpu_active i valid capture/tile; bez bramki direct-row flag. from_address raw_ptr+40; row table +by0*8, +(by1-1)*8; full0/+ (gh-1)*8 | `gauge_data`/`gauge_region_data` przechowują gauge_img. Compositor capture :738 zachowuje `res` bez kopii; exporter kopiuje crop tylko przy clipping. Referencja nie daje immutability mutable canvas między producer i consumer. |

Gauge odczyty pozycji table: :5518–5519, :5556–5557, :5583–5584; map helper :120/:123/:124, row-table helper :162/:163/:167/:170. Nie traktować tego zestawienia jako layout spec gwarantowanego przez Pillow. Testowanie dims/contiguity następuje po dereferencjach; try/except nie łapie OS access violation. Hardcoded8 zakłada x64. Brak weryfikacji wszystkich wierszy, stabilności ABI wersji i pamięci source między etapami.

C++ sources `telem_amd_update_map` → UpdateMapTexture oraz update_gauge/region → UpdateGaugeTexture/RegionTexture przekazują dane do UpdateSubresource. Proponowany kontrakt ownera: silna referencja plus niezmienność source od przygotowania do powrotu upload call; owned staging po zakończeniu call może zostać zwolniony/reused zgodnie z API i eventami slotu. Obecna produkcyjna konfiguracja harnessu SYNC ogranicza concurrent risk; samo posiadanie referencji nie dowodzi poprawności opt-in ASYNC.

Pozostałe ctypes/numpy pointers do własnych buforów nie są same w sobie private Pillow ABI. `_ImagingMemoryInstance` :1166 nie ma callerów. Nie zmieniano native ABI lub DLL; weryfikacja źródeł native nie jest certyfikacją całej załadowanej DLL.

Bezpieczne warianty do izolowanego etapu po zgodzie:

1. Map public `tobytes('raw','RGBA')`, owned bytes przez PreparedFrame do powrotu update_map. Nie zmienia pikseli, ale kopiuje około2MB/frame. W 5M dla mapy706×706 mediana1.0307ms/p951.2106ms; nie jest to end-to-end A/B.
2. Gauge public crop().tobytes() dla AUTO/MANUAL regions i tobytes() dla full tile; preserve poprzednie supports/early clears/stride. Odłączyć private path osobno od mapy.
3. Below direct-row opt-in: fallback do własnego numpy/bytes/ring storage publicznym API; nigdy odczyt struktury Pillow. Nie zmieniać razem z mapą/Gauge.
4. Potem ewentualny caller-owned raster/Image.frombuffer z jawnie zweryfikowanym aliasingiem i slot events; obecne np.asarray(Pillow) nie dowodzi zero-copy. To większy etap niż public copy.

Projekt A/B: osobna flaga wyłącznie testowego adaptera public upload, bez zmiany default produkcji. A = aktualny znany renderer, B = public owned bytes dla jednego subsyst. Identyczne GX010345/FIT/layout/profile/QP, NEEDLE i ROSE shadows,1500/3000f, przeplatane powtórzenia, ten sam config fingerprint. Mierzyć med/p95 prepare/copy/upload, Render i Process Effective FPS, bytes/allocation. Pre-encode GPU surfaces porównywać max_diff/MAE/different_pixels, dirty coverage i brak ghostingu. Testować cancel/slot release, error/lifetime oraz SYNC/odrębne opt-in ASYNC. Istotny koszt FPS zgłosić przed wdrożeniem; żadna podmiana w 5N.

## 9. Projekt fail-closed Single Live Mux — bez wdrożenia

Obecnie CreateNamedPipeW failure lub Popen failure ustawia direct_mux_enabled=False (:3373/:3480), co pozwala na raw encoded file i późniejszy remux (:7651). Historyczny intermediate MP4 Stage A/C wymaga multi-file i single_pass=0. **Korekta skrótu: automatyczny startup fallback bezpośrednio przechodzi na raw H265/H264 + remux, a video-only temp_video.mp4 jest osobną historyczną gałęzią.** Obie są niezgodne z docelowym produkcyjnym kontraktem. Nie zmieniono ich w tym etapie.

Proponowany odrębny etap lifecycle:

- Preflight produkcji wymaga direct_mux + single_pass; jawne tryby diagnostic nie mogą być cichym fallbackiem produktu. Rozpoznanie niezgodnej konfiguracji przed alokacją eksportu.
- Pipe failure: zgłosić typowany błąd ze stage=create_live_pipe i Windows error code; nie rozpoczynać native encode do pliku.
- FFmpeg Popen failure: zamknąć utworzony pipe, odpiąć holder, usunąć wyłącznie nowy plan concat/niedokończone dane tego job, zgłosić stage=start_live_mux z przyczyną. Bez raw/MP4 intermediate.
- Błąd musi być propagowany przez streaming, bez `return False` uruchamiającego software fallback. Użyć subtype AMDNativeFinalizationError lub jawnego catch dla typed startup mux error z RenderError metadata; obecny catches sprawdzić testem integracyjnym.
- Zasoby mają jednego ownera i idempotent close: unblock/disconnect pipe, zamknięcie stdin, terminate/wait FFmpeg, ostatecznie kill/wait, join pump/stderr, release native context, clear active_process_holder. GUI otrzymuje jasny komunikat i output/partial status.
- Wcześniejszy .part/final zawsze zachowany i zgłoszony, nigdy automatycznie kasowany jako nowy artifact. Nowy partial po startup failure może zostać usunięty; po błędzie działającego muxera politykę recovery/preserve należy ustalić oddzielnie, nie kasować recoverable video pod hasłem cleanup.
- Explicit cancel nadal kończy worker/procesy i usuwa tylko nieukończone dane bieżącego job. Race startup→cancel i cancel→drain musi mieć pojedynczy terminal state.

Multi-file: nadal jeden tekstowy concat plan źródłowych MP4 z właściwymi local ranges, jeden HEVC pipe i jeden live A/V mux, bez Stage A/B/C. FFmpeg startup error nie może rozdzielać audio/video ani przechodzić do remux. Anulowanie: test przed/po Popen, w pipe connect/read, w drain i w MP4 finish; zachować completed output. FFmpeg error: bad executable, denied access/output/disk-full, błędny concat/source/no-audio i nonzero exit; typed error + no orphan worker/process.

Obowiązkowe testy przyszłego etapu: CreateNamedPipe error, Popen exception, source/concat write failure, preexisting partial, protected final, live mux error/preserve, cancel cleanup, multi-clip audio sync, streaming does-not-fallback, one Popen mux assertion i poprawny MP4 po drain. Nie wdrożono i nie generowano rzeczywistego M4A/ADTS/audio_cache/intermediate/remux.

## 10. Regresja AMD przez kanoniczny harness

Jawnie zadana para: `D:\Comparator\GX010345.MP4` + `C:\Users\Malcerz\AppData\Local\SportCamHUD\remote_telemetry\garmin\24621925414.fit`, bez zamiany FIT. Polecenie projektu: `SportCamHUD.py --test-amd-export --mode direct --frames 1500 --start-seconds 120 --quality FAST --codec hevc --bitrate 45M --video ... --fit ... --layout ... --output ... --result-json ...`. Nie użyto zastępczego benchmarku ad-hoc.

Kopie layoutów z 5M, obecnie canonical compass_rotation_mode=needle/rose, full HUD, cienie ON; samo def_layout bez zmian. Profil SYNC/depth0/VP REFERENCE i brak ambient AMD overrides; te same defaulty co 5M, fingerprint `ed2077e94adedf1882f3051bc895da0fddf272ba3fa20916cca9c0f4d2739abf`. Nie wymuszano flags dla uzyskania FPS.

| Tryb | Render FPS5M | Render FPS5N | Process Effective FPS5M | Process Effective FPS5N | Export Effective FPS5N |
|---|---:|---:|---:|---:|---:|
| NEEDLE | 40.85294 | **40.91735** | 35.07 | **35.15** | 40.03774 |
| ROSE | 40.48282 | **40.77980** | 34.85 | **35.05** | 39.92784 |

Oba eksporty:1500f, QP28, child exit0, success=true, output valid, HEVC3840×2160 + AAC, video50.050s/audio50.069333s. FFprobe i profile w artifacts. Single pass=true, Stage A N/A, Stage C elapsed0. Brak obserwowanej regresji w obu FPS w tych próbach. To pojedyncze kontrole, nie statystyczny dowód dowolnego workloadu; nie deklarować Process FPS jako steady-state GUI FPS. CPU chart overlap fallback layoutu pozostaje jak w5M, bez zmiany polityki.

## 11. Stan Intel / NVIDIA

Brak zmian produkcyjnych w eksporterach, konfiguracji, dispatcher/cache, DLL i runtime Intel/NVIDIA. Nie wykonywano ich eksportów sprzętowych: **NOT TESTED**. Wspólne poprawki testów nie zmieniają backendów. W przyszłej naprawie shared cache konieczny dowód backend-neutrality; nie modyfikować ich defaults pod nazwą AMD cache.

## 12. Zmienione pliki i dowody

Dwa commity w pkt2/5. Raport oraz `Raporty/etap5n_artifacts/` nie są częścią commitów; duże MP4/profile i zastane raporty pozostały lokalnie. Protected hashes: `protected_files.json`; baseline/final pytest: `baseline.log`/`final_suite.log`; cache reproduction: `cache_ownership.json`; pomiary: `export_summary.json`, `needle.json`, `rose.json`, logi i ffprobe.

Brak production delta w 5N względem zaakceptowanych porządków 5M: nie zmieniono rendererów, native exporter, mux lifecycle, global cache, ustawień ani appearance. Jedyna zmiana src zatwierdzona w cleanup jest tą samą martwą definicją9 lines z5M. Nie połączono jej z testami w jednym commicie.

## 13. Bezpieczna kolejność dalszej refaktoryzacji

**Refaktor jeszcze nie rozpoczęty.** Najpierw zamknąć decyzje Bar ownership/shared cache i ROSE contract oraz ustalić dokładny zakres zielonego baseline. Nie przenosić kodu z aktywnymi niejasnościami bezpieczeństwa.

1. Osobny etap czystego resolved config eksportera AMD; stary exporter zachowuje fasadę/signature i wszystkie defaults/fingerprint.
2. Osobny etap pure geometry: clip/union/dirty bbox, previous/current supports, bez przenoszenia upload/clear calls.
3. Osobno pure helpers/profiling serialization bez efektów ubocznych, zachowanie liczników i definicji FPS.
4. Dopiero później FramePrepare context/PreparedFrame, byte/pixel parity i jawny owner.
5. Osobno bezpieczeństwo upload/pamięci (public API A/B), potem ewentualne wydzielenie upload subsystem. Nie łączyć podmiany ABI z kosmetycznym move.
6. Osobny fail-closed Live Mux etap, test startup/single/multi/cancel/errors; dopiero potem wydzielenie mux lifecycle.
7. Na końcu finalizacja/drain/recovery i state machine. Każdy etap ma własny commit, adapter zgodności i harness regression obu FPS.

Nie wydzielać wielu podsystemów w jednym commicie. Publiczne importy/API pozostają adapterami; każdy krok wymaga pełnego HUD4K, NEEDLE/ROSE shadows, pre-encode pixel parity, cache/ghosting, Single Live Mux i poprawnego finish. Brak akceptacji regresji za porządki.

## 14. Wynik końcowy

**PARTIAL:** uzyskano opisaną, odtwarzalną bazę testów i odseparowano16 błędów testów/fixture od rzeczywistych problemów. Bar mutation pozostaje realnym defektem; ROSE upright wymaga poprawnego observera i decyzji semantycznej. Ryzyka singletonu, prywatnego ABI i startup remux mają konkretne plany, ale nadal są aktywne. Nie rozpoczęto refaktoru, nie zadeklarowano MEMORY SAFETY/FULL PASS. Zatrzymano się po raporcie.
