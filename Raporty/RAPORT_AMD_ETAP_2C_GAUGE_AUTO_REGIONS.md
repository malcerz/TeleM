# RAPORT AMD ETAP 2C — AUTO dynamic-region gauge uploads (regiony z semantyki renderera)

Data: 2026-08-25 · Branch: `amd-render` · HEAD: `d9afa75` · Backend: `AMD_NATIVE_D3D11` (izolowany)

---

## 1. Zadanie

Zastąpić ręczne `AMD_GAUGE_DYNAMIC_RECTS` (ETAP 2B) trybem **AUTO**: prostokąty
uploadu persistent AFTER-MAP GPU Speed Gauge mają wynikać **z geometrii
renderera** (bbox igły ∪ bbox tekstu wartości, raportowany przez `gauge.py`
w czasie renderu), skalować się z size/resolution/position/HUD-scale/DPI i
zmieniać epokę przy każdej zmianie stylu/geometrii. Bez hardcoded 960×960,
bez per-frame numpy-diff w ścieżce produkcyjnej, z fallbackiem SAFE = pełny
upload tile'a GPU (nigdy CPU). Feature domyślnie **OFF**
(`AMD_AFTER_MAP_GAUGE_GPU` default bez zmian); jawny env MANUAL ma wygrywać
z AUTO; mandowany log `[AMD GAUGE GPU] mode=... rects=N geometry=WxH
full_refresh=N`; zachowany pełny resync co `AMD_GAUGE_FULL_REFRESH_N`.

## 2. Stan początkowy

* ETAP 2B COMPLETE: regiony wyłącznie z env `AMD_GAUGE_DYNAMIC_RECTS`
  (jedna wartość `444,468,424,360` zmierzona offline dla v10/4K), epoka =
  `(gw,gh,gx,gy)`; mediana 610 560 B/frame (16.56% tile'a).
* Brak mechanizmu wyprowadzania rectów z renderu; zmiana stylu/skali gauge
  poza zmierzony sektor = ryzyko (raport 2B §11.1).
* Drzewo robocze zawierało niezwiązane modyfikacje (pozostawione nietknięte).

## 3. Projekt AUTO (semantyka)

**Renderer (`gauge.py`) raportuje** do modułowego rejestru
`GAUGE_DYNAMIC_INFO[key]` przy KAŻDYM renderze:

* `needle_bbox` — dokładny bbox trójkąta igły w współrzędnych obrazka
  widgetu (wierzchołki ± `needle_width/2`, margines rasteryzatora 2 px);
* `text_bbox` — bbox sklejonego kafla 5Q (byte-exact) lub `textbbox()`
  z tymi samymi metrykami co rysowanie (ścieżka legacy);
* `sig` — krotka styl/geometria (rozmiary, kąty, skala, font, grubości,
  kolory, marker, tekst, compose5Q, opacity, rotacja…): **jakakolwiek
  zmiana ⇒ nowa epoka ⇒ pełny upload + przeliczenie regionów**;
* compass / rotacja ≠ 0 / brak rekordu ⇒ `supported=False`.

**Eksporter** mapuje supporty na tile: `_support_to_tile_rect()` (floor/ceil
+ margines bezpieczeństwa 1 px, offset clipu `cx0-_wgx`, clamp), sumuje
z supportami **poprzedniej klatki** (erase przeniesionych elementów świeżymi
bajtami), scala superset-owo `_merge_tile_rects()` (limit 8 jak pętla
konsumenta). Klatka bez żadnych supportów ⇒ `gauge_clear_only` (same
early-clears HUD, zero bajtów). Fallback SAFE: pełny tile co klatkę.
Kolejność Z / warstwy / shader / `BlendGauge` — bez zmian.

## 4. Zmienione pliki (ten etap)

1. `src/indicators/gauge.py` — rejestr + `record/get_gauge_dynamic_info`,
   supporty igły/tekstu, sygnatura, rekord compass(unsupported).
2. `src/ffmpeg/amd_native_exporter.py` — import rejestru; helpery AUTO;
   wybór trybu FULL_TILE/MANUAL_RECTS/AUTO (+logi); stan epoki+supportów;
   sekcja capture 2B/2C; oracle `AMD_GAUGE_REGION_ORACLE`;
   `PreparedFrame.gauge_clear_only`; early-clears także dla clear-only;
   profil `etap2c_gauge_regions`.
3. `scratch/etap2c_unit_probe.py`, `run_etap2c_state_sim.py`,
   `run_etap2c_smoke.py`, `run_etap2c_mode_matrix.py`,
   `run_etap2c_ghost_ab.py`, `check_etap2c_ghost_equivalence.py`,
   `run_etap2c_bench.py` — walidacja.
4. **Native C++/DLL: ZERO zmian** (ABI 9, build z HEAD `d9afa75`).

## 5. Implementacja (kluczowe fakty)

* Env: `AMD_GAUGE_AUTO_REGIONS` default **ON** (gdy flaga gauge GPU ON),
  ale całość martwa dopóki `AMD_AFTER_MAP_GAUGE_GPU` OFF (default).
  `AMD_GAUGE_DYNAMIC_RECTS` ustawione ⇒ MANUAL_RECTS wygrywa z AUTO.
* Epoka AUTO: `(gw, gh, gx, gy, hash(sig))`; nieobsługiwane klatki dzielą
  wspólną epokę `"fallback"` (brak spamu logami/uploadów).
* Supporty prev aktualizowane **co klatkę** (także full/resync) — patrz §6a.
* Logi: start `[AMD GAUGE GPU] mode=<FULL_TILE|MANUAL_RECTS|AUTO> rects=…
  geometry=- full_refresh=N`; przy zmianie epoki tylko raz:
  `mode=AUTO_SAFE|AUTO_FALLBACK_FULLTILE|MANUAL_RECTS … geometry=WxH …`.
* Oracle (env-gated): diff kolejnych capture'ów ⊆ wysłane recty;
  shape-change = zmiana epoki ⇒ liczony jako full; naruszenia do profilu.

## 6. Defekty graniczne znalezione i naprawione w ramach ETAP 2C

a) **Stale-prev po resyncu**: pierwsza klatka regionowa po pełnym uploadzie
   unionowałaby cur z support sprzed ≥2 klatek → potencjalny ghost między
   pozycjami igły. Naprawa: aktualizacja prev-supportów co klatkę.
b) **Crash oracle przy zmianie geometrii** (shape mismatch numpy) → guard +
   klasyfikacja jako full frame.
c) **Rotacja** nie wchodziła do `sig` → dodana (fallback i tak SAFE dla
   rot ≠ 0; teraz dodatkowo distinct epoki).

## 7. Testy jednostkowe i symulacja producenta

* Unit probe (`scratch/etap2c_unit_probe.py`): rekord speed (needle
  284.3–317.9 × 23.5–278.4; text 246–331 × 331–365 @576²), sig
  value-independent / style-sensitive / geometry-sensitive, skalowanie bandy
  z size, compass unsupported, mapowanie tile (offsety/clamp/margines/
  malformed-safe), merge-superset. **PASS.**
* Symulacja maszyny stanów (`run_etap2c_state_sim.py`, realne rendery,
  logika 1:1 z eksporterem): M1 sizes 160/240/360/480 — missed=0; M2 zmiana
  geometrii i stylu w trakcie (epochs=2, full na krawędzi, missed=0); M3
  warianty arc210/redtext/wide — missed=0; M4 resynci obecni. **ALL PASS.**

## 8. Testy E2E (real pipeline, DLL ABI 9)

* **Smoke 4K/40f (AUTO+oracle)**: PASS — oracle 39f diff, 36 region, 3 fulls
  (=co 10f), **missed_dynamic_pixels=0**, violations=[].
* **Smoke 1080p/24f**: PASS — geometry **480×480** (skaluje się z wyjściem),
  missed=0.
* **Mode matrix**: T1 default→AUTO ✓, T2 rects→MANUAL_RECTS ✓ (env wygrywa),
  T3 `AUTO_REGIONS=0`→FULL_TILE ✓.
* **Ghost A/B (340f, 13 klatek sweep)**: tile canvas **bit-exact** AUTO vs
  FULL-TILE(2A-ref) na wszystkich klatkach (differing px=0); oracle AUTO:
  339f, 337 region, 2 fulls (f0+f120), changed=76 143, **missed=0**; bbox
  stabilny (1440,665,960×960); art varies. **GHOSTING_PARITY: PASS.**

## 9. Benchmark 1131f REF/FULL/AUTO (GX010115 / v10 / 3840×2160)

| metryka | REF | FULL (2A-path) | **AUTO (2C)** | Δ AUTO vs FULL |
|---|---|---|---|---|
| RENDER FPS | 26.558 | 32.443 | **35.965** | **+3.52** |
| USER EFFECTIVE FPS | 22.479 | 26.726 | **29.047** | +2.32 |
| above_total avg/med/p95 [ms] | 21.68/20.75/31.74 | 14.14/12.99/24.86 | **13.90/12.95/24.22** | −0.25 avg |
| compose_overlay avg [ms] | 5.636 | 6.010 | 6.019 | ≈0 |
| gauge_tobytes avg/med/p95 [ms] | — | 1.589/1.469/2.089 | **0.245/0.214/0.352** | **−85%** |
| gauge_upload avg/med/p95 [ms] | — | 0.533/0.509/0.741 | **0.261/0.249/0.533** | −51% |
| bajty/klatkę avg/med | — | 3 686 400 | **351 690 / 329 780** | **−90% (med = 8.94%)** |
| producer_prepare avg [ms] | 31.34 | 24.09 | **22.31** | −1.78 |
| pipeline_total avg [ms] | 6.02 | 6.09 | **5.04** | −1.04 |
| region/full frames | — | 0/1131 | **1121/10** | resync co 120f ✓ |

vs ETAP 2B (manual 1 rect): mediana bajtów 610 560 → **329 780 (−46%)**, bez
offline-pomiaru rectów. REF-vs-gauge-on `compose_overlay` +0.37 ms występuje
identycznie w FULL (pre-existing na obecnym drzewie, nie jest regresją 2C).

## 10. Izolacja backendu

Zmiany wyłącznie w `src/indicators/gauge.py` (współdzielony renderer —
zmiana czysto informacyjna, zero wpływu na piksele: potwierdzone bit-exact
A/B) oraz `src/ffmpeg/amd_native_exporter.py` (AMD). NVIDIA/CUDA/NVENC,
Intel/QSV, AMF, map-rotate, GPU HR/Cadence, kolejność warstw — brak zmian.
Ścieżka legacy BEFORE-MAP nie wchodzi w regiony. Default feature bez zmian.

## 11. Ryzyka / ograniczenia

1. Regiony pokrywają elementy dynamiczne raportowane przez renderer; nowy
   element dynamiczny w gauge bez aktualizacji rekordu/sig wymagałby
   rozszerzenia — oracle (`AMD_GAUGE_REGION_ORACLE=1`) wykrywa lukę jako
   MISSED>0.
2. `hash(sig)` jest per-proces (PYTHONHASHSEED) — poprawne, bo epoka żyje
   tylko w ramach jednego renderu.
3. Klatki clear-only (zero supportów) nie występują w mierzonym workloadzie
   (igła zawsze obecna) — code-reviewed + unit-covered only.

## 12. Odkryte poza zakresem (do osobnych zadań)

* Latentny `NameError` starego probe'a `AMD_GAUGE_VARIABILITY_PROBE`
  (`gauge_bytes` także na klatkach regionowych) — superseded przez oracle
  2C; nie dotykane (scope).
* `compose_overlay` +0.37 ms (REF vs gauge-on) obecne także w FULL —
  pre-existing na obecnym drzewie.

## 13. NOT TESTED / NOT PROVEN

* Zmiana geometrii/stylu **w prawdziwym E2E renderze** nie występuje przy
  statycznym presecie — pokryte symulacją producenta (M2: realne rendery,
  logika 1:1) i guardem oracle; NOT TESTED in-native.
* Fallback compass / rotacja ≠ 0 w realnym E2E: pokryty unit-probe + logiką
  fallback-epoki; brak przebiegu z compass-presetem — NOT TESTED E2E.
* GUI smoke: niewymagany (flaga OFF default; ścieżka default = REF run).

## 14. Podsumowanie

ETAP 2C: recty uploadu AFTER-MAP GPU Speed Gauge wyprowadzane automatycznie
z semantyki renderera (igła ∪ tekst ∪ poprzednia klatka), epoki z sygnatury
styl/geometria, fallback SAFE full-tile, MANUAL env zachowany z priorytetem.
Bit-exact vs referencja 2A, oracle missed=0 na wszystkich przebiegach,
benchmark: **35.965 fps (+3.52 vs FULL)**, mediana **329 780 B/frame
(8.94% tile'a)**. Feature default OFF — **bez flipowania defaultu**.

## STATUS KOŃCOWY

```
AMD ETAP 2C COMPLETE
```

Uzasadnienie: wszystkie akceptacje zweryfikowane pomiarami (unit / sim /
E2E smoke 4K+1080p / mode matrix / ghost bit-exact / oracle missed=0 /
bench trio 1131f z AVG/Median/P95). Wyjątki jawnie oznaczone NOT TESTED
(§13). Zgodnie z zakresem: STOP — ewentualny default ON to osobne zadanie.
