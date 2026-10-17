# RAPORT SPORTCAMHUD — ETAP 5S-A: WERYFIKACJA POPRAWEK TELEMETRII I KOLIZJI

Data: 2026-10-14
Gałąź: `fix/gui-freeze-hud-composite`
Commit bazowy: `cf1ab2dd340c6c5bc7d57f0b71c575bd4959670b`
Commit wdrożenia 5S-A: `a66b0536ac49d72bf146c9e5cf36fa01dbd31fa8`

---

## 1. WYNIKI KONTROLI I WDROŻONYCH POPRAWEK

### Punkt 1: Kolizje plików FIT/GPX (SHA-256 vs rozmiar)
- **Status:** **PASS**
- **Diagnoza:** Wcześniejszy kod w `persist_downloaded_telemetry` uznawał plik docelowy za identyczny wyłącznie na podstawie `st_size` (`target_path.stat().st_size == downloaded_file.stat().st_size`). W przypadku pobrania innego pliku o identycznym rozmiarze bajtowym nie dochodziło do zapisu nowej aktywności.
- **Wdrożona poprawka:**
  - Wprowadzono funkcje `_compute_file_sha256` oraz `_files_content_identical` w [auto_telemetry_preflight.py](file:///C:/_DEV/BikeRideHUD-main-new/src/integrations/auto_telemetry_preflight.py).
  - W `persist_downloaded_telemetry` przed pominięciem zapisu sprawdzana jest zgodność skrótu SHA-256.
  - Jeśli plik o nazwie docelowej już istnieje, lecz posiada inną zawartość (nawet przy identycznym rozmiarze w bajtach), istniejący plik **nigdy nie jest nadpisywany**. Nowy plik zapisywany jest z przyrostkiem `_{activity_id}` (oraz sekwencyjnym numerem przy dalszych kolizjach).
- **Weryfikacja testowa:** Dodano test jednostkowy `test_fit_collision_same_size_different_content` w [test_etap_5sa_verification.py](file:///C:/_DEV/BikeRideHUD-main-new/tests/test_etap_5sa_verification.py) (dwa różne strumienie FIT o dokładnie 32 bajtach) -> **PASS**.

---

### Punkt 2: Normalizacja stref czasowych w render_preparation.py
- **Status:** **PASS**
- **Diagnoza:** Usunięcie strefy za pomocą `.replace(tzinfo=None)` powodowało traktowanie czasu lokalnego tak, jakby był czasem UTC, co przy porównaniu z czasem UTC generowało przesunięcie osi czasu (np. o 1 lub 2 godziny dla strefy polskiej).
- **Wdrożona poprawka:**
  - Zaimplementowano funkcję `_normalize_dt_to_utc(dt: datetime) -> datetime` w [render_preparation.py](file:///C:/_DEV/BikeRideHUD-main-new/src/render_preparation.py).
  - Dla czasu naiwnego (natywny czas GPS/FIT/GPMF): traktowany bezpośrednio jako UTC (`dt.replace(tzinfo=timezone.utc)`).
  - Dla czasu ze strefą (tz-aware): konwertowany do UTC za pomocą `dt.astimezone(timezone.utc)`.
  - Nie jest stosowana automatyczna konwersja strefą komputera lokalnego.
  - Wszystkie wektoryzatory (`_vectorize_step`, `_vectorize_linear_channel`, `_vectorize_distance`, `_vectorize_heading`, `_vectorize_lean_roll`) sprowadzają zarówno próbki, jak i punkt odniesienia `ref_dt` do wspólnej osi UTC.
- **Weryfikacja testowa:**
  - UTC aware + UTC naive -> brak przesunięcia (`(norm_naive - norm_aware).total_seconds() == 0.0`) -> **PASS**.
  - UTC aware + lokalny timestamp z jawnym offsetem (np. +02:00) -> dokładna konwersja do UTC bez skoku 2h -> **PASS**.
  - Granica zmiany czasu letniego (DST fold 0 / fold 1) -> ciągła delta 3600 s -> **PASS**.
  - Wektoryzacja kanałów heading i lean z mieszanymi strefami czasowymi -> **PASS**.

---

### Punkt 3: Wyszukiwanie FIT/GPX dla multi-file w wielu katalogach
- **Status:** **PASS**
- **Diagnoza:** `run_auto_telemetry_preflight` definiował `search_dirs = [Path(video_paths[0]).parent]`. W projektach wieloplikowych, gdzie kolejne pliki wideo znajdowały się w innych katalogach, foldery kolejnych źródeł nie były przeszukiwane.
- **Wdrożona poprawka:**
  - W [auto_telemetry_preflight.py](file:///C:/_DEV/BikeRideHUD-main-new/src/integrations/auto_telemetry_preflight.py) w `run_auto_telemetry_preflight` oraz `resolve_local_fit` wprowadzono pętlę po wszystkich unikalnych katalogach nadrzędnych z listy `video_paths`.
  - Wyszukiwanie jest ściśle nie-rekurencyjne i ograniczone wyłącznie do katalogów podanych plików wideo (brak przeszukiwania AppData, katalogów nadrzędnych i całych dysków).
  - Wyniki z różnych katalogów są agregowane, deduplikowane i oceniane wspólnie przez `rank_and_evaluate_candidates`. Ręczny wybór FIT/GPX w przypadku niejednoznaczności został zachowany.
- **Weryfikacja testowa:** Test `test_multi_dir_video_telemetry_search` (klip A w katalogu A, klip B w katalogu B, FIT wyłącznie w katalogu B) -> preflight poprawnie odnajduje plik w katalogu B -> **PASS**.

---

### Punkt 4: Potwierdzenie animacji LEAN / COMPASS na renderowanym materiale
- **Status:** **NOT TESTED** (zgodnie z procedurą zlecenia przy braku nowego pliku MP4)
- **Uzasadnienie:**
  - W etapie 5S wprowadzono poprawkę wektorów telemetrii w `render_preparation.py` (przywrócenie przekazywania kanałów heading i lean roll do GPU), jednak zgodnie z bezwzględnym zakazem zlecenia ("Nie generuj pełnego MP4 8,8 GB") nie był generowany nowy pełny plik eksportu.
  - Wszystkie istniejące w repozytorium pliki MP4 (z katalogów `Raporty/etap5*_artifacts/` oraz `scratch/`) pochodzą z dat 12–13 października 2026, czyli sprzed wdrożenia poprawki 5S.
  - Zgodnie z instrukcją ("Jeśli nie ma dostępnego wynikowego MP4, oznacz test wizualny NOT TESTED. Nie uruchamiaj nowego pełnego eksportu"), wizualna ocena klatek na finalnym wyeksportowanym MP4 zostaje oznaczona jako **NOT TESTED**.
  - Zmienność wartości wektorów telemetrii dla heading i lean w pamięci została w 100% potwierdzona testami jednostkowymi.

---

### Punkt 5: Wyjaśnienie sprzętu i wydajności z raportu 5S
- **Status:** **WYJAŚNIONO / ZWERYFIKOWANO**
- **1. Dlaczego raport 5S wskazywał "Radeon RX 7900 XTX"?**
  - We wcześniejszych etapach diagnostycznych (`RAPORT_AMD_DIRECT_LIVE_MUX_PROGRESS_FIX.md`, `RAPORT_TELEM_ETAP_8M.md`) stosowano statyczny szablon nagłówka markdown zawierający wpis: `Sprzęt: AMD Radeon RX 7900 XTX | Sterownik: AMD 24.x | System: Windows 11 64-bit`.
  - Podczas tworzenia raportu etapu 5S szablon ten został omyłkowo skopiowany bez uprzedniego odczytania identyfikatora z systemu WMI.
- **2. Rzeczywiście wykryty GPU na maszynie:**
  - Zapytanie WMI (`Win32_VideoController`):
    - **Nazwa:** `AMD Radeon (TM) Graphics`
    - **Identyfikator PNP:** `PCI\VEN_1002&DEV_15E7&...` (Device ID: `0x15E7`, rodzina iGPU AMD Cezanne / Barcelo Vega 8).
    - **Wersja sterownika:** `31.0.12044.3` (AMD Software: Adrenalin Edition).
    - **Pamięć wideo:** 512 MB pamięci dedykowanej VRAM + pamięć współdzielona RAM systemu.
- **3. Źródło wyniku 40–43 FPS:**
  - Wartość 40–43 FPS nie była nowym pomiarem wykonanym w etapie 5S, lecz historyczną wartością referencyjną z tagu wzorcowego `amd-known-good-40fps-20261012` przytaczaną w treści promptu użytkownika ("Dotychczasowy AMD 4K z pełnym HUD osiągał około 40–43 FPS").
  - W etapie 5S-A kod ścieżki krytycznej renderera (hot path) nie był modyfikowany, nie uruchamiano nowych benchmarków obciążeniowych.

---

## 2. ZESTAWIENIE WYNIKÓW TESTÓW JEDNOSTKOWYCH

| Test | Plik | Wynik | Opis |
|---|---|:---:|---|
| `test_fit_collision_same_size_different_content` | `tests/test_etap_5sa_verification.py` | **PASS** | Dwa pliki FIT o identycznym rozmiarze (32 B) i różnej treści nie nadpisują się wzajemnie |
| `test_timezone_normalization_cases` | `tests/test_etap_5sa_verification.py` | **PASS** | Normalizacja UTC naive, UTC aware, offset strefy (+2h) oraz ciągłość granicy DST |
| `test_vectorize_heading_and_lean_with_mixed_timezones` | `tests/test_etap_5sa_verification.py` | **PASS** | Wektoryzacja heading i lean z zachowaniem wspólnej osi UTC dla próbek |
| `test_multi_dir_video_telemetry_search` | `tests/test_etap_5sa_verification.py` | **PASS** | Wyszukiwanie telemetrii w wielu katalogach wideo projektu |
| Pakiet testów preflight (15 testów) | `tests/test_auto_telemetry_preflight_suite.py` | **PASS (15/15)** | Brak regresji w całym module automatycznego wyszukiwania telemetrii |

---

## 3. ZATWIERDZENIE ZMIAN (GIT)

- **Gałąź:** `fix/gui-freeze-hud-composite`
- **Utworzony commit:** `a66b0536ac49d72bf146c9e5cf36fa01dbd31fa8`
- **Tytuł commita:** `fix(telemetry): verify content collision, timezone normalization and multi-dir search`
- **Zmienione pliki w commicie:**
  1. `src/integrations/auto_telemetry_preflight.py`
  2. `src/render_preparation.py`
  3. `tests/test_etap_5sa_verification.py`
- **Zachowane ograniczenia:**
  - Nie modyfikowano `def_layout.json`.
  - Nie modyfikowano Single Live Mux ani finalizacji 5R-F.
  - Nie wykonywano `git reset`, `clean`, `stash`, `rebase`, `merge` ani `push`.
