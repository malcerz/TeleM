# SPORTCAMHUD — ETAP 5Q: commity Bar i ROSE

Data: 2026-10-13. Repozytorium: `C:\_DEV\BikeRideHUD-main-new`. Gałąź: `fix/gui-freeze-hud-composite`.

## Commity

Początkowy HEAD: `8465744675c5e75b1ce19a6edde7792ee6da7adc`.

- Bar: `eaa8fb00e6fe535d44039b7b44a0fc118ee3940f` — `fix(bar): isolate public cache ownership without compositor copies`. Zawiera wyłącznie `src/indicators/bar.py`, `src/indicators/dispatcher.py`, `src/indicators/compositor.py`, `src/indicators/widget_cache.py`, `src/indicators/raster_ownership.py` i `tests/test_bar_cache_ownership.py`.
- ROSE: `8e761c3b80f192ec447909bfad1501d4dda324ff` — `test(compass): validate final rose raster rotation`. Zawiera wyłącznie `tests/test_compass_source_parity_hotfix.py`.

Przed commitami potwierdzono pełne SHA-256 wszystkich siedmiu plików z `Raporty/etap5p_artifacts/initial_hashes.json`; są identyczne z wersją badaną w 5P. Nie zmieniano funkcji, nie formatowano ani nie porządkowano importów.

## Testy i kontrole

Po obu commitach uruchomiono istniejący zestaw regresji: **189 passed, 0 failed, 0 skipped** (`28.60s`). Obejmował testy cache i ownership, GUI, kompas/cienie/parytet, mux, anulowanie i finalizację. `git diff --check` przechodzi; staging area jest pusty.

Końcowy HEAD to `8e761c3b80f192ec447909bfad1501d4dda324ff`. Tag `amd-known-good-40fps-20261012` zachował swój annotated tag object `8feaa2f78af38ac60fa9713eabe2090564ec4fde` i wskazuje commit `e7582d8e2c212990987380ee10e5980f2dfd5867`.

W working tree pozostaje zastana modyfikacja `def_layout.json` — nie była staged ani commitowana i jej SHA-256 pozostał `8375ca40ba3670dd52de765eb91642082c9097a8fbc12dbe7fa1d1203ffa4440` zgodnie z manifestem 5P. Pozostają też wcześniejsze nieśledzone raporty i artefakty użytkownika. Żadnego z nich nie dodano do commitów. Nie wykonano reset, clean, stash, rebase, merge, push ani synchronizacji portable.

## Wydajność odziedziczona z 5P

Nie powtórzono wielogodzinnej macierzy ani nie wygenerowano nowych MP4. Ponieważ kod jest SHA-identyczny z badanym 5P, wyniki pozostają punktem odniesienia, a nie pomiarem po commitach:

- Stabilniejsza seria NEEDLE: A 40.66042, B 40.59008 Render FPS (−0.173%); Process Effective FPS 35.72 → 35.89 (+0.476%).
- Lekka seria ROSE: A 40.18858, B 40.37300 Render FPS (+0.459%); Process Effective FPS 35.29 → 35.61 (+0.907%).
- W 5P wykonano 20 eksportów AMD 4K po 1500 klatek; MP4 wariantów A/B były bitowo identyczne. Nie wykazano powtarzalnej istotnej regresji, ale nie dowiedziono zerowego narzutu.

## Backendy, DLL i audio

W tych commitach nie zmieniono AMD native exportera, DLL, AMF, D3D11, Gauge/Compass rendererów, Intel, NVIDIA ani parametrów eksportu. Hashy AMD DLL (`7f93c483404f970ea4e2110dcfe12535429b25b11df7415b688c07cef508752f`), AMD exportera (`0598bc640b6ba46ae261dc08fb444461791820e0a32777a83c2a0aea99c7dd43`) i Gauge (`2d8b408aa80a5ff98cfe1f44afd4a9b4730bd5f70153849bfa8c4f6142e55fca`) nie zmieniono względem manifestu 5P. Intel/NVIDIA nie były przedmiotem zmian; rzeczywistych eksportów sprzętowych tych backendów nie uruchamiano w tym etapie.

Single Live Mux pozostaje bez zmian. Wcześniejsze 20 eksportów 5P potwierdziły live mux i obecne audio; po commitach nie powtarzano eksportu MP4. Nie dodano rozdzielania audio/wideo, M4A, ADTS, `audio_cache`, pośredniego MP4 ani remuxingu.

## Otwarte ryzyka

Pozostają ryzyka opisane w 5P: prywatne ABI Pillow i natywne zarządzanie pamięcią w istniejącej ścieżce AMD nie były zmieniane ani ponownie badane; historyczny file-mux fallback pozostaje bez zmian i nie jest wycofany. Zestaw testów po commitach przeszedł, ale nie zastępuje pomiaru FPS ani eksportu sprzętowego po commitach. Nie rozpoczęto kolejnego etapu.
