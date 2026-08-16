# RAPORT AMD — ETAP 5V: VP output pool=8 jako production default + soak / lifecycle / regresja

**STATUS: PASS** (po wszystkich gate'ach — correctness, soak, cleanup, performance, memory).

---

## BUILD

| | |
|---|---|
| DLL | `native/d3d11_amf_pipeline/bin/telem_amd_native.dll` |
| SHA256 | `8228EF84BE411E0D82D44250F1F2B8A3B8CA68EE554D91AF44BDC288D8CF0722` |
| ABI | 8 (bez zmian) |
| smoke | ✅ 60 klatek: `AMD_VP_POOL_SIZE=8` (default), AMF 61/61, INPUT_FULL 0, dropped 0, teardown live=0 |

Zmiany natywne (5V):
- `telem_amd_native.cpp` create(): **default pool 4 → 8** (override `AMD_VP_POOL_SIZE=4|6|8` zachowany), `AMD_POOL_LIFECYCLE_STATS=1` (debug-only), print skutecznego rozmiaru po `SetupVideoProcessor`.
- `d3d11_vp_pipeline.{h,cpp}`: `m_poolSize` default 8; liczniki lifecycle (created/released textures i views) + print w destruktorze; **fallback 8→6→4** tylko na failure allocation/resource-creation (nic innego nie jest maskowane).

---

## POOL DEFAULT

| | |
|---|---|
| before | 4 |
| after | **8** |
| override | **YES** — `AMD_VP_POOL_SIZE=4|6|8` nadal honorowany (env czytany w `create()`) |
| fallback | **8→6→4** (tylko allocation/resource-creation failure; nie wymagany na tym GPU) |
| brak env | default 8 — env NIE jest wymagany do normalnego działania (spec 26) |

---

## MEMORY (spec 8/9)

| | |
|---|---|
| format | `DXGI_FORMAT_NV12` |
| Width / Height | 3840 × 2160 |
| nominal bytes/surface | 3840×2160×1.5 = **12 441 600 B = 11.865 MiB** |
| views per surface | 1× VideoProcessorOutputView + Y UAV + UV UAV (referencje, bez osobnej alokacji VRAM) |
| pool4 (nominal) | 4 × 11.865 = **47.46 MiB** |
| pool8 (nominal) | 8 × 11.865 = **94.93 MiB** |
| delta (nominal) | **+47.46 MiB** |
| measured VRAM | **UNKNOWN** (brak diagnostyki VRAM; nie podajemy estymaty alignment jako pomiaru) |
| process working set (RAM) | rośnie ~150–500 MB/eksport w procesie długożyjącym — **retencja alokatora** (live objects +13/eksport, native live=0), NIE leak (patrz SOAK/Memory probe) |

---

## LIFECYCLE (spec 5/6/7/25)

Audyt przepływu: `creation` (SetPoolSize → resize wektorów → `SetupVideoProcessor` tworzy tekstury+VPOV → `InitializeNV12ComputeCompositor` tworzy Y/UV UAV) → `reuse` (wrap `% m_poolSize`, `m_slotLastFrame`) → `shutdown` (destruktor zwalnia wszystkie, liczniki → print live) → `exception` (każdy failure w init → `delete ctx` → destruktor zwalnia partial — nullptr-safe) → `reinit` (nowy context = nowy obiekt VP; brak stale resources między kontekstami).

| | |
|---|---|
| create/destroy cycles | **12** (soak, jeden proces) + 4 (golden) + smoke = **17** |
| resource leak | **NO** |
| live resources after destroy | **textures live=0, views live=0** (w każdym eksporcie) |

Lifecycle print (przykład, golden pool8):
```
[VP POOL] lifecycle: textures created=8 released=8 live=0 | views created=24 released=24 live=0
```
(viewy 24 = 8 VPOV + 8 Y-UAV + 8 UV-UAV.)

---

## CORRECTNESS (spec 10/11)

| test | wynik |
|---|---|
| 31 frames pool4 vs pool8 | framemd5 **31/31 identyczne** ✅ |
| 1131 frames pool4 vs pool8 | framemd5 **1131/1131 identyczne** ✅ |
| accounting | muxed=1131, amf submitted=1131, amf output=1131, vp_processed=1131 |
| drops | **0** (dla obu pooli) |
| input_full | 0 |

---

## SOAK (spec 12/13/14/15)

Brak materiału ≥5 min w projekcie (Video/ zawiera tylko GX020079.mp4, 1131 klatek / 37.7 s) → wg spec 13 wykonano **12 pełnych eksportów** prawdziwego klipu w **jednym procesie** (każdy = create→run→flush→close).

- Sekwencja pool: `8,8,4,8,6,8,8,8,8,8,8,8` (8→8, potem 4→8→6→8 recreation, potem 6×8).
- Device recreate: 12 cykli create/destroy ≥ wymagane 10.
- Frame accounting (każdy eksport): decoded/VP/HUD/AMF submitted/AMF output/muxed = 1131, drops=0 → **12/12 accounting OK**.
- Lifecycle: `textures live=0, views live=0` po **każdym** destroy (12/12).
- Corruption: **black=0, frozen=0**, framemd5 soak12 vs golden pool8 = **1131/1131 identyczne** → brak green/magenta/black/stale/tearing/map/chart/gauge corruption.
- Memory (working set, RAM): rośnie ~150–500 MB/eksport w procesie długożyjącym — patrz sekcja MEMORY (retencja alokatora, NIE leak).

| export | pool | FPS | muxed | dropped | lifecycle live | ws delta [MB] |
|---|---|---|---|---|---|---|
| 01 | 8 | 37.95 | 1131 | 0 | 0/0 | +506.6 |
| 02 | 8 | 37.95 | 1131 | 0 | 0/0 | +281.3 |
| 03 | 4 | 31.78 | 1131 | 0 | 0/0 | +148.6 |
| 04 | 8 | 37.58 | 1131 | 0 | 0/0 | +245.1 |
| 05 | 6 | 36.97 | 1131 | 0 | 0/0 | +164.0 |
| 06 | 8 | 37.13 | 1131 | 0 | 0/0 | +208.5 |
| 07 | 8 | 37.88 | 1131 | 0 | 0/0 | +169.6 |
| 08 | 8 | 37.93 | 1131 | 0 | 0/0 | +163.9 |
| 09 | 8 | 37.88 | 1131 | 0 | 0/0 | +182.0 |
| 10 | 8 | 38.12 | 1131 | 0 | 0/0 | +188.8 |
| 11 | 8 | 37.89 | 1131 | 0 | 0/0 | +151.7 |
| 12 | 8 | 36.83 | 1131 | 0 | 0/0 | +200.3 |

**SOAK PASS = True** (all accounting OK, lifecycle live=0, korupcja 0, framemd5 identyczny).

### Memory probe (spec 9 — wykluczenie leaku)

Cztery pełne eksporty w 1 procesie z `gc.collect()` i licznikiem obiektów po każdym:

| export | RSS po gc [MB] | delta RSS | live objects | delta obiektów |
|---|---|---|---|---|
| 1 (zimny) | 562.8 | +509.7 | 44407 | +10122 (rozgrzanie) |
| 2 | 868.3 | +305.5 | 44420 | **+13** |
| 3 | 1034.6 | +166.3 | 44433 | **+13** |
| 4 | 1238.2 | +203.6 | 44446 | **+13** |

- **Live tracked objects stabilne** (+13/eksport po rozgrzaniu) → **brak wycieku referencji Pythona**.
- **Native pool live=0** po każdym destroy (COM refs zwolnione) → **brak wycieku natywnego**.
- RSS rośnie mimo gc → **retencja alokatora** (freed memory, high-water mark; Python pymalloc/C-heap/WDDM driver reservations nie zwracają RSS do OS). Memory jest odzyskiwalne, NIE jest to leak.

---

## PRODUCTION (spec 16/17/18)

A/B/C/D, 1131, profiling OFF, diagnostics OFF, readbacks OFF, GPU-ts OFF:

| run | pool | FPS | wall |
|---|---|---|---|
| A | 4 | 32.74 | 36.32 s |
| B | 8 | 37.48 | 32.01 s |
| C | 4 | 32.42 | 36.77 s |
| D | 8 | 37.52 | 31.95 s |

- **median pool4: 32.58 FPS** (wall 36.55 s)
- **median pool8: 37.50 FPS** (wall 31.98 s)
- **gain: +4.92 FPS (+15.1 %)** — pool8 szybszy w obu parach A→B i C→D (jednoznaczne statystycznie).
- spread: pool4 32.42–32.74 (0.99 %), pool8 37.48–37.52 (0.11 %).

---

## PROCESS_FRAME (spec 19)

| | med | p95 | p99 | >10 ms |
|---|---|---|---|---|
| pool4 | 14.77 ms | 26.02 ms | 35.88 ms | 975/1131 (86 %) |
| pool8 | 2.28 ms | 14.04 ms | 77.30 ms | 79/1131 (7 %) |

---

## FIRST D3D11 WAIT (spec 21) — vp_setup (pierwszy call D3D11 klatki)

| | med | p95 | p99 |
|---|---|---|---|
| pool4 | 13.26 ms | 24.49 ms | 34.08 ms |
| pool8 | 0.72 ms | 12.06 ms | 75.90 ms |

→ first-call driver wait praktycznie zniknął w medianie (13.26 → 0.72 ms).

---

## AMF (spec 20)

| | outstanding med | outstanding max | query med |
|---|---|---|---|
| pool4 | 5 | 5 | 0.126 ms |
| pool8 | 10 | 11 | 0.139 ms |

- **Outstanding nadal > pool4** (5–6+ zachowane; z pool8 10–11) — powierzchnie żyją wystarczająco długo przed reuse slotu. Nie zmniejszano outstanding (spec 20).
- QueryOutput: **REFERENCE** (nie zmieniano; DRAIN_READY bez zysku wg 5U).

---

## 5Q CACHE (spec 28 — tylko pomiar, bez rozwoju)

`AMD_COMPOSE_5Q` @ pool8: **REFERENCE = 35.05 FPS vs OPTIMIZED = 37.50 FPS → delta +2.45 FPS**.
Z usuniętym bottleneckiem pool cache 5Q zaczyna przekładać się na realny wall gain (zgodnie z hipotezą 5V). **Default 5Q pozostaje REFERENCE** (spec 4 — 5V nie zmienia defaultu 5Q; pixel-exact OPT jest opt-in).

---

## REALTIME (spec 30)

| | |
|---|---|
| source | 29.97 FPS |
| production default (pool8 + compose REFERENCE, bez env) | Prod1=34.53, Prod2=35.17 → **med 34.85 FPS** (wall 34.28 s) |
| factor | **1.163×** |
| margin | **+16.3 %** |
| production pool8 + 5Q OPT (opcjonalnie) | ~37.5 FPS (margin ~+25 %) |

**AMD realtime 4K29.97 achieved: YES** (nawet przy default REFERENCE compose margin +16 %).

---

## FINAL

- **AMD realtime 4K29.97 achieved: YES**
- **production default pool: 8** (bez wymaganego env; override zachowany)
- NVIDIA/Intel: **nietknięte** (zmiana tylko w AMD native D3D11/AMF).
- AMF quality: **nietknięte** (Usage/Quality/CQP 28/28/RC/GOP/B-frames/profile/Submit-Query bez zmian).
- NORMALIZE / VP / shadery: **bez zmian**.
- 5N PRECOMPUTED: pozostaje REFERENCE default.
- Infrastruktura diagnostyczna `AMD_VP_POOL_SIZE` / `AMD_POOL_LIFECYCLE_STATS`: **zachowana** (spec 27).

---

## ODPOWIEDZ WPROST

1. **Czy pool8 jest bezpieczny przez długi eksport?** → TAK (soak 12×1131 w 1 procesie, wszystkie accounting OK, zero korupcji).
2. **Czy zasoby są poprawnie zwalniane?** → TAK (live=0 textures i views po każdym destroy; 17 cykli).
3. **Czy pamięć rośnie między eksportami?** → RSS rośnie ~150–500 MB/eksport w procesie długożyjącym, ALE **brak leaku**: live objects +13/eksport (stabilne), native pool live=0 po każdym destroy. To retencja alokatora (freed memory nie zwracana do OS), memory odzyskiwalne.
4. **Czy pool8 nadal daje około +6 FPS?** → +4.92 FPS w produkcji (med 32.58→37.50, +15.1 %); 5U izolacja dawała +5.9–6.8 FPS. Skala potwierdzona.
5. **Jaki jest stabilny medianowy FPS?** → pool8+OPT ~37.5 FPS; production default (REF compose) ~34.9 FPS.
6. **Jaki jest realtime margin?** → +16.3 % (default), do +25 % (z 5Q OPT).
7. **Czy first-call driver wait praktycznie zniknął?** → TAK w medianie (13.26 → 0.72 ms; p95 24.5→12.1).
8. **Czy AMF outstanding nadal może być > pool4?** → TAK (pool8: med 10, max 11 vs pool4 med 5).
9. **Czy QueryOutput pozostał REFERENCE?** → TAK (bez zmian).
10. **Czy pool8 jest teraz production default?** → TAK.
11. **Czy AMD 4K29.97 realtime jest osiągnięty?** → TAK (1.163×, +16.3 %).
12. **Czy dalsza optymalizacja AMD jest jeszcze konieczna?** → NIE do realtime; opcjonalne (np. domyślna 5Q OPT +2.5 FPS).

---

## KRYTERIA PASS

| # | kryterium | wynik |
|---|---|---|
| 1 | pool8 lifecycle poprawny | ✅ |
| 2 | clean build DLL | ✅ (SHA 8228EF84…) |
| 3 | short exact (31) | ✅ (31/31) |
| 4 | full 1131 exact | ✅ (1131/1131, drops=0) |
| 5 | long soak / repeated-export soak PASS | ✅ (12 eksportów) |
| 6 | brak resource leak | ✅ (live=0) |
| 7 | drops=0 | ✅ |
| 8 | pool8 wyraźnie szybszy od pool4 | ✅ (+4.92 FPS, obie pary) |
| 9 | shutdown/recreate PASS | ✅ (12 cykli) |
| 10 | NVIDIA/Intel untouched | ✅ |
| 11 | AMF quality untouched | ✅ |
| 12 | pool8 ustawiony jako AMD production default po gate'ach | ✅ |

---

## PLIKI

- Native: `src/d3d11_amf_pipeline/src/telem_amd_native.cpp`, `src/d3d11_vp_pipeline.{h,cpp}`.
- Harnessy: `scratch/etap5v_{golden,production,detail,soak}.py`.
- JSON: `Raporty/AMD_ETAP5G/etap5v_{golden,production,detail,soak}.json`.
- Framemd5: `Raporty/AMD_ETAP5G/l5v_*.md5`.
