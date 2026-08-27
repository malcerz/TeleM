# RAPORT AMD ETAP 2B — Optymalizacja transferu gauge (statyczny cache + dynamiczne sub-boxy)

Data: 2026-08-25 · Branch: `amd-render` · Backend: `AMD_NATIVE_D3D11` (izolowany)

---

## 1. Zadanie

Zoptymalizować transfer klatkowy ETAP 2A AFTER-MAP GPU Speed Gauge tak, aby
CPU→GPU bajty/klatkę spadły istotnie poniżej ~3,7 MB pełnego uploadu
(960×960×4), przy zachowaniu pikselowo dokładnego wyniku 2A.
Feature pozostaje domyślnie OFF (`AMD_AFTER_MAP_GAUGE_GPU` default OFF,
`AMD_GAUGE_DYNAMIC_RECTS` default nieustawione).

Obowiązywały twarde ograniczenia: bez zmian architektury kompozycji, reuse
istniejącej tekstury/shadera/`BlendGauge`, brak zmian NVIDIA/Intel/AMF/
map-rotate/HR-Cadence-GPU; REF wipe-defekt i statyczna rodzina AA-stroke
poza zakresem.

## 2. Stan początkowy (ETAP 2A CAND, benchmark 1131f)

* Pełny `UpdateSubresource` tile'a 960×960 co klatkę
  (`UpdateGaugeTexture`, d3d11_vp_pipeline.cpp).
* `gauge_tobytes` avg **1.964 ms** + `gauge_upload` avg **0.616 ms**
  ≈ 2.58 ms/frame; **3,686,400 B/frame**.
* `compose_overlay` (main compose) miał regresję **+1.72 ms** vs REF
  (niewyjaśniona w 2A).
* RENDER FPS CAND **25.033** vs REF 26.465 (−1.43).

## 3. Pomiar zmienności gauge (wymagany krok 1)

Nowy tymczasowy, env-gated probe `AMD_GAUGE_VARIABILITY_PROBE=1`
(eksporter): numpy-diff kolejnych capture'ów w producentcie, rekordy
per-frame do `<out>.gauge_variability.json`.

Przebieg: `scratch/run_etap2b_variability.py 350` (GX010115 /
cycling_dashboard_v10 / 3840×2160 / ciepły cache mapy). Analiza:
`scratch/analyze_etap2b_variability.py`.

Wyniki (tile 960×960 = 3,686,400 B; diffowalne 349/350 klatek):

| metryka | avg | median | p95 | max |
|---|---|---|---|---|
| changed_px | 224.4 | 253 | 550 | 682 |
| tight bbox_w [px] | 272.7 | 291 | 347 | 387 |
| tight bbox_h [px] | 228.3 | 240 | 303 | 319 |
| tight bbox_bytes | 265,428 | 288,496 | 326,784 | 347,984 |

* Unia zmian (dokładna): **39,578 px = 4.2945%** tile'a;
  tight union bbox lokalnie `[458,485,393,330]`.
* Proponowany zestaw rectów (składowe spójne na siatce /8, margin 12 px):
  **k=1**: `(444,468,424,360)` = **610,560 B/frame = 16.56%** pełnego
  tile'a; pokrycie unii **100%**.
* Klasyfikacja (px-hits): igła ≥50% klatek dominuje; wartości 2–50%;
  <2% margines. Zero zmian poza sektorem igły i paskiem wartości.

Wniosek projektowy: per-frame numpy-diff odpada (mikrobenchmark:
`asarray` ≈ `tobytes`, diff+nonzero ~2.4 ms dodatkowego). Wybrano **stałe
regiony dynamiczne** (sub-box D3D11) + statyczna część w persistent
teksturze + okresowy pełny resync.

## 4. Diagnoza regresji `compose_overlay` (+1.72 ms)

Gauge żyje wyłącznie w `map_above_layout`; main compose nie zawiera gauge,
więć wzrost nie pochodził z renderu. Przyczyna: kontencja pamięci/bandwidth
między wątkiem konsumenta (3.7 MB upload + DMA co klatkę) a Pillow-work
producenta. Potwierdzenie: po redukcji bajtów `compose_overlay` CAND wrócił
do poziomu REF (5.062 vs 5.188 ms — patrz §9).

Dodatkowe odkrycie (ten sam obszar kodu): capture robił **zbędny crop-copy
pełnego tile'a** co klatkę nawet gdy widget w całości na kanwie (~kilka ms
memcpy). ETAP 2B pomija crop gdy clipping niewymagany (korzysta też ścieżka
legacy 5L).

## 5. Zmienione pliki

Kod produkcyjny:

1. `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.h` — deklaracja
   `UpdateGaugeRegionTexture`, getter `GetGaugeRegionUploads`, licznik
   `m_gaugeRegionUploads`.
2. `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp` — implementacja
   `UpdateGaugeRegionTexture` (D3D11_BOX `UpdateSubresource`; tworzenie
   tekstury i bookkeeping dst identycznie jak w `UpdateGaugeTexture`;
   clamp boxa do bounds; liczniki bytes/uploads).
3. `native/d3d11_amf_pipeline/src/telem_amd_native.cpp` — eksport
   `telem_amd_update_gauge_region`.
4. `src/ffmpeg/amd_native_exporter.py` — parsowanie env, prototyp ctypes,
   pola `PreparedFrame.gauge_region_data/gauge_tile_bbox`, logika regionów
   w producentcie, gałąź uploadu w konsumencie, force-dirty na tile-bbox,
   warunek early-clears, metryki, sekcja profilu.

DLL przebudowany (target `telem_amd_native` z `build-etap8s`; eksport
potwierdzony `objdump -p`). Uwaga: pełny target all nie buduje się przez
**pre-existing** błąd w `main_etap2c.cpp` (`CreateHUDTexture`) — niezwiązany,
nie naprawiany (§16 AGENTS).

Skrypty (scratch): `run_etap2b_variability.py`,
`analyze_etap2b_variability.py`, `run_etap2b_smoke.py`,
`run_etap2b_ghost_ab.py`, `check_etap2b_ghost_equivalence.py`,
`extract_etap2b_rows.py`, `etap2b_serialize_bench.py`.

## 6. Implementacja (dokładnie)

**Env (default OFF / legacy = dokładnie ETAP 2A):**

* `AMD_GAUGE_DYNAMIC_RECTS="x,y,w,h;..."` — tile-lokalne prostokąty
  pokrywające WSZYSTKO zmiennej grafiki gauge (igła + wartości), wyliczone
  z pomiaru (§3). Walidacja parse (0<w,h; ≤8 rectów); błąd ⇒ fallback do
  pełnych uploadów + komunikat.
* `AMD_GAUGE_FULL_REFRESH_N` (default **120**) — co N-tą klatkę epoki
  geometrii wymuszony pełny upload tile'a (resync safety-net).

**Producent (capture block):**

* Crop-copy tylko gdy faktyczne clipowanie (widget poza kanwą);
  `gauge_capture_ms` mierzy ten koszt (0 w steady state).
* Epoka geometrii `(gw,gh,gx,gy)`: pierwsza klatka epoki oraz klatki
  `frame_in_geom % N == 0` → pełny path (stary kod bez zmian).
  Pozostałe → dla każdego recta: clamp do tile'a, `crop` +
  `tobytes("raw","RGBA")`, payload `(bytes,bx,by,bw,bh)` do
  `PreparedFrame.gauge_region_data`. Legacy BEFORE-MAP (5L) nigdy nie
  wchodzi w regiony (warunek `after_map_gauge_gpu`).

**Konsument:**

* `prepared.gauge_region_data` → N wywołań
  `telem_amd_update_gauge_region(h,bytes,bx,by,bw,bh,rowPitch=bw*4,tileW,tileH,gx,gy,...)`
  — sub-box update istniejącej persistent tekstury. `BlendGauge`
  **bez zmian** (blenduje cały tile z tekstury). Pełne klatki używają
  starego `telem_amd_update_gauge`.
* Early-clears (`telem_amd_run_early_clears`) także na klatkach region.
* Force-dirty BELOW (2A FIX) przełączone z unpackowania `gauge_data` na
  `gauge_tile_bbox` — działa dla obu ścieżek (erase dotyczy całego bboxa
  tile'a). Duplikaty rectów: strzeżone `not in` (zweryfikowane brak
  podwójnych uploadów dist_visual).

**Metryki:** nowe próbki per-frame `gauge_capture`, `gauge_diff`
(=0 z definicji trybu stałych regionów), `gauge_bytes_per_frame`,
`gauge_upload_calls`; istniejące `gauge_tobytes`, `gauge_upload`;
liczniki `etap2b_*` w profilu (`etap5l`).

## 7. Testy — bramki poprawności

### 7.1 Smoke funkcjonalny (40 f, `AMD_GAUGE_FULL_REFRESH_N=10`)

`region_frames=36, full_frames=4 (0/10/20/30), calls=40`; mediana bajtów
610,560; p95 = pełny tile (klatki resync). PASS.

### 7.2 Bramki parity ETAP 2A (bez zmian skryptu) — z AKTYWNYM transferem 2B

Przebiegi: `ref_short` / `cand_short` (340 f, dumps 30/300,
`AMD_ETAP2A_COMPOSE_PROBE`, recty 2B włączone w CAND).

```
GATE_TRUTH_DETERMINISM: PASS
GATE_VICTIM_ROI f30:  ref~cand=0 cand~truth=0   → PASS
GATE_VICTIM_ROI f300: ref~cand=0 cand~truth=0   → PASS
GATE_NO_NEW_WIPES f30:  ref_wiped=7400 cand_wiped=49 PASS
GATE_NO_NEW_WIPES f300: ref_wiped=7400 cand_wiped=49 PASS
GATE_CONTROL_UNTOUCHED: PASS
PARITY_GATE: PASS (4/4)
```

## 8. Ghosting (needle sweep 13 klatek)

**Kontrola metodologiczna:** niecommitowany skrypt
`scratch/etap2a_ghosting_check.py` wymaga `tile_diff_px==0` dla każdej
klatki — to jest ostrzejsze niż kryteria raportu 2A (§6 tamtego raportu
dopuszczał statyczny zestaw ~1606 px). Eksperyment kontrolny: ten sam sweep
na czystej ścieżce **2A-path (bez rectów)** na obecnym drzewie daje
**identyczny wynik FAIL** (1606 px w każdej klatce, banda y[1546..1624],
wartości zmienne per klatka przez przywracaną pod spodem treść dist_visual).
⇒ rozjazd skrypt-vs-raport jest pre-existing i dotyczy statycznej rodziny
AA-stroke (poza zakresem zadania). Nie jest to regresja 2B.

**Właściwy dowód 2B — równoważność A/B**
(`scratch/run_etap2b_ghost_ab.py` + `check_etap2b_ghost_equivalence.py`):
ten sam workload cand uruchomiony dwukrotnie (osobne CWD), tryb „2a”
(pełne uploady) vs „2b” (regiony), 13 klatek sweepa:

* **E1: canvas-tile(2B) == canvas-tile(2A) BIT-EXACT — 0 różniących px
  na wszystkich 13 klatkach.**
* E2: diff-vs-expected(truth+art) ma **0 px w strefie dynamicznej**
  (rect ∪ pad 16) w OBU trybach ⇒ żaden stary piksel igły/wartości/śladu
  nie może przetrwać (brak ghostingu); całość 1606 px leży w statycznej
  bandzie poza strefą.
* E3: bbox tile stały `{1440,665,960,960}` ✓; grafika gauge zmienna ✓.

```
ETAP2B GHOSTING_EQUIVALENCE: PASS
```
## 9. Benchmark (1131 f, GX010115, cycling_dashboard_v10, 3840×2160)

Trzy warianty na tym samym drzewie/buildzie (czysta atrybucja):

| metryka (avg ms/frame) | REF (flag off) | CAND 2A-path (full upload) | CAND 2B (regiony) |
|---|---|---|---|
| RENDER FPS | 27.301 | 34.355 | **37.615** |
| USER EFFECTIVE FPS | 23.006 | 27.843 | **29.797** |
| producer_prepare | 30.522 | 22.832 | **21.066** |
| above_total | 21.409 | 13.478 | **13.320** |
| compose_overlay | 5.188 | 5.362 | **5.062** |
| gauge_tobytes | — | 1.535 | **0.361** |
| gauge_upload | — | 0.557 | **0.267** |
| gauge bytes/frame | — | 3,686,400 | **avg 637,756** |
| consumer_upload | 1.948 | 2.297 | 1.832 |

Mandowane metryki 2B (AVG / Median / P95):

| metryka | AVG | Median | P95 |
|---|---|---|---|
| gauge_capture [ms] | 0.000 | 0.000 | 0.000 |
| gauge_diff [ms] (z definicji trybu =0) | 0.000 | 0.000 | 0.000 |
| gauge_tobytes [ms] | 0.361 | 0.320 | 0.565 |
| gauge_upload [ms] | 0.267 | 0.277 | 0.412 |
| gauge_bytes_per_frame [B] | 637,756 | 610,560 | 610,560 |
| gauge_upload_calls [1/f] | 1.000 | 1.000 | 1.000 |

Liczniki: `gauge_gpu_frames=1131`, pełne uploady **10**
(klatki 0/120/…/1080), regionowe **1121**, `calls=1131`,
`MiB/frame=0.6082`.

**Delta vs ETAP 2A CAND (wymagany wiersz):**

| pozycja | ETAP 2A CAND | ETAP 2B CAND | Δ |
|---|---|---|---|
| RENDER FPS | 25.033 | **37.615** | **+12.58 (+50%)** |
| above_total | 18.231 | 13.320 | −4.91 |
| compose_overlay (regresja vs REF +1.72) | 7.103 | 5.062 | regresja usunięta |
| gauge_tobytes+gauge_upload [ms] | 2.58 | **0.63** | **−75%** |
| gauge bajty/klatkę | 3,686,400 | med 610,560 | **−83%** |

Atrybucja: (a) skip redundantnego crop-copy pełnego tile'a pomaga obu
ścieżkom GPU-gauge (2A-path producer 31.56→22.83 vs stary build);
(b) właściwy transfer regionowy dodaje kolejne −1.77 ms producenta
(tobytes −1.17, upload −0.29, mniej alokacji/GC) i podnosi RENDER FPS
34.355→37.615.

## 10. Izolacja backendu

Dotyczy wyłącznie `native/d3d11_amf_pipeline/*` i
`src/ffmpeg/amd_native_exporter.py` (AMD). Nowy eksport DLL jest addytywny;
stary `telem_amd_update_gauge` nietknięty; NVIDIA/CUDA/NVENC, Intel/QSV,
AMF, map-rotate, GPU HR/Cadence — zero zmian (brak diffów w tych plikach).
Ścieżka legacy BEFORE-MAP (5L) nie wchodzi w regiony.

## 11. Ryzyka / ograniczenia

1. Recty są ważne dla zmierzonego workloadu/presetu; zmiana stylu/skali
   gauge poza zmierzony sektor może wymagać przeliczenia rectów.
   Safety-net: pełny resync co `AMD_GAUGE_FULL_REFRESH_N` (default 120)
   ogranicza ewentualną nieświeżość do <N klatek; pierwsza klatka każdej
   epoki geometrii zawsze pełna.
2. Tryb stałych regionów zakłada statyczność pikseli poza rectami między
   resyncami (potwierdzone pomiarem 350f i A/B sweepem).
3. Konfiguracja env-driven (świadomie; domyślne per-preset wiring to
   osobne zadanie przy ewentualnym włączeniu default ON).

## 12. Odkryte problemy poza zakresem (do osobnych zadań)

* `main_etap2c.cpp` nie kompiluje się (pre-existing; blokuje target all).
* Niecommitowany `etap2a_ghosting_check.py` ma ostrzejsze kryterium niż
  raport 2A (strict-zero vs dopuszczony static-set); do ujednolicenia.
* Statyczna banda ~1606 px pod tile'em (AA-stroke × restored dist_visual)
  — wartości zmienne per klatka na obecnym drzewie (identycznie 2A/2B).
* Profile JSON pełnych przebiegów CAND nadpisują się przy wspólnej
  ścieżce wyjściowej runnera (skopiować przed kolejnym wariantem).

## 13. Testy NIE-wykonane / NOT PROVEN

* Brak testu zmiany geometrii tile'a w trakcie jednego renderu (reset
  epoki pokryty kodowo i smoke'em brzegowym; brak dedykowanego przebiegu).
* Zachowanie przy `AMD_GAUGE_DYNAMIC_RECTS` błędnie sparsowanym zweryfikowane
  tylko logiką parse (fallback) — bez dedykowanego przebiegu E2E.
* GUI smoke po zmianach nie był wymagany protokołem (flaga OFF default);
  ścieżka default przechodzi te same pliki co 2A (zweryfikowane REF-runem).

## 14. Podsumowanie

Transfer gauge po ETAP 2B: statyczna grafika rezyduje w persistent
teksturze GPU; klatkowo wysyłane są wyłącznie zmienne sub-recty
(mediana **610,560 B = 16.56%** dawnego uploadu), z pełnym resynciem
co 120 klatek. Wyjście bit-to-bit identyczne ze ścieżką 2A (E1),
parity gates 4/4 PASS, benchmark: RENDER FPS 37.615 (vs 25.033 w 2A,
vs 27.301 REF), regresja compose_overlay usunięta.

## STATUS KOŃCOWY

```
AMD ETAP 2B COMPLETE
```

Uzasadnienie: wszystkie akceptacje zweryfikowane pomiarami —
parity gates 4/4 PASS (z aktywnym transferem region), ghosting:
bit-to-bit równoważność z referencyjną ścieżką 2A na 13-klatkowym
needle-sweepie + 0 diffów w strefie dynamicznej (E2), benchmark 1131f
REF/2A-path/2B z mandowanymi metrykami (AVG/Median/P95) i wierszem delta
vs ETAP 2A CAND. Feature default OFF zachowany; backendy NVIDIA/Intel/
map-rotate/HR-Cadence nietknięte.




