# SportCamHUD Intel — benchmark na zasilaczu i kontrola stabilności, 2026-10-19

STATUS: pomiary na zasilaczu wykonane. Ścieżka SharedMemory działa stabilnie (30/30 eksportów native + 4 FFmpeg, 0 zawieszeń). 55 FPS z pełnym HUD osiągane tylko w pierwszych minutach obciążenia; po wejściu platformy w limit mocy wynik spada do 37–44 FPS, także po 5 min schładzania. Push: nie wykonano.

## 0. Stan początkowy i zakres

- `main`, HEAD `7874a78` (po commicie poprawki `5896e38`). Zastana praca nietknięta: `def_layout.json`, `C`, font, kopie `.bak`, raport root, a także niezacommitowany raport sesji diagnostycznej `Raporty/RAPORT_INTEL_C_R3_HANG_AND_VIDEO_ONLY_1799_20261019.md` i jej katalogi `C_r31…C_r36`.
- Nie zmieniano: VBR, jakości, HUD, kodeków, DLL, rendererów AMD/NVIDIA. Nie wdrażano kolejnych optymalizacji GPU.
- Zasilanie: Windows API `SystemInformation.PowerStatus.PowerLineStatus = Online` przed startem. Narzędzie dostało `--require-ac`: przed każdym przebiegiem przerywa, jeśli `GetSystemPowerStatus().ACLineStatus != 1`. Wszystkie przebiegi z tego raportu: AC przed i po = 1. Plan zasilania: „Wysoka wydajność”.
- Uśpienie systemu zablokowane na czas pomiarów (keep-awake aplikacji; nie chroni przed zamknięciem pokrywy). Narzędzie wykrywa przerwę w próbkowaniu > 10 s jako `system_standby_suspected`: 0 przypadków.

## 1. Konfiguracja (bez zmian względem RAPORT_INTEL_QSV_PIPELINE_PERFORMANCE_20261019)

`C:\GoPro\2026-10-16\GX010381.MP4`, 1800 klatek, native Intel HEVC Main10 Fast (TU7), VBR 40/50 Mb/s, VBV 10000/5000 KB. FIT `C:\GoPro\2026-10-16\2026-10-16_13-06-05.fit` (z projektu użytkownika `GX010381.toproj`). Layout `Raporty/intel_vbr_qp_20261017/layout.json` (18 aktywnych wskaźników), „bez HUD” = ten sam layout z `enabled=false`. Harness kanoniczny `SportCamHUD.py --test-intel-export`, narzędzie `tools/benchmark_intel_qsv_pipeline.py`. Warianty native uruchamiane z `TELEM_HUD_STARTUP_TRACE=1` (kilka linii logu na eksport), żeby potwierdzić równoległy start workerów.

## 2. Wyniki na zasilaczu (1800 klatek)

Seria główna: rozgrzewka (C) + C/A/B naprzemiennie ×3 (rep 41–43), przerwa 20 s.

| Przebieg | Render FPS | Stan ustalony 500–1500 | 1. klatka | Czas całk. | 3D | VideoProc | VDBox (2×) | CPU perf |
|---|---|---|---|---|---|---|---|---|
| rozgrzewka C | 66.66 | 70.9 | 1.50 s | 28.10 s | 97.5% | 12.1% | 61.1% | 138% |
| C r41 | 66.52 | 70.9 | 1.51 s | 28.13 s | 96.7% | 12.1% | 60.9% | 136% |
| A r41 | 71.52 | – | – | 25.17 s | 64.4% | 0% | 60.9% | 128% |
| B r41 | 63.35 | 65.8 | 1.17 s | 29.37 s | 84.6% | 12.2% | 76.0% | 131% |
| C r42 | 66.78 | 70.9 | 1.42 s | 27.98 s | 96.4% | 12.2% | 63.6% | 140% |
| A r42 | 69.44 | – | – | 25.92 s | 65.5% | 0% | 60.4% | 64% |
| B r42 | 51.36 | 54.6 | 1.98 s | 36.84 s | 83.8% | 11.0% | 57.1% | 56% |
| C r43 | 43.82 | 46.3 | 2.40 s | 42.81 s | 90.6% | 11.2% | 57.8% | 54% |
| A r43 | 68.14 | – | – | 26.42 s | 65.5% | 0% | 60.8% | 70% |
| B r43 | 51.84 | 56.5 | 2.07 s | 36.49 s | 83.2% | 11.2% | 78.4% | 57% |

Mediana i zakres (rep 41–43, bez rozgrzewki):

| Wariant | Mediana render FPS | Zakres | Mediana stanu ustalonego | Mediana 1. klatki | Mediana czasu |
|---|---|---|---|---|---|
| A FFmpeg QSV bez HUD | 69.44 | 68.14–71.52 | – | – | 25.92 s |
| B native bez HUD | 51.84 | 51.36–63.35 | 56.5 | 1.98 s | 36.49 s |
| C native pełny HUD | 66.52 | 43.82–66.78 | 70.9 | 1.51 s | 28.13 s |

Seria długotrwała: 5 min bezczynności, potem C ×4 jeden po drugim (rep 61–64), na koniec A i B (rep 65).

| Przebieg | Render FPS | Stan ustalony | 1. klatka | Czas całk. | Encode Sync | 3D | CPU perf |
|---|---|---|---|---|---|---|---|
| C r61 | 37.34 | 38.6 | 2.18 s | 49.83 s | 25.4 ms | 87.2% | 54% |
| C r62 | 42.75 | 45.9 | 2.14 s | 43.76 s | 21.9 ms | 88.9% | 58% |
| C r63 | 42.26 | 45.2 | 2.18 s | 44.27 s | 22.2 ms | 88.8% | 57% |
| C r64 | 40.84 | 41.8 | 2.14 s | 45.76 s | 23.1 ms | 87.3% | 55% |
| A r65 | 68.67 | – | – | 26.2 s | – | 63.0% | 61% |
| B r65 | 52.35 | 54.3 | – | 46.6 s (proces) | 18.0 ms | 81.0% | 58% |

Wszystkie 7 eksportów C na zasilaczu (1800 klatek): 66.52, 66.78, 43.82, 37.34, 42.75, 42.26, 40.84 → **mediana 42.75 FPS**, zakres 37.34–66.78.

Taktowanie i moc GPU: **NOT AVAILABLE** (brak liczników bez narzędzi Intel/administratora). Temperatura strefy ACPI 46–57°C we wszystkich przebiegach (to nie jest temperatura rdzenia).

## 3. Co ogranicza wynik na zasilaczu

- Przebiegi szybkie (rozgrzewka, C r41, C r42) i wolne różnią się stanem platformy, nie kodem: „% Processor Performance” spadł z ~130–140% (turbo) do ~54–70% od ok. 21:41 i nie wrócił po 5 min bezczynności. Wolne przebiegi mają dłuższe Encode Sync (14 → 21–25 ms) przy nadal wysokim 3D, czyli GPU działa wolniej.
- W szybkich przebiegach WMI `BatteryStatus.DischargeRate` pokazywało **rozładowanie baterii o 1.1–1.9 W mimo podłączonego zasilacza** (`PowerOnline=True`). Od ok. 21:41 rozładowanie = 0 i od tego momentu wydajność jest niska. Interpretacja: w szybkiej fazie system dobierał moc z baterii ponad możliwości zasilacza, potem przeszedł na sam zasilacz z niższym limitem mocy pakietu. Mocy zasilacza nie dało się odczytać — **NOT PROVEN**. Do sprawdzenia: moc ładowarki (urządzenie Surface) i ustawienia trybu zasilania/DTT.
- FFmpeg A traci niewiele w stanie ograniczonym (68–69 FPS), bo prawie nie używa CPU i nie ma VP Blt ani uploadu HUD. Native z HUD dzieli ten sam budżet mocy z workerami HUD na CPU i dokłada pracę 3D (VP Blt, upload HUD), więc traci najwięcej. Zgodne z diagnozą z poprzedniego raportu: silnik 3D jest wąskim gardłem stanu ustalonego.
- B w tej serii wypada gorzej niż C (51.8 vs 66.5 mediany), bo dwa z trzech przebiegów B trafiły już w stan ograniczony, a dwa z trzech C jeszcze nie. To efekt kolejności przebiegów, nie różnicy wariantów. W porównywalnym stanie B ≥ C (B r41 63.3 vs C r41 66.5 → oba szybkie; B r65 52.3 vs C r61–64 37–43 → oba ograniczone).

## 4. Porównanie z wynikami na baterii (ten sam kod `5896e38`, ten sam materiał)

| Warunek | A FFmpeg | B bez HUD | C pełny HUD | Stan ustalony C | 1. klatka C |
|---|---|---|---|---|---|
| Bateria 42→30%, ograniczenie mocy (poprzedni raport, ×3) | 61.5 (61.3–65.1) | 53.6 (51.4–56.4) | 52.6 (51.0–57.3) | 56.2 | 2.23 s |
| Zasilacz, faza szybka (rozgrzewka + r41–r42) | 71.5 / 69.4 | 63.3 | 66.5–66.8 | 70.9 | 1.42–1.51 s |
| Zasilacz, faza ograniczona (r43, r61–r65) | 68.1–68.7 | 51.4–52.3 | 37.3–43.8 | 38.6–46.3 | 2.14–2.40 s |

Wniosek: na tym zasilaczu, po kilku minutach pracy, eksport z pełnym HUD jest **wolniejszy niż na częściowo naładowanej baterii** (42.8 vs 52.6 mediany). Najlepsze wyniki daje tylko faza z dodatkową mocą z baterii.

## 5. Weryfikacja

| Pytanie | Wynik |
|---|---|
| Mediana z pełnym HUD > 55 FPS | Seria 3×: TAK (66.52), ale jeden z trzech przebiegów już 43.82. Wszystkie 7 przebiegów C na zasilaczu: NIE (42.75). W pracy ciągłej: **NIE**. |
| Stan ustalony > 60 FPS | Tylko w fazie szybkiej: TAK (70.9). W fazie ograniczonej: NIE (38.6–46.3). |
| Start workerów HUD równoległy | TAK we wszystkich 30 eksportach native z tej sesji (12×1800 + 18×300 klatek): 4 workery tworzone w ≤ 0.083 s, `InitBlob=ON`. |
| MP4 zachowuje wszystkie klatki | TAK: 1800/1800 we wszystkich eksportach 1800-klatkowych, 300/300 w seriach direct i queue. SHA256 pakietów wideo i audio pełnego HUD (`fbbd3c0b…` / `d7acdb75…`) i bez HUD (`335f40b5…`) identyczne z przebiegami na baterii. |
| Live mux audio i finalizacja | TAK: `audio_live_mux=True`, A/V < 0.1 s (walidacja harnessu), finalizacja 0.21–0.77 s, bez `ensure_audio_cache` i bez plików pośrednich audio. |
| Brak zawieszeń w kolejnych eksportach | 0 zawieszeń w 34 eksportach tej sesji (12× native 1800 klatek, 4× FFmpeg A, 18× seria stabilności 300 klatek), 0 zadziałań watchdoga, 0 przerw próbkowania. |

## 6. Zawieszenie na klatce 100 (C_r3)

- Diagnoza z sesji diagnostycznej (dowody w `RAPORT_INTEL_C_R3_HANG_AND_VIDEO_ONLY_1799_20261019.md`): w czasie C_r3 laptop wszedł w Modern Standby po zamknięciu pokrywy (Kernel-Power 506 „Lid” 16:47:09, wyjście 507 o 17:33:11; dziura 2766 s w `battery.csv`). Proces był zamrożony, a po wybudzeniu narzędzie zabiło go jako „timeout”.
- Seria powtórzeń w tej sesji, z zasilaniem i włączonym keep-awake:
  - 8× direct 300 klatek: 8/8 OK, 300/300 klatek, audio live.
  - 6× kolejka (queue) 300 klatek: 6/6 OK, 300/300 klatek.
  - 6× anulowanie (GUI Cancel po 150 klatkach przez nową opcję harnessu `--cancel-after-frames`, wywołującą `RenderTab._on_cancel` jak przycisk): 6/6 zakończone `cancelled=True` w 16.7–18.9 s; workery kończone (`_RenderExecutor.__exit__ cancel: terminating 4 workers`), brak częściowego MP4, natywny eksport zgłasza `success=NO (cancelled)`.
  - Do tego 12 eksportów native 1800 klatek (rozgrzewka, C/B rep 41–43, C rep 61–64, B rep 65) i 6 powtórzeń sesji diagnostycznej (C_r31–C_r36).
- Sprzątanie SharedMemory: po każdym eksporcie (także anulowanym) eksporter pod `TELEM_HUD_STARTUP_TRACE=1` zamyka blok i próbuje go ponownie otworzyć po nazwie: `released=YES` w 18/18 eksportach serii stabilności.
- Dodana diagnostyka: watchdog faulthandlera harnessu 300 s (zrzut stosu przy prawdziwym zawieszeniu), wykrywanie uśpienia systemu w narzędziu, kontrola zasilania, kontrola zwolnienia SharedMemory.
- **Nie deklaruję naprawy.** Zawieszenia nie odtworzono (0 w 30 eksportach native tej sesji i 0/6 w sesji diagnostycznej). Dowody wskazują na uśpienie systemu, nie na blokadę w kodzie, ale brak odtworzenia nie jest dowodem, że w kodzie nie ma zakleszczenia.

## 7. Ryzyko odkryte przez sesję diagnostyczną: wyścig flush enkodera

`intel_native_pipeline_finish` przerywa pętlę flush przy każdym statusie innym niż `MFX_ERR_NONE` (nie ponawia `MFX_WRN_DEVICE_BUSY`). W każdym eksporcie jedna klatka jest buforowana przez enkoder (`MFX_ERR_MORE_DATA`, `submitted=1799`) i wychodzi dopiero przy flushu. W trybie diagnostycznym VIDEO_ONLY flush przychodzi za szybko i ostatnia klatka ginie (4/4 → 1799). W ścieżkach produkcyjnych zamykanie workerów HUD daje enkoderowi czas, więc wszystkie eksporty tej sesji miały pełną liczbę klatek. Utrata klatki zależy jednak od czasu, więc ryzyko pozostaje dla produkcji. Nie poprawiano (poprawka w DLL Intel jest poza zakresem tego etapu) — propozycja osobnego zadania.

## 8. Testy

- Usunięte nieaktualne założenia QP (diagnostyka QP nie wraca do produkcji):
  - `tests/test_intel_av1_quantizer.py` — przepisany: sprawdza, że `IntelCompressionTracker` nie istnieje, ABI statystyk 752 B zachowuje tylko pola `reserved_quant_*`, karta kolejki nie pokazuje QP/Quantizer nawet dla starych pól, `notify_render_done` przyjmuje stare argumenty QP, ale ich nie zapisuje, a plik kolejki ze starymi polami nadal się wczytuje. Błąd zbierania testów (import usuniętej klasy) usunięty.
  - `tests/test_export_gpmf_and_qp_summary.py` — 3 testy QP zamienione na kontrakt „podsumowanie eksportu nie pokazuje QP”.
  - `tests/test_amd_vbr_qp_status.py` — 4 testy QP zamienione na kontrakt „status renderu nie pokazuje QP”, także dla AMD i starych pól snapshotu. Kod AMD bez zmian.
- Codec selector (`tests/test_intel_native_8b.py`, `tests/test_intel_native_8c.py`): testy zakładały stary kontrakt „lista tylko dostępnych kodeków”. Od `bc2b173` GUI celowo pokazuje wszystkie kodeki w stałej kolejności, a niedostępne wyłącza; domyślny AV1 10-bit, inaczej HEVC Main10. Testy zaktualizowano do obecnego kontraktu, GUI bez zmian.
- Testy celowane (Intel ×41 plików, SHM, izolacja runtime, SmartSync, presety, capability, async, live mux): **325 passed, 7 skipped, 0 failed, 0 błędów zbierania** (`intel_qsv_pipeline_20261019/pytest_targeted_ac.log`). Pominięcia: 5× brak hooka self-test Slice QP w DLL (oczekiwane po usunięciu QP), 1× wymaga i5-12400/UHD 730, 1× brak sprzętowego AV1.
- Pliki QP poza zestawem Intel (`test_export_gpmf_and_qp_summary`, `test_qp_analyzer`, `test_amd_qp_governance`, `test_amd_vbr_qp_status`): 45 passed, **7 failed** — wszystkie 7 to testy ścieżek eksportu w `test_export_gpmf_and_qp_summary.py`, które używają nieistniejących tu ścieżek `D:\Video` i `E:\Exports`, podczas gdy `src/export_paths.py` sprawdza dostępność katalogu. Zależne od maszyny, niezwiązane z QP — nie poprawiane (poza zakresem).
- Nowe/zmienione narzędzia: `--require-ac`, `--frames`, warianty `_Q` (kolejka) i `_CANCEL` (anulowanie), wykrywanie uśpienia, metryki `cancelled`/`mp4_frames`; harness `--cancel-after-frames N`; eksporter: kontrola zwolnienia SharedMemory pod `TELEM_HUD_STARTUP_TRACE=1`.
- NOT TESTED: AMD/NVIDIA (brak sprzętu), eksport wieloplikowy, ręczne GUI, moc ładowarki.

## 9. Zmienione pliki

- `tools/benchmark_intel_qsv_pipeline.py` — kontrola AC, wykrywanie uśpienia, `--frames`, warianty kolejki i anulowania.
- `src/gui/qt/application.py` — opcja harnessu `--cancel-after-frames` (tylko tryb `--test-intel-export`).
- `src/ffmpeg/intel_native_exporter.py` — log zwolnienia bloku SharedMemory pod flagą śladu (bez zmiany zachowania).
- `tests/test_intel_av1_quantizer.py`, `tests/test_intel_native_8b.py`, `tests/test_intel_native_8c.py`, `tests/test_export_gpmf_and_qp_summary.py`, `tests/test_amd_vbr_qp_status.py`.
- Dowody: `Raporty/intel_qsv_pipeline_20261019/` — `warmup_C_TR_r0`, `*_r41–43`, `*_r51–56`, `C_TR_r61–64`, `*_r65`, `ac_summary_20261019.json`, `stability_summary_20261019.json`, logi serii i pytest. Pliki MP4 nie są w Git.

## 10. Podsumowanie

| Kryterium | Wynik |
|---|---|
| Zasilanie sieciowe potwierdzone przez Windows API | PASS (Online przed i po każdym przebiegu) |
| A/B/C ≥ 3 pomiary po rozgrzewce | PASS |
| Mediana C > 55 FPS | PASS w serii 3× (66.5), **FAIL w pracy ciągłej** (mediana 7 przebiegów 42.8) |
| Stan ustalony > 60 FPS | PASS tylko w fazie szybkiej (70.9); FAIL w fazie ograniczonej |
| Równoległy start workerów | PASS (30/30) |
| Komplet klatek, audio live, finalizacja | PASS |
| Brak zawieszeń, kolejka, anulowanie, sprzątanie SharedMemory | PASS (34/34 eksportów, 6/6 anulowań, 18/18 `released=YES`) |
| Zawieszenie C_r3 naprawione | NOT PROVEN (nieodtworzone; dowody wskazują na uśpienie systemu) |
| Testy QP i codec selector | PASS (0 błędów zbierania); 7 testów ścieżek eksportu zależnych od maszyny — FAIL, poza zakresem |
| Ryzyko utraty ostatniej klatki (flush) | OTWARTE — do osobnego zadania |
