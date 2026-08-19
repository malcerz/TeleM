# Wprowadzenie dla Gemini — TeleM

Przejmujesz istniejący projekt **TeleM** po długiej serii audytów i poprawek. Nie zaczynaj od przebudowy architektury i nie próbuj „upraszczać” kodu. Najważniejsze kontrakty telemetryczne, timingowe, geometryczne oraz AMD z-order zostały już ustalone i mają pozostać nienaruszone.

Najpierw przeczytaj `AGENT.md` w repozytorium. Traktuj go jako obowiązujący kontrakt pracy.

## Czym jest TeleM

TeleM generuje nakładki telemetryczne na wideo GoPro na podstawie:

- GPMF,
- FIT,
- GPX.

Projekt posiada preview oraz final rendering. Aktualnie najważniejsza produkcyjna ścieżka to AMD:

```text
AMD_NATIVE_D3D11
D3D11VA decode
D3D11 VideoProcessor
GPU HUD
GPU track_map
GPU gauge
AMD AMF HEVC encode
PRECOMPUTED telemetry
```

Materiał referencyjny:

```text
Video/GX030120.MP4
Video/Poranna_jazda_na_rowerze.fit
```

Wideo:

```text
3840×2160
30000/1001 FPS
HEVC
~180 s
5395 decoded frames
```

Sprzęt referencyjny:

```text
AMD Ryzen 5 5500U
AMD Radeon(TM) Graphics
```

## Najważniejsze zamknięte kontrakty

Nie zmieniaj ich bez osobnego polecenia:

```text
requested GPMF -> GPMF only
requested FIT  -> FIT only
requested GPX  -> GPX only

missing = None
real zero = 0.0

STEP current:
greatest timestamp <= target_dt

chart history:
timestamp <= target_dt
```

GPS9 korzysta z prawdziwego czasu `days + secs`. Nie syntetyzuj czasu z `creation_time`.

Geometry/font bug został zamknięty. Canonical text size to `font_size`.

AMD map z-order został zamknięty przez:

```text
CPU_BELOW_MAP
-> GPU_MAP
-> CPU_ABOVE_MAP
```

Poprawny native lifecycle:

```text
base VP
-> clear previous CPU_ABOVE_MAP bbox
-> CPU_BELOW / chart
-> GPU gauge
-> GPU map
-> current CPU_ABOVE_MAP
-> final HUD
```

Nie przesuwaj mapy na koniec layoutu i nie zmieniaj insertion order.

## Ostatnio zakończony etap — 8C

ETAP 8C usunął duży CPU bottleneck.

Przed:

```text
CPU_ABOVE_MAP:
getchannel("A").getbbox() na całym 3840×2160
~8.29 mln pikseli/frame

median ~10.7–11.1 ms
p95 ~19 ms
```

Po:

```text
existing compositor bbox
-> union
-> pad 64 px
-> candidate crop
-> local alpha getbbox
-> final crop
```

Typowy candidate:

```text
559×190
```

Typowy final bbox:

```text
~431×62
```

Wynik:

```text
above_bbox_crop median ~0.25 ms
p95 ~0.8–1.1 ms
alpha scan reduction ~98.7%
```

3 × 900 klatek:

```text
28.073 FPS
28.349 FPS
27.786 FPS

median 28.073 FPS
dropped 0
```

Pełna suite:

```text
336 passed
3 failed
17 skipped
```

Trzy failure'y są stare i niezwiązane:

```text
test_amd_native_etap4.py
test_qp_analyzer.py
test_render_tab.py
```

Nie naprawiaj ich bez osobnego zadania.

## Co jest teraz istotne

Mimo usunięcia full-frame alpha scan projekt nadal osiąga około 28 FPS na referencyjnym AMD 5500U.

Nie zakładaj automatycznie, że kolejny bottleneck to mapa, gauge, AMF albo `compose_overlay`.

Pełny `CPU_ABOVE_MAP` canvas nadal jest tworzony przez istniejące `compose_overlay()`. To jest **kandydat do kolejnego audytu**, nie potwierdzony jeszcze root cause.

Jeżeli dostaniesz ETAP 8D:

1. najpierw profiluj,
2. oddziel allocation / clear / compose / crop / upload,
3. sprawdź czy region-aware composition jest realnie opłacalne,
4. nie zmieniaj renderingu przed potwierdzeniem kosztu,
5. zachowaj pixel parity i ETAP 7D lifecycle.

## Zasady pracy

- wykonuj dokładnie zakres promptu,
- przy `READ-ONLY` nie zmieniaj kodu,
- nie rób dużych refaktorów bez potrzeby,
- nie zmieniaj telemetry correctness contracts,
- nie zmieniaj encoder settings bez polecenia,
- testy jednostkowe nie zastępują realnego AMD runtime,
- po każdym etapie wygeneruj `RAPORT_TELEM_ETAP_<nr>.md`,
- rozdziel `CONFIRMED / SUSPECTED / OUT OF SCOPE`,
- po raporcie zatrzymaj się.

Pierwsza czynność w repo:

```text
1. przeczytaj AGENT.md
2. git status
3. przeczytaj prompt aktualnego etapu
4. odtwórz baseline
5. dopiero potem analizuj lub zmieniaj kod
```

Nie zakładaj, że wcześniejsza nazwa timera opisuje rzeczywisty koszt. W tym projekcie bucket `chart_upload` okazał się w rzeczywistości kosztem `CPU_ABOVE_MAP` alpha scan. Zawsze sprawdzaj dokładny zakres timera przed wnioskami wydajnościowymi.
