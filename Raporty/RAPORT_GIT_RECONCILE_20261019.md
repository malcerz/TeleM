# SportCamHUD — zabezpieczenie obu historii i lokalny merge, 2026-10-19

STATUS: LOCAL MERGE PREPARED / PARTIAL VALIDATION. Nie opublikowano main. Pełna zgodność natywnych modułów z Pythonem 3.15 oraz sprzętowe testy AMD/NVIDIA i docelowy SmartSync DJI pozostają NOT TESTED / BLOCKED.

## 1. Stan początkowy
Repo C:\_DEV\SportCamHUD, istniejący main, Git 2.56.0.windows.2.
Lokalny HEAD: 6218eafed79d68a52afb045c6c0c4dce72c6a130.
origin/main: ae5771755a2960367b3dabaeec1c0bdda0e4c6ac.
Wspólny przodek: cd7c3c4891c36a90e132ff0594b71d86ca9cebef.
Rozbieżność main...origin/main: 146 / 10. Listy wszystkich commitów: [lokalne](commits_local_reconcile_20261019.txt) i [zdalne](commits_remote_reconcile_20261019.txt). Fetch nie wykazał zmiany origin/main.

## 2. Zabezpieczenia i odtwarzanie
Stary bundle C:\GoPro\TeleM_backup_20261018\TeleM_all_refs_20261018.bundle istnieje, git bundle verify PASS, complete history, 19 refów. Zawiera e21d625 i ae57717, NIE zawiera późniejszych siedmiu commitów Intel/GUI/SmartSync/raportów. Nie nadpisano go.
safety/pre-commit-20261018 -> e21d625.
Pierwszy push tagów został zablokowany przez brak poświadczeń; po ponowieniu i logowaniu oba tagi opublikowano. Odczyt git ls-remote --tags origin potwierdził:

| Tag na GitHubie | Obiekt tagu | Commit po dereferencji |
|---|---|---|
| safety/sportcamhud-main-20261019 | 159b17ed226b51a6075e1114cec98709c9745c99 | 6218eafed79d68a52afb045c6c0c4dce72c6a130 |
| safety/origin-main-before-reconcile-20261019 | 60fc199a24b26a1b65bf93f25e9663bad8aac44f | ae5771755a2960367b3dabaeec1c0bdda0e4c6ac |

Odtworzenie każdej wersji jest możliwe przez pobranie odpowiedniego tagu z origin i checkout wskazanego commitu w przeznaczonym do odtwarzania repozytorium. Nie wykonywać resetu bieżącej prywatnej pracy. W tej sesji potwierdzono zdalne refy oraz lokalną osiągalność pełnych historii; nie tworzono osobnego klonu odtworzeniowego.

## 3. Merge i rozwiązania konfliktów
Zwykły merge --no-ff origin/main na istniejącym main. Bez reset/rebase/stash/force, nowych gałęzi i worktree.
Konflikty oraz początkowe stadia indeksu: [merge-tree](merge_tree_reconcile_20261019.txt).

- .gitignore: suma niezależnych reguł obu stron; AGENTS.md: zachowane oba kontrakty (live audio i izolacja runtime).
- AMD exporter: konflikt jedynie formatowania importu; produkcyjny kod AMD zachowany.
- Intel exporter: zachowane nowsze VBR, HEVC Slice QP, walidacja Main10 osobno od HEVC 8-bit i live mux. Dodano API odświeżania cache z remote; błędny probe nie używa wcześniejszych pozytywnych wyników.
- streaming: zachowano walidację wybranego kodeka i metadane faktycznego enkodera. RenderMixin nie zastępuje pustego wyboru HDR kodekiem SDR.
- NVIDIA: połączono lokalne P1/P3/P5 oraz override jakości z runtime probingiem funkcji NVENC z remote. Jawny Max Quality/P7 pozostaje dostępny dla zapisanych ustawień/API. Wspólny command builder zachowuje zdalną obsługę FFmpeg NVIDIA 8.1 i highbitdepth.
- RenderTab: zachowano nowszy wybór HEVC Main10/SDR, niedostępne kodeki są widoczne i wyłączone; przy braku HDR wymagany jest jawny wybór SDR. Zachowano dynamiczną listę backendów i NVIDIA z remote. Niedostępny zapisany kodek nie jest automatycznie zastępowany innym.
- runtime_paths: zachowane lokalne aliasy i diagnostyka, dodane odseparowane narzędzia NVIDIA i canonical native source directory. Legacy lokalizacja parsera DJI nadal obsługiwana.
- manifest: zachowano metadane lokalne, dodano schema_version/vendor, ścieżki względem runtime i rzeczywiste hashe/rozmiary istniejących DLL. Nie zmieniono DLL.
- native sources: zachowano aktualny kod Intel przy przeniesieniu do src/native/intel. Hash blobu przed/po identyczny: 4aa43d11a64ad4f64712bb302664497957b65343.
- GPMF: ten sam plik przeniesiono z src/native/gpmf do runtime/common/telemetry/gpmf zgodnie z kontraktem source-only; blob przed/po identyczny: 5612fa9db1371a86458c806665d8119441cea95d. Poprawiono ścieżkę w Portable builderze; bez przebudowy ABI.
- testy Intel: konflikty importów rozwiązano z zachowaniem kanonicznego runtime; zachowano test capability niezależny od obecności konkretnego GPU.
- testy z remote dostosowano do nowszej polityki HDR (wyłączone pozycje zamiast ukrywania, jawny SDR, blokada nieobsługiwanego przywróconego kodeka). Testy wymagające i5-12400/UHD730/P400 mają jawny warunek sprzętowy. Zachowano symulacje nowoczesnego NVENC i P400.

Lista plików integracji: [reconcile_changed_files_20261019.txt](reconcile_changed_files_20261019.txt). Dodatkowo raport i dowody o prefiksie reconcile w Raporty/. Nie zmieniano rendererów przy okazji.

## 4. Testy funkcjonalne i porównanie
Python 3.15: 151 passed, 3 skipped — reconcile_315_final_tests_20261019.log.
Python Portable 3.14: 151 passed, 3 skipped — reconcile_314_tests_20261019.log. Harness pytest i jego czysto pythonowe zależności udostępniono z instalacji 3.15, przy zachowaniu natywnych numpy/PySide6 Portable 3.14. Automatyczne ładowanie dodatkowych pluginów pytest wyłączono.

Te zestawy obejmują ręczny offset FIT/GPX, algorytm SmartSync IMU, zapis/odczyt offsetu, odporność presetów, GUI recovery, bezpieczny wybór kodeka, VBR, live mux, finalizację MP4, izolację runtime i dynamiczne możliwości backendów.

Porównanie istniejących testów ze stanem 6218eaf: 112 PASS przed oraz po integracji, 0 nowych niepowodzeń w tym zestawie. Baseline odczytano przez git archive do scratch/reconcile_baseline_6218eaf (nie worktree); runtime jest junction do istniejącego runtime. Dodatkowe testy backendów: po integracji 40 PASS / 2 FAIL, przed 39 PASS / 1 SKIP / 2 FAIL. Te same dwa FAIL dotyczą niemożności załadowania AMD DLL/zależności na tej maszynie. Nie uznano ich za PASS ani za udowodnione regresje integracji. Pełny pakiet wszystkich testów repozytorium: NOT TESTED.

Rzeczywisty Qt project recovery: PASS start/ready/clear/invalid-video, istniejący harness tools/probe_gui_project_recovery.py. Nowy wynik zapisano w reconcile_gui_project_20261019; poprzedni śledzony result.json przywrócono po skopiowaniu nowego dowodu.
Panel Ustawienia/licencja: PASS, 107 dokumentów, aktywny heartbeat i sondy ffmpeg/ffprobe, tools/probe_gui_license_recovery.py, reconcile_gui_license_20261019/result.json.
Pełna interaktywna ocena wizualna wszystkich ekranów: NOT TESTED.

## 5. Rzeczywisty Intel
GPU: Intel Iris Xe; NVIDIA i AMD nieobecne.
Istniejący canonical Intel GUI harness, para C:\GoPro\GX010378.MP4 + C:\GoPro\2026-10-15_15-03-50.fit, layout Raporty/intel_vbr_qp_20261017/layout.json. Pierwotna para Video/GX020079.MP4 + Video/GX020079.fit nieobecna. Nie podmieniano FIT w istniejącym harnessie.
Macierz tools/run_intel_vbr_matrix.py --phase smoke --smoke-frames 30: 12/12 PASS — native i FFmpeg QSV, HEVC/H264, Fast/Balanced/Quality. Każdy wynik: 30 klatek, 30000/1001 fps, oryginalne AAC, brak błędu dekodowania, różnica czasu audio/wideo <0.1 s, HRD obecne i cbr_flag=0. HEVC: Main 10, yuv420p10le, HLG. Wyniki i pełne komendy: reconcile_intel_matrix_20261019/summary_smoke.json.
Native HEVC: dostępna telemetria Slice QP. Nie oznacza to średniego QP klatki/CU; frame QP nadal niedostępne zgodnie z dotychczasowym kontraktem. Natywne H264 raportuje rzeczywiste próbki QP.
Dodatkowy native HEVC Balanced na Portable 3.14: PASS, 30 klatek i poprawna walidacja MP4; reconcile_intel_20261019/portable314_hevc_balanced.json.
To krótkie smoke testy, NIE benchmark wydajności ani dowód zachowania długookresowego VBV. NVIDIA/AMD GPU, pełny długi eksport i anulowanie sprzętowe: NOT TESTED. Symulowane testy NVENC nie zastępują sprzętu.

## 6. Python i ABI
Audyt importów 175 modułów src w osobnych procesach: 171/175 PASS zarówno 3.15 jak i Portable 3.14. Szczegóły: reconcile_imports_20261019/modules.json. Trzy harnessy źródłowe AMD nie ładują amfrt64.dll; historyczny prototype_nvidia_stage8e ma błąd typu GUID (c_ubyte/c_byte). Nie poprawiano tych odziedziczonych prototypów.

| Środowisko | numpy / Qt | SmartSync Python | DJI native | GPMF native | Intel export |
|---|---|---|---|---|---|
| Portable 3.14.7 | PASS, 2.5.1 / 6.11.1 | PASS | PASS import cp314 | PASS po inicjalizacji Qt, jak w aplikacji | PASS native HEVC |
| System 3.14.8 | FAIL, brak numpy i PySide6 | BLOCKED przez brak numpy | PASS import cp314 | bez Qt/zależności FAIL | NOT TESTED |
| System 3.15.0 | PASS, 2.5.4 / 6.12.0 | PASS | FAIL, brak modułu ABI 3.15 | FAIL, plik zależy od python314.dll | PASS native i FFmpeg |

Bezpośredni import GPMF w czystym Portable bez Qt zgłasza brak DLL VC++; po załadowaniu Qt istniejący loader poprawnie importuje niezmieniony GPMF. Zapisano osobny dowód native_gpmf_after_qt.json. Nie zadeklarowano pełnego PASS zgodności 3.15. Potrzebne są osobne buildy ABI, nie zastąpiono binariów cp314.
SmartSync DJI z realnym IMU i pasującym FIT: NOT TESTED — brak odpowiedniego materiału. Syntetyczny algorytm i kontrakty synchronizacji PASS; nie zastępują docelowego DJI.

## 7. Prywatna praca i Git
Zachowano niezacommitowane def_layout.json: font Digital-7 Mono PL, amd_hdr_mode=preserve_hlg, auto_activity_source=garmin. Nie dodano tego pliku do merge commitu.
Zachowano nieśledzone: C (321 B, sam nagłówek CSV), pusty RAPORT_INTEL_HEVC_SLICE_QP_20261017.md w root, font third_party/Digital-7 Mono PL.ttf (36540 B), obie kopie runtime/intel/bin/telem_intel_native.dll.bak_*. Żadnego automatycznego usuwania ani stash.
git diff --check dla niezacommitowanej pracy: PASS. Pełny staged diff ma odziedziczone trailing whitespace w źródłach SDK i raportach z remote (reconcile_staged_whitespace_20261019.log); nie przepisywano dostarczonych SDK tylko dla formatowania. Poza blank-at-eol/EOF kontrola staged diff PASS. Nie ukrywa to błędów semantycznych ani konfliktów: indeks bez unmerged entries.

## 8. Publikacja i ograniczenia
Obie stare historie pozostają w tagach i stanowią rodziców lokalnego merge. Commitów 835d857, 6fa9a1d, 67dfce7, 6d41d1e, 535fb7a, d79a682 i 6218eaf nie przepisano. Wszystkie 146 lokalnych i 10 zdalnych commitów mają pozostać przodkami nowego main; końcowe sprawdzenie Git zapisane po utworzeniu merge.
Nie wykonano push main. Zgoda użytkownika jest wymagana przez punkt 8 jego prośby, dopiero po przedstawieniu wyników. Docelowo wyłącznie zwykły fast-forward.
Ryzyka: niepełna zgodność natywnych parserów 3.15, brak testów AMD/NVIDIA na sprzęcie, brak docelowego DJI IMU/FIT i pełnej wizualnej oceny GUI, brak pełnego pakietu testów i długiego benchmarku. W testowanych kontraktach nie wykryto nowych regresji; globalnego braku regresji NIE UDOWODNIONO.

## 9. Końcowe potwierdzenie po merge
Merge commit: 482e9437b767086df5e42af0283f40556d7f2db1.
Rodzice: 6218eafed79d68a52afb045c6c0c4dce72c6a130 oraz ae5771755a2960367b3dabaeec1c0bdda0e4c6ac.
Sprawdzenie pełnych zbiorów rev-list: zachowano 146/146 lokalnych oraz 10/10 zdalnych commitów, w tym wszystkie siedem najnowszych commitów lokalnych. Oba testy merge-base --is-ancestor PASS. Indeks bez konfliktów.
origin/main...main po merge: 0 / 147. Uzupełnienie niniejszego raportu dodaje wyłącznie commit dokumentacyjny, więc po nim oczekiwane 0 / 148; końcowy fetch i odczyt są wykonywane przed odpowiedzią użytkownikowi.

Nowy, osobny bundle C:\GoPro\TeleM_backup_20261018\SportCamHUD_reconciled_20261019.bundle: git bundle verify PASS, complete history, 22 refy, main 482e943 i oba tagi bezpieczeństwa. Zawiera kod merge i obie historie, w tym najnowsze Intel/GUI/SmartSync. Nie nadpisano starej kopii. To niezależna lokalna możliwość przywrócenia obu wersji i wersji scalonej; późniejsze dokumentacyjne uzupełnienie raportu nie jest w tej kopii.

Working tree po merge: jedyna śledzona modyfikacja def_layout.json (prywatna, identyczna z początkiem sesji); te same prywatne pliki nieśledzone C, pusty raport w root, obie kopie DLL i font. Brak zmian kodu poza commitami. Materiały wideo testów i screenshoty pozostają lokalnymi artefaktami ignorowanymi przez istniejący .gitignore. Błąd git add dotyczący ignorowanych PNG nie dotyczył źródeł ani raportów; commit zawierał wszystkie przygotowane nieignorowane dowody. Screenshotów nie wymuszano do Git.
Kontrola manifestu po dodaniu wpisu GPMF: 1 PASS. git diff --check: PASS.

Main jest technicznie gotowy do zwykłego push fast-forward pod warunkiem niezmienionego origin/main, z ograniczeniami testowymi opisanymi powyżej. Nie oznacza to pełnego PASS wszystkich kryteriów produktu. Publikacja pozostaje wstrzymana do wyraźnego zatwierdzenia użytkownika.
