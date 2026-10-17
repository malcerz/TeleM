# SPORTCAMHUD — ETAP 5M: audyt aktualnych źródeł

Data: 2026-10-13, Europe/Warsaw. Repo: `C:\_DEV\BikeRideHUD-main-new`.

**Wynik: audyt i minimalne porządki wykonane; pełna bramka akceptacyjna PARTIAL / NOT PROVEN.**
Nie zmieniono pamięci natywnej, potoku AMD, DLL, kodeka, QP, konfiguracji Intel/NVIDIA ani finalizacji. Nie wykonano push, synchronizacji portable, git clean, masowego formatowania ani podziału monolitów.

## 1. HEAD i working tree

- Gałąź: `fix/gui-freeze-hud-composite`.
- HEAD początkowy i końcowy: `4587b657f2a678fda2b869b08b91d1eaeb4a530a`.
- Tag `amd-known-good-40fps-20261012` wskazuje `e7582d8e2c212990987380ee10e5980f2dfd5867`, a nie aktualny HEAD. Nie przesuwano tagu.
- Przeczytano główne `AGENTS.md` i `BENCHMARKS.md`. Jawna gałąź i materiał użytkownika mają pierwszeństwo przed starszymi zaleceniami o main i GX020079.
- Zastane zmiany: `def_layout.json` (20 dodanych / 9 usuniętych linii), siedem nieśledzonych raportów AMD/SportCamHUD i `Raporty/DELETED_FILES_MANIFEST_20261013.json`. Zachowano je.
- SHA256 zastanego i końcowego `def_layout.json`: `8375ca40ba3670dd52de765eb91642082c9097a8fbc12dbe7fa1d1203ffa4440`.
- Eksporter ładuje DLL przez `get_amd_native_dll()` z `src/runtime_paths.py`: domyślnie `runtime/amd/bin/telem_amd_native.dll`, opcjonalnie `TELEM_AMD_NATIVE_DLL`. W środowisku audytu brak tego override i brak ambient AMD_*.
- DLL: SHA256 `7f93c483404f970ea4e2110dcfe12535429b25b11df7415b688c07cef508752f`, ABI 9, build ID `telem-amd-native/1.0.0+600c2a6b1826.srcb9957bf212e2`. Zweryfikowano publicznymi eksportami DLL; brak rebuild.
- Build info: version 1.0.0; timestamp `2026-10-02T09:53:21+02:00`; native git commit `600c2a6b18261ab71a289ef7364c7033ea9b8e25`; source hash `b9957bf212e28920e680b96dd96411a69a7aaf4102207bcb08f926cae12dc9da`.

## 2. Największe pliki

Liczenie rzeczywistych wierszy przez `splitlines()`, bez dodatkowego pustego wiersza końcowego; różnica o 1 względem danych ZIP wynika z konwencji liczenia.

| Plik | Wiersze przed zmianą | Po zmianie |
|---|---:|---:|
| src/ffmpeg/amd_native_exporter.py | 8537 | 8537 |
| src/gui/qt/tabs/render_tab.py | 4026 | 4026 |
| src/ffmpeg/streaming.py | 2786 | 2786 |
| src/ffmpeg/intel_native_exporter.py | 2416 | 2416 |
| src/indicators/bar.py | 2242 | 2233 |
| src/gui/qt/_mixins/render_mixin.py | 1788 | 1788 |
| src/ffmpeg/nvidia_native_exporter.py | 1745 | 1745 |
| src/gui/telemetry_manager.py | 1667 | 1667 |
| src/qp_analyzer.py | 1654 | 1654 |
| src/gui/qt/_mixins/project_mixin.py | 1606 | 1606 |
| src/indicators/gauge.py | 1441 | 1441 |

`export_amd_native_d3d11`: linie 2081–8537, **6457 wierszy**. Pełne zestawienie top 15, definicje i importy: `etap5m_artifacts/static_audit.json`.

## 3. Mapa odpowiedzialności i zależności

| Moduł | Obecne odpowiedzialności | Główne granice zależności |
|---|---|---|
| amd_native_exporter | ABI/config/preflight, próbki telemetrii, partycjonowanie HUD, dirty regions, producer/consumer, map/chart/gauge upload, D3D11/AMF, pipe/FFmpeg, cancel, finalizacja, profil | runtime_paths, amd_config, watchdog, worker_cache, compositor, moving_map, gauge dynamic info, render_progress, render_errors, native DLL |
| render_tab | Budowa QWidget, opcje i stan eksportu, snapshot zadań, kolejka, transport podglądu, HUD preview, progress/ETA/FPS, wynik i błędy | controller/signals, export_queue, export_preview, video_preview, encoder_profile, render_progress, export_paths |
| streaming | Wspólny dispatch backendów, zakres/timeline i rozdzielczość HUD, worker pool/SHM, writer, postęp i proces FFmpeg, fallback i metadata orientation | command_builder, detection, intel_backend, frame_renderer, worker_cache, shared_memory, multifile, pipeline_audit; lazy import eksporterów |
| bar | Ruler horizontal/vertical, segmenty, slope, text metrics, zakresy, geometria markerów, warstwy/cache i compatibility aliases | helpers (wspólny STATIC_CACHE), icons; dispatcher jako caller |
| render_mixin | Snapshot opcji/telemetrii, walidacja, uruchomienie job/child, progress callback, preview, cancel session i wynik | controller, ffmpeg dispatch, hybrid_render, telemetry_extract, video_helpers, render_progress, export_paths |
| gauge | NEEDLE/ROSE, tarcza/teksty, wskazówka, cienie, affine rotation, canvas state, cache rasterów, dynamic support bboxes dla GPU | helpers/STATIC_CACHE, Pillow, lokalne numpy/cv2; dispatcher i eksporter AMD |

Aktywna droga: RenderTab → sygnał/controller RenderMixin → `_render_pipeline` → `stream_overlay_to_ffmpeg` → detection AMD_NATIVE_D3D11 → `export_amd_native_d3d11`. AMD obsługuje także video_timeline multi-file; komentarz w streaming.py:1342 o pomijaniu native multi-file jest nieaktualny: `amd_native_multi_guard=False`, dispatcher wywołuje native i przekazuje timeline. Native finalization exception jest propagowany; zwrot False może uruchomić software exporter. Intel/NVIDIA mają osobne gałęzie dispatch i osobne runtime.

## 4. Potwierdzone duplikaty

| Lokalizacja przed zmianą | Przesłonięta definicja | Decyzja |
|---|---|---|
| bar.py:1064 i 2011 | clear_bar_cache | Usunięto tylko pierwszą definicję, 9 wierszy. Druga bez zmiany treści, teraz :2002. |
| render_tab.py:3092 i 3939 | RenderTab.showEvent | Pozostawiono; pierwsza używa `_update_preview_size`, druga `_update_preview_width`; potrzebny odrębny audyt GUI. |
| render_tab.py:3096 i 3944 | RenderTab.resizeEvent | Pozostawiono z tego samego powodu. |
| render_errors.py:79 i 141 | RenderError.__str__ | Pozostawiono; różne komunikaty storage i lokalizacja, osobny etap kontraktu błędów. |

Importy `clear_bar_cache`: controller.py:306, testy cache/parity/exhaustive/lean/solar i skrypty benchmarków Bar/dirty regions. Po wykonaniu modułu wszyscy pobierają drugą definicję. Między definicjami brak wywołania ani zachowania referencji do pierwszej, brak dekoratorów. Pierwsza nie jest implementacją publicznego API dostępną po imporcie.

Dowód minimalności: AST całego Bar po usunięciu pierwszego FunctionDef z AST HEAD jest identyczny z AST working tree. Parytet trzech stylów z rzeczywistym rendererem HEAD: 12 porównań, wszystkie max_diff=0, MAE=0, different_pixels=0.

## 5. Martwy kod i ograniczenia dowodu

Skan AST wszystkich znalezionych `src/**/*.py` wykrył 277 kandydatów importów bez odczytu nazwy i 52 funkcje z pojedynczym wystąpieniem symbolu w tekstach Python repo. To lista do analizy, **nie dowód nieużywania**: eksport API, adnotacje, Qt, re-exports, getattr/importlib i narzędzia zewnętrzne mogą je wykorzystywać. Przeszukano też testy, CLI, tools, scripts i scratch, nie tylko src. Dane skanu mają zakres lokalnego repo, nie wszystkich zewnętrznych klientów.

- `bar.py` import `os`: brak lokalnego odczytu w AST; pozostawiony zgodnie z poleceniem usunięcia wyłącznie pierwszej definicji.
- `amd_native_exporter.py` import `render_debug_print`: analogiczny kandydat; pozostawiony.
- `_segment_gradient_stops`: oznaczony deprecated alias do `_resolve_segment_gradient`, brak innych odniesień w lokalnym Python. Pozostawiony jako adapter zgodności.
- `get_bar_cache_stats`: publiczne API diagnostyczne, brak lokalnych odwołań nie uzasadnia usunięcia.
- `_ImagingMemoryInstance` (amd_native_exporter.py:1166): prywatny opis struktury, brak odwołań do klasy poza definicją. Nie wykazano aktywnej dereferencji przez tę klasę; pozostawiona w audycie AMD.
- `_create_amd_local_scratch_dir`: nie jest wywoływany przez produkcyjny exporter, lecz jest importowany i wywoływany przez `tests/test_amd_direct_mp4_mux.py:61,74`. Pozostawiony.
- Brak `if` z literalnym stałym warunkiem w skanie AST. To nie dowód osiągalności wszystkich dynamicznych gałęzi. `stage_scratch_dir` jest stale None w bieżącej funkcji; jej cleanup/metryki są historyczne, pozostawione.

Jedyny usunięty kod z dowodem martwości: pierwsza, bezwarunkowo przesłonięta definicja Bar. Nie usuwano kodu na podstawie samej nieobecności callerów.

## 6. Pillow private ABI — krytyczne ustalenia

**Produkcja nadal korzysta z prywatnego ABI mimo `AMD_DIRECT_ROW_TABLE=0`.** Raport `AMD_KNOWN_GOOD_40FPS_20261012.md`, sekcja 3, deklaruje brak struktur prywatnych Pillow; aktualny kod temu przeczy. Także nagłówek runnera Etap5G utożsamia tę flagę z publicznym API, co nie jest prawdą dla mapy/Gauge.

| Ścieżka | Warunek i faktyczne odwołanie | Status |
|---|---|---|
| Mapa | GPU map + dostępne map_img/map_dst; :5748 wywołuje `_pillow_rgba_contiguous_pointer` bez sprawdzenia flagi; helper :96 czyta capsule i offset +40, pierwszy/ostatni wiersz | Osiągalna w normalnym eksporcie. `map_data` zachowuje Image; consumer :6417 przekazuje pointer/stride do `telem_amd_update_map`. |
| HUD below | :5796 wywołuje `_pillow_rgba_row_table` tylko przy target_addr i `AMD_DIRECT_ROW_TABLE=1` (domyślnie 0) | Opt-in. Offsety +16/+20/+40, potem memmove do własnego ring buffer. |
| GPU Gauge | `gauge_gpu_active` + capture; :5493–5597 czyta capsule i +40, potem wiersze przy offsetach mnożonych przez **8** | Osiągalna domyślnie, nie zależy od flagi direct row table. AUTO/MANUAL/full tile mogą używać borrowed pointer. |
| ABOVE / inne | `_above_region_pointer` używa własnego bufora ctypes; numpy buffer pointers odnoszą się do własnych alokacji | Nie są prywatnym ABI Pillow. Opis `_ImagingMemoryInstance` nie ma callerów. |

Nie znaleziono innych `PyCapsule`/`from_address`/core.ptr w produkcyjnym src poza tym eksporterem. Stabilność API Python capsule nie stabilizuje struktury Imaging. Walidacja pierwszego i ostatniego wiersza nie potwierdza wszystkich wierszy. `try/except` nie zabezpiecza przed access violation przy odczycie nieprawidłowego adresu; odczyty odbywają się przed możliwością rozpoznania błędu. Samo podtrzymanie Image rozwiązuje lifetime, nie ABI.

Istniejący test `test_amd_map_pillow_pointer.py` bezpośrednio dereferencjonuje private pointer przez `ctypes.string_at`; **nie uruchamiano go ani nowych eksperymentów dereferencji**. Realne eksporty użyły istniejącej, niezmienionej ścieżki produkcyjnej. Nie wykonywano prób z adresami ani nową interpretacją layoutu pamięci.

Bezpieczny fallback już istnieje: `map_img.tobytes('raw','RGBA')`; Gauge używa crop().tobytes() albo pełnego tile.tobytes(). Publiczne `np.asarray(Pillow)` nie gwarantuje zero-copy i nie usuwa samoistnie kosztu. Można użyć publicznego owned bytes z zachowaniem lifetime; zero-copy wymaga projektowania własnej pamięci rastra, testu aliasowania i bezpieczeństwa producer/consumer.

Pomiar publicznego API bez eksportu równoległego, 20 warmup + 300 próbek, RGBA:

| Raster | Bajty | mediana ms | p95 ms |
|---|---:|---:|---:|
| Rzeczywisty rozmiar mapy obecnego layoutu, 706×706 | 1 993 744 | 1.0307 | 1.2106 |
| Gauge reprezentatywny 300×300 | 360 000 | 0.20745 | 0.2469 |
| Pełny HUD 3840×2160 | 33 177 600 | 21.6073 | 23.2105 |

To koszt samego serializowania publicznego API, nie zmierzona różnica pełnego eksportu. Zależy od alokatora i rozmiaru regionów; wcześniejszy pomiar pod obciążeniem jest zapisany osobno. Kopia mapy jest przygotowywana przed konsumenckim skip_upload, więc prosta zamiana kopiowałaby także obrazy później niewysłane. Przy hipotetycznym dodaniu 1.03 ms do 25 ms budżetu 40 FPS otrzymuje się około 38.4 FPS; to oszacowanie, **NOT PROVEN**, nie wynik A/B.

**Nie wdrożono zamiany.** Publiczne API jest dostępne i zapewnia identyczne bajty; brak dużego spadku FPS nie został udowodniony. Zgłoszono problem użytkownikowi przed zmianą. Proponowane izolowane A/B, dopiero po zgodzie:

1. Osobny etap MAP public-bytes: adapter z owned bytes, bez zmian DLL/D3D11/codec/QP; Gauge i below pozostają bez zmian. Brak nowego kodu dereferencji.
2. Osobny etap GAUGE public-crop/full: istniejące fallbacki, zachowanie AUTO rectangles, previous supports i start-of-frame clears.
3. Identyczne 1500/3000f, GX010345 + FIT z pkt 11, kopie layoutów NEEDLE/ROSE z cieniami, taki sam zestaw flag; przeplatane powtórzenia A/B, fingerprint i pomiary Render oraz Process Effective FPS.
4. Pre-encode readback publicznym harness/API DLL: max_diff, MAE, different_pixels, dirty coverage, brak ghostingu, cancel/drain i mux lifecycle. Nie porównywać HEVC jako dowodu bit-exact.
5. Jeżeli kopia mapy powoduje regresję, najpierw osobny projekt eliminowania kopiowania przy reuse, następnie ewentualny caller-owned raster przez publiczne API. Bez automatycznego wdrożenia.

## 7. Globalny cache

`widget_cache.py:360–383`: `_CURRENT_CACHE` singleton procesu; domyślne `AMD_CPU_WIDGET_CACHE=1`. Dispatcher :109 wywołuje `get_widget_cache()` bez backendu. Cache obsługuje tylko segment_bar/segments, nie wszystkie formy Bar/Gauge.

| Konsument | Faktyczny wpływ |
|---|---|
| AMD | CPU segmenty trafiają do tego cache; zachowano default ON. Child exporter ma własny singleton procesu. |
| Intel/NVIDIA | Wspólny dispatcher nie ma bramki backendu; CPU raster segmentów może korzystać z tej samej polityki AMD-nazwanej flagi. Brak zmiany defaults. |
| Preview / HUD editor | Używają wspólnego compositor/dispatcher w procesie GUI; współdzielą singleton i policy. |
| Wiele sesji w jednym procesie | Jawne `get_widget_cache(enabled=...)` zmienia enabled już istniejącego singletonu dla wszystkich callers. `reset_widget_cache` występuje w testach, nie w produkcyjnym src. |

Klucz instancji to indicator key, signature obejmuje geometrię, cfg, font path, tekst i stan segmentów. `get_or_render` zwraca `inst.last_result` bez kopii, więc obraz/metadata są współdzielone z callerem. Kompletność sygnatury pomaga invalidacji, ale nie dowodzi immutability/thread safety ani izolacji sesji. Cache nie ma synchronizacji.

Potwierdzony problem cache safety w istniejącym rendererze: test mutation safety Bar nie przechodzi już na HEAD; po zmianie tak samo. Nie twierdzimy, że wszystkie te błędy wynikają z generic widget cache. Testy `test_generic_widget_cache.py` oraz Etap5F należą do zaliczonej części zestawu.

Mały projekt późniejszej izolacji: jawny `RenderCacheContext(session_id, backend, enabled)` przekazywany do dispatch; legacy `get_widget_cache()` pozostaje adapterem dotychczasowego singletonu. Osobno integracja AMD (ON), osobno GUI per preview/editor session. Intel/NVIDIA adapter zachowuje obecny default aż do odrębnej analizy. Testy: dwie sesje z tym samym key, toggle bez wpływu na drugą, resize/font/cfg/source zmiana, A→B→A, mutacja obrazu i metadata, współbieżność, zamknięcie i reset sesji; smoke każdego konsumenta. Nie wdrożono.

## 8. Historyczne audio/remux — osiągalność

| Ścieżka | Aktywacja / użycie | Kompatybilność i decyzja |
|---|---|---|
| Single Live Mux → output.mp4.part → final | AMD_DIRECT_MUX default true, AMD_SINGLE_PASS_AV_MUX default true, AMF produkcyjny; single i multi. HEVC przez named pipe, audio z oryginalnych MP4 przez concat plan tekstowy; c:a copy | Produkcja, zachowano. `.part` jest docelowym kontenerem przed rename, nie MP4 do późniejszego remuxu. |
| `.part.temp_video.mp4`, Stage A | multi-file i jawne AMD_SINGLE_PASS_AV_MUX=0 przy działającym direct mux | Diagnostyczna historyczna ścieżka video-only; nie wymagana przez produkcyjny default, lecz osiągalna i powiązana z recovery/testami. Nie usuwać mechanicznie. |
| Stage B / C | multi + istniejący stage_video + single_pass=false; Stage B zapisuje concat tekstowy, C kopiuje video/audio do .part | Dodatkowy remux sprzeczny z wymaganym produkcyjnym kontraktem. Wycofać w osobnym etapie po decyzji o diagnostyce/recovery i aktualizacji testów. Nie zmieniono. |
| raw `.h265` / `.h264` + file remux | AMD_DIRECT_MUX=0 albo CreateNamedPipe failure albo Popen live mux failure; finalizacja else :7651 | **Może włączyć się automatycznie w obsłudze błędu normalnego eksportu**, nie tylko przez flagę. Historyczny fallback. Osobny projekt fail-closed Single Live Mux z recovery/error testami; wymaga zgody na zmianę potoku. |
| SUBMIT_NO_MUX / BYPASS | Diagnostyczny AMF mode; pomijanie finalizacji mux | Nie spełnia produkcyjnego A/V kontraktu, pozostawić jako jawne diagnostyki poza produkcją. |
| local scratch helper | AMD_LOCAL_SCRATCH_DIR lub tempfile wewnątrz helpera; brak produkcyjnego callera | Używany przez testy kompatybilności, zachowano. stage_scratch_dir=None, więc dawne rmdir/metryki nie działają w obecnej produkcji. |
| Anulowanie | `_cleanup_cancelled_amd_outputs` / `_abort_direct_mux`, niedokończone .part/stage/concat | Wymagany lifecycle. Nie usuwa completed output; nie jest drugim muxem. Zachowano. |
| Błąd finalizacji już działającego live mux | zachowanie partial + raise MuxError/AMDNativeFinalizationError; streaming propaguje finalization exception | Zachowano; odróżnić od failure podczas tworzenia pipe/muxera, który przełącza na file mux. |
| Native False → software exporter | streaming.py po nieudanym native, jeśli nie cancel | Osiągalny adapter recovery/backend capability. Nie zmieniono wspólnego dispatch; wymaga osobnej analizy kontraktu finalizacji. |

Nie znaleziono w produkcyjnym Python src `audio_cache`, `ensure_audio_cache`, osobnego M4A ani ADTS. `.audio.concat.txt` zawiera listę oryginalnych MP4, nie wydzielone audio. Na dysku są historyczne artefakty scratch i raw/test pliki; nie usuwano ich. Nie wprowadzono audio extraction, pośredniego MP4 ani dodatkowego remuxu.

## 9. Bezpiecznie usunięte elementy i archiwa

Usunięto wyłącznie pierwsze `clear_bar_cache`. Nie skasowano fizycznie żadnego .pyc, .pyd, DLL, .lib, .exp ani katalogu scratch.

- W `src` na dysku: **167 .pyc**. `git ls-files '*.pyc'`: **0**. `.gitignore:23–24` wyklucza `__pycache__/` i `*.pyc`.
- Dostępny w głównym repo `TeleM_project.zip`: 1872 entries, **0 .pyc, 0 __pycache__**. ZIP z opisu użytkownika nie został dostarczony jako wskazany plik; nie utożsamiono go z tym archiwum. Obecność 167 plików na dysku nie dowodzi ich obecności w każdym ZIP-ie.
- Nie znaleziono wersjonowanego ogólnego generatora source ZIP. Dodano `tools/create_source_archive.py` i `tools/SOURCE_ARCHIVES.md`: snapshot bieżącej zawartości Git-tracked files, jawne wykluczenie pycache/pyc/pyo, exclusive-create ZIP (brak nadpisania). Skrypt nie dołącza nowych nieśledzonych plików ani ignored runtime — wymaga sprawdzenia statusu przed archiwizacją; nie jest paczką portable.
- Functional fixture w tymczasowym repo: śledzone .pyc i __pycache__ nie weszły do ZIP; .pyd/DLL/.lib/.exp weszły; próba nadpisania odmówiona. Nie tworzono ogromnego nowego archiwum produkcyjnego.
- `scripts/sync_portable.py` wyklucza pycache i używa allowlist rozszerzeń bez .pyc; nie uruchamiano.
- `tools/build_portable_release.py` pomija katalogi __pycache__, ale kopiuje wszystkie pliki z innych src directories, więc orphan .pyc poza pycache mogłyby zostać skopiowane; denylist extensions nie ma .pyc. Zgłoszone do osobnego etapu packagera, bez zmiany portable/backendów. Dodatkowo jego EXPECTED_AMD_DLL_SHA256 (`90be...`) różni się od aktualnej DLL (`7f93...`); nie korygowano bez odrębnej walidacji wydania.

## 10. Pozostawione dla kompatybilności

Zachowano `_segment_gradient_stops`, `get_bar_cache_stats`, `_create_amd_local_scratch_dir`, opis `_ImagingMemoryInstance`, aktywne diagnostyki AMF, stare Stage A/C i file mux fallback, cleanup recovery, wszystkie publiczne importy i sygnatury rendererów. Zachowano natywny GPMF `src/native/gpmf/telem_gpmf_native.pyd` (SHA256 `a47757fcdf26d680a5455f024ea64976d0c923f81184bb83d06391d0afcbdaa0`) i drugi śledzony parser `.pyd` w runtime/telemetry_parser. Nie przeprowadzano przebudowy ani synchronizacji.

## 11. AMD 40 FPS i kontrola realnego eksportu

Jawnie zastosowana para spoza BENCHMARKS: `D:\Comparator\GX010345.MP4` + `C:\Users\Malcerz\AppData\Local\SportCamHUD\remote_telemetry\garmin\24621925414.fit`. Para pochodzi z zapisanych wyników 5L i raportu known-good, nie z domysłu nazw/czasów. Plik FIT istnieje. Harness: `SportCamHUD.py --test-amd-export --mode direct --video ... --fit ... --frames 1500 --start-seconds 120 --quality FAST --codec hevc --bitrate 45M --layout ... --output ... --result-json ...`.

Kopie aktualnego pełnego HUD w artifacts; cienie kompasu jawnie ON, distance=3, length=5, opacity=.7, fade=.5. Oryginalny def_layout bez zmian. Te konfiguracje służą audytowi, nie są dowodem identycznego workloadu każdego historycznego pomiaru 5L. Brak AMD_* overrides; fingerprint `ed2077e94adedf1882f3051bc895da0fddf272ba3fa20916cca9c0f4d2739abf`, SYNC/queue_depth=0/VP REFERENCE, single_pass_av_mux=true. Historyczny opis ASYNC/depth2 nie odpowiada bieżącemu profilowi — nie zmieniano konfiguracji w celu uzyskania oczekiwanego wyniku.

| Próba | Render FPS (stats/harness) | Process Effective FPS (cały benchmark GUI) | Export Effective FPS | Wynik |
|---|---:|---:|---:|---|
| NEEDLE, control_needle | 40.85294 | 35.07 | 39.96926 | 1500f, 3840×2160 HEVC + AAC, QP28, valid |
| ROSE, control_rose_verified | 40.48282 | 34.85 | 39.64715 | 1500f, 3840×2160 HEVC + AAC, QP28, valid |

W pierwszej próbie `control_rose` użyto błędnego `compass_mode`; resolver używa `compass_rotation_mode`/legacy `compass_motion_mode`, więc tę próbę **odrzucono jako dowód ROSE**. Poprawiono kopię layoutu, sprawdzono resolver i normalize_layout, powtórzono realny eksport do nowego pliku. Pierwszy control_needle poprawnie rozwiązywał default NEEDLE; późniejsza kopia layoutu ma już canonical key. Log początkowej próby przechowuje jej rzeczywisty layout hash.

FFprobe: 1500 klatek wideo, video duration 50.050 s, audio 50.069333 s; końcowe pliki valid, child exit 0. Profile: Single Live Mux true, Stage A N/A/path None/size0, Stage C elapsed0. Brak zmian DLL, parametrów eksportu i QP. GPU Gauge active 1500f, AUTO 1487 region frames / 13 full refresh; layout ma CPU chart fallback z powodu overlap, odnotowany w rzeczywistym profilu, nie ukryty jako pełny GPU chart PASS.

Minimalne usunięcie martwej definicji nie zmienia aktywnego kodu renderowania (dowód AST). Render ~40 FPS potwierdzony w kontrolach. **Brak sparowanego realnego benchmarku HEAD vs patch; statystyczny brak regresji całego eksportu NOT PROVEN.** Mikrobenchmark fallbacku Pillow nie został wdrożony. Process Effective FPS zawiera preload/start/finish i nie należy utożsamiać go z odczytem steady-state 41.1 w historycznym GUI.

## 12. Testy i bramki

| Weryfikacja | Wynik |
|---|---|
| Grupa cache/GUI/compass/mux/cancel/finalizacja, HEAD przed zmianą | 89 passed, 13 failed, 26.15 s |
| Ta sama grupa po usunięciu duplikatu | 89 passed, te same 13 failed, 26.22 s |
| Dodatkowa grupa shadows/effects/bar/orientation/controller/governance/queue/clear | 78 passed, 5 failed, 3.35 s |
| Ta sama dodatkowa grupa z załadowanym Bar z git HEAD | 78 passed, te same 5 failed, 3.95 s |
| Rastery Bar HEAD vs patch: ruler/segments/slope | 12/12 max_diff=0, MAE=0, different_pixels=0 |
| NEEDLE/ROSE canonical resolver, 0→180→45→270→0, cienie ON | Oba max_diff=0, MAE=0, different_pixels=0 |
| AST całego Bar poza usuniętym duplikatem | identyczny |
| Archiwum źródeł: bytecode out / native in / exclusive create | PASS functional fixture |
| Realne AMD 4K 1500f, NEEDLE + poprawiona ROSE | PASS eksport, audio/video valid, Single Live Mux |
| Import Intel/NVIDIA/worker_cache | PASS |
| git diff --check | PASS |

Zestaw główny: test_etap5f_bar_cache_and_immutability, test_cache_and_parity_validation, test_generic_widget_cache, test_gui_freeze_dummy_cache_safety, test_gui_bar_drag_hotfix, test_render_tab, test_render_tab_controls_cleanup, test_compass_rendering, test_compass_source_parity_hotfix, test_amd_direct_mp4_mux, test_render_cancel_process_lifecycle, test_export_finalization_lifecycle. Dodatkowy: test_compass_and_shadow_outline, test_effects_percent_amd_parity, test_bar_integration, test_bar_orientation_contract, test_controller_properties, test_amd_benchmark_governance, test_export_queue_lifecycle, test_amd_native_ordered_map_clear.

13 zastanych błędów: 2 cache parity/mutation Bar, 1 prewarm GUI cache, 2 RenderTab controls/dialog, 1 compass GUI schema, 1 ROSE upright cardinal contract, 6 mux lifecycle/range/failure/cancel. Pięć dodatkowych: 4 orientation/ruler/slope contracts i 1 test źródłowy early-clears. Ostatni wycina źródło od wrappera `_consume_prepared_frame` (:6717), podczas gdy early-clears są wcześniej w `_consume_prepared_frame_impl` (:6049, wywołanie :6463). Dlatego nie znajduje stringa wywołania; sam prefix `native_dll.` nie jest przyczyną błędu testu. Mux mocks tworzą wcześniejsze .part i trafiają w istniejący PARTIAL_OUTPUT_EXISTS guard. Nie zmieniano testów ani guardów, by uzyskać zielony wynik.

**Pełna cache safety FAIL już na baseline; pełne pre-encode pixel parity całego AMD HUD i brak ghostingu GPU NOT TESTED.** Ghosting lokalnego kompasu i Bar parity nie dowodzą GPU readback parity. GUI testy wykonano QT_QPA_PLATFORM=offscreen; ręczny test interakcji widocznego GUI NOT TESTED. Nie uruchamiano całej wielobackendowej suite ani realnego multi-file/cancel/error GPU w tym audycie. Obecne zmiany pozostają reviewable w working tree; pełnego production gate PASS nie zadeklarowano.

Surowe logi/JSON: `Raporty/etap5m_artifacts/`. Wyniki testów Before/After pokazują brak nowych błędów w sprawdzonych zestawach. Bezpośredni test prywatnego wskaźnika Pillow świadomie pominięty.

## 13. Intel / NVIDIA

Eksportery, konfiguracje, runtime i wspólny dispatcher/cache są bez zmian. Usunięta definicja Bar była martwa również dla nich; aktywne API i renderer są identyczne. Importy native exporterów i worker_cache PASS. Realne eksporty Intel/NVIDIA **NOT TESTED** — nie deklarujemy walidacji sprzętowej. Nie wyłączono ich dotychczasowego cache ani nie zmieniono polityki urządzeń/QSV/NVENC.

## 14. Plan refaktoru — do późniejszego wdrożenia

Każdy wiersz to osobny mały etap/commit, z zachowaniem starych importów, sygnatur i adapterów w dotychczasowym module. Bez zmiany defaultów, render order, floating-point rounding czy parametrów kodeka. Najpierw naprawa/ustalenie baseline istniejących failing tests. Nie wycinać równocześnie geometrii, uploadu i lifecycle.

| Etap AMD | Docelowa granica | Walidacja przed następnym etapem |
|---|---|---|
| A1 | amd_native_config: immutable resolved settings + preflight; native runtime binding adapter | fingerprint/options/range/ABI zgodne, 4K smoke |
| A2 | amd_native_geometry: pure clip/union/coalesce/layout roles/dirty supports | existing geometry tests, exact bboxes, Z-order i previous/current coverage |
| A3 | amd_frame_prepare: jawny PrepareContext + PreparedFrame, bez consumer/FFmpeg | byte/pixel parity, cache lifetime, producer timing |
| A4 | amd_gpu_upload: consumer upload buffers/map/chart/gauge, owned/borrowed lifetimes jako jawny kontrakt | native ABI safety, pre-encode parity, queue/cancel/ghosting; osobna zgoda na pamięć |
| A5 | amd_live_mux: pipe/FFmpeg/audio concat plan/open/drain; jeden owner lifecycle | single+multi/audio ranges, one mux, pipe startup failure, partial recovery |
| A6 | amd_profile: counters/accounting/serializacja bez hot-path side effects | identyczne znaczenie Render i Process Effective FPS, narzut profiler OFF/ON |
| A7 | amd_finalize: kontrola output, atomic replace, cancellation/error state machine | finish/cancel/error/disk-full/range/GPMF, brak wtórnego mux |

`export_amd_native_d3d11` pozostaje publiczną fasadą orchestratora; początkowo przekazuje istniejące dane bez przebudowy pipeline. A4/A5/A7 wymagają zgody użytkownika przed zmianą zachowania pamięci/potoku. Problem ABI można zabezpieczyć osobnym etapem przed podziałem monolitu; nie łączyć go z kosmetyczną ekstrakcją.

| Etap GUI | Docelowa granica | Test |
|---|---|---|
| B1 | render_tab_ui builder (sekcjami), klasa QWidget pozostaje | controls/signals/tab sizing, duplicate event handlers osobno |
| B2 | RenderOptions/RenderViewState, jawne snapshoty | normalizacja/serializacja, brak mutacji layoutów job |
| B3 | queue presenter/controller oparty na istniejącym export_queue | kolejność, cancel/pause/retry, generation IDs |
| B4 | preview presenter, ownership sesji/transportu | HUD vs export, resize/fullscreen, seek/end/release |
| B5 | progress presenter, istniejący RenderProgress jako jedyne dane | FPS/ETA/phase, finalizacja/cancel, brak blokowania GUI |
| B6 | result/error presenter | valid output, partial, backend failure i UX, zachowanie sygnałów |

RenderMixin pozostaje adapterem controller API; jego `_render_pipeline` można odciążać dopiero po ustaleniu ownership opcji i callbacków w B2/B3. streaming pozostaje backend routerem; wspólne lifecycle utils wydzielać dopiero po dowodzie backend-neutrality.

| Etap wskaźników | Docelowa granica | Test |
|---|---|---|
| C1 | Bar static layers/text metrics, bez zmiany render_entrypoint | 4K pixel parity ruler/segments/slope |
| C2 | Bar dynamic geometry/markers + pure signatures | min/max, vertical/horizontal, dirty supports, A→B→A |
| C3 | jawny cache/session policy z legacy adapterem | mutation/lifetime/two-session/backend isolation |
| C4 | effects jako wyraźny kontrakt padding/alpha/cache key | shadow/fade/outline, preview/export, clipping |
| C5 | Gauge/Compass static layers dopiero po ustabilizowaniu C3/C4 | NEEDLE/ROSE shadows, 0/360, exact parity wobec aktualnego HEAD |
| C6 | Gauge dynamic geometry/support info (odrębnie od uploadu AMD) | previous/current sweep coverage, no ghosting, performance |

Nie wdrożono żadnego z A/B/C. Każdy rzeczywisty etap wymaga istniejącego harnessu: GX010345 + jawny FIT, full HUD, 4K, NEEDLE/ROSE, cienie, pre-encode parity, cache safety, Single Live Mux, poprawne zakończenie i brak regresji Render/Process Effective FPS. Nie akceptować kosztu FPS za samą estetykę kodu.

## 15. Zmienione pliki i hashe

Zmiany zadania:

- `src/indicators/bar.py`: -9 wierszy, tylko pierwsza definicja clear_bar_cache.
- `tools/create_source_archive.py`: nowy bezpieczny generator source ZIP.
- `tools/SOURCE_ARCHIVES.md`: reguły i ograniczenia archiwizacji.
- Niniejszy raport oraz `Raporty/etap5m_artifacts/`: dowody audytu, kopie layoutów, logi pytest, pomiary publicznych kopii, wyniki/profile/MP4 eksportów i ffprobe.

Nie tworzono commitów. HEAD pozostaje `4587b657f2a678fda2b869b08b91d1eaeb4a530a`; zmiany do przeglądu lokalnego, bez push. Hashe SHA256 plików zmienionych i chronionych są w `etap5m_artifacts/integrity.json`. Siedem chronionych modułów porównano z HEAD po normalizacji CRLF/LF — identyczne. SHA256 nowych źródeł: Bar `757a7a80f3a17189c151fe669c7f3be201543680ad60ae2a41b66d1dffdbae5f`, generator ZIP `ec59e1af9a5cf8c46efa13cdf1d89a8006439303ac854a7db9b4c2af40bea002`.

**Zatrzymano się na audycie i minimalnych porządkach. Następne zmiany ABI/cache/mux i podział monolitów nie zostały rozpoczęte.**
