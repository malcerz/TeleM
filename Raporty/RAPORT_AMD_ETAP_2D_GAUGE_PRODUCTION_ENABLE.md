# RAPORT AMD ETAP 2D — GAUGE PRODUCTION ENABLE

Data: 2026-08-25 · Branch: `amd-render` · HEAD bazowy: `d9afa75`
Poprzednie etapy: 2A (`RAPORT_AMD_ETAP_2A_AFTER_MAP_GAUGE_GPU.md`),
2B (`..._2B_GAUGE_TRANSFER_OPT.md`), 2C (`..._2C_GAUGE_AUTO_REGIONS.md`)

---

## 1. Zadanie

Walidacja pozostałych bram i przełączenie domyślnej wartości flagi
`AMD_AFTER_MAP_GAUGE_GPU` **OFF → ON** (produkcyjny GPU speed gauge po mapie
z trybem AUTO dynamic regions), zgodnie ze specyfikacją ETAP 2D:

* pre-enable fallback E2E (supported / rotation≠0 / compass),
* geometry/style epoch E2E lub dowód statyczności layoutu,
* GUI smoke z flagą ON przy domyślnej wartości nadal OFF,
* final parity gate (PARITY_GATE / GHOSTING / NO_NEW_WIPES / ORACLE),
* flip defaultu, post-flip fallbacki (`=0`, `AUTO_REGIONS=0`),
* normalny GUI bez env, perf smoke ≥300f, raport końcowy.

## 2. Stan początkowy

* Drzewo robocze zawiera niezaangażowane zmiany etapów 2A–2C (zachowane;
  żadna praca użytkownika nie została odrzucona).
* Flaga: `_env_flag("AMD_AFTER_MAP_GAUGE_GPU", False)` — feature OFF.
* Baseline do ochrony (ETAP 2C bench, 1131f, GX010115/v10/4K):
  AUTO **35.965 FPS**, `above_total` **13.90 ms**, median bytes/frame
  **329 780** (~8.94 % kafla), REF 26.558, FULL 32.443.
* Tryby transferu: MANUAL_RECTS (env wygrywa) > AUTO (default) > FULL_TILE;
  per-frame SAFE fallback `AUTO_FALLBACK_FULLTILE` dla konfiguracji
  nieobsługiwanych (widget rotation≠0, brak info renderera, compass-style);
  pełny resync co `AMD_GAUGE_FULL_REFRESH_N=120`.

## 3. Zmienione pliki

| Plik | Zmiana |
|---|---|
| `src/ffmpeg/amd_native_exporter.py` | L1406/L1418–1421: komentarze „(default OFF)” → „(default ON)” + wzmianka o ścieżce powrotu CPU; **L1411: `_env_flag("AMD_AFTER_MAP_GAUGE_GPU", False)` → `True`** (jedyna zmiana semantyczna 2D) |
| `AGENTS.md` | §8 (status optymalizacji + nowe liczby bazowe), §9 (wyzwanie rozwiązane), §10 (constraint OFF → produkcyjne ON + reguły fallbacku) |
| `scratch/run_etap2d_matrix.py` | NOWY — macierz walidacyjna 2D (7 przypadków) |
| `scratch/run_etap2d_perf.py` | NOWY — perf smoke z porównaniem do baseline 2C |
| `Raporty/RAPORT_AMD_ETAP_2D_GAUGE_PRODUCTION_ENABLE.md` | NOWY (ten raport) |

Semantyka `AMD_GAUGE_AUTO_REGIONS` **bez zmian** (AUTO nadal preferowane,
jawny env MANUAL/nadpisanie nadal wygrywa). Żaden plik NVIDIA/Intel/shared
poza wymienionymi nie został dotknięty.

## 4. Implementacja

Flip (jedyna zmiana produkcyjna):

```python
# przed: after_map_gauge_gpu = _env_flag("AMD_AFTER_MAP_GAUGE_GPU", False)
after_map_gauge_gpu = _env_flag("AMD_AFTER_MAP_GAUGE_GPU", True)
```

Nowe harnessy (tylko scratch, bez wpływu na produkcję):

* `run_etap2d_matrix.py CASE…` — przypadki: `A_supported`, `B_rot90`,
  `C_compass`, `preflip_on`, `cpu_off`, `fulltile_forced`,
  `zeroenv_default`. Każdy przypadek: własny CWD (natywne dumpy
  `H_hud_canvas_<f>.png` lądują w root CWD; artefakty probe Pythona
  w `scratch/etap2a_test/`), tee stdout → `console.log`, liczniki
  `MapTileStats` (reset→snapshot wokół eksportu), asercje z profilu JSON
  (`etap2c_gauge_regions.*`, `etap5l.etap2b_gauge_*`) i tokenów logów,
  oraz check widoczności gauge (alpha-art ≥500 px w bbox kafla z
  `gauge_meta_f*.json`). B/C mutują tylko konfigurację widgetu
  `_GAUGE_KEY="fit_enhanced_speed_text"` (rotation=90 /
  `gauge_style="compass"`+`field=heading`) — preset v10 w pamięci.
* `run_etap2d_perf.py [frames=300]` — zero gauge-env (produkcja po flipie),
  `AMD_PROFILING=1`, ekstrakcja metryk + twarde bramki (ok, mode=AUTO,
  region_frames>0) + delty vs baseline 2C.

## 5. Pre-enable fallback E2E (flaga jeszcze OFF w kodzie)

Uruchomienie: `python scratch/run_etap2d_matrix.py A_supported B_rot90
C_compass` (40 f / 4K / oracle ON). Wynik: **wszystkie trzy przypadki PASS
13/13**.

| Przypadek | Konfiguracja | Oczekiwane = uzyskane |
|---|---|---|
| A_supported | v10 stock, flaga=1 | log `AMD_AFTER_MAP_GAUGE_GPU: ON (env; …)`; `[AMD GAUGE GPU] mode=AUTO rects=-`; profil `mode=AUTO`; oracle `missed=0`; `oracle_region_frames>0`; uploady GPU>0 |
| B_rot90 | `fit_enhanced_speed_text.rotation=90` | selekcja zostaje AUTO (`mode=AUTO rects=-`), a pierwsza epoka loguje **`mode=AUTO_FALLBACK_FULLTILE … geometry=960x960`**; `oracle_region_frames==0`; full-tile uploady ≥ frames−1; oracle missed=0; uploady GPU obecne → **nigdy CPU-only** |
| C_compass | `gauge_style="compass"` (+heading/gpmf) | identyczny bezpieczny degredacja jak B (renderer zgłasza `supported=False`) |

Dodatkowo każdy przypadek: eksport ok, brak tracebacku, brak
`[MAP CACHE MISS DURING RENDER]`, `network_requests==0` i
`network_misses==0`, gauge widoczny w dumpie HUD (alpha-art w bbox kafla).
Wniosek: konfiguracje nieobsługiwane degradują do **FULL_TILE GPU** — bez
crasha, bez brakującego gauge, bez ghostingu. **PASS.**

## 6. Geometry/style epoch E2E

**E2E zmiany layoutu w trakcie eksportu = NOT APPLICABLE IN PRODUCTION**
(architektura celowo tego zabrania):

* `amd_native_exporter.py` L1361–1364: `layout = copy.deepcopy(layout)` —
  komentarz wprost: snapshot raz, rendering i plan zależności 5B immutable
  przez cały eksport; GUI edytowalny layout nie jest osiągalny w trakcie.
* L455/L456: `semantic_layout = layout`, `compose_layout = layout`;
  partycjonowanie `_ordered_map_layout_parts()` wykonywane jednokrotnie przy
  starcie (`_amd_layout_roles`). Brak ścieżki mutacji layoutu w pętli klatek.
* Eksport jest synchroniczny — zmiana geometrii/stylu z GUI w trakcie runu
  jest niemożliwa bez sztucznej ramy mutacyjnej (spec: nie tworzyć).

Mechanizm epoch (OLD EPOCH DISCARDED / FULL RESYNC ON CHANGE / NEW GEOMETRY
USED / NO GHOST) dowiedziony świeżym uruchomieniem
`scratch/run_etap2c_state_sim.py` na realnych renderach gauge:

```text
size160/240/360/480 : epochs=1 region=72  full=7  missed=0  (każdy)
geometry_change     : epochs=2 region=108 full=11 missed=0   (M2a)
style_change        : epochs=2 region=108 full=11 missed=0   (M2b)
variant_arc210/redtext/wide : missed=0                       (M3)
ALL STATE-SIM PROBES PASS (missed=0 everywhere)
```

Zmiana geometrii i stylu mid-stream → reset epoki, pełny upload, zero
pikseli poza wysłanymi regionami. **PASS** (mechanizm); produkcja: N/A.

## 7. GUI smoke z flagą ON (default nadal OFF w tym kroku)

`preflip_on`: 120 f / 4K, jawne `AMD_AFTER_MAP_GAUGE_GPU=1`, produkcyjne
defaulty reszty (MAP ROTATE=1, CHART=1, GPU_HUD), oracle + dumpy f40/f80.
**PASS 15/15**, w tym:

```text
[AMD NATIVE D3D11] AMD_GPU_MAP_ROTATE: 1 …
[AMD NATIVE D3D11] AMD_AFTER_MAP_CHART_GPU: ON …
[AMD NATIVE D3D11] AMD_AFTER_MAP_GAUGE_GPU: ON (env; gauge AFTER-MAP GPU BlendGauge active)
[AMD GAUGE GPU] mode=AUTO rects=- geometry=- full_refresh=120
```

* MAP / CADENCE / HR / GAUGE: wszystkie ścieżki GPU aktywne (tokeny + profil
  `mode=AUTO`, uploady region>0). CPU GAUGE = NO (widget wykluczony z
  above_compose przy aktywnej fladze — strukturalnie z ETAP 2A; tu dowód
  dodatni: uploady kafelka GPU>0 i oracle liczony z capture AFTER-MAP).
* HTTP w pętli klatek: `network_requests=0`, `network_misses=0`.
* Wizualne: kafel gauge zawiera żywą sztukę (>500 px alpha) w obu dumpach;
  oracle (changed ⊆ sent regions, missed=0) potwierdza poprawne
  odświeżanie wskazówki/wartości między klatkami; artefakty PNG zachowane w
  `scratch/etap2d_test/preflip_on/` do oględzin (needle / SPEED / HUD).

## 8. Final parity gate (przed flipem) — PARITY / GHOSTING / NO_NEW_WIPES

Ponownie uruchomiono pełny A/B `run_etap2c_ghost_ab.py` (2 × 340 f, 13
klatek sweep 100–320 z dumpami) i `check_etap2c_ghost_equivalence.py`:

```text
G3 tile bbox across sweep: {(1440, 665, 960, 960)} stable=True
f100…f320: tile(AUTO) vs tile(FULL) differing px=0 OK   (13/13 klatek)
AUTO oracle: frames=339 region_frames=337 full_frames=2
             changed=76143 missed=0                     -> G2 True
G3 art varies across sweep: True
G1 canvas-tile equality AUTO==FULL all frames: True
ETAP2C GHOSTING_PARITY: PASS
```

* **PARITY_GATE: PASS** — kafel gauge na kanwie bit-exact między FULL_TILE
  (referencja 2A) i AUTO na każdej klatce sweep (porównanie przed NV12/AMF).
* **GHOSTING: PASS** — zero różnic vs referencja + oracle missed=0.
* **ORACLE MISSED = 0** (339 klatek porównania).
* **NO_NEW_WIPES: PASS** — audyt dodanych linii `clear|wipe` w diffie
  `amd_native_exporter.py`: wyłącznie mechanizmy już zwalidowane w 2A FIX /
  2C (`telem_amd_run_early_clears` wykonywany PRZED uploadem HUD; stan
  clearów konsumowany, więc wewnętrzne `ClearPreviousAboveMap()` w
  `telem_amd_process_frame` no-opuje — każdy clear dokładnie raz na klatkę;
  `gauge_clear_only` dla klatek AUTO bez supportów). **ETAP 2D nie dodał
  żadnej nowej operacji czyszczenia** (jego diff produkcyjny = default
  flagi + komentarze).

## 9. Flip defaultu i post-flip fallbacki

Flip wykonany po wszystkich bramkach pre-enable (sekcje 5–8):
`_env_flag("AMD_AFTER_MAP_GAUGE_GPU", False)` → `True` (L1411) +
aktualizacja komentarzy. `py_compile` OK.

| Przypadek | Env | Wynik |
|---|---|---|
| `cpu_off` | `AMD_AFTER_MAP_GAUGE_GPU=0` | **PASS** — log `AMD_AFTER_MAP_GAUGE_GPU: OFF (env; gauge CPU_REFERENCE in above_compose)`; `etap2b_gauge_upload_calls_total == 0` (zero uploadów GPU → legacy CPU gauge); eksport ok |
| `fulltile_forced` | flaga=1 + `AMD_GAUGE_AUTO_REGIONS=0` | **PASS 11/11** — log/profil `mode=FULL_TILE`, `auto_regions_default_on=False`, `region_upload_frames==0`, full uploady>0, oracle missed=0 |

Semantyka zachowana: jawny env zawsze wygrywa z AUTO; `AUTO_REGIONS=0`
wyłącza AUTO bez dotykania samej flagi GPU.

## 10. Normalny GUI bez env (po flipie)

`zeroenv_default`: 120 f / 4K, żaden gauge-env nie ustawiony. **PASS 15/15**:

```text
[AMD NATIVE D3D11] AMD_AFTER_MAP_GAUGE_GPU: ON (default; gauge AFTER-MAP GPU BlendGauge active)
[AMD GAUGE GPU] mode=AUTO rects=- geometry=- full_refresh=120
```

Profil: `mode=AUTO`, oracle missed=0, region frames>0; HTTP/tile-miss = 0;
gauge widoczny w dumpie f60. Wymagany log `ON (default)` obecny dosłownie.

## 11. Performance smoke (po flipie, default config)

`run_etap2d_perf.py 300` — 300 f / 4K / zero gauge-env / `AMD_PROFILING=1`.
Twarde bramki: eksport ok, `mode=AUTO`, region_frames>0 → **PASS**.

```text
RENDER FPS:            34.344    (baseline 2C AUTO 1131f: 35.965; delta −4.5 %)
above_total avg:       13.950 ms (baseline: 13.90 ms;  +0.05 ms)
producer_prepare avg:  23.179 ms
gauge_tobytes avg:     0.300 ms
gauge_upload avg:      0.347 ms
pipeline_total avg:    6.550 ms
region frames:         297   full resyncs: 3 (= co AMD_GAUGE_FULL_REFRESH_N=120)
bytes/frame median:    338612 B    (baseline: 329780 B; +2.7 %)
bytes/frame avg/p95:   363760 / 347308 B
```

Interpretacja: metryki per-frame **na poziomie baseline'u** (above_total
+0.4 %, bytes +2.7 %). DELTA FPS −4.5 % pochodzi z krótkiego przebiegu
(300 f vs 1131 f): stały koszt mux (~6 s) i startu amortyzuje się inaczej;
USER EFFECTIVE FPS 18.05 przy 300 f nie jest porównywalny z 22.18 @1131 f.
Nie jest to dramatyczna regresja — kryterium „stop & diagnose" nie
zostało spełnione. Pełny bench 1131 f pozostaje zadaniem osobnym
(nie wymagany przez spec 2D).

## 12. Regresje / ryzyka · izolacja backendów · cleanup

* **Ryzyka:** (1) krótkie przebiegi <600 f mają podwyższoną wariancję FPS —
  przy ocenach wydajności używać 1131 f; (2) kombinacja
  „speed-gauge-widget jako compass" w teście C jest sztuczna (prawdziwy
  kompas to odrębny widget i pozostaje na CPU ABOVE — niezmienione); (3)
  brak pełnego re-benchu 1131 f w ramach 2D (referencja: liczby 2C).
* **Izolacja backendów:** zmiany wyłącznie w module AMD
  (`amd_native_exporter.py`: 1 linia semantyczna + komentarze) oraz
  dokumentacja/scratch. NVIDIA/NVENC/CUDA, Intel/QSV, shared code —
  **niedotknięte** (brak jakichkolwiek edycji; brak uruchomień tych ścieżek
  — NOT RUN by design).
* **Cleanup:** zgodnie z zasadą „when unsure, leave it" — nie usunięto
  żadnego istniejącego pliku/probe. Nowe artefakty 2D:
  `scratch/run_etap2d_matrix.py`, `scratch/run_etap2d_perf.py`,
  `scratch/etap2d_test/*` (konsole, profile, dumpy, JSON-y wynikowe).
* **NOT TESTED:** interaktywne klikanie w GUI (harness replikuje dokładnie
  wywołanie eksportu GUI: `TelemetryDataManager` + `export_amd_native_d3d11`
  — ta sama ścieżka co we wszystkich smoke'ach 2A–2C); presety inne niż v10.

---

## STATUS KOŃCOWY

```text
TASK:     AMD ETAP 2D — produkcyjne włączenie AFTER-MAP GPU Speed Gauge (AUTO)
STATUS:   COMPLETE

GATES:
  pre-enable A_supported/B_rot90/C_compass ....... PASS (13/13 każdy)
  epoch geometry/style (state-sim M1–M4) ......... PASS; prod E2E = NOT APPLICABLE IN PRODUCTION (statyczny layout — dowód w §6)
  GUI smoke flaga ON (preflip_on 120f) ........... PASS (15/15), HTTP/tile-miss = 0
  PARITY_GATE (tile bit-exact vs FULL, 13/13) .... PASS
  GHOSTING ....................................... PASS (ETAP2C GHOSTING_PARITY: PASS)
  NO_NEW_WIPES ................................... PASS (audyt diffu — zero nowych clearów w 2D)
  ORACLE MISSED .................................. 0
  flip OFF->ON ................................... DONE (L1411)
  post-flip cpu_off (=0 -> CPU gauge) ............ PASS
  post-flip fulltile_forced (AUTO=0) ............. PASS (11/11)
  normal GUI zero env ("ON (default)", AUTO) ..... PASS (15/15)
  PERF smoke 300f vs baseline .................... PASS (34.344 FPS; above_total 13.95 ms; bytes median 338612)

NVIDIA / Intel: UNCHANGED

STOP — nie rozpoczynano kolejnego etapu optymalizacji.
```



