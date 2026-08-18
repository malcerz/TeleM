# TeleM — ETAP 4B: zachowanie i wykorzystanie prawdziwego timingu GPMF dla ISOE / SHUT

Materiał: `Video/GX030120.MP4`  
Cache: `Video/GX030120.json` / `Video/GX030120.json.meta.json`  
Zmiany: implementacja ETAPU 4B; `TMPC`, GPS9, SmartSync, FIT, mapy, speed, HR i cadence pozostawiono poza zakresem.

## A. Root cause

`to_exiftool_json()` spłaszczał GPMF do dokumentów i zachowywał wartości ISOE/SHUT, ale nie zachowywał ich stream-specific `STMP/TSMP`. Następnie `extract_iso_samples()` i `extract_exposure_samples()` budowały czas jako `GPSDateTime + i/n`. Kwantyzacja czasu dokumentów powodowała 6 kolizji po deduplikacji i cztery sztuczne luki po 133.333 ms.

## B. Implementation

Zmieniono:

- `src/telemetry_gpmf_new.py` — przy ISOE/SHUT zapisuje `ISO_STMP`, `ISO_TSMP`, `ISO_SampleCount`, `SHUT_STMP`, `SHUT_TSMP`, `SHUT_SampleCount`.
- `src/telemetry_extract.py` — nowe wydobywanie timingowe ISO/SHUT; wykorzystuje lokalny odstęp `STMP/TSMP` między kolejnymi blokami i nie deduplikuje poprawnych próbek.
- `src/gui/qt/_mixins/project_mixin.py` — wersja cache podniesiona z 2 do 3, więc stary cache jest automatycznie odrzucany przez istniejący kontrakt fingerprint/version/atomic write.
- `tests/test_gpmf_timing.py` — regresja pełnej, monotonicznej osi ISO/SHUT bez deduplikacji.

Dla danych bez nowych metadanych timingowych zachowany jest dotychczasowy fallback, aby nie zmieniać semantyki innych źródeł.

## C. New timing model

Surowe dane są mapowane następująco:

```text
stream STMP (czas pierwszej próbki bloku)
+ TSMP (licznik próbek)
+ następny blok STMP/TSMP (lokalny sample interval)
→ czas każdej próbki w bloku
→ absolutny czas przez pierwszy poprawny GPSDateTime jako anchor
→ lookup względem target_dt
```

Nie używa się `GPSDateTime + i/n` jako zegara próbek ISO/SHUT. Nie ma założenia, że indeks ISO/SHUT jest indeksem klatki wideo.

Na materiale referencyjnym surowe ISOE/SHUT mają 180 bloków × 30 próbek. `STMP` pierwszego bloku to `1006093120`, `TSMP=30180`; ostatni to `1185272014`, `TSMP=35550`. Różnica daje 179.178894 s i 29.97005 próbek/s, zgodnie z osią GPMF/MP4.

## D. Cache schema

```text
old version = 2
new version = 3
```

Stary cache bez timingowych pól jest nieważny przez zmianę wersji i jest regenerowany. Zachowano `source_size`, `source_mtime_ns`, `version`, generator oraz atomowy zapis JSON i sidecar metadata.

## E. ISO result

| Właściwość | Wynik |
|---|---:|
| Raw count | 5400 |
| Cache count | 5400 |
| Pipeline count | 5400 |
| Pierwsza próbka | `2026-08-18 04:46:25.700000 UTC`, ISO 84 |
| Ostatnia próbka | `2026-08-18 04:49:25.846525 UTC`, ISO 80 |
| Min delta | 33.362 ms |
| Median delta | 33.367 ms |
| P90 delta | 33.369 ms |
| Max delta | 33.371 ms |
| Duplicates | 0 |
| Backward jumps | 0 |

Oś ma 5399 odstępów i efektywną częstotliwość około 29.97005 próbek/s.

## F. SHUT result

| Właściwość | Wynik |
|---|---:|
| Raw count | 5400 |
| Cache count | 5400 |
| Pipeline count | 5400 |
| Pierwsza próbka | `2026-08-18 04:46:25.700000 UTC`, około `1/400` |
| Ostatnia próbka | `2026-08-18 04:49:25.846525 UTC`, około `1/543` |
| Min delta | 33.362 ms |
| Median delta | 33.367 ms |
| P90 delta | 33.369 ms |
| Max delta | 33.371 ms |
| Duplicates | 0 |
| Backward jumps | 0 |

Dekodowanie shutter pozostawiono bez zmiany: wartości sekund są prezentowane jako mianowniki `1/x` tak jak wcześniej.

## G. Block boundary validation

Przejścia są ściśle monotoniczne i mają około 33.367 ms:

| Przejście | ISO | SHUT |
|---|---|---|
| blok 0: sample 29 → blok 1: sample 0 | 04:46:26.667657 → 04:46:26.701024 | 238 → 237 |
| blok 14: sample 29 → blok 15: sample 0 | 04:46:40.681572 → 04:46:40.714939 | 445 → 448 |
| blok 178: sample 29 → blok 179: sample 0 | 04:49:24.845527 → 04:49:24.878894 | 552 → 552 |

Nie występują duplikaty, cofnięcia ani sztuczne przerwy 133.333 ms.

## H. Reference point

`target_dt = 2026-08-18 04:46:40 UTC`, około 14.3 s:

- ISO: indeks 428, czas `04:46:39.980874 UTC`, delta `-19.126 ms`, wartość `70`;
- SHUT: indeks 428, czas `04:46:39.980874 UTC`, delta `-19.126 ms`, około `1/431`.

Jest to normalna kwantyzacja do poprzedniej próbki przy zachowanym lookupie previous-value hold. Nie dopasowywano wyników do Telemetry Overlay.

## I. Multi-point validation

| video_s | ISO index | ISO delta ms | ISO | SHUT index | SHUT delta ms | SHUT |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 299 | -23.383 | 82 | 299 | -23.383 | 377 |
| 30 | 899 | -3.470 | 76 | 899 | -3.470 | 484 |
| 60 | 1798 | -6.772 | 152 | 1798 | -6.772 | 2399 |
| 90 | 2697 | -10.181 | 78 | 2697 | -10.181 | 268 |
| 120 | 3596 | -13.583 | 118 | 3596 | -13.583 | 703 |
| 150 | 4495 | -16.875 | 157 | 4495 | -16.875 | 180 |
| 175 | 5244 | -25.299 | 87 | 5244 | -25.299 | 726 |

Wartości delta są ujemne, ponieważ lookup zachowuje poprzednią próbkę. Ich zmienność wynika z dyskretnej kwantyzacji próbek, bez rosnącego driftu, skoku okresowego lub skoku na granicy bloku.

## J. Cache round-trip

Wykonano świeże parsowanie GPMF oraz drugi odczyt z cache v3.

```text
ISO:  fresh=5400, cache=5400, parity=True
SHUT: fresh=5400, cache=5400, parity=True
```

Porównanie obejmowało wartości i timestampy każdej próbki.

## K. Tests

- Nowy test timingowy ISO/SHUT: przechowanie wszystkich próbek i ścisła monotoniczność.
- Testy zakresowe: **80 passed**.
- Pełna suite: **299 passed, 4 failed, 17 skipped**.

Cztery failure'y są tym samym wcześniejszymi, niezwiązanymi z ETAPEM 4B:

```text
tests/test_amd_native_etap4.py
tests/test_amd_native_etap5b.py
tests/test_qp_analyzer.py
tests/test_render_tab.py
```

Nie naprawiano ich w tym etapie.

## L. Remaining differences vs Telemetry Overlay

W punkcie referencyjnym TeleM po prawidłowym timestampowaniu wybiera około ISO 70 i SHUT `1/431`. Overlay raportował wcześniej około ISO 74 i `1/455`. Różnica została tylko odnotowana; nie zmieniano implementacji w celu dopasowania do Overlay.

## M. Remaining issues

### CONFIRMED

- Raw ISOE/SHUT mają 5400 próbek i prawdziwy stream-specific timing.
- Cache i świeże parsowanie są identyczne.
- `GPSDateTime + i/n` nie jest już źródłem per-sample timingu ISO/SHUT.

### SUSPECTED

- Różnica względem Telemetry Overlay wymaga osobnego audytu, jeśli nadal będzie istotna.

### OUT OF SCOPE

- TMPC, GPS9, SmartSync, FIT sync, track/map, HR, cadence, speed, renderer PTS/VFR, GPU, GUI i dalsze dopasowanie do Overlay.

## ETAP 4B — RESULT

**ZAKOŃCZONY.** ISOE i SHUT zachowują pełne 5400 próbek oraz timing wynikający z `STMP/TSMP`, bez kolizji i sztucznych luk. Nie wykonano zmian poza zakresem.
