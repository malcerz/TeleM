# RAPORT AMD — ETAP 5K: GPU static chart layers + small dynamic chart updates

**STATUS: ✅ PASS-EXACT** (weryfikacja GPU-level readback + 1131 klatek pure-Python)

- Static chart (1160×511) uploadowany **1 raz / eksport** per slot (cadence + HR).
- Per frame tylko małe dynamiczne tile'y: **cursor + current value** (pre-komponowane
  nad static na CPU), REPLACE do HUD canvas.
- **Dynamic upload ~0.016 MiB/frame** (oba charty) vs **4.52 MiB/frame** (5J) →
  **redukcja ~99.7%**.
- Pełne 1160×511 `tobytes`/klatka = **0** (static tylko raz).
- **GPU→CPU readback = 0** w produkcji (readback tylko w diagnostyce A/B).

> Zgodnie z dyrektywą: **NIE** zaimplementowano GPU font engine, **NIE** przepisano
> chart rendererów, **NIE** wykonano ETAPU 5L.

---

## AUDIT (Brama A — z kodu 5D/5J)

**Static contents (FINAL_STATIC_CHART):**
- `hdr_img` — przezroczysty oprócz LABEL na (4+tox, toy) (góra-lewo).
- `bg_img` pasted przy (4, margin_top) — tło, osie, grid, etykiety osi, history
  polyline, fill (α≈40), HR average line (dashed).

**Dynamic contents (per frame):**
- **Cursor** `_draw_post_paste_cursor`: pionowa linia w cursor_x (plot_y1..plot_y2),
  width max(2, calc_thickness), color = cursor_color·α(200) (post_rgb),
  alpha = (200·200+127)//255 = 157; dot r = max(3, calc_thickness+1), fill α=255,
  outline line_color. Klip do obszaru plot.
- **Current value text**: `draw.text((chart_w − vw + tox, toy), v_str, …)`,
  fill text_color α=255, stroke czarny. Góra-prawo w header.

**Bbox-y (lokalne w chart 1160×511):**
- cursor: x ∈ [cursor_x ± dot_r], y ∈ [plot_y1, plot_y2] → ~9 × ~360 px (≈12.5 KB)
- value: x ∈ [chart_w−vw+tox, …], y ∈ [toy, toy+fs] → ~39×18 px (≈2.8 KB)
- **cursor i value NIE pokrywają się** (cursor y ≥ margin_top+4 = fs+12, value y ≤ fs)
  → 2 osobne regiony, **nie łączymy** (połączenie = pełna szerokość, droższe).

**Render order (alpha):** static → cursor → value.

**Static invalidation:** klucz 5D cache `final_key = ("final_static_chart", bg_key,
hdr_key, chart_w+8, final_h, margin_top)` — pełny (bg_key + hdr_key). Każda zmiana
parametru FINAL_STATIC_CHART odświeża cache → static texture musi być re-uploadowana.

---

## KLUCZOWE USTALENIE EXACTNESS (dlaczego REPLACE zamiast blendu)

- Pillow `Image.paste(img, pos, img)` z maską RGBA **pre-multiplikuje alpha**
  (α=201 → 158) — to NIE jest straight-alpha "over".
- Blend `draw.line`/`draw.text` Pillow ≠ straight-alpha "over" GPU
  (czysto-pythonowy test: MAX=77 w regionie kursora nad static).
- ⇒ Osobny przezroczysty overlay komponowany blendem GPU **nigdy nie jest
  pixel-exact** dla kursora nad nieprzezroczystym static.
- **Rozwiązanie:** dynamiczne tile'y są pre-komponowane nad static na CPU
  (crop static + rysunek kursora / tekstu value) i GPU **REPLACE'uje** region
  (shader mode 2 = straight copy). Tile = dokładne piksele finalnego chartu CPU.
- `_render_value_text_tile`: tekst rysowany w punkcie `(-sl, -st)` (stroke bbox),
  nie `(sl, st)` — podwójne przesunięcie.
- Tile'e klipowane do granic chartu (`_clip_tile`) — stroke value wystaje nad
  chart (local y = −4); wiersze ujemne są odrzucane (CPU je przycina).

---

## ARCHITECTURE

**BEFORE (5J):**
```
CPU chart RGBA 1160×511 → tobytes (~2.26 MiB/chart) → full texture upload
  → GPU blend (clear bbox + straight-alpha over)   [4.52 MiB/frame]
```

**AFTER (5K GPU_SPLIT):**
```
CPU static 1160×511 (cache 5D) → tobytes → upload 1 raz/eksport (persistent)
CPU cursor tile (static crop + cursor)   → tobytes → REPLACE
CPU value tile (text over transparent)   → tobytes → REPLACE
GPU: clear bbox → blend static → REPLACE cursor → REPLACE value
```

---

## BEFORE 5J (memory/upload baseline)

| Metryka | Wartość |
|---|---|
| Full copy/frame (`final_static.copy()`) | 2 × 1160×511 RGBA |
| Full tobytes/frame | 2 × 2.26 MiB = **4.52 MiB/frame** |
| Chart upload | **4.52 MiB/frame** |

---

## GPU_SPLIT — UPLOADY

| Metryka | Wartość |
|---|---|
| Static upload/export | 2 (cadence + HR), 4.52 MiB razem |
| Static MiB/export | 4.52 |
| Cursor upload/frame | ~10–13 KB |
| Value upload/frame | ~2.6–2.8 KB |
| **Total dynamic MiB/frame** | **~0.016 (oba charty)** |
| Full chart tobytes/frame | **0** |

---

## PURE-PYTHON 1131 EXACTNESS (§20/§21)

`scratch/k5_pure_python_exact.py --all` — rekonstrukcja GPU (static + REPLACE
cursor + REPLACE value) vs pełny CPU chart, **1131/1131 klatek**:

| Chart | MAE | MAX | mismatching frames |
|---|---|---|---|
| Cadence | **0** | **0** | 0/1131 |
| Heart rate | **0** | **0** | 0/1131 |

---

## SHORT TEST (§27)

31 klatek, D3D11VA + GPU MAP + GPU_SPLIT charts: ✅ PASS-VISUAL — charty widoczne,
kursor się przesuwa, wartości aktualne, mapa OK, z-order OK, brak ghost/trails,
brak artefaktów, **AMF drops 0**, 31/31 muxed.

---

## RAW STATIC TEST (§19) — GPU readback

`AMD_CHART_STATIC_READBACK=1`, GPU_SPLIT, 31 klatek (readback statycznej tekstury):

| Chart | MAE | MAX | diff_px |
|---|---|---|---|
| Cadence | **0** | **0** | 0 |
| Heart rate | **0** | **0** | 0 |

**CPU FINAL_STATIC_CHART == GPU static texture (UpdateSubresource → readback): PASS-EXACT.**

---

## CHART A/B — GPU-level HUD region readback (§21)

`AMD_CHART_AB_READBACK=1`, GPU_SPLIT, 31 klatek (readback HUD canvas w bbox chartu,
vs rekonstrukcja CPU static + REPLACE cursor + REPLACE value):

| Chart | Frames | MAE | MAX | n>1 |
|---|---|---|---|---|
| Cadence | 31 | **0** | **0** | 0.0 |
| Heart rate | 31 | **0** | **0** | 0.0 |

**GPU assembly (clear → static blend → cursor REPLACE → value REPLACE) == CPU chart: PASS-EXACT.**

---

## FINAL HUD TEST (§22) — GPU (5J) vs GPU_SPLIT

Diagnostyczne dumpy `H_hud_canvas_30.png` (31-klatkowy przebieg każdej ścieżki):

| Region | MAE | MAX | diff_px |
|---|---|---|---|
| **Poza bboxami chartów** | **0** | **0** | **0** |
| Wewnątrz bboxów chartów | **0** | **0** | 0 |

**Finalny HUD canvas jest byte-identical między GPU (5J) a GPU_SPLIT — PASS-EXACT.**
(Ramy 300/900 nie istnieją w 31-klatkowym teście; porównanie oparte o klatkę 30.)

---

## FULL PRODUCTION A/B/C/D (§28) — 1131 klatek każdy, profiling/diag/readback OFF

| Run | Path | TRUE FPS | wall s | enc/mux |
|---|---|---|---|---|
| A | GPU (5J) | **18.250** | 63.5 | 1131/1131 |
| B | GPU_SPLIT (5K) | **19.746** | 59.2 | 1131/1131 |
| C | GPU (5J) | **20.692** | 56.3 | 1131/1131 |
| D | GPU_SPLIT (5K) | **23.086** | 50.7 | 1131/1131 |

- **GPU median: 19.471 FPS**
- **GPU_SPLIT median: 21.416 FPS**
- **GAIN: +9.99 %** (mediana A/B/C/D)
- drops = 0, frame accounting 1131/1131 (source/decoded/D3D/VP/HUD/charts/map/AMF/mux).

### Per-stage median (ms) — A → B → C → D

| Etap | A (GPU) | B (SPLIT) | C (GPU) | D (SPLIT) |
|---|---|---|---|---|
| compose_overlay | 28.518 | 27.177 | 26.833 | **25.624** |
| chart_cpu_tobytes | 1.377 | **0.000** | 1.295 | **0.000** |
| chart_python_upload | 0.310 | **0.000** | 0.292 | **0.000** |
| GPU chart blend submit | 0.115 | 0.126 | 0.118 | 0.098 |
| HUD dirty extract | 5.281 | 5.380 | 4.940 | 5.004 |
| PIL/buffer preparation | 5.406 | 5.492 | 5.055 | 5.111 |
| update_hud | 0.841 | 0.845 | 0.797 | 0.799 |
| Telemetry/frame_data | 4.275 | 4.294 | 3.746 | 3.611 |

**Pełny tobytes + pełny upload chartu zniknęły (0.000 ms) w GPU_SPLIT; compose_overlay
niższy (brak per-frame `final_static.copy()`).**

### CPU cost split renderera (mikro-benchmark, izolowany)

- **cursor CPU (oba charty):** ~0.29 ms/frame
- **current-value CPU (oba charty):** ~0.83 ms/frame
- **dynamic tile tobytes:** ~0.061 ms med
- **dynamic tile upload:** ~0.065 ms med
- static build: ~0.02 ms (cache hit) · compose_overlay split (CPU): ~13.2 ms

---

## MEMORY

| Metryka | 5J | 5K | redukcja |
|---|---|---|---|
| Chart upload | 4.52 MiB/frame | **~0.016 MiB/frame** | **~99.7%** |
| Full 1160×511 tobytes/frame | 2×2.26 MiB | **0** | 100% |
| Static upload | — | 2× / eksport (4.52 MiB razem) | — |

---

## BOTTLENECKS AFTER 5K

1. **compose_overlay (~25.6 ms med, run D)** — pozostałe widgety CPU + render
   chartów + tile'e dynamiczne (dominujący koszt).
2. **PIL/buffer preparation + HUD dirty extract (~5.1 + ~5.0 ms)** — dirty HUD
   upload pozostałych wskaźników (nie chartów).
3. **Telemetry/frame_data (~3.6 ms)** — frozen 5B.
4. **GPU chart blend submit (~0.10 ms)** — minimalny.
5. chart CPU render (static cache-hit) + dynamic tiles (~1.1 ms łącznie) — mały.

---

## ODPOWIEDZ WPROST

1. Czy pełne `FINAL_STATIC_CHART.copy()` zniknęły? **TAK** — w GPU_SPLIT nie ma
   per-frame copy (tylko mały crop regionu kursora).
2. Czy full chart `tobytes` zniknął? **TAK** — pełne tobytes tylko 1×/eksport
   (static); `chart_cpu_tobytes` med = **0.000 ms** w produkcji.
3. Ile razy static charts uploadowane są na eksport? **2** (cadence + HR), 1×.
4. Ile MiB/frame uploadują teraz charty? **~0.016 MiB/frame** (oba charty).
5. Ile procent mniej niż 4.52 MiB? **~99.7%**.
6. Czy reconstructed charts są pixel-exact? **TAK** — GPU A/B MAE 0 / MAX 0
   (31/31); pure-Python 1131/1131 MAE 0 / MAX 0; finalny HUD byte-identical.
7. Ile kosztuje cursor CPU? **~0.29 ms/frame (oba charty)**.
8. Ile kosztuje current-value CPU? **~0.83 ms/frame (oba charty)**.
9. Ile kosztuje GPU assembly? **~0.10 ms med (GPU chart blend submit)**.
10. Jaki jest medianowy TRUE FPS? **GPU_SPLIT 21.416** vs GPU 19.471 (**+9.99%**).
11. Co jest obecnie największym bottleneckiem? **compose_overlay (~25.6 ms)** —
    pozostałe widgety CPU; charty to już ~1.1 ms + ~0.1 ms GPU.
12. Czy GPU fonts mają jeszcze ekonomiczny sens? **NISKI** — dynamiczny value render
    to ~0.83 ms (mały tekst); przeniesienie na GPU fonts (5L) dałoby ograniczony
    zysk względem dominującego compose_overlay. Nie opłaca się bez przeniesienia
    większej części rendererów na GPU.

---

**STOP — raport gotowy. Nie wykonano ETAPU 5L. Nie zaimplementowano GPU fontów.**
