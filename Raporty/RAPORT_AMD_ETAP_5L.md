# RAPORT AMD — ETAP 5L: GPU final compositing dla speed gauge

**STATUS: ✅ PASS-EXACT**

- `fit_enhanced_speed_text` (speed gauge) renderowany **identycznie na CPU**;
  GPU przejmuje **wyłącznie finalne złożenie** gauge do HUD (wzorzec ETAPU 5J).
- GPU blend = **byte-identical** z CPU_REFERENCE (MAE 0 / MAX 0 w gauge bbox
  i poza nim, frame 30).
- Gauge znika z CPU Pillow HUD, CPU dirty rectów i HUD backing buffer prep.
- **GPU→CPU readback = 0** w produkcji.
- Gauge upload: **1.602 MiB/frame** (648×648 RGBA), usunięty koszt ~1.6 MiB
  z CPU dirty HUD + Pillow composite (~5 ms/frame).

> Zgodnie z dyrektywą: **NIE** przepisano gauge renderera na GPU, **NIE**
> zaimplementowano GPU needle, **NIE** wykonano ETAPU 5M (brak static/dynamic
> split gauge).

---

## AUDIT (Brama A)

| Parametr | Wartość |
|---|---|
| Gauge size (runtime) | **648×648 px** RGBA |
| Gauge bbox | **(1544, 1632, 648, 648)** |
| Layout index | **7 / 18** |
| Rotation | 0 |
| Form | gauge |
| Overlap z cadence | **0 px** (gauge x 1544..2192 vs cadence x 185..1345) |
| Overlap z HR | **0 px** (gauge x ..2192 vs HR x 2477..) |
| Overlap z map | **0 px** (gauge y ..2280 vs map y 137..828) |
| Overlap z tekstami | **0 px** (wszystkie teksty w lewym górnym rogu) |
| Clipping | brak (shadow zawarty w 648×648) |
| Final alpha | shadow α≈89 (0.35×), ticki α=255, etykiety α=240, needle α=255 |

**Dirty contribution (BEFORE):** 648·648·4 = **1.602 MiB/frame**
**Gauge CPU render:** ~1.45 ms med (izolowany mikro-benchmark)
**Final CPU composite (Pillow):** compose_overlay spada z ~30.6 → ~25.4 ms
przy GPU-capture (usuwa alpha_composite 648×648 + dirty extraction).

### Render order (JSON, aktywne widgety)
`time_block[0] → cadence[3] → gauge[7] → battery[8] → HR[9] → iso[11] →
exposure[12] → temp[13] → track_map[14]`

GPU overlay plan (disjoint — kolejność nie zmienia wyniku, guard to gwarantuje):
**cadence chart → HR chart → speed gauge → map**.

---

## ARCHITECTURE

**BEFORE:**
```
CPU gauge renderer → final RGBA 648×648 → Pillow alpha_composite do CPU HUD
  → dirty extraction (1.60 MiB) → backing copy → HUD regional upload
```

**AFTER:**
```
CPU gauge renderer → final RGBA 648×648 → tobytes → dedicated GPU texture
  → GPU blend (clear bbox + straight-alpha "over", mode 3) → HUD
```

---

## RAW GAUGE (§8)

CPU_REFERENCE vs GPU-mode CPU gauge RGBA: **byte-identical z konstrukcji**
(ten sam renderer — GPU mode przechwytuje dokładnie ten sam widget, bez zmian
renderera). GPU HUD A/B (poniżej) potwierdza end-to-end.

## GPU BLEND (§9–§11)

`AMD_NATIVE_DIAGNOSTICS=1`, frame 30, CPU_REFERENCE vs GPU gauge:

| Region | MAE | MAX | n>1 | n>2 | n>4 | n>8 |
|---|---|---|---|---|---|---|
| **Poza gauge bbox** | **0** | **0** | 0 | 0 | 0 | 0 |
| **W gauge bbox** | **0** | **0** | 0 | 0 | 0 | 0 |

**Classification: PASS-EXACT.**

> Uwaga: pierwszy pomiar wykazał różnicę wyłącznie przy pikselach **alpha=0**
> (dirty zeros — RGB 240 przy α=0). GPU blend 5J zachowywał RGB dla α=0
> (potrzebne dla chartów), a CPU `alpha_composite` zeruje RGB przy α=0. Dodano
> **tryb 3** shadera (blend z odrzuceniem dirty zeros) dla gauge — po tym
> HUD canvas jest byte-identical.

---

## SHORT TEST (§22)

31 klatek, D3D11VA + GPU MAP + GPU_SPLIT charts + GPU gauge: ✅ PASS-VISUAL —
gauge widoczny, needle poprawna, prędkość poprawna, charty poprawne, mapa
poprawna, z-order OK, brak ghost/clipping/artefaktów, **AMF drops 0**, 31/31.

---

## TRANSFERS

| Metryka | Wartość |
|---|---|
| Gauge upload | **1.602 MiB/frame** (648×648×4) |
| HUD dirty BEFORE | ~1.60 MiB/frame (gauge bbox) |
| HUD dirty AFTER | ~0 (gauge poza CPU dirty) |
| GPU→CPU | **0** |

---

## TIMINGS (izolowane / produkcja)

| Etap | Wartość |
|---|---|
| Gauge CPU render | ~1.45 ms med (izolowany) |
| Gauge tobytes | 0.78–0.94 ms med (produkcja B/D) |
| Gauge upload | 0.16–0.22 ms med (produkcja B/D) |
| GPU gauge blend submit | 0.079 ms med |
| compose_overlay (CPU-capture mikro) | ~30.6 ms → ~25.4 ms |

---

## FULL A/B/C/D (§24–§25) — 1131 klatek każdy, profiling/diag/readback OFF

GPU_SPLIT charts + GPU map + HUD BUFFER REFERENCE we wszystkich rundach.

| Run | Gauge path | TRUE FPS | wall s | enc/mux |
|---|---|---|---|---|
| A | CPU_REFERENCE | **17.315** | 65.3 | 1131/1131 |
| B | GPU | **18.427** | 61.4 | 1131/1131 |
| C | CPU_REFERENCE | **18.711** | 60.4 | 1131/1131 |
| D | GPU | **22.296** | 50.7 | 1131/1131 |

- **CPU_REFERENCE median: 18.013 FPS**
- **GPU gauge median: 20.361 FPS**
- **GAIN: +13.04 %** (mediana A/B/C/D)
- drops = 0, frame accounting 1131/1131.

### Per-stage median (ms) — A → B → C → D

| Etap | A (CPU) | B (GPU) | C (CPU) | D (GPU) |
|---|---|---|---|---|
| compose_overlay | 30.894 | 28.222 | 27.496 | **24.847** |
| gauge_tobytes | — | 0.943 | — | 0.779 |
| gauge_upload | — | 0.215 | — | 0.155 |
| GPU gauge blend submit | — | 0.079 | — | 0.079 |
| HUD dirty extract | 6.232 | 3.912 | 5.471 | **3.289** |
| PIL/buffer preparation | 6.369 | 4.025 | 5.582 | **3.388** |
| update_hud | 0.945 | 0.686 | 0.843 | 0.649 |
| chart_dynamic_tobytes | 0.128 | 0.117 | 0.129 | 0.095 |
| chart_dynamic_upload | 0.038 | 0.034 | 0.035 | 0.028 |
| GPU chart blend submit | 0.134 | 0.131 | 0.146 | 0.136 |
| Telemetry/frame_data | 7.368 | 6.678 | 7.666 | 10.003 |

**Kluczowy zysk:** compose_overlay −3 ms (bez Pillow alpha_composite 648×648),
HUD dirty extract −2.2 ms (gauge poza CPU dirty), PIL/buffer prep −2.2 ms (bez
backing copy gauge). Koszt GPU: gauge tobytes ~0.94 ms + upload ~0.22 ms + blend
~0.08 ms — taniej niż usunięty koszt CPU.

---

## BOTTLENECKS AFTER 5L

1. **compose_overlay (~24.8 ms med, run D)** — pozostałe widgety CPU + charty
   (dominujący koszt).
2. **Telemetry/frame_data (~10 ms)** — frozen 5B.
3. **PIL/buffer preparation + HUD dirty extract (~3.3 + ~3.3 ms)** — pozostałe
   tekstowe widgety CPU.
4. **GPU chart blend + dynamic tiles (~0.14 + ~0.10 ms)** — minimalny.
5. **Gauge upload + blend (~0.22 + ~0.08 ms)** — minimalny.

---

## ODPOWIEDZ WPROST

1. Czy gauge renderer CPU pozostał identyczny? **TAK** (gauge.py bez zmian).
2. Czy finalny Pillow composite gauge zniknął? **TAK** (GPU-capture, bez paste).
3. Czy gauge zniknął z CPU dirty HUD? **TAK** (poza _bboxes → poza dirty).
4. Ile MiB/frame usunięto z HUD buffer prep? **~1.60 MiB/frame** (dirty extract
   spadł o ~2.2 ms).
5. Ile MiB/frame kosztuje dedicated gauge upload? **1.602 MiB/frame**
   (648×648×4; tobytes ~0.94 ms, upload ~0.22 ms).
6. Czy GPU gauge composite jest pixel-exact? **TAK** (MAE 0 / MAX 0 w gauge bbox
   i poza nim, frame 30).
7. Ile kosztuje gauge CPU render? **~1.45 ms med** (izolowany mikro-benchmark).
8. Ile kosztuje gauge upload? **~0.22 ms med** (native UpdateSubresource).
9. Ile spadł HUD buffer prep? **~2.2 ms** (6.2→3.9 / 5.5→3.3 ms med).
10. Jaki jest medianowy TRUE FPS? **GPU 20.361** vs CPU 18.013 (**+13.04%**).
11. Co jest największym bottleneckiem? **compose_overlay (~24.8 ms)** —
    pozostałe widgety CPU; gauge to już ~0.22+0.08 ms na GPU.
12. Czy warto zrobić później static/dynamic split gauge? **NISKI priorytet** —
    pełny upload 1.60 MiB/frame jest tani (~0.22 ms UpdateSubresource);
    needle+value to mała dynamiczna część. Zysk ze split byłby niewielki
    względem dominującego compose_overlay.

---

**STOP — raport gotowy. Nie wykonano ETAPU 5M. Nie zaimplementowano GPU needle
ani static/dynamic split gauge.**
