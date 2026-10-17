# RAPORT — Sprzątanie folderów SportCam* w C:\_DEV (2026-10-15)

## Zadanie
Przejrzeć `C:\_DEV`, usunąć niepotrzebne foldery SportCam*. Usuwanie tylko po zgodzie użytkownika, do Kosza.

## Stan początkowy
- `git worktree list` (z `C:\_DEV\BikeRideHUD-main-new`): `BikeRideHUD-main-new` (f14e45f), `worktree_baseline` (fa8ba86, czysty), `BikeRideHUD-amd-oracle-9451` (prunable, folder nie istnieje).
- Żaden z usuniętych folderów nie był repozytorium git ani worktree.
- Bundle z `_SportCamHUD_BACKUP_20261011_175842`: wszystkie 17 refów obecne w bieżącym repo (`git cat-file -t`). Nowszy pełny bundle: `D:\SportCamHUD_BACKUPS\SportCamHUD_AMD_KNOWN_GOOD_20261012\`.
- Kosz: MaxCapacity >= 14 GB na wolumen, NukeOnDelete=0.

## Decyzja użytkownika
Wariant **A+B** (wiadomość w wątku, 2026-10-15 10:14 UTC).

## Przeniesione do Kosza (15 folderów, ok. 5,7 GB)
| Folder | Rozmiar | Pochodzenie |
|---|---|---|
| `_SportCamHUD_BACKUP_20261011_175842` | 1724 MB | backup ETAP 0 (bundle+zip), zastąpiony backupem na D: |
| `_ETAP4B_BUNDLE_INSPECT_20261012` | 1710 MB | rozpakowany bundle do inspekcji ETAP 4B |
| `_SportCamHUD_ETAP2_TEST_20261011` | 1333 MB | testowa kopia buildu ETAP 2 |
| `_SportCamHUD_ETAP1_TEST_20261011` | 137 MB | testowa kopia ETAP 1 |
| `_SportCamHUD_ETAP1_COLD_TEST_20261011` | <1 MB | 1 plik npz |
| `_SportCamHUD_ETAP1_REAL_PREFLIGHT_20261011` | <1 MB | 18 json |
| `_SportCamHUD_ETAP1_REAL_TEST_20261011` | 0 | pusty |
| `_SPORTCAMHUD_ETAP_4B_RESULTS_20261012` | 251 MB | wyniki pomiarów |
| `_SPORTCAMHUD_ETAP_4E_RESULTS_20261012` | 169 MB | wyniki pomiarów |
| `_SPORTCAMHUD_ETAP_5A_RESULTS_20261012` | 30 MB | wyniki pomiarów |
| `_SPORTCAMHUD_ETAP_5D_RESULTS_20261012` | 22 MB | wyniki pomiarów |
| `_SPORTCAMHUD_ETAP_5E_RESULTS_20261012` | 44 MB | wyniki pomiarów |
| `_SPORTCAMHUD_ETAP_5F_RESULTS_20261012` | 21 MB | wyniki pomiarów |
| `_SPORTCAMHUD_ETAP_5G_RESULTS_20261012` | 191 MB | wyniki pomiarów |
| `_SPORTCAMHUD_ETAP_5H_RESULTS_20261012` | 170 MB | wyniki pomiarów |

Dodatkowo: `git worktree prune -v` usunął martwy wpis `worktrees/BikeRideHUD-amd-oracle-9451`.

## Zachowane
`BikeRideHUD-main-new` (nietknięty), `SportCamHUD-portable` (zmieniany 14.10, unikalne raporty), `worktree_baseline` (worktree), `BikeRideHUD-amd`.

## Miejsce
Pliki są w Koszu, więc wolne miejsce na C: zwolni się (ok. 5,7 GB) dopiero po opróżnieniu Kosza. Przywrócenie: Kosz → Przywróć.

## Izolacja backendów
Brak zmian w kodzie.

## Podsumowanie
PASS: 15/15 folderów przeniesionych do Kosza, prune wykonany. Raport niecommitowany (zgodnie z dotychczasową praktyką raportów w `Raporty/`).
