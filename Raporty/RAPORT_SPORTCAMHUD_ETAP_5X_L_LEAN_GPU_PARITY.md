# SPORTCAMHUD — ETAP 5X-L: pełna zgodność LEAN w podglądzie i AMD GPU

2026-10-15, Europe/Warsaw. **STATUS: PASS** (rowerek PASS, linia PASS, podziałka PASS, tytuł PASS, podgląd/AMD PASS). DLL bez zmian.

## 1. HEAD i working tree
- Start `f520f1d`, koniec `baf157b` (`fix(amd): restore lean overlay visual parity`), gałąź `fix/gui-freeze-hud-composite`, bez push.
- Niezacommitowane pozostają tylko wcześniejsze/cudze zmiany (`def_layout.json`, Intel/NVIDIA, `live_av_mux.py`, raport 5R‑F, `tools/validate_5w_map_gpu.py`). Tymczasowe wydruki diagnostyczne (`AMD_5XL_DEBUG`) w `compositor.py` i eksporterze zostały usunięte przed commitem (diff `compositor.py` = 0).
- `def_layout.json`: SHA256 `65fa8390…606f4` przed i po każdym z 12 eksportów testowych. DLL `runtime/amd/bin`: `5ad042bb…` (bez zmian od 5W).

## 2. Przyczyna
Przepływ w AMD: rowerek jest rysowany na GPU (`telem_amd_update_lean_static_texture` + `set_lean_transform` → shader `BlendLean`, obrót CatmullRom), a tytuł, linia odniesienia, podziałka i wartość mają przychodzić z warstwy CPU ABOVE (`lean._render_lean_indicator` z `_skip_dynamic_graphic=True`, statyczna baza w `_LEAN_BASE_CACHE`).
- Instrumentacja pętli `compose_overlay` w eksporcie pokazała dla `lean_indicator` w roli `above`: `enabled=True`, **`indicator_availability=False`** → wskaźnik pomijany, brak bboxa, brak regionu ABOVE; w regionach GPU tylko sprite rowerka.
- Źródło: `telemetry_precompute` (tryb `AMD_TELEMETRY_MODE=PRECOMPUTED`) liczy dostępność przez `get_effective_indicator_availability(...)` bez tablic IMU (`gyroscope/accelerometer/_lean_roll_cache`). Dla źródła `gyro` daje to „brak IMU”, choć ten sam precompute liczy poprawne wartości przechyłu (`_worker_lean_roll`) — z nich korzysta GPU.
- Błąd występuje, gdy layout eksportu nie niesie `_indicator_availability` (harness/CLI, layout wczytany z pliku — zapis projektu usuwa ten klucz). Gdy GUI wstrzyknie dostępność z pełnej telemetrii (`True`), warstwa CPU była rysowana — warianty „*_before” z jawną dostępnością pokazują pełny przechył także na starym kodzie. Prawdziwy stan „przed” (layout bez klucza, kod `f520f1d`) udokumentowano zrzutem przed kompresją `chk_before_lean_crop.png` (tylko rowerek) oraz `chk_leancpu_lean_crop.png` (z `AMD_LEAN_GPU=0` brak całego przechyłu — ten sam powód).

## 3. Zmienione pliki
- `src/ffmpeg/amd_native_exporter.py`: po zbudowaniu cache telemetrii, jeśli layout nie ma `_indicator_availability`, a precompute oznaczył klucz przechyłu jako niedostępny, sprawdzane jest 256 równomiernie rozłożonych klatek; gdy istnieją rzeczywiste wartości przechyłu, dostępność tego klucza = True. Tylko eksporter AMD; dostępność podana przez GUI nie jest nadpisywana; brak danych IMU → nadal niewidoczny.
- `tests/test_lean_parity_5xl.py` (cache, odświeżenie ustawień, pusty tytuł, obecność poprawki).
Nie zmieniano `lean.py`, renderera, shaderów, DLL ani wspólnego `telemetry_precompute.py` (używa go też Intel — izolacja backendów; wspólna przyczyna opisana w p. 15).

## 4. Statyczne / dynamiczne
| element | gdzie w AMD | charakter |
|---|---|---|
| rowerek | GPU: statyczna tekstura sprite'u (upload raz) + transformacja per klatka | dynamiczny (kąt) — bez zmian |
| tytuł, linia odniesienia, podziałka | CPU: `_LEAN_BASE_CACHE` (raster raz na zestaw ustawień), region ABOVE | statyczne |
| wartość kąta z graficznym `°` | CPU: `_draw_text_bounded_cached` | dynamiczna (tekst) |

## 5. Cache
Baza przechyłu jest rasteryzowana raz na klucz ustawień (font, tytuł, rozmiary, flagi linii/podziałki, kolory); zmiana kąta nie tworzy nowej bazy (test). Zmiana `show_ticks` daje inny raster, powrót daje bajtowo poprzedni (test A→B→A). Wyłączony wskaźnik: brak wszystkich elementów (`O1_off`). Nowych transferów GPU nie dodano; region ABOVE przechyłu idzie istniejącym mechanizmem dirty‑regions.

## 6–9. Wyniki (kanoniczny harness `--test-amd-export`, `GX020079.mp4 + .fit`, 4K, HEVC FAST 40M)
Warianty layoutu (kopie, `def_layout.json` tylko czytany): `user` (jak u użytkownika: `title_text=""`, linia i podziałka wyłączone), `full` (tytuł „PRZECHYŁ”, linia ON, podziałka ON), `off` (wskaźnik wyłączony), `*_before` (jak wyżej + jawna dostępność False z GUI).
- **Przed kompresją** (`AMD_DUMP_CHECKPOINT` = wejście AMF, klatka 150; `run/lean_precompress_f150.png`): `user` → rowerek + „-0.9°”, bez tytułu, linii i podziałki (zgodnie z ustawieniami); `full` → tytuł „PRZECHYŁ” (polskie Ł z 5X), linia odniesienia z podziałką, rowerek, „-0.9°” z graficznym pierścieniem; `off` → nic.
- **Podgląd vs AMD** (`preview_vs_amd.py`, raster `compose_overlay` podglądu bez sprite'u vs wejście AMF, piksele w pełni kryjące): `full` max_diff 28, MAE 20.09 (2302 px); `user` max_diff 22, MAE 19.96 (565 px). Kontrola na niezmienionym wskaźniku tekstowym (`exposure_text`, ta sama klatka): max_diff 29, MAE 16.64 — to stały koszt konwersji NV12/zakresu w zrzucie, nie różnica geometrii (przy przesunięciu różnice sięgałyby 255). Pozycje, rozmiary, font, jednostka i obrys zgodne.
- **Animacja** (MP4, co 25 klatek, `run/angles_sheet.png`): m.in. +3.6° (k. 50), −0.1° (k. 100), −3.0° (k. 250), −2.1/+2.7/+0.9/−1.5°. Rowerek zmienia kąt, tytuł, linia i podziałka stoją; kierunek zgodny ze znakiem wartości. Kąty pochodzą z rzeczywistych danych IMU (bez syntetycznego ruchu).
- Rowerek w AMD to dalej ścieżka GPU (CatmullRom), w podglądzie CPU (BICUBIC) — bez zmian w tym etapie; nie porównywano go pikselowo.

## 10. Render FPS (300 klatek)
| przebieg | Render FPS |
|---|---|
| `user` po poprawce (`U1b`) | 42.188 |
| `user` z jawną dostępnością, czyli z warstwą CPU (`U0b`) | 42.419 |
| stan sprzed poprawki bez warstwy CPU (5X `B_on_user`/`B2`, ten sam layout) | 41.329 / 39.777 |
Przebiegi z `AMD_DUMP_CHECKPOINT` (36.0–36.3) zawierają koszt zrzutu PNG i nie służą do oceny. Brak mierzalnego spadku; dodatkowy koszt to jeden mały region ABOVE (~226×311 px) i tekst wartości z cache. Liczba uploadów tekstury rowerka: 1 (bez zmian). Pełny benchmark 1131 klatek: NOT TESTED.

## 11. DLL
Przebudowa niepotrzebna — istniejące API (warstwa CPU ABOVE + GPU sprite) wystarcza.

## 12. Commit
`baf157b4fa500b613576bb61a9418ed9048d0f3c` fix(amd): restore lean overlay visual parity.

## 13. def_layout.json
Niezmieniony (hash sprawdzany po każdym eksporcie).

## 14. Funkcje produkcyjne
Log `U1b`: `rc=VBR target=40000000`, `Hardware QP stats: avg=33.6 … samples=300`, diag QP `ok=300 fail=0`; mux `-c copy` z `setts`, audio z oryginalnego AAC. Mapa 5W, finalizacja, Intel/NVIDIA, FIT/GPX/SmartSync bez zmian.

## 15. Otwarte ryzyka
- Wspólna przyczyna w `telemetry_precompute.py` i `render_preparation.py` (dostępność bez IMU) dotyczy też ścieżek Intel/NVIDIA — poprawiono tylko AMD; do osobnego zadania.
- Shadow/obrys rowerka GPU vs CPU nie były porównywane pikselowo.
- Test `tests/test_lean_imu_contract.py::test_zero_offset_subtracts` nie przechodzi także przed zmianą (lista 34 z 5X).
- Testy jednostkowe: nowe 4 + powiązane 82 przechodzą (86/87, jedyny błąd jak wyżej).

## Artefakty
`Raporty/etap5x_l_artifacts/`: `run_lean_export.py`, `preview_vs_amd.py`, `run/*.log|json`, `run/layout_*.json`, `run/lean_precompress_f150.png`, `run/angles_sheet.png`, `run/chk_*_lean_crop.png`, `run/preview_vs_amd_f150.json`. MP4 i pełne zrzuty 4K usunięte.

## ntfy
Wysyłane po zapisaniu raportu; wynik poniżej.

Wynik: wysłano, id=9zEOo3d3R3Xf.
