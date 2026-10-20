# AMD compass / BAR value placement — 2026-10-20

## Stan początkowy i zakres

Repozytorium `C:\_DEV\SportCamHUD`, `main`, HEAD `16cab38`.
Zachowano istniejące zmiany użytkownika w `def_layout.json` oraz wszystkie
zastane pliki nieśledzone. Bez branch/worktree/stash/push. Przeczytano
AGENTS.md i BENCHMARKS.md. Produkcyjna DLL AMD ma SHA-256
`BBCA75FBD0DFC5D7CBB61922E92F8D5F049B4305DD18335315667E6E5E54CA5F`.

## A. Diagnoza i minimalna poprawka

**Nie odtworzono zgłoszonego zamrożenia dla aktualnego ustawienia GPMF.**
Eksport sprzed zmian kodu na istniejącym materiale użytkownika pokazuje
058° → 062° → 061° → 059° (klatki 0/30/60/119).
Nie można uczciwie przypisać temu konkretnemu zgłoszeniu potwierdzonej przyczyny.
Użytkownika poproszono o projekt i przedział czasu występowania błędu.

Potwierdzono osobny, rzeczywisty błąd ścieżki AMD final przy budowaniu cache:
`amd_native_exporter.py` przekazywał `heading_samples` GPMF, następnie GPX,
następnie kurs wyliczony z przekazanego tracka, **ignorując `compass.source`**.
Argument `compass_heading_samples` nadpisywał poprawny wybór w builderze.
Dla ustawienia FIT, stałego GPMF=90° i zmiennego FIT=350°→20° stary blok
zwracał stałe 90°. Preview używa `telemetry.resolve_samples` i wybranego źródła.
To potwierdzona przyczyna zamrożenia dla takiej kombinacji danych, nie dowód
na przyczynę pierwotnego zgłoszenia z GPMF.

Drugi problem: builder przy pustej liście ponownie wybierał FIT/GPMF/GPX,
a ostatecznie także `heading_samples` z ogólnej ścieżki (potencjalnie dystans).
Mógł też sięgać do WORKER_CACHE mimo jawnie przekazanych danych nowego projektu.

Zmiany:

- `src/ffmpeg/amd_native_exporter.py`: `_amd_compass_samples` korzysta z
  kanonicznego `resolve_samples_from_sources`, zgodnie z ustawionym źródłem;
  wywołanie raz podczas przygotowania eksportu, bez pracy dodatkowej per-frame.
- `src/render_preparation.py`: `build_telemetry_cache_vectorized` respektuje
  jawnie pusty stream, nie zastępuje go innym źródłem ani dystansem; przy
  przekazanym `field_samples` używa danych tego projektu. Przygotowanie w GUI
  również nie zastępuje brakującego wybranego streamu GPMF-em.
- `compute_cache_key`: kontrakt kompasu podniesiono do
  `selected_source_cog_v2_no_fallback`; stare cache tego kompasu nie są używane.
  Dotychczasowe fingerprinty plików, źródło, czas startu, FPS i timeline nadal
  należą do klucza. Nie zmieniano formatu serializacji kolumn.
- `worker_cache.py`, `frame_data.py`, `frame_renderer.py` i compositor:
  prześledzone, bez zmian. `heading_compass[frame_idx]` trafia przez
  `extra_indicators["compass"]` do istniejącego renderera tarczy. Cache rastra
  kompasu już uwzględnia heading i formatowany tekst. Wygląd bez zmian.

Dowód: `tests/test_amd_compass_selected_source.py` sprawdza FIT/GPMF/GPX/auto,
61 kolejnych klatek przy 30 FPS, interpolację przez północ, zapis/odczyt mmap
oraz brak przejęcia danych poprzedniego projektu przy pustym streamie.
Wraz z istniejącymi testami source/parity: **12 passed**.

## B. BAR

Implementacja i walidacja w toku w kolejnym logicznym commicie.

## Wstępne testy sprzętowe i ograniczenia

Kanoniczne pliki `Video/GX020079.MP4` i `.fit` są nieobecne w checkoutcie.
Przed użyciem zgłoszono parę zastępczą istniejącego materiału użytkownika:
`F:\GoPro\2026-10-12\GX010368.MP4` + `Afternoon_Ride.fit`.
Użyto istniejącego harnessu `SportCamHUD.py --test-amd-export`, bez zmiany
kodowania, muxowania lub DLL. To materiał 8K → 4K, QUALITY/HEVC/40M/HLG,
start 60 s. Nie jest kanonicznym benchmarkiem 1131 klatek.

Wyniki, logi, profile, MP4 i zrzuty: `Raporty/amd_compass_bar_20261020/`.
Pierwszy start harnessu zablokował własny plik loga, ponieważ stdout skierowano
do tej samej nazwy co log eksportera; poprawiono uruchomienie na `.stdout.log`.
Nie zmieniano storage preflight.

## Status etapu A

PASS: naprawiony i przetestowany wybór źródła kompasu AMD oraz brak fallbacku
do starego streamu/dystansu. NOT PROVEN: przyczyna pierwotnego zgłoszenia GPMF;
reprodukcja wymaga wskazania konkretnego projektu i czasu. NOT PROVEN: 40 FPS.
QP/VBR/VBV/HRD/live mux/finalizacja/DLL i kod Intel/NVIDIA pozostały niezmienione.

Commit A: `fix(amd): honor selected compass source in final telemetry cache`.
Identyfikatory i końcowe wyniki zostaną uzupełnione przy etapie B.
