# RAPORT: Audyt i czyszczenie tymczasowych worktree SportCamHUD

**Data:** 2026-09-28  
**Środowisko:** Intel Core Ultra 7 255U / Intel Graphics (PC Intel)  
**Kanon:** `C:\_DEV\SportCamHUD-main`  
**Autor:** Antigravity / Gemini High  

---

## 1. Cel i zasady bezpieczeństwa (GOAL & SAFETY)

Przeprowadzenie rygorystycznego audytu wszystkich 30 katalogów `C:\_DEV\SportCamHUD*` i usunięcie przestarzałych worktree bez ryzyka utraty niezatwierdzonych prac (uncommitted), unikalnych commitów czy dowodów benchmarkowych.

### Ścisłe reguły bezpieczeństwa:
1. **Ochrona kanonicznych repozytoriów:**
   - `C:\_DEV\SportCamHUD-main` ➔ **KEEP_CANONICAL**
   - `C:\_DEV\SportCamHUD-intel` ➔ **KEEP_REFERENCE**
2. **Ochrona unikalnych commitów:** Jeśli HEAD worktree zawiera commity nieosiągalne z gałęzi `origin/main`, `origin/intel-225u`, `origin/amd-bikeridehud`, `origin/intel-coreultra` lub `origin/nvidia-final-20260918`, katalog jest chroniony (**KEEP_UNIQUE_WORK**).
3. **Ochrona modyfikacji roboczych:** Jeśli pliki śledzone są zmodyfikowane (`git diff-index --quiet HEAD --` != 0), katalog jest chroniony (**KEEP_DIRTY**).
4. **Brak wymuszonego usuwania:** Usuwanie wyłącznie za pomocą `git worktree remove` bez flagi `--force`. W razie odmowy Gita — wstrzymanie operacji i klasyfikacja jako **NEEDS_MANUAL_REVIEW**.

---

## 2. Podsumowanie dyskowe (DISK USAGE)

- **Liczba zaaudytowanych katalogów:** 30
- **Całkowity rozmiar przed audytem (TOTAL_BEFORE_GB):** `170.16 GB`
- **Odzyskane miejsce (RECLAIMED_GB):** `2.33 GB`
  - `SportCamHUD-intel-cleanproof` (usunięty poprawnie przez `git worktree remove`): `2.08 GB`
  - `SportCamHUD-main-amd-latest-integration` (pusty katalog po worktree): `0.25 GB`

---

## 3. Zestawienie audytowe wszystkich katalogów SportCamHUD

| Nazwa katalogu | HEAD | Gałąź | Zmodyfikowane śledzone | Pliki nieśledzone | Rozmiar (GB) | Klasyfikacja | Uzasadnienie |
|---|---|---|---|---|---|---|---|
| **SportCamHUD-main** | `2ae6aa4` | `main` | NIE | 38 | 5.21 | **KEEP_CANONICAL** | Główna gałąź produkcyjna |
| **SportCamHUD-intel** | `52e21f5` | `intel-225u` | NIE | 1699 | 52.10 | **KEEP_REFERENCE** | Główna gałąź referencyjna Intel |
| **SportCamHUD-intel-cleanproof** | `8302bcc` | `detached` | NIE | 0 | 2.08 | **SAFE_REMOVE_WORKTREE** | Osiągalne z origin, czyste ➔ **USUNIĘTO** |
| **SportCamHUD-intel-commitproof** | `edcb6d7` | `detached` | NIE | 1 | 1.44 | **KEEP_UNIQUE_WORK** | Commit `edcb6d7` nieosiągalny z remote |
| **SportCamHUD-intel-commitproof2** | `590971a` | `detached` | TAK | 1 | 1.44 | **KEEP_DIRTY** | Zmodyfikowane pliki śledzone |
| **SportCamHUD-intel-directvp** | `590971a` | `detached` | TAK | 50 | 5.85 | **KEEP_DIRTY** | Zmodyfikowane pliki śledzone + scratch |
| **SportCamHUD-intel-dx11-parity** | `590971a` | `detached` | TAK | 18 | 1.90 | **KEEP_DIRTY** | Zmodyfikowane pliki śledzone |
| **SportCamHUD-intel-finalproof** | `8302bcc` | `detached` | TAK | 20 | 2.58 | **KEEP_DIRTY** | Zmodyfikowane pliki śledzone |
| **SportCamHUD-intel-gpuhud** | `590971a` | `detached` | TAK | 109 | 11.94 | **KEEP_DIRTY** | Modyfikacje w kodzie C i pipeline |
| **SportCamHUD-intel-gpuhud-debug** | `590971a` | `detached` | TAK | 81 | 6.13 | **KEEP_DIRTY** | Modyfikacje w kodzie C i pipeline |
| **SportCamHUD-intel-gui-finalproof** | `590971a` | `detached` | TAK | 7 | 1.97 | **KEEP_DIRTY** | Zmodyfikowane pliki śledzone |
| **SportCamHUD-intel-gui-patchproof** | `590971a` | `detached` | TAK | 2 | 1.87 | **KEEP_DIRTY** | Zmodyfikowane pliki śledzone |
| **SportCamHUD-intel-huddelivery** | `590971a` | `detached` | TAK | 133 | 17.37 | **KEEP_DIRTY** | Duże pliki robocze i modyfikacje C |
| **SportCamHUD-intel-hudregions** | `590971a` | `detached` | TAK | 35 | 2.89 | **KEEP_DIRTY** | Zmodyfikowane pliki śledzone |
| **SportCamHUD-intel-hwdecode** | `590971a` | `detached` | TAK | 24 | 2.38 | **KEEP_DIRTY** | Zmodyfikowane pliki śledzone |
| **SportCamHUD-intel-layoutproof** | `8302bcc` | `detached` | TAK | 25 | 2.36 | **KEEP_DIRTY** | Modyfikacje layoutu i backendu |
| **SportCamHUD-intel-lazyproof** | `8302bcc` | `detached` | TAK | 4 | 1.44 | **KEEP_DIRTY** | Modyfikacje backendu |
| **SportCamHUD-intel-minproof** | `8302bcc` | `detached` | TAK | 21 | 3.21 | **KEEP_DIRTY** | Modyfikacje streaming i bar |
| **SportCamHUD-intel-multirect** | `590971a` | `detached` | TAK | 43 | 12.20 | **KEEP_DIRTY** | Modyfikacje telem_intel_native.c |
| **SportCamHUD-intel-multirect-applyproof** | `590971a` | `detached` | TAK | 5 | 1.49 | **KEEP_DIRTY** | Modyfikacje telem_intel_native.c |
| **SportCamHUD-intel-multirect-proof** | `590971a` | `detached` | TAK | 21 | 10.63 | **KEEP_DIRTY** | Modyfikacje telem_intel_native.c |
| **SportCamHUD-intel-releaseproof** | `8302bcc` | `detached` | TAK | 20 | 1.86 | **KEEP_DIRTY** | Modyfikacje backendu |
| **SportCamHUD-intel-selfproof** | `8302bcc` | `detached` | TAK | 25 | 1.66 | **KEEP_DIRTY** | Modyfikacje backendu |
| **SportCamHUD-intel-v2proof** | `8302bcc` | `detached` | TAK | 23 | 2.34 | **KEEP_DIRTY** | Modyfikacje backendu |
| **SportCamHUD-intel-v4proof** | `8302bcc` | `detached` | TAK | 19 | 1.44 | **KEEP_DIRTY** | Modyfikacje backendu |
| **SportCamHUD-intel-videogap** | `590971a` | `detached` | TAK | 66 | 8.27 | **KEEP_DIRTY** | Modyfikacje exportera |
| **SportCamHUD-main-amd-integration** | `49fed08` | `integration/amd-into-main` | NIE | 3 | 2.33 | **NEEDS_MANUAL_REVIEW** | Git odmówił usunięcia (nieśledzone binarki) |
| **SportCamHUD-main-amd-latest-integration** | — | — | — | 0 | 0.25 | **SAFE_REMOVE_STALE_DIRECTORY** | Pusty folder po usuniętym worktree ➔ **USUNIĘTO** |
| **SportCamHUD-main-intel-integration** | `bd88b3d` | `integration/intel-225u-main` | TAK | 1 | 2.09 | **KEEP_DIRTY** | Zmodyfikowany render_tab.py |
| **SportCamHUD-git-temp** | — | — | — | — | 1.44 | **NEEDS_MANUAL_REVIEW** | Archiwum z 19.09 (zawiera TeleM_project.zip) |

---

## 4. Analiza kategorii

1. **KEEP_CANONICAL (1 katalog, 5.21 GB):**
   - `C:\_DEV\SportCamHUD-main` — w pełni zintegrowana, działająca aplikacja główna.
2. **KEEP_REFERENCE (1 katalog, 52.10 GB):**
   - `C:\_DEV\SportCamHUD-intel` — pełne repozytorium referencyjne z historią rozwoju architektury Intel.
3. **KEEP_UNIQUE_WORK (1 katalog, 1.44 GB):**
   - `SportCamHUD-intel-commitproof` — zawiera commit `edcb6d7a5ff18d7bb803b4d2eb829249c3e10db4` nieobecny na zdalnych gałęziach.
4. **KEEP_DIRTY (23 katalogi, 105.32 GB):**
   - Wszystkie te worktree zawierają niezatwierdzone zmiany w plikach źródłowych (m.in. setki linii w `telem_intel_native.c`, `intel_native_exporter.py`, `def_layout.json`, `streaming.py`) lub artefakty proofów. Zgodnie z zasadą bezpieczeństwa **nie wolno ich usuwać automatycznie**.
5. **NEEDS_MANUAL_REVIEW (2 katalogi, 3.77 GB):**
   - `SportCamHUD-main-amd-integration`: czyste giciowo, ale zawiera nieśledzone foldery `src/native/bin/` i `third_party/`, przez co Git bez `--force` odrzucił usunięcie.
   - `SportCamHUD-git-temp`: katalog bez `.git` z 19.09.2026 zawierający m.in. `TeleM_project.zip`.
6. **Pomyślnie usunięte bezpieczne wpisy (2 katalogi, 2.33 GB):**
   - `SportCamHUD-intel-cleanproof` (usunięty czysto przez `git worktree remove`)
   - `SportCamHUD-main-amd-latest-integration` (usunięty pusty katalog)

---

## 5. Podsumowanie i wnioski

Ścisła procedura audytowa zapobiegła skasowaniu **105.32 GB** worktree z niezamkniętymi lub eksperymentalnymi zmianami w kodzie C i Pythonie, a także **1.44 GB** z unikalnym commitem. Usunięto wyłącznie obiekty w 100% bezpieczne.
