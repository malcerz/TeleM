# SportCamHUD — Synchronizacja telemetrii FIT/GPX ↔ wideo: SmartSync IMU (DJI) + regulacja ręczna

Data: 2026-10-18 · Gałąź: `main` · HEAD: `e21d625c0f` (= `origin/main`) · Maszyna: Intel i7-1265U / Iris Xe, Python 3.15.0

## 0. Stan Git i bezpieczeństwo

- Na początku zadania **nie było `git.exe`**; historię i status analizowano własnym, wyłącznie odczytującym czytnikiem `.git`. W trakcie użytkownik zainstalował git (`C:\tools\Git`, 2.56). `git status` potwierdził ten sam zestaw zmian, a `git log --all -S` potwierdził ustalenia: `telemetry_sync_offset_s` pojawia się tylko w `02f4117` i `b1e6507` (klucz cache); `fit_offset_s`, `src/telemetry_dji_smartsync.py` i `tests/test_dji_smartsync.py` nie występują w żadnym commicie. Zgodne z niezależnym audytem `Raporty/RAPORT_SPORTCAMHUD_DJI_SYNC_LOSS_AUDIT_20261018.md` (292 commity).
- `main` = `origin/main` = `e21d625c0f` → poprzednia wersja jest na GitHubie (`malcerz/TeleM`), są też gałęzie `backup/*`.
- Przed zadaniem w drzewie było **25 niezacommitowanych plików użytkownika** (Intel, GUI: `project_mixin`, `main_window`, `signals`, `controller`, `application`, `render_tab`…). Zostały zachowane; moje zmiany w tych plikach to wyłącznie dopisane linie. Kopia stanu sprzed zadania (`src/gui`, `src/ffmpeg`, `tests`, `def_layout.json`, `tools/...`) leży w scratchpadzie sesji (`backup_pre_sync/`).
- **Nic nie zostało zacommitowane ani wypchnięte** (brak gita; zgodnie z poleceniem bez push). `def_layout.json` — bajtowo identyczny z kopią sprzed zadania.

## 1. Co odnaleziono w historii Git

Przeszukano wszystkie commity osiągalne z wszystkich gałęzi/tagów (lokalnych i `origin/*`) pod kątem m.in. `telemetry_sync_offset_s`, `SYNCHRONIZACJA`, `btn_sync`, `spin_sync`, `fit_offset_s`, `_apply_fit_dataset`, `with_offset`, `dji_smartsync`, korelacji IMU/gyro.

- `telemetry_sync_offset_s` występował **wyłącznie** w `render_preparation.py` / `render_mixin.py` — był czytany z layoutu i wchodził **tylko do klucza cache**, nigdy do próbkowania telemetrii. Żaden commit GUI go nie zapisywał.
- **Brak w całej historii** sekcji GUI „Synchronizacja telemetrii”, przycisków ±, `fit_offset_s`, `_apply_fit_dataset`, `ActiveTimeMapper.with_offset` i `tests/test_dji_smartsync.py`. Wspominają o nich tylko raporty (`RAPORT_DJI_ACTION2_FULL_REGRESSION_FIX.md`), a `RAPORT_SPORTCAMHUD_ETAP_5C…` i `…ETAP_1_AUTOFIT…` potwierdzają, że `src/telemetry_dji_smartsync.py` i ten test nie istnieją w tym repozytorium. Kod opisany w raporcie DJI pochodził spoza tej historii (inne repo / niezacommitowany) — **nie do odzyskania stąd**.
- Istniejący „SmartSync” = wyłącznie wyrównanie GoPro po **trajektorii GPS** (`_align_offset_by_track`) + fallbacki czasowe; algorytmu korelacji IMU DJI ↔ FIT nigdy nie było w historii.
- Repo Android (`SportCamHUD-Android-main`) ma SmartSync GPS + offset ręczny, bez IMU.

## 2. Usunięte vs ukryte

- GUI regulacji ręcznej: **nie istnieje w historii tego repo** → zaimplementowane od nowa.
- Offset w pipeline: istniał tylko w kluczu cache (**martwy klucz**) → teraz faktycznie przesuwa dane.
- SmartSync IMU: **nigdy nie istniał** → zaimplementowany od nowa (`src/telemetry_smartsync_imu.py`).
- Dodatkowo naprawiony istniejący defekt: przy niezerowym przesunięciu bazowym (strefa czasowa / GPS) próbki FIT były przesuwane, a **mapper pauz (`active_time_mapper`) nie** — „Pomiń pauzy” i średnia prędkość korzystały z niezsynchronizowanych przerw.

## 3. Kontrakt i propagacja

```
telemetry_time = video_start_time + video_position + telemetry_sync_offset_s
```

- `video_start_time` = kotwica klipu na zegarze kamery (GoPro: czas GPS z GPMF, DJI: `creation_time` MP4).
- Offset jest stosowany **dokładnie raz**: przy (re)derywacji strumieni FIT/GPX znaczniki próbek są przesuwane o `−offset` (`TelemetryDataManager.set_telemetry_sync`, `src/telemetry_sync.py`). Bazowe wyrównanie z ładowania (UTC / strefa / ślad GPS GoPro) zostaje osobno, bez zmian.
- Wszyscy konsumenci czytają te same przesunięte próbki z menedżera: resolver podglądu, wektorowa preparacja (`render_preparation`, AMD/kolejka), skalarny builder `telemetry_precompute` (Intel native / streaming / fallback FFmpeg — potwierdzone realnym eksportem Intel), stany NVIDIA `telemetry_states_fast` (czytają `telemetry.resolve_samples(..., "fit")` — potwierdzone statycznie), wykresy, marker mapy, mapper pauz, okrążenia. **Nikt nie dodaje offsetu przy odczycie** (sprawdzono `streaming.py`, `amd_native_exporter.py` — tam `sync_offset_s` służy tylko do klucza cache).
- Klucz cache eksportu bierze offset z menedżera telemetrii (rzeczywisty stan danych), a korekty per klip są dodawane do klucza tylko gdy istnieją (istniejące klucze bez zmian).
- Strumienie kamery (GPMF, IMU DJI) i obraz **nie są przesuwane**. Zmiana offsetu nie parsuje ponownie MP4 ani FIT (re-derywacja z rekordów w pamięci: 20–190 ms dla FIT 54 min).
- Wielu klipów: klip *i* używa `offset + clip_offsets_s[i]` w swoim oknie (granice w połowie przerw).
- `lean_sync_ms` (wskaźnik Przechył) jest osobnym parametrem IMU kamery — nietknięty.
- Przyspieszenie x2/x4: **w obecnym kodzie nie ma takiej funkcji** (sprawdzono `setpts`/speed factor) → brak ścieżki do podwójnego skalowania; offset jest w sekundach czasu źródłowego.

## 4. SmartSync IMU — jak działa

`src/telemetry_smartsync_imu.py` (numpy, bez scipy):

1. **Kamera** (żyroskop + akcelerometr, czasy względem startu klipu): resampling 50 Hz → kierunek grawitacji z akcelerometru (LP 2 s) → **yaw rate = gyro · ĝ** (niezależny od montażu) oraz **|przyspieszenie poziome|** (akcelerometr minus grawitacja). Filtry wyłącznie centralne (zero-phase) → 10 Hz.
2. **FIT/GPX**: pozycje → lokalne ENU → wygładzenie trajektorii 2 s → **pochodna rozwiniętego kursu** (maskowana poniżej 2 m/s i przy lukach > 6 s); |dv/dt| z prędkości. Nie zakłada się surowego akcelerometru w FIT; surowe osie akcelerometru nie są porównywane z prędkością.
3. **Maskowana znormalizowana korelacja krzyżowa (FFT)** dla obu znaków yaw (montaż nieznany). Kanał brakujący przy danym przesunięciu daje 0 (bez renormalizacji).
4. **Wyszukiwanie adaptacyjne**: ±120 s → ±900 s → cała aktywność; szersze okno zastępuje węższe tylko przy wyższej pewności lub wyraźnie lepszym piku.
5. **Doprecyzowanie** pozycji piku tylko na kanale yaw (±2 s), interpolacja paraboliczna (rozdzielczość < 0,01 s).
6. **Wiarygodność**: korelacja w piku, **jednoznaczność** (pik / drugi lokalny pik poza ±4 s), z-score piku, liczba **dopasowanych zdarzeń** (zakręty o zgodnym znaku, przyspieszenia/hamowania, tolerancja 1,5 s), zgodność połówek klipu (tylko gdy każda połowa ≥ 120 s; daje też szacunek dryfu w ppm).
7. **Automatyczne zastosowanie tylko przy `high`**: score ≥ 0,30, jednoznaczność ≥ 1,8, z ≥ 5, zdarzenia ≥ 4, yaw w piku ≥ 0,4, połówki niesprzeczne. W pozostałych przypadkach wynik jest **propozycją** (przycisk „Zastosuj propozycję”), offset nie jest zmieniany.

Kolejność w przycisku Auto: GoPro z dobrym GPS → SmartSync GPS (istniejący algorytm trajektorii); jeśli GPS odrzucony lub brak → SmartSync IMU; brak IMU → komunikat, tylko ręczna regulacja. Analiza w wątku tła, z postępem i anulowaniem (ten sam przycisk → „Anuluj analizę”), obsługą błędów i komunikatem wyniku. Multi-file: osobna estymacja na klip; zgodne (≤ 0,3 s) → jeden offset; różne → korekty per klip tylko dla klipów wiarygodnych; klipy niewiarygodne używają offsetu globalnego.

**Kalibracja progów** (dane rzeczywiste GX010378): prawdziwe dopasowanie 0,58 / jednoznaczność 2,33 / z 7,3 / 8 zdarzeń; celowo błędne segmenty aktywności maks. 0,41 / 1,72 / z 4,0 / 4 zdarzenia.

## 5. Wyniki na rzeczywistych materiałach

| Materiał | Wynik |
|---|---|
| **DJI Osmo Action 6** `C:\GoPro\DJI_20261005062901_0004_D.MP4` (25 min, proto `dvtm_ac206`, EIS **włączone**) | Parser rozpoznaje kamerę, ale `normalized_imu()` = **0 próbek**; strumień `djmd` ma tylko **134 B/klatkę** (brak żyroskopu), `dbgi` to zastrzeżony strumień debug. → SmartSync IMU **niemożliwy dla tego klipu** (przypadek E na realnym pliku); poprawny wynik ścieżki to `NO_IMU` + regulacja ręczna. **Brak pliku FIT z 2026-10-05 na tej maszynie** → rzeczywista synchronizacja DJI↔FIT: **NOT TESTED**. |
| DJI Action 2 | Brak plików na maszynie (dysk `F:` z wcześniejszych raportów niepodłączony). Wcześniejszy raport: proto `dvtm_ac103` nie zawiera IMU. **NOT TESTED**. |
| **GoPro GX010378 + `2026-10-15_15-03-50.fit`** (para spoza `BENCHMARKS.md`; kanoniczny katalog `Video/` nieobecny) | GPS kamery **zamrożony** (125 unikalnych pozycji, minutami bez zmian) → istniejący SmartSync GPS **odrzucił** parę (mediana 230 m). Zachowuje się jak kamera bez GPS. SmartSync IMU: **−0,299 s, high, pewność 74%, 8 zdarzeń, korelacja 0,57, jednoznaczność ×2,27**, w GUI 0,2–0,7 s. Wynik względem kotwicy czasu GPS (GPSU) jest bliski 0, co jest spójne z tym, że Garmin i GPMF działają na czasie GPS. |

Zastrzeżenia środowiska: natywny parser GPMF i parser DJI są skompilowane tylko dla CPython 3.14 (`cp314`); na tej maszynie aplikacja działa na 3.15 (3.14 nie ma numpy/PySide6). **Wczytanie klipu DJI w GUI na tej maszynie zakończy się błędem „DJI telemetry parser is unavailable for Python 3.15”** jeszcze przed synchronizacją — problem istniejący, nie zmieniany (poza zakresem). IMU DJI Action 6 sprawdzono bezpośrednio parserem pod 3.14.

## 6. Dokładność przy znanym offsecie

**Prawdziwe IMU (GX010378) z wstrzykniętym błędem zegara kamery** (przesunięte znaczniki IMU względem FIT):

| Wstrzyknięty błąd | Oczekiwany offset | Wynik | Błąd |
|---|---|---|---|
| +1,5 s (A) | −1,798 | −1,798 | 0,000 s |
| −3,2 s (B) | +2,902 | +2,902 | 0,000 s |
| +47 s (C) | −47,298 | −47,299 | 0,001 s |
| −125 s (C, poza ±120 → wyszukiwanie adaptacyjne) | +124,702 | +124,702 | 0,000 s |
| +600 s (C) | −600,298 | −600,299 | 0,001 s |

To mierzy względną poprawność kontraktu i wyszukiwania. Absolutnej prawdy dla tej pary nie ma (GPS nieprzydatny). Rozrzut wyniku między wariantami filtrów w trakcie strojenia: −0,16…−0,30 s, co daje realistyczną niepewność ~0,15 s.

**Syntetyczne przejazdy z prawdą absolutną** (`tests/smartsync_synth.py`: losowy montaż kamery, przechył roweru, wibracje, szum IMU, skorelowany szum GPS 2 m, FIT 1 Hz; 80 przypadków, offsety +1,5 / −3,2 / +0,37 / +47,6 / −250 s):

| Długość klipu | Zastosowane automatycznie | Maks. \|błąd\| zastosowanych |
|---|---|---|
| 60 s | 0/20 (słusznie: za mało zdarzeń) | — |
| 146 s | 17/20 | 0,318 s |
| 300 s | 20/20 | 0,119 s |
| 600 s | 20/20 | 0,088 s |

Wszystkie zastosowane: średni \|błąd\| 0,074 s, mediana 0,043 s, obciążenie −0,013 s. **Żaden** przypadek ujemny nie został zastosowany: jazda prosto ze stałą prędkością (F), jazda prosto ze zmienną prędkością, inna aktywność (G), błędne segmenty rzeczywistej aktywności, odwrócony w czasie FIT, FIT bez pozycji GPS (tylko prędkość) → `AMBIGUOUS` / `INSUFFICIENT_EVENTS`. Brak IMU → `NO_IMU` z komunikatem.

Dryf zegara: szacowany z połówek klipu (pole `drift_ppm`), tylko gdy każda połowa ≥ 120 s. **Korekta dryfu nie jest stosowana automatycznie** — przy 1 Hz FIT szum estymacji połówek (~0,1–0,3 s) przewyższa typowy dryf kamery (~20–50 ppm ≈ 0,1 s/h). Ograniczenie: dla bardzo długich nagrań możliwy niekorygowany dryf rzędu dziesiątych sekundy.

## 7. Korekta ręczna (rzeczywisty test GUI, GX010378)

Sekcja **SYNCHRONIZACJA TELEMETRII** w Projekt → Właściwości (gdy nie zaznaczono wskaźnika): pole offsetu (0,01 s), −1 / −0,1 / +0,1 / +1 s, Reset, Auto synchronizacja, źródło i wiarygodność, komunikat, „Zastosuj propozycję”. Zrzuty z rzeczywistego okna wykonano (scratchpad sesji: `gui_project_after_auto.png`, `gui_panel_after_nudge.png`).

- Sekwencja +1, +0,1, +0,1, −1, −0,1 od −0,299 → **−0,199** (oczekiwane −0,199). Szybkie kliknięcia są scalane (5 kliknięć → 2 re-derywacje), a GUI nie jest blokowane.
- Działa przy zatrzymanym podglądzie; obraz/pozycja filmu nie zmieniają się.
- **Tożsamość przesunięcia** (podgląd): wartość przy offsecie X w chwili t vs przy offsecie 0 w chwili t+X — maks. różnica **0,0**.
- Zmiana zakładek nie zmienia offsetu. Panel pokazuje −0,30 s.

## 8. Zapis i odczyt projektu

- Offset, metoda, wiarygodność, korekty per klip i diagnostyka SmartSync są zapisywane per materiał (ścieżka+rozmiar+mtime filmów i FIT/GPX) w `%LOCALAPPDATA%\SportCamHUD\session\telemetry_sync.json` (nigdy obok wideo) i lustrzanie w layoucie sesji (`telemetry_sync_offset_s`, `telemetry_sync_clip_offsets_s`, `telemetry_sync_method`). Dzięki temu migawki kolejki eksportu niosą offset, a przywrócenie zadania go stosuje.
- **Test w nowym procesie**: po ponownym wczytaniu GX010378+FIT → „Przywrócono zapisaną synchronizację (SmartSync IMU)”, −0,299 s, layout −0,299. Reset → offset 0, wpis usunięty ze store.
- Wyczyszczenie projektu resetuje offset; wczytanie nowego materiału zaczyna od 0 i przywraca tylko jego własny zapis. Late-attach FIT/GPX także przywraca.
- **Offset nie należy do presetu HUD** (decyzja użytkownika, wdrożone w drugiej iteracji):
  - „Zapisz preset” i zapis `def_layout.json` usuwają `telemetry_sync_offset_s`, `telemetry_sync_clip_offsets_s`, `telemetry_sync_method` (`strip_sync_keys` w `src/telemetry_sync.py`, wywołane w `preset_mixin.py`).
  - „Wczytaj preset” ignoruje te pola (także w starszych presetach) i ponownie lustruje synchronizację **bieżącego materiału**. Dane telemetrii nie są ponownie przesuwane, a offset nie jest zerowany ani nadpisywany.
  - Źródłem prawdy jest zapis per materiał. Lustro w layoucie sesji/projektu służy wyłącznie migawkom kolejki i kluczowi cache.
  - Testy: `tests/test_telemetry_sync_presets.py` (3/3) — zapisany preset i `def_layout.json` bez kluczy; wczytanie starego presetu z `99 s` / korektą klipu zachowuje 1,5 s, dane i działanie przycisków ±; ponowne otwarcie projektu z 3 klipami DJI odtwarza offset globalny 2,0 s i korektę klipu 2 (+5 s), a inny materiał nie dziedziczy offsetu.
  - Realny test GUI (GX010378): po przywróceniu −0,299 s wczytano stary preset z `99 s` → offset −0,299 s, layout −0,299, wartości podglądu bez zmian (18,3156 / 18,8469 km/h przed i po); ponownie zapisany preset nie zawiera kluczy sync.

## 9. Zgodność podglądu i eksportu (rzeczywisty eksport, harness `--test-intel-export`)

- Kolumny preparacji eksportu vs resolver podglądu w tych samych klatkach (offset 0 i −0,299): zgodność do ≤ 0,006 km/h — ta sama różnica przy offsecie 0 (zaokrąglenie float32 kolumn, istniejące, niezwiązane z sync).
- Dwa rzeczywiste eksporty Intel native HEVC, 1900 klatek, przez kanoniczny harness — offset przywrócony produkcyjną ścieżką ładowania (`[TelemetrySync] restored …`):
  - −0,299 s: `success=True`, 27,4 fps; +30 s (test): `success=True`, 27,8 fps.
  - Oba: wideo HEVC 63,397 s + **audio AAC 63,381 s muxowane na żywo z oryginalnego MP4** (bez ekstrakcji audio, bez `ensure_audio_cache`); walidacja A/V harnessu przeszła.
- **Test wizualny MP4**: eksport +30 s w 20 s pokazuje 23,6 km/h, 58 rpm, 94 bpm, 0 W, 36,38 m, solar 18% — **identycznie** jak eksport −0,3 s w 50,3 s. Eksport −0,3 s w 20 s pokazuje 9,0 km/h / 79 rpm / 81 bpm. Dane kamery (zegar 15:04:18, Exp 1/246, ISO 615, GP 30,2 °C) i obraz są identyczne w obu eksportach → offset wpływa wyłącznie na FIT, raz.
- Testowy wpis +30 s usunięto ze store użytkownika.
- Po wdrożeniu zasady „offset nie należy do presetu”: eksport z czystego stanu (`def_layout.json`, offset −0,299 s) i eksport wykonany po teście starego presetu są **bitowo identyczne** w 4K (5/20/45/60 s: max_diff 0, MAE 0, 0 różnych pikseli z 8 294 400). Wcześniejszy eksport −0,299 s różnił się wyglądem HUD (font, ikona Przechyłu), bo powstał z layoutem sesji zapisanym przez sterownik E2E. Wartości telemetrii były te same (9,0 km/h, 79 rpm, 81 bpm, 157 W, 35,16 m).
- AMD / NVIDIA: brak sprzętu → **NOT TESTED** na żywo. Używają tej samej preparacji i tych samych przesuniętych danych; kod rendererów nie był zmieniany.

## 10. Testy

- Nowe: `tests/test_telemetry_sync_smartsync.py` — **22/22 PASS** (A, B, C, E, F, G, J, K, kontrakt bez podwójnego dodania, reset, mapper pauz, per klip, klucz cache, zapis/odczyt).
- Istniejące testy telemetrii (`test_telemetry_manager`, `test_fit_gpx_file_validation`, `test_map_sync`, `test_common_render_preparation`, `test_etap10k3_fit_speed`): **86 passed, 1 skipped**; 1 fail + 5 error = brak pliku `Video/Jazda_na_rowerze_w_porze_lunchu.fit` (środowisko).
- **Pełny pakiet `tests/` — porównanie z bazą sprzed zadania.** Kopia stanu sprzed zadania w scratchpadzie: HEAD + wcześniejsze niezacommitowane zmiany użytkownika, bez SmartSync. Każdy plik testowy uruchamiano osobno, z limitem 240 s, Py 3.15, Qt offscreen i **izolowanym `LOCALAPPDATA`**.
  - Baza: 2343 passed / 137 failed / 18 errors / 109 skipped. Obecnie: 2369 passed / 140 failed / 18 errors / 105 skipped. Te same 3 pliki z timeoutem w obu przebiegach (`test_amd_decode_gui_switch`, `test_export_lifecycle_p1_fixes`, `test_render_progress_single_source`).
  - Różnica: +25 nowych testów sync (PASS). Pozornie „nowe” 3 faile to `test_preview_map_cache_miss::test_export_branch_matches_git_baseline_pixels`: w bazie były pominięte (kopia bez `.git`), a w przebiegu bieżącym powłoka tła nie widziała świeżo zainstalowanego gita. Uruchomione z gitem w PATH: **14/14 PASS**. **Nowych regresji: 0.** 137 faili / 18 errorów istniało wcześniej (m.in. brak `Video/`, DLL/symbole AMD, `TelemetryOrchestrator`, kontrakty DJI z raportu ETAP 1).
  - Uwaga środowiskowa: wcześniejszy przebieg pakietu z prawdziwym `LOCALAPPDATA` nadpisywał `%LOCALAPPDATA%\SportCamHUD\session\active_layout.json` układem testowym (istniejące testy nie izolują AppData). Plik odłożono jako `active_layout.test_contaminated_20261018.json`; aplikacja wraca do presetu startowego / `def_layout.json`. Po odświeżeniu PATH z rejestru `python` wskazuje na 3.14 (bez numpy) — testy uruchamiać jawnie interpreterem 3.15.
- I (spójność podgląd/MP4): PASS (sekcja 9). H (ręczna + zapis + odczyt): PASS (sekcje 7–8). D (DJI bez GPS): ścieżka IMU DJI na realnym Action 6 → brak IMU w pliku; korelacja DJI-specyficzna **NOT TESTED** z braku FIT i braku pliku DJI z IMU.

## 11. Zmienione pliki

Nowe:
- `src/telemetry_sync.py` — kontrakt, przesunięcie (także per klip), zapis per materiał
- `src/telemetry_smartsync_imu.py` — algorytm SmartSync IMU
- `src/gui/qt/_mixins/sync_mixin.py` — kontroler: ręczna/auto, wątki, anulowanie, zapis, kolejka
- `src/gui/qt/widgets/telemetry_sync_panel.py` — sekcja GUI
- `tests/test_telemetry_sync_smartsync.py`, `tests/smartsync_synth.py`, `tests/test_telemetry_sync_presets.py`

Zmienione (dopisane fragmenty):
- `src/gui/telemetry_manager.py` — baza wyrównania FIT/GPX, re-derywacja, `set_telemetry_sync`, `activity_motion_arrays`, przesunięcie mappera pauz/okrążeń, reset przy czyszczeniu
- `src/telemetry_active_time.py` — `ActiveTimeMapper.with_offset`
- `src/render_preparation.py` — offset z menedżera w kluczu, korekty per klip w kluczu
- `src/gui/qt/_mixins/render_mixin.py` — `sync_offset_s` z menedżera (klucz rodzic = dziecko)
- `src/gui/qt/_mixins/project_mixin.py` — reset przed wczytaniem aktywności, przywrócenie po zbudowaniu osi czasu, reset w `clear_project`, przywrócenie po late-attach
- `src/gui/qt/tabs/render_tab.py` — zastosowanie offsetu z migawki zadania kolejki
- `src/gui/qt/_mixins/preset_mixin.py` — presety/`def_layout.json` bez kluczy sync; wczytanie presetu ignoruje je i zachowuje sync materiału
- `src/gui/qt/signals.py`, `src/gui/qt/controller.py`, `src/gui/qt/_mixins/__init__.py`, `src/gui/qt/widgets/property_editor.py`

Nietknięte: Intel D3D11/QSV, renderery AMD/NVIDIA, VBR/VBV/HRD, presety eksportu, kodeki, ustawienia HUD, mapa/pochylenie, FPS, audio (live mux), AutoFIT (wyszukiwanie lokalne → Garmin Connect bez zmian; znalezienie FIT ≠ synchronizacja).

## 12. Status Git i ograniczenia

- Brak `git.exe` → **nic nie zacommitowano**. Zmiany leżą w drzewie roboczym obok 25 wcześniejszych niezacommitowanych plików użytkownika. Moje pliki są wymienione w sekcji 11, co ułatwia selektywny commit.
- Ograniczenia: brak rzeczywistego DJI z IMU i pasującym FIT; parsery natywne tylko cp314; dryf nie jest korygowany automatycznie; niepewność rzeczywista ~0,1–0,3 s przy FIT 1 Hz (zależna od liczby zakrętów); klipy < ~2 min zwykle dają tylko propozycję; per-klip mapper pauz używa mediany offsetów klipów.

## 13. Podsumowanie

| Kryterium | Status |
|---|---|
| Regulacja ręczna w GUI, natychmiastowa, przy pauzie | **PASS** (realne GUI) |
| Jeden kontrakt offsetu, bez podwójnego dodania, podgląd = eksport | **PASS** (dane + realny MP4) |
| SmartSync IMU: algorytm, confidence, jednoznaczność, zdarzenia, propozycja | **PASS** (realne IMU GoPro bez GPS + syntetyka) |
| Asynchroniczność, postęp, anulowanie, błędy | **PASS** (GUI nieblokowane; anulowanie — ścieżka kodu, NOT TESTED interaktywnie) |
| Zapis/odczyt/reset/zakładki | **PASS** |
| Multi-file per klip | **PASS** (jednostkowo); realny multi-file: **NOT TESTED** (brak materiału) |
| GoPro GPS bez regresji | **PASS** (testy istniejące + test metody GPS); realny GoPro z dobrym GPS: **NOT TESTED** |
| Rzeczywista synchronizacja DJI ↔ Garmin FIT | **NOT TESTED / BLOCKED** — Action 6 bez IMU (EIS on), brak FIT z 2026-10-05, parser DJI niedostępny na Py 3.15 |
| Eksport z live mux audio | **PASS** (Intel); AMD/NVIDIA **NOT TESTED** |

**Status ogólny: PARTIAL.** Funkcjonalność jest przywrócona, zweryfikowana na rzeczywistych danych kamery bez GPS i w rzeczywistym eksporcie. Docelowego przypadku DJI↔FIT nie dało się zweryfikować na tej maszynie.
