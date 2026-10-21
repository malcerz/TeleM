# SportCamHUD — kompas Preview, zapis konfiguracji, geometria, kolory i postęp HUD

**Data:** 2026-10-21 · **Gałąź:** `main` · **Platforma:** AMD (Ryzen 7 7730U / Radeon) · **Bazowy HEAD:** `5d69840`
**DLL AMD:** `runtime/amd/bin/telem_amd_native.dll` SHA-256 `BBCA75FBD0DFC5D7CBB61922E92F8D5F049B4305DD18335315667E6E5E54CA5F` — **zgodny, nieprzebudowany, niepodmieniony**.
**Artefakty:** `Raporty/compass_preview_ui_20261021/` (skrypty, JSON-y; PNG są w `.gitignore` i leżą tylko lokalnie).

Materiał: `F:\GoPro\2026-10-16\GX010380.MP4` + `2026-10-16_06-22-14.fit` (wskazany w zadaniu, nie jest parą z `BENCHMARKS.md`), dodatkowo materiał dwuplikowy użytkownika `F:\GoPro\2026-10-20\GX010389.MP4`, `GX010390.MP4` + `2026-10-20_15-04-03.fit` (jedyny FIT w folderze, wskazany przez użytkownika).

---

## 1. Przyczyna zastoju kompasu do ~2:44

Poprzedni raport deklarował PASS na podstawie harnessu, który **podstawiał** layout z `compass_heading_mode = gps_imu` (`layout_fit.json`) i przekazywał konfigurację ręcznie do `resolve_value`. Rzeczywisty `def_layout.json` użytkownika **nie miał** tego pola → kompas pracował w trybie standardowym (kurs GPS GoPro, źródło `gpmf`).

Pomiar w realnej ścieżce Preview (`_render_preview_sync`, przechwycona wartość przekazana do `_render_compass_indicator`), layout użytkownika, bez Play (`probe_before_user_layout_scan.json`):

| t [s] | 0–76 | 80 | 88–108 | 112–176 | 180–188 |
|---|---|---|---|---|---|
| rysowany kurs | **brak** (`---`, tarcza N w górę) | 90.7° | 34–62° | **141–155° (prosta)** | 176→239° |

Kompas był nieruchomy do ~79 s (brak kursu GPMF), a potem jechał prostą ~146–154° aż do skrętu ~176–184 s. Dokładnej wartości 164 s nie odtworzono — obserwacja użytkownika mieści się w tym obrazie. Dlaczego hybryda nie była aktywna: patrz §2 (utrata ustawienia przy ponownym otwarciu MP4) i §13 (startowy preset z innego katalogu).

Po poprawkach (i ostatecznie po usunięciu trybu standardowego, §7a) rysowany kurs: 0 s 258.2°, 10 s 297.1°, 30 s 185.8°, 60 s 152.3°, 79 s 78.5°, 164 s 149.6°, 180 s 192.0° — od klatki 0, wyłącznie przez seek.

## 2. Przyczyna niezapisywania ustawień kompasu

Dwie niezależne przyczyny, obie potwierdzone w GUI:

1. **`bg_load` przy każdym otwarciu MP4 czytał layout ponownie z dysku** (`def_layout.json` lub startowy preset), kasując wszystkie niezapisane zmiany z Property Editora. Test GUI „edycja → ponowne otwarcie MP4”: przed poprawką przetrwało **1/47** pól kompasu (tylko `enabled`), po poprawce **47/47** (`roundtrip_reload_before.json` / `roundtrip_reload_after.json`).
2. **Startowy preset wskazywał inny plik**: `%APPDATA%\SportCamHUD\app_preferences.json` → `startup_preset = C:/_DEV/BikeRideHUD-main-new/def_layout.json`. Zapis szedł do `C:\_DEV\SportCamHUD\def_layout.json`, a odczyt z tamtego pliku. Dowód: zapis użytkownika z 11:35 zawierał `value_position` dla Bar i ustawienia kompasu; zapis z 11:46 miał już kompas z tamtego pliku (3→3.086, 2→2.057 po migracji) i brak położeń Bar. Użytkownik poprawił preferencję; aplikacja ostrzega teraz o konflikcie (§13).

Zapis przyciskiem „Zapisz ustawienia” był poprawny już przed zmianami: 47/47 (`roundtrip_before.json`).

## 3. Serializacja i deserializacja

- `project_mixin._working_layout_copy()` + flaga `_working_layout_active`: od drugiego otwarcia projektu w sesji używany jest roboczy layout z pamięci (głęboka kopia, bez kluczy runtime: `_indicator_availability`, `cut_regions`, `_presentation_video_*`). Kolejność: sidecar `.layout.json` > roboczy layout sesji > startowy preset > `def_layout.json`.
- Migracja geometrii kompasu v1→v2 (§5) wywoływana w: `normalize_layout`, `_on_load_preset`, wczytaniu sidecar i startowego presetu w `bg_load`.
- Zapis bez zmian w mechanizmie (`normalize_layout_for_save`, `sanitize_layout_for_json`). Nowe pola (`compass_geometry_version`, `compass_subticks`) nie są odrzucane przez walidację.

## 4. Dowód Round Trip JSON

`gui_compass_roundtrip.py` (realny `AppController` + `MainWindow`, izolowany APPDATA/LOCALAPPDATA, kopia layoutu w katalogu tymczasowym): zmiana **każdego** widgetu kompasu przez Property Editor → „Zapisz ustawienia” → zamknięcie → nowy proces → ponowne otwarcie MP4 → porównanie modelu, JSON i widgetów GUI.

| scenariusz | wynik |
|---|---|
| edycja → zapis → restart | 47/47 |
| edycja → ponowne otwarcie MP4 (przed poprawką) | **1/47** |
| edycja → ponowne otwarcie MP4 (po poprawce) | 47/47 |
| po zmianie geometrii (float grubości, `compass_subticks`) | 47/47 |
| GUI: „Zapisz preset” → „Wczytaj preset” → restart z presetem startowym (kompas + `value_position` Bar) | identyczne |

Uwaga: zestaw 47 pól obejmował jeszcze tryb/metodę IMU/offset, które w §7a zostały usunięte z GUI.

## 5. Skalowanie grubości z Rozmiarem (geometria v2)

Jednostki przed zmianą: `compass_ring_width`, `compass_tick_width` — piksele wyjściowe ×supersampling; `compass_needle_width` (połowa szerokości) i `compass_marker_size` (promień) — piksele wyjściowe; obrys i cień — piksele. Długości (ticki, wskazówka) już skalowały się z promieniem. Skutek: stała grubość przy zmianie Rozmiaru oraz inna proporcja w Preview (~1060 px) i w Final 4K.

Nowa semantyka (`compass_geometry_version: 2`): wartości są pikselami przy **promieniu referencyjnym 172.8 px** (Rozmiar 8 % na kanwie 2160 px, czyli preset produkcyjny 4K) i skalują się współczynnikiem `size_px / 172.8` — dotyczy pierścienia, ticków, wskazówki, markera, obrysu oraz odległości/długości/rozmycia cienia. Minimalna grubość linii w v2 = 1 piksel wyjściowy; minimalna połowa wskazówki 1.5 px (jak wcześniej). Klucze cache zawierają przeliczone wartości.

Migracja v1→v2: `wartość × 172.8 / s(size, 2160)` — dla rozmiaru zapisanego w layoucie raster Final 4K pozostaje identyczny. Konfiguracje bez wersji (np. bezpośrednio przekazane dicty) renderują się dokładnie jak wcześniej.

Pola GUI grubości są teraz typu float (krok 0.5).

## 6. Nowa semantyka Subtick

Było: „Subtick co” = odstęp kątowy (mniejsza wartość = gęściej). Jest: **„Subticki między głównymi”** (`compass_subticks`) = liczba drobnych kresek między dwoma głównymi tickami; odstęp = `major / (n+1)`. Zakres 0–14 (limit 14 → przy 45° co 3°, 120 ticków; wartości powyżej są obcinane). Migracja: `round(major/tick) − 1` (np. 45/5 → 8).

## 7. Wyniki testów geometrii (`compass_geometry_check.py`, `geometry/geometry_check.json`)

| test | wynik |
|---|---|
| v1 nowy renderer vs renderer z `5d69840` (4 konfiguracje × 4K i Preview) | **identyczne** (max_diff 0, MAE 0, different_pixels 0) |
| po migracji v2 vs v1 z `5d69840`, kanwa 4K (4 konfiguracje, w tym obrys + długi cień) | **identyczne** (max_diff 0, MAE 0, different_pixels 0) |
| grubość pierścienia (mediana radialna) 4K przy Rozmiar 50/100/200 % | v2: **1.10 / 1.86 / 3.74 px**; v1: 1.97 / 1.86 / 1.88 px |
| raster | 206 / 415 / 830 px — kwadrat, bez deformacji |
| subticki 0/1/4/8 (major 45°) | 8 / 16 / 40 / 72 ticki (odstęp 45 / 22.5 / 9 / 5°) |

Pomiar grubości na małej kanwie Preview jest zaburzony stykaniem się ticków z pierścieniem — ocenione wizualnie (`geometry/sizes_4k_50_100_200.png`, `geometry/subticks_0_1_4_8.png`).

## 7a. Zmiana po decyzji użytkownika: jeden tryb kompasu

Na prośbę użytkownika usunięto z GUI „Tryb kierunku”, „Metoda IMU” i „Offset kamery”. Rekonstrukcja GPS/FIT + IMU jest jedynym trybem (`telemetry_compass_hybrid.hybrid_enabled()` — wszystkie miejsca w kodzie przechodzą przez tę funkcję). Metoda IMU na stałe „auto” (CORI tylko po przejściu testu zgodności z GRAV, inaczej GYRO+ACCL; na GX010380 i GX010389/90 CORI jest odrzucane, p95 29.9° / 24.0° / 49.1°). Offset na stałe 0. Wartości zapisane przez stare layouty (`standard`, `cori`, offset 25°) są ignorowane — sprawdzone: ten sam kurs co do 0.1° co przy domyślnych. Pozostały: źródło kalibracji (FIT domyślnie / GPS GoPro), stabilizacja, okna kalibracji, minimalna prędkość, korekta dryftu.

## 7b. Krótkie pliki (zgłoszenie użytkownika: GX010389 bez kompasu)

GX010389 (216 s, 24 min przerwy przed GX010390 → kalibracja wyłącznie z własnych danych): FIT od 69. s pliku; okna 30 s i 60 s zaraz po stabilizacji zawierają ostre skręty przy ~9 km/h, w których kurs FIT opóźnia się względem żyroskopu do 55° → p95 > 10°; okno 120 s nie mieści się w pliku → **0 % kursu**. Analiza (`twofile/clip1_windows.json`): okno zaczynające się 45 s po fiksie i sięgające do końca pliku spełnia wszystkie kryteria (p95 8.3°, mediana 3.4°, korelacja skrętów 0.46, niepewność wstecz 13.9°).

Poprawka (`calibrate_segment`): gdy dane segmentu kończą się bez zaakceptowanego okna, sprawdzane są okna zaczynające się później (krok 15 s) i kończące na końcu danych, z **tymi samymi** kryteriami akceptacji. `ALGORITHM_VERSION = 2` unieważnia stare wyniki z cache.

| plik | przed | po |
|---|---|---|
| GX010389 | unavailable, 0 % | ok, **100 %**, okno +15 s / 92 s, p95 9.33°, niepewność wstecz 14.2° |
| GX010390 | ok, 97.7 % | bez zmian |
| GX010380 | ok | **identyczne** wartości (11 punktów, do 0.001°) |

Ryzyko: p95 9.33° przy limicie 10° — wynik poprawny wg kryteriów, ale mniej precyzyjny niż dla długich plików.

## 8. Color Picker

Wspólny komponent koloru w `PropertyEditor` (wszystkie wskaźniki): kliknięcie kolorowego kwadratu (`ColorSwatch`) otwiera `QColorDialog` z bieżącym kolorem; przycisk „...” usunięty. Kwadrat aktualizuje się przy ręcznej edycji HEX. Niepoprawny HEX (dozwolone `#RGB`, `#RRGGBB` — formy parsowane przez renderer) nie trafia do modelu (czerwona ramka), po zakończeniu edycji przywracana jest ostatnia poprawna wartość. Anuluj nie zapisuje niczego.

Test GUI (`gui_color_sync_ux.py`, `ux/ux_checks.json`) — wszystkie PASS: brak „...”, wybór koloru (HEX + kwadrat + model + odświeżenie Preview), Anuluj bez zmiany, ręczny HEX, odrzucenie niepoprawnego HEX, trwałość po zapisie i restarcie. Testy jednostkowe `test_property_editor_color_swatch.py` (2/2).

## 9. Kliknięcie pustego obszaru Preview

Kliknięcie w podgląd poza wskaźnikami (także w czarne marginesy przeskalowanego obrazu) → odznaczenie wskaźnika, pokazanie panelu „Synchronizacja telemetrii”, fokus na „Przesunięcie” z zaznaczonym tekstem. Działa tylko gdy zakładka Projekt jest widoczna (podgląd jest współdzielony z Renderingiem). Wynik testu GUI na rzeczywistym widgecie mpv: panel widoczny, fokus na polu, wartość 0.00 → 0.00, **zero** sygnałów `sig_sync_offset_set`; kliknięcie kompasu nadal go zaznacza; przeciąganie zmienia X 94.31 → 91.32; klik w margines aktywuje synchronizację.

## 10. HUD_PREPARING

`src/gui/hud_preparation.py` (`HudPreparation`, stany `HUD_PREPARING` / `HUD_READY`), sygnał `sig_hud_preparation`. Preview: półprzezroczyste przyciemnienie + panel na środku (tytuł „Przygotowywanie wskaźników...”, etap „(etap k z n)”, pasek). Rysowanie QPainter: nad `image_label` jako lekki widget-dziecko, w trybie mpv w istniejącym oknie `TopLevelHUDWindow` (natywnego okna mpv nie da się przykryć dzieckiem). Brak kodowania czy osobnego obrazu; animacja paska nieokreślonego to timer 40 ms aktywny tylko podczas przygotowania. Podczas przygotowania nie jest pokazywany stary/niekompletny HUD.

Koniec przygotowania: wszystkie etapy zakończone lub z błędem — w tym pierwsza **kompletna** klatka HUD bieżącego projektu w rozmiarze **widocznego** podglądu. Kompas hybrydowy w trakcie kalibracji wstrzymuje zakończenie. Limity: mapa 20 s (dalej kafelki w tle), klatka HUD 30 s. Błędy etapów kończą przygotowanie i są pokazywane w pasku stanu („HUD gotowy. Niedostępne: …”). Generacja projektu: anulowanie, błąd i zmiana projektu zamykają nakładkę; późne doczepienie FIT otwiera nową rundę; kolejność snapshotów jest globalnie monotoniczna.

## 11. Źródła rzeczywistego postępu

| etap | źródło | pasek |
|---|---|---|
| Wczytywanie telemetrii | pętla klipów `_load_or_generate_telemetry` | określony tylko przy ≥2 klipach (liczba klipów), inaczej nieokreślony |
| Synchronizacja FIT | wczytanie FIT + oś czasu + przywrócenie synchronizacji | nieokreślony |
| Analiza IMU i kalibracja kompasu | `prepare_compass` / `sig_compass_prepared` | nieokreślony |
| Przygotowanie danych HUD | odkrycie strumieni → `project_ready` | nieokreślony |
| Składanie podglądu HUD / Budowanie wykresów i podglądu HUD | pierwsza klatka HUD (wykresy budowane w pierwszym renderze) | nieokreślony |
| Przygotowanie mapy | `MapBackgroundPrefetchManager` (kafelki gotowe / wymagane) | **określony** |

Bez sztucznych kroków procentowych i bez postępu z timera.

## 12. Czas wczytywania MP4 (GX010380 + FIT, layout użytkownika)

| scenariusz | ready | pełny HUD (nakładka znika) | goły film przed zmianą |
|---|---|---|---|
| zimny cache (izolowany LOCALAPPDATA) | 6.3–6.7 s | 8.8–9.3 s | **~2.4–2.8 s** między `ready` a pierwszą klatką HUD |
| ciepły (drugie otwarcie w sesji) | 1.56–2.0 s | 3.9–4.7 s | przed poprawką HUD nie pojawiał się wcale aż do przesunięcia suwaka |

Dodatkowo naprawiony błąd znaleziony podczas testów: ponowne otwarcie projektu przy niezmienionym rozmiarze podglądu nie renderowało HUD do czasu seek.

## 13. Startowy preset — zabezpieczenie

`export_paths.startup_preset_conflict()`: „Zapisz preset” i „Zapisz ustawienia” pokazują ostrzeżenie z obiema ścieżkami, gdy jako Startowy preset ustawiony jest inny istniejący plik. `bg_load` loguje, z którego presetu wczytał układ.

## 14. Rozdzielczość pierwszej klatki HUD

Zgłoszenie użytkownika: tuż po pokazaniu HUD niska rozdzielczość do czasu przesunięcia suwaka. Pomiar: pierwsza klatka **640×360** przy podglądzie **1060×596**, brak ponownego renderu. Przyczyna: `_render_preview` odrzucał żądanie bez seek przychodzące w trakcie innego renderu (resize po pokazaniu zakładki Projekt). Poprawka: żądania łączone w jeden kolejny render (pod lockiem), HUD_PREPARING kończy się tylko na klatce w rozmiarze widocznego podglądu. Po poprawce: 640×360 nie kończy przygotowania, 1060×596 przychodzi ~0.1 s później; ciepłe otwarcie od razu 1060×596.

## 15. Zrzuty ekranu GUI (lokalnie, `.gitignore`)

`screens/user|hybrid|cori_fail|late_fit|map/`: `hud_preparing_project_tab.png` (HUD_PREPARING), `hud_ready_project_tab.png` (HUD_READY), `ux/ux_property_editor_color_swatch.png`, `ux/ux_color_dialog.png`, `ux/ux_sync_after_empty_click.png`, `geometry/sizes_4k_50_100_200.png`, `geometry/subticks_0_1_4_8.png`, `e2e/compass_t030_old_vs_new.png`. Środowisko offscreen nie przechwytuje natywnej powierzchni mpv — obszar wideo jest na zrzutach czarny; nakładka i HUD są widoczne.

## 16. Testy kompasu bez Play

`gui_compass_preview_e2e.py` (przepływ użytkownika: wybór trybu w GUI → ponowne otwarcie MP4 → seek sygnałem `sig_seek_changed`, `_playing == False`): stary przepływ — `---` od 0 do 79 s; nowy — kurs w każdym punkcie od 0 s. Po §7a/§7b: GX010380 od klatki 0; GX010389/90: GX010389 od klatki 0 (0 s 172.0°, 30 s 108.4°, 60 s 78.1°), GX010390 bez zmian.

## 17. Preview / Final

Eksport AMD wykonany przez użytkownika w normalnym GUI (log `D:\GoPro\SCH\20261020-1505.log`, materiał GX010389+GX010390+FIT): klatka Final 30 s pokazuje **108°**, Preview 108.4° (format `03d`). Klatka 90 s: 074°. Bitowej parity Preview/Final w tym etapie **NIE TESTOWANO** (Preview i Final mają różne rozdzielczości; zgodność rastra 4K v1/v2 udowodniono w §7).

## 18. Sprzętowy eksport AMD

Wyniki z logu użytkownika (QUEUE, multi-file):

- DLL SHA-256 `bbca75fb…54ca5f` ✔; D3D11VA → AMF HEVC Main10, HLG_PRESERVE (BT.2020 / ARIB STD-B67) ✔
- VBR 60/90 Mb/s, profil FAST (ustawienie użytkownika) ✔; QP feedback: ok=60031 fail=0, avg QP 24.6 ✔
- live mux AAC z oryginalnych MP4, 2 segmenty, bez plików pośrednich ✔; audio 2003.008 s / wideo 2003.034 s (zgodnie z planem AAC) ✔
- 60031/60031 klatek, finalizacja rc=0, 14.39 GB ✔; mapa: 0 brakujących kafelków ✔
- Render FPS 39.585, effective 39.492

Moje próby harnessu A/B (`run_amd_ab.sh`) z izolowanym APPDATA/LOCALAPPDATA **nie powiodły się** (A1: brak FIT w jobie i zawieszenie dziecka na etapie przygotowania; B1: render zatrzymany na klatce 0) — procesy zakończono, wyniki odrzucone. Izolacja dodatkowo spowodowała, że launcher `python` pobrał Python 3.15.1 do katalogu tymczasowego (instalacja użytkownika 3.14.7 nienaruszona). Porównanie A/B FPS: **NIE WYKONANO — z decyzji użytkownika („nie ma potrzeby porównania”)**.

## 19. FPS i RAM

Wpływ na FPS: **NOT PROVEN** (brak A/B). Zmiany w ścieżce eksportu: renderer kompasu (CPU ABOVE) — te same operacje z przeskalowanymi parametrami; hybryda bez narzutu per-frame (lookup tablicy). Nakładka HUD_PREPARING to wyłącznie malowanie Qt w GUI. RAM: bez nowych buforów per-frame; przy eksporcie użytkownika `process_private_mb=1704.68` na klatce 0.

## 20. Nienaruszone

DLL AMD (hash), AMD QP, VBR/VBV/HRD, GPU Pitch, HEVC Main10 HLG, live mux, audio (brak `ensure_audio_cache`, brak końcowego muxowania audio), finalizacja, profile kodowania, mapa, temperatura, BAR, moduł Bearing — bez zmian w kodzie. Ścieżki NVIDIA/Intel nie modyfikowane; zmiany wspólne (GUI, `telemetry_compass_hybrid`, `render_preparation`, `gauge.py`) są niezależne od backendu.

`def_layout.json` użytkownika: nienadpisywany i niecommitowany przez agenta (zmiany w pliku pochodzą z zapisów użytkownika w aplikacji).

## 21. Lokalne commity (bez push)

```
ed0e271 fix(layout): keep the session's edited layout when re-opening a project
06cc40e test(compass): real-GUI reproduction of the Preview compass freeze
44dd0f6 feat(compass): scale geometry with Rozmiar and count subticks between majors
e10febb feat(gui): clickable colour swatch and empty-Preview click focuses sync offset
23a2d03 feat(gui): HUD_PREPARING overlay with real stage progress until the HUD is ready
e2a7594 fix(preview): never drop a resize re-render; first HUD at the visible size
64f1691 fix(layout): warn when a different Startowy preset overrides the saved layout
5da0ad8 feat(compass): GPS/FIT + IMU reconstruction is the only compass mode
ff2b3b3 fix(compass): calibrate short files on a later window to the end of their data
```

## 22. Testy automatyczne

- kompas, geometria, HUD_PREPARING, kolory, layout roboczy: **78 passed, 15 skipped** (15 = testy usuniętego trybu standardowego, oznaczone `skip` z powodem, nie usunięte); `test_compass_hybrid_calibration.py` + integracja + rendering + geometria: 61 passed, 2 skipped.
- testy GUI (`test_gui_*`, `test_etap10t2_segment_gui_hardening`, `test_icon_font_gauge_fixes` i in.): niepowodzenia identyczne jak na `5d69840` (porównanie zbiorów FAILED: **0 nowych**). Dotyczą segment-bar/wykresów FIT/schematu gauge — istniejące wcześniej, poza zakresem.

## 23. Końcowy git status

Zmieniony tylko `def_layout.json` (prywatny plik użytkownika, nie commitowany). Nieśledzone pliki sprzed zadania pozostawione bez zmian.

## 24. Otwarte ryzyka i brakujące testy

- Brak automatycznego fallbacku źródła: projekt bez FIT pokaże „Brak danych” w kompasie, dopóki użytkownik nie wybierze „GPS GoPro”.
- Kalibracja krótkich plików może zaakceptować okno blisko limitu p95 (GX010389: 9.33°).
- `late_attach_telemetry` wczytuje FIT w wątku GUI (~1.5 s blokady) — nakładka nie animuje się w tym czasie. Istniejące, nie zmieniane.
- Diagnostyka per-klip eksportu AMD podaje fps 106/114 niezgodne z całkowitym 39.6 FPS; ffmpeg loguje `Error during demuxing: Invalid argument` przy zamknięciu potoku AAC (audio kompletne). Istniejące, nie zmieniane.
- Pole „Źródło” w nagłówku kompasu nie ma już wpływu (zastąpione przez „Źródło kalibracji”) — do uporządkowania w osobnym zadaniu.
- `unit` kompasu w `def_layout.json` użytkownika zawiera znak `�` (uszkodzony `°` z wcześniejszego zapisu) — nie poprawiano bez zgody.
- NOT TESTED: bitowa parity Preview/Final dla nowego kodu, A/B FPS (rezygnacja użytkownika), scenariusz realnego błędu sieci mapy (testowano skryptowo wymuszony błąd i spowolnienie).

## PASS / FAIL

| kryterium | wynik |
|---|---|
| 1. Kompas działa od początku nagrania w realnym Preview | PASS (GX010380, GX010389) |
| 2. Bez Play | PASS |
| 3. Ustawienia kompasu zapisują się i odtwarzają | PASS (47/47; po §7a mniej pól) |
| 4. Rozmiar skaluje grubość | PASS (1.10 / 1.86 / 3.74 px) |
| 5. Więcej subticków = gęściej | PASS |
| 6. Klik w kolorowy kwadrat otwiera wybór koloru | PASS |
| 7. Klik w pusty Preview aktywuje synchronizację | PASS |
| 8. Przyciemnienie + pasek postępu | PASS |
| 9. Brak samego filmu jako rzekomo gotowego podglądu | PASS (w tym rozdzielczość pierwszej klatki) |
| 10. Preview i Final zgodne | PASS dla wartości (108° / 108.4°); bitowo NOT TESTED |
| 11. Brak regresji wydajności AMD | NOT PROVEN (brak A/B, decyzja użytkownika) |
| 12. DLL AMD nienaruszona | PASS |
