# Intel HEVC Main10 — eksperyment z hevcqp (rzeczywisty QP bloków)

Data: 2026-10-17 · i7-1265U (2P+8E, 12 wątków) · materiał: eksporty kanonicznego harnessu Intel z `C:\GoPro\GX010378.MP4`, HEVC Main10 HLG, 40M VBR
Kod SportCamHUD: bez zmian. Dane surowe: `Raporty/intel_hevc_qp_20261017/hevcqp/`. Skrypty i build: `scratch/hevcqp/`.

## Werdykt w skrócie

- hevcqp **działa** na Intel HEVC Main10 i zwraca **prawdziwy, zmienny QP bloków**: 16–35, a nie stałe 26.
- Metryka jest **poprawna**. Na x265 przy stałym QP wynik jest dokładny, a przy AQ zgadza się z QP raportowanym przez sam enkoder (±0.02).
- Narzędzie jest **za wolne do pracy w czasie rzeczywistym**: ok. **17–19 kl./s na jednym rdzeniu** (pełne dekodowanie), wobec ~55 kl./s eksportu Fast. Integracji nie implementowano (zgodnie z poleceniem).

## Etap 1 — pobranie, zawartość, licencje, integralność, build

| Element | Wynik |
|---|---|
| Wydanie 260418 | 1 asset `hevcqp_260418.zip` (11 037 549 B, sha256 wg GitHub `d78532f0…5407`) — **nie pobierano i nie uruchamiano** gotowych `.exe` (niezweryfikowane binaria z konta prywatnego). |
| Źródła | zipball tagu 260418 (10 918 584 B, sha256 `64959EA0…5C89`); `hevcqp.cpp`, `hevc_parse.cpp`, `h264_parse.cpp`, `utils.cpp`, `ffprobe_mod/hevcdec.c` **zgodne bajt w bajt** z commitem `af2134e` na GitHub. |
| Licencje | hevcqp: **Unlicense** (domena publiczna). ffprobe_mod: **LGPL 2.1** (praca pochodna FFmpeg 8.0; modyfikacje oznaczone `mod by HG`, częściowo od stg7/hevc_bitstreamparser). |
| Przegląd kodu | hevcqp tylko uruchamia `ffmpeg.exe … -c:v copy -f hevc pipe: \| ffprobe_mod.exe -threads 1 …` przez `_popen` i parsuje tekst; brak operacji ryzykownych. Modyfikacja dekodera to 3 bloki (suma ważona QP w `hls_coding_unit`, reset w `hevc_frame_start`, `printf` w `hevc_frame_end`). |
| Build | MSYS2 (tarball 42 860 696 B; podpis GPG instalatora **nie został zweryfikowany** — klucz spoza keyringu pacmana; pakiety `make/nasm/p7zip/diffutils` zweryfikowane przez pacman). `ffprobe_mod` zbudowany z **lokalnego FFmpeg 8.0** + **te same 3 bloki HG** (wstawione ręcznie po przeglądzie; plik autora różni się od lokalnego snapshotu o 513 linii upstream), minimalna konfiguracja, x86 asm włączone, clang llvm-mingw. `hevcqp.exe` skompilowany ze źródeł bez zmian (tylko `-include process.h` dla MinGW). |

## Etap 2 — wyniki QP na materiale Intel

| Materiał | Klatki OK | Śr. QP (średnia klatek) | Zakres śr. QP klatek | SD między klatkami | QP bloków min / max | Śr. SD w klatce | Klatki ≠ 26 |
|---|---|---|---|---|---|---|---|
| Fast 60 | 60/60 | 19.46 | 16.00–20.71 | 1.21 | 16 / 26 | 0.66 | 60 |
| Fast 600 | 600/600 | 21.88 | 16.00–24.76 | 1.38 | 16 / 28 | 0.85 | 600 |
| Balanced 600 | 600/600 | 21.58 | 16.00–24.60 | 1.35 | 16 / 28 | 0.84 | 600 |
| Quality 600 | 600/600 | 21.28 | 16.00–23.78 | 1.26 | 16 / 27 | 0.84 | 600 |
| Fast 1800 | 1800/1800 | 25.16 | 16.00–31.87 | 2.90 | 16 / 35 | 0.91 | 1800 |

Obserwacje (dane per klatka: `*.dat`):
- QP zmienia się między klatkami. Klatki IDR mają jednolity QP 16 lub 18 (SD 0), klatki inter przeważnie 18–25, w dłuższym fragmencie do ~32.
- Wewnątrz klatki QP jest prawie jednolity: BRC Intela ustawia QP klatki przez `cu_qp_delta`, a w nagłówku slice jest atrapa 26. Pojedyncze bloki z QP 26 to najpewniej CU bez residuum (skip), które zgodnie ze standardem dziedziczą przewidywany QP, a na początku slice'a wynosi on SliceQpY = 26. Nie mają współczynników, więc nie wpływają na kwantyzację, ale hevcqp wlicza je do średniej (lekko ją zawyżają i zwiększają SD w klatce).
- Typy: hevcqp oznacza klatki inter jako „B”, bo FFmpeg zwraca `pict_type` ze `slice_type`. Intel koduje P jako generalized-B; nasz parser klasyfikuje je poprawnie jako P (590 P + 10 I).

## Sposób liczenia średniego QP

- Po każdej CU: `w = 1 << (log2_cb_size − ct_depth)`. Dla CTB 2^L daje to w = 2^(L−2·depth), czyli wagę **proporcjonalną do powierzchni CU** (stała 2^L na strumień się skraca).
- Średnia klatki = Σw·QpY / Σw (**średnia QP ważona powierzchnią**). Wariancja = Σw·QpY² / Σw − średnia², SD = pierwiastek z wariancji. Min i max to wartości po wszystkich CU.
- `lc->qp_y` w FFmpeg to QpY w **natywnej domenie** (−QpBdOffset…51). Dla HEVC hevcqp nie stosuje przesunięcia −12; przesuwa tylko H.264 10-bit. Zgodność z QP raportowanym przez x265 10-bit potwierdza domenę.
- Uwaga: hevcqp wypisuje w pliku statystyk `sqrt(var)` (SD), ale na stdout „StdDev (MB)” liczy z wariancji klatek. Do raportu użyto pliku per klatka.

## Weryfikacja niezależna

| Test | Wynik |
|---|---|
| x265 Main10, stały QP 22/30/38, AQ/cutree wył. | średnia klatek dokładnie 22/30/38, min = max, SD = 0 (60/60 klatek) |
| x265 Main10, CRF 28 + AQ 2 (aktywne `cu_qp_delta`) vs CSV enkodera (`QP` per klatka) | średnia różnica bezwzględna 0.009, maksymalna 0.02 (zaokrąglenie CSV do 2 miejsc), 60/60 klatek |
| Intel: spójność | QP w zakresie [16, 35] ⊂ [−12, 51]; IDR = jednolity QP; średnia rośnie razem z rozmiarem klatek w dłuższym fragmencie |

Wyniki: `Raporty/intel_hevc_qp_20261017/hevcqp/verify/verify_metric.json`.
Ograniczenie: dla samego materiału Intel brak „prawdy” od enkodera, bo oneVPL HEVC QP jest niewiarygodny (patrz `RAPORT_INTEL_HEVC_QP_AUDYT_20261017.md`). Poprawność przenosimy z testów x265 na ten sam dekoder.

## Etap 3 — wydajność (bez innych obciążeń)

| Materiał | Czas | FPS analizatora | CPU (rdzenie zajęte średnio) | Szczyt RAM |
|---|---|---|---|---|
| 60 klatek | 3.7 s | 16.2 | 0.88 | 133 MB |
| Fast 600 | 32.4 s | 18.5 | 0.97 | 133 MB |
| Balanced 600 | 35.2 s | 17.0 | 0.98 | 194 MB |
| Quality 600 | 35.5 s | 16.9 | 0.97 | 225 MB |
| Fast 1800 | 94.4 s | 19.1 | 0.98 | 133 MB |

- 97–99% czasu CPU zużywa `ffprobe_mod` (pełne dekodowanie z rekonstrukcją, `-threads 1`); ffmpeg (remux) i hevcqp są pomijalne.
- **Pełne dekodowanie jest konieczne** w tej implementacji: modyfikacja nie wyłącza predykcji, transformaty ani MC. Wielowątkowość dekodera odpada, bo sumy są globalne i niebezpieczne przy wątkach ramek/slice'ów.
- **Wydzielenie samego CABAC** jest możliwe teoretycznie (dekodowanie składni coding_quadtree/transform_tree bez rekonstrukcji). Szacunkowo przyspieszyłoby to 2–3×, czyli nadal ok. 1 rdzeń przy 55 kl./s. Wymaga własnej implementacji (FFmpeg nie ma trybu „tylko składnia”). Niezmierzone.
- Na potrzeby porównania: eksport Fast jest ~3× szybszy niż analizator. Bez próbkowania potrzebne byłyby ok. 3 rdzenie.

## Etap 4 — możliwość integracji (bez implementacji)

1. **Bez pliku tymczasowego:** tak. `ffprobe_mod` czyta Annex B z `pipe:`, a natywny enkoder i tak oddaje Annex B w `mfxBitstream`.
2. **Pakiety z natywnego enkodera:** tak, w procesie przez zmodyfikowany `libavcodec` (dekoder HEVC) karmiony pakietami z wątku drain. Wymagałoby to własnego, zmodyfikowanego builda avcodec (obecny runtime jest niezmodyfikowany).
3. **Asynchronicznie:** tak, ale analizator nie nadąża. Możliwe warianty:
   - **(a)** pełne pokrycie: 3 dekodery na zamkniętych GOP-ach (IDR co 60 klatek) na rdzeniach E;
   - **(b)** próbkowanie, np. co 3. GOP na 1 rdzeniu — QP dla ~1/3 klatek, opóźnienie ok. 1 GOP;
   - **(c)** analiza po eksporcie (+~3× czasu eksportu dla pełnego pliku).
4. **Licencje:**
   - hevcqp: brak ograniczeń (Unlicense);
   - zmodyfikowany dekoder: **LGPL 2.1** — przy dystrybucji trzeba dołączyć źródła modyfikacji i umożliwić podmianę biblioteki (linkowanie dynamiczne), z informacją o zmianach;
   - wbudowanie statyczne w GPL-niezgodny kod jest problematyczne.
   Obecny runtime SportCamHUD już dystrybuuje DLL FFmpeg, więc model jest ten sam, ale należy sprawdzić, czy dotychczasowy build jest LGPL, czy GPL (np. z x265) — tego nie badano.
5. **Wpływ na FPS renderera** (eksport Fast 600, kolejność 0,1,3,3,1,0 analizatorów w tle):

| Analizatory w tle | FPS eksportu (przebiegi) | Średnio | Zmiana |
|---|---|---|---|
| 0 | 36.6 / 32.5 | 34.6 | — |
| 1 | 33.1 / 27.7 | 30.4 | −12% |
| 3 | 19.5 / 21.3 | 20.4 | −41% |

Bazowy FPS (32–37) był wyraźnie niższy niż wcześniej tego dnia (~54) — maszyna rozgrzana po wielogodzinnych testach; ważniejsze są zmiany względne. Jeden analizator kosztuje ~12% FPS, pełne pokrycie (3) ~41%. To nieakceptowalne przy wymaganiu „bez istotnego spadku wydajności”.

## Ograniczenia

- **Techniczne:**
  - pełne dekodowanie programowe 4K Main10 (~1 rdzeń na 17–19 kl./s);
  - globalne liczniki uniemożliwiają wielowątkowość;
  - wynik wlicza CU bez residuum (QP przewidywany);
  - hevcqp nie obsługuje przyciętych strumieni i klatek niewyświetlanych (README);
  - etykieta „B” dla generalized-B Intela.
- **Integralność:** podpis instalatora MSYS2 niezweryfikowany. Gotowych binariów autora nie uruchamiano — wyniki pochodzą z własnego buildu z przejrzanego kodu.
- **Licencyjne:** LGPL 2.1 dla zmodyfikowanego dekodera (obowiązki przy dystrybucji); hevcqp bez ograniczeń.

## Warianty dalszego postępowania

1. **Pozostawić Slice QP na żywo + opcjonalny raport QP po eksporcie** (hevcqp-like, offline, ~3× czasu eksportu albo w tle po zakończeniu). Najmniejsze ryzyko.
2. **Lekki dekoder CABAC tylko pierwszych QG klatki.** Intel ustawia jednolity QP klatki przez `cu_qp_delta`, więc odczyt pierwszego zakodowanego `cu_qp_delta` w klatce dałby „QP klatki BRC” za ułamek kosztu. Ograniczony zakres CABAC (split/skip/pred/part/merge/mvd/cbf do pierwszego `cu_qp_delta_abs`), ~1000 linii C. Nie dałby min/max ani pełnej średniej. Wymaga osobnej decyzji i walidacji z hevcqp jako referencją.
3. **Próbkowanie GOP w tle** (1 dekoder, co 3. GOP): −12% FPS według pomiaru — raczej nie.
4. **Pełny syntax-only CABAC** dla wszystkich CU: dokładna średnia/min/max, szacunkowo ~1 rdzeń przy 55 kl./s. Duży nakład; wymaga pomiaru przed decyzją.
