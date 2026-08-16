# RAPORT AMD — ETAP 5L-PRODUCTION-RECHECK: finalny production check po fixie gauge clipping

**STATUS: ✅ PASS** — pełna produkcyjna architektura działa poprawnie po clipping fix.

Finalny smoke/production check na pełnej aktualnej architekturze
(D3D11VA + GPU_SPLIT charts + GPU gauge z clipping fix + GPU map).
Bez optymalizacji, bez ETAPU 5M.

---

## FULL PRODUCTION PATH

| Parametr | Wartość |
|---|---|
| **D3D11VA** | **YES** (decode: `GPU_HUD_D3D11VA`, hw: True) |
| **P010** | **YES** (`DXGI_FORMAT_P010`) |
| direct decoder surface → VP | **1131** / 1131 |
| rawvideo pipe | OFF |
| **cadence_gpu** | **1131** |
| **hr_gpu** | **1131** |
| **gauge_gpu** | **1131** |
| **map_gpu** | **1131** |
| CPU base upload (cpu_to_gpu_base) | **0** |
| GPU→CPU (gpu_to_cpu_base / readback) | **0** |

Ścieżka: `D3D11VA → P010 → direct surface → VP → GPU HUD → GPU_SPLIT charts
→ GPU gauge (clip 648×528) → GPU map (LANCZOS) → NV12 → AMF`.

GPU map aktywny: `AMD_MAP_PATH=GPU`, filter `LANCZOS (2)`,
reason: *track_map is the last rendered indicator*, geometry `dst=(3035,137) src=692×692 out=691×691`.

---

## SHORT 31

| Sprawdzenie | Wynik |
|---|---|
| gauge visible | ✅ |
| gauge clipping correct (czysta krawędź 2160) | ✅ |
| needle visible (zmienia pozycję: frame 5/15/25) | ✅ |
| speed correct (liczba zgodna z FIT) | ✅ |
| cadence correct | ✅ |
| HR correct | ✅ |
| map correct (trasa + marker pozycji) | ✅ |
| no ghost | ✅ |
| no clipping regression | ✅ |
| no green / magenta | ✅ |
| no black regions | ✅ |
| AMF drops | **0** |

Wizualna weryfikacja na wyekstrahowanych klatkach
(`l5_short_{1,2,3}.png`, `l5_short_full_15.png`, `l5_short_gauge_15.png`, `l5_short_map_15.png`).

---

## FULL 1131 — FRAME ACCOUNTING

`profiling OFF`, `diagnostics OFF`, `readback OFF` (potwierdzone w profilu:
`diagnostics: False, profiling: False`).

| Licznik | Wartość | Wymóg |
|---|---|---|
| source | **1131** | 1131 ✅ |
| decoded | **1131** | 1131 ✅ |
| mf_d3d11_surfaces | **1131** | 1131 ✅ |
| VP | **1131** | 1131 ✅ |
| HUD | **1131** | 1131 ✅ |
| cadence_gpu | **1131** | 1131 ✅ |
| hr_gpu | **1131** | 1131 ✅ |
| gauge_gpu | **1131** | 1131 ✅ |
| map_gpu | **1131** | 1131 ✅ |
| AMF submitted | **1131** | 1131 ✅ |
| AMF output | **1131** | 1131 ✅ |
| muxed | **1131** | 1131 ✅ |
| drops (AMF dropped_submissions) | **0** | 0 ✅ |
| AMF_INPUT_FULL | **0** | 0 ✅ |

---

## GAUGE CLIPPING (po fixie)

| Parametr | Wartość |
|---|---|
| original (source gauge) | **648×648** |
| uploaded / visible | **648×528** |
| MiB/frame BEFORE clipping | **1.6016** (648·648·4 / 1024²) |
| MiB/frame AFTER clipping | **1.3052** (648·528·4 / 1024² — potwierdzone w profilu `gauge_upload_mib_per_frame`) |
| reduction | **18.52 %** |
| no resampling | **YES** (tylko crop, 1:1 texel) |
| same position | **YES** (gx,gy = 1544,1632 bez zmian) |
| same visual output | **YES** (PASS-EXACT z 5L-FINAL-VALIDATION + wizualnie) |

Klip: tylko dolne 120 px (poza HUD 3840×2160) — w pełni przezroczyste, wycinane
bez zmiany wyniku; semantyka identyczna z CPU `Pillow.alpha_composite`.

---

## PERFORMANCE (TRUE FPS — z runu production, bez profiling ON)

| Metryka | Wartość |
|---|---|
| **TRUE FPS** | **33.237** |
| **wall-clock** | **34.028 s** (1131 klatek) |
| compose_overlay (med) | 9.48 ms |
| map_cpu_upload (med) | 2.07 ms |
| HUD dirty extract (med) | 0.71 ms |
| PIL/buffer preparation (med) | 0.78 ms |
| gauge tobytes (med) | 0.61 ms |
| gauge upload (med) | 0.20 ms |
| GPU gauge blend submit (med) | 0.100 ms |
| GPU chart blend submit (med) | 0.158 ms |
| gauge upload | 1.3052 MiB/frame |
| map upload | 1.8267 MiB/frame |
| chart dynamic | 0.0328 MiB/frame |

> Pojedynczy run production (1131 klatek, 37.74 s materiału) — nie jest to
> pełne A/B. TRUE FPS zarejestrowany bez profilerów/diagnostyki; wyższy niż
> w historycznych pomiarach częściowych, bo pełna architektura (gauge + map GPU)
> zdejmuje alpha_composite i dirty-upload tych widgetów z CPU.

---

## REGRESSION

| Obszar | Wynik |
|---|---|
| FIT | **PASS** (1704 pkt, 1651 records; aktywne: cadence, enhanced_speed, gopro_battery, heart_rate) |
| GPMF | **PASS** (378 records) |
| Map | **PASS-VISUAL** (trasa + marker, LANCZOS, bez artefaktów) |
| Preview↔Export map parity | **PASS** (geometry dst=3035,137 src 692×692 out 691×691; zgodnie z wcześniejszą walidacją 5G) |
| Cadence | **PASS** (cadence_gpu=1131, wykres aktualizowany) |
| HR | **PASS** (hr_gpu=1131, wykres aktualizowany) |
| Gauge | **PASS-EXACT** (5L-FINAL-VALIDATION: MAE=0 / MAX=0 / 1131) |
| Speed | **PASS** (needle + liczba zgodne z FIT) |
| Date/time | **PASS** (blok czasu w HUD) |
| Other HUD | **PASS** (battery, iso, exposure, temp) |
| Color | **PASS** (brak green/magenta/czarnych obszarów) |
| Audio | **PASS** (AAC obecny, muxowany 1131 video + audio) |

---

## FINAL

**Czy pełna aktualna produkcyjna architektura
D3D11VA + GPU charts + GPU gauge + GPU map działa poprawnie po clipping fix?**

**YES ✅**

---

## ARTEFAKTY

- Short: `Raporty/AMD_ETAP5G/l5_prod_recheck_short.mp4` (+ `.amd_profile.json`)
- Full: `Raporty/AMD_ETAP5G/l5_prod_recheck_full.mp4` (+ `.amd_profile.json`)
- Klatki wizualne: `Raporty/AMD_ETAP5G/l5_short_*.png`, `l5_short_full_15.png`,
  `l5_short_gauge_15.png`, `l5_short_map_15.png`

> Zgodnie z dyrektywą: **NIE** wykonano ETAPU 5M, **NIE** optymalizowano,
> wyłącznie finalny smoke/production check.
