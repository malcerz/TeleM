# RAPORT AMD — ETAP 5G-VALIDATION: Walidacja ścieżki mapy GPU na CZYSTYM źródle

**Status końcowy: ✅ PASS-VISUAL** (raw 691×691 GPU resample vs Pillow LANCZOS:
**MAE 0.173 > 0, MAX 37.75 > 0** → zgodność wizualna, NIE „EXACT")

> **Korekta klasyfikacji z RAPORT_AMD_ETAP_5G.md:** poprzedni raport błędnie oznaczył
> wynik jako **PASS-EXACT**. Zgodnie z kryteriami zadania **PASS-EXACT wymaga
> MAE=0, MAX=0, mismatching pixels=0**. Ponieważ MAE=0.173 i MAX≈37.75 (n>1 = 0.20%),
> poprawna klasyfikacja to **PASS-VISUAL** — nie „praktycznie exact", nie „≈ exact".

**Zakres:** WYŁĄCZNIE walidacja na czystym źródle. **Brak nowych optymalizacji.**
**STOP — nie rozpoczęto ETAPU 5H.**

---

## 1. CZYSTE ŹRÓDŁO (CLEAN SOURCE)

| Element | Wartość |
|---|---|
| Oryginalne czyste źródło | `Raporty/AMD_ETAP0_GOLDEN/golden_pre_etap0.mp4` (1130 klatek) |
| Plik roboczy do pipeline'u | `Raporty/AMD_ETAP5G/VAL/clean_m10.mp4` (libx265 re-encode, Main10 BT.2020/HLG/full-range) |
| Potwierdzenie braku wypalonego HUD/mapy | **TAK** — klatki 30/300/900 sprawdzone wizualnie (`clean_{30,300,900}.png`), brak jakiegokolwiek overlay'u |
| Tryb dekodowania (harness) | `AMD_NATIVE_DECODE_MODE=GPU_HUD_CPU_DECODE_REFERENCE` — czyste źródło nie ma metadanych VUI GoPro → D3D11VA `VideoProcessorBlt` zwraca 0x80004005; tryb CPU-decode reference działa (`[VP] blt hr=0x0`), **logika mapy GPU identyczna** |

> Uwaga metodologiczna: `Video/GX020079.mp4` użyty jako golden w raporcie 5G jest
> **zanieczyszczony** (wypalony overlay w regionie mapy). Niniejsza walidacja używa
> wyłącznie czystego źródła.

## 2. BRAK ZMIAN W ARCHITEKTURZE 5G

- Architektura 5G **bez zmian**: CPU renderuje mapę roboczą 692×692 RGBA → upload
  GPU (persistent texture) → `ResampleAndBlendMap()` (Pass1 resize 692→691,
  Pass2 blend "over" do HUD UAV) → `ComposeHUDDirectNV12`.
- Zmiany wyłącznie w harnessie walidacyjnym / diagnostyce:
  - dumpy PNG HUD canvas na klatkach 30/300/900 (`H_hud_canvas_%u.png`),
  - dumpy CPU HUD (`01_python_hud_%u.png`),
  - pomiar czasów natywnych mapy (`AMD_MAP_STATS=1`),
  - `AMD_MAP_AB_READBACK=1` wyłącznie do surowego A/B 691 (diagnostyka).
- **Żadna ścieżka produkcyjna nie została zmieniona** (oprócz wcześniej już
  obecnych dumpów diagnostycznych w wersji deweloperskiej DLL).

## 3. KOREKTA KLASYFIKACJI

| Określenie | Poprzedni raport 5G | Poprawnie |
|---|---|---|
| Status | PASS-EXACT (błędnie) | **PASS-VISUAL** |
| Kryterium | „99.8% pikseli ±1" | PASS-EXACT = MAE 0 / MAX 0 / mismatching 0; tu MAE 0.173 / MAX 37.75 |

## 4. RAW MAP A/B — 1130 KLATEK, CZYSTE ŹRÓDŁO (LANCZOS)

Eksport: `Raporty/AMD_ETAP5G/VAL/raw_ab_1131_clean.mp4` (`AMD_MAP_AB_READBACK=1`, diagnostyka).

| Metryka | avg | median | p95 | p99 |
|---|---|---|---|---|
| **MAE** (raw 691 RGBA) | **0.1730** | 0.1729 | 0.1735 | 0.1736 |
| **MAX** | **37.75** | 37 | 42 | 44 |
| n>1 | 0.20 % | 0.20 % | 0.21 % | 0.21 % |
| n>2 | 0.11 % | 0.11 % | 0.12 % | 0.12 % |
| n>4 | 0.052 % | 0.052 % | 0.052 % | 0.052 % |
| n>8 | 0.033 % | 0.033 % | 0.033 % | 0.033 % |
| n>16 | 0.020 % | 0.020 % | 0.020 % | 0.020 % |

- `map_gpu_frames` = **1130**; upload = **1.827 MiB/klatkę**; klatki 1130/1130; AMF drops 0.
- GPU vs CPU mean RGBA 98.3/101.6/80.5/255 — identyczne; różnice tylko na krawędziach (MAX ~37).
- **Klasyfikacja: PASS-VISUAL** (MAE/MAX > 0 → NIE EXACT).

Artefakty: `Raporty/AMD_ETAP5G/map_gpu_lanczos_frame_{30,300,900}.png`,
`map_cpu_ref_frame_{30,300,900}.png`, `map_diff_lanczos_frame_{30,300,900}.png`.

## 5. FINAL HUD A/B PRZED NV12 — KLATKI 30/300/900

GPU final HUD (`H_hud_canvas_%u.png`, po GPU blend mapy) vs CPU final HUD
(rekonstrukcja: `01_python_hud_%u.png` + CPU LANCZOS mapa w (3035,137)).

| Frame | Diff poza regionem mapy | Diff w regionie mapy | Ghost/dup mapy | Alpha |
|---|---|---|---|---|
| 30 | **0 pikseli (pixel-exact)** | MAE ~0.17 (jak raw A/B) | NIE | PASS |
| 300 | **0 pikseli (pixel-exact)** | MAE ~0.17 | NIE | PASS |
| 900 | **0 pikseli (pixel-exact)** | MAE ~0.17 | NIE | PASS |

- Cały diff (MAE 0.010 / MAX 49 w skali całej klatki) zamknięty w bboxie mapy
  `x[3035,3725] y[137,827]` (691×691) — poza mapą GPU kompozyt == CPU **co do piksela**.
- **Ghost/dup mapy: NIE** — dokładnie jedna mapa, jeden bbox.

Artefakty: `VAL/hud_cpu_final_{30,300,900}.png`, `VAL/hud_gpu_final_{30,300,900}.png`,
`VAL/hud_diff_amp8_{30,300,900}.png`.

## 6. Z-ORDER

| Scenariusz | Layout | Wynik |
|---|---|---|
| **A (bezpieczny, GPU)** | `def_layout.json` — `track_map` OSTATNI włączony | GPU map path aktywny, `map_gpu_frames=1130` |
| **B (niebezpieczny, fallback)** | `scratch/layout_unsafe.json` — `track_map` PIERWSZY | `GPU_MAP_UNSAFE_LAYOUT -> CPU_REFERENCE fallback` (last=temp_text); CPU_REFERENCE active; 31 klatek, TRUE FPS 5.599 |

## 7. CZYSTOŚĆ BAZY (CLEAN BASE CORRECTNESS)

- Baza czysta: w regionie mapy brak „starej mapy"/ghosta (czysty base `golden_pre_etap0`).
- W trybie GPU region mapy w canvassie CPU (`01_python_hud_%u.png`) jest **w pełni
  przezroczysty** (alpha=0, RGB=0) — `track_map` poprawnie usunięty z `compose_layout`.
- Region mapy w canvassie GPU (`H_hud_canvas_%u.png`) == `H_resample_texture.png`
  **dokładnie** (MAE 0, MAX 0) — wynik GPU resample jest tym, co trafia do HUD.
- Mapa występuje **dokładnie raz**; alpha regionu mapy = 255 (opaque), poza mapą = HUD.
- `I_map_source_texture.png` = 692×692 (mapa robocza uploadowana na GPU).

## 8. PREVIEW ↔ EXPORT ZOOM

- `track_map.zoom = 14`; `_map_render_plan()` (reference canvas 960):
  - 960 px (preview) → **effective zoom 14**
  - 1920 px (export) → **effective zoom 15**
  - 3840 px (export) → **effective zoom 16**
- working 692 × 692 → output 691 × 691 (dokładnie resize 5G).
- Trasa + marker + bounds poprawne na klatkach 30/300/900
  (`map_gpu_lanczos_frame_{30,300,900}.png`, marker przesuwa się wzdłuż trasy).

## 9. PERFORMANCE — KONTROLOWANE A/B/C/D (każde pełne 1130 klatek)

Warunki: ta sama sesja, bez obciążenia w tle, **profilowanie/diagnostyka/readback OFF**
(`AMD_OVERLAY_PROFILE=0, AMD_NATIVE_PROFILING=0, AMD_NATIVE_DIAGNOSTICS=0, AMD_MAP_AB_READBACK=0`),
`AMD_NATIVE_DECODE_MODE=GPU_HUD_CPU_DECODE_REFERENCE`, LANCZOS.

| Run | Ścieżka | TRUE FPS | compose_overlay (median) | map_cpu_upload (median) | Klatki | AMF drops |
|---|---|---|---|---|---|---|
| A | CPU_REFERENCE | **7.518** | 65.25 ms | — | 1130/1130 | 0 |
| B | GPU | **12.029** | 29.52 ms | 2.87 ms | 1130/1130 | 0 |
| C | CPU_REFERENCE | **9.433** | 52.12 ms | — | 1130/1130 | 0 |
| D | GPU | **11.790** | 30.24 ms | 2.89 ms | 1130/1130 | 0 |

Pliki: `VAL/perf_A_cpu.mp4`, `perf_B_gpu.mp4`, `perf_C_cpu.mp4`, `perf_D_gpu.mp4` (+ `.amd_profile.json`).

## 10. STATYSTYKI PERFORMANCE (mediany z 2 przebiegów)

| Metryka | Wartość |
|---|---|
| CPU_REFERENCE median TRUE FPS (A, C) | **8.476** |
| GPU median TRUE FPS (B, D) | **11.910** |
| **Zysk GPU vs CPU_REFERENCE (ta sama sesja)** | **+40.5 %** |
| compose_overlay median CPU vs GPU | 58.7 ms → 29.9 ms (**−49 %**) |

- GPU szybszy w OBU parach (7.5→12.0; 9.4→11.8). Rozrzut przebiegów CPU (7.5–9.4)
  wynika ze współdzielenia CPU przez dekodowanie (tryb reference).

## 11. HISTORYCZNY BASELINE 5E (KONTEKST TYLKO)

| Baseline | TRUE FPS | compose_overlay | Uwaga |
|---|---|---|---|
| 5E (historia) | 15.781 | 38.571 ms | **tylko kontekst** — inne warunki (D3D11VA), inna sesja |

- Nie deklaruję regresji/zysku względem 5E. Miarodajne jest kontrolowane porównanie
  CPU_REFERENCE vs GPU w tej samej sesji (sekcja 9–10).
- Niższe TRUE FPS niż 5E wynika z trybu CPU-decode reference (harness dla czystego
  źródła bez metadanych VUI), nie z architektury 5G.

## 12. CZASY (SEKCJA 5G)

| Etap | CPU_REFERENCE | GPU |
|---|---|---|
| compose_overlay (median) | 52.1–65.3 ms | 29.5–30.2 ms |
| mapa CPU — `track_map.total` (crop+marker+LANCZOS+paste, median) | 21.7 ms | — |
| &nbsp;&nbsp; w tym Pillow LANCZOS 692→691 (dominujący koszt) | ~35 ms | — |
| mapa CPU — `map_cpu_upload` (crop+marker+tobytes+upload, median) | — | 2.87–2.89 ms |
| GPU map upload — natywny `UpdateSubresource` (avg) | — | 0.256 ms |
| GPU map resize+blend submit — Pass1+Pass2+Flushes (avg) | — | 0.295 ms |
| HUD texture upload (median) | 2.1–2.4 ms | 1.4–2.0 ms |

- Źródło czasów: profile JSON (timings) z przebiegów A–D + pomiar `AMD_MAP_STATS=1`
  (`VAL/timing_gpu_60.mp4.amd_profile.json`) + overlay profile (`VAL/timing_cpu_60.mp4`).

## 13. TRANSFERY

| Kierunek | Wielkość | Uwagi |
|---|---|---|
| CPU → GPU (mapa) | **1.827 MiB/klatkę** (692×692×4) | `UpdateSubresource`, persistent texture |
| GPU → CPU | **0 MiB/klatkę (produkcja)** | readback wyłącznie diagnostyka (`AMD_MAP_AB_READBACK=1`) |
| CPU → GPU (baza, tylko harness) | 11.87 MiB/klatkę (NV12) | tryb CPU-decode reference; w produkcji D3D11VA baza zostaje na GPU (0 upload) |

## 14. PEŁNA KSIĘGOWOŚĆ KLATEK (1130)

```
source_frames=1130  decoded_frames=1130  native_processed=1130  hud_frames=1130
vp_processed=1130   amf_submitted=1130   amf_output=1130        muxed_frames=1130
AMF drops=0  retries=0  input_full=0
```

## 15. REGRESJA (CZYSTE ŹRÓDŁO, GPU export)

| Obszar | Wynik |
|---|---|
| FIT | **PASS** — odkryto 14 pól (K1, K2, alt, cadence, curVpower, distance, enhanced_altitude, enhanced_speed, fractional_cadence, gopro_battery, heart_rate, speed, temperature, track) |
| GPMF | **PASS** — telemetria wczytana bez błędu |
| Mapa | **PASS** — A/B + final HUD (sekcje 4–5) |
| Cadence | **PASS** — widget `fit_cadence_text` w HUD |
| HR | **PASS** — widget `fit_heart_rate_text` w HUD |
| Speed | **PASS** — widget `fit_enhanced_speed_text` w HUD |
| Date-time | **PASS** — widget `time_block` w HUD |
| Inny HUD | **PASS** — canvas HUD pixel-exact względem CPU poza regionem mapy; widgety obecne (FIT, gauge, dolny pasek) |
| Kolor | **PASS** — pipeline GPU P010→NV12→AMF; output HEVC Main 8-bit (limit `hevc_amf` — brak Main10; nie jest regresją 5G) |
| Audio | **PASS** — `audio_present=True`, zremuxowane 1130 klatek |

## 16. STATUS KOŃCOWY I ODPOWIEDZI NA PYTANIA KONTROLNE

**STATUS: ✅ PASS-VISUAL**

1. **Czy użyto czystego źródła?** Tak — `golden_pre_etap0.mp4` (re-encode
   `clean_m10.mp4`), brak wypalonego HUD/mapy (potwierdzone klatki 30/300/900).
2. **Czy mapa jest dokładnie jedna?** Tak — jeden region 691×691, brak ghost/dup.
3. **Czy GPU Lanczos jest pixel-exact?** Nie — MAE 0.173, MAX 37.75, n>16 0.02% →
   zgodność **wizualna**, nie EXACT.
4. **Poprawny status?** **PASS-VISUAL** (błędnie PASS-EXACT w raporcie 5G).
5. **Z-order fallback?** Działa — unsafe layout → `GPU_MAP_UNSAFE_LAYOUT ->
   CPU_REFERENCE fallback` (zweryfikowane).
6. **Readback GPU→CPU w produkcji?** 0 MiB/klatkę.
7. **Median CPU_REFERENCE TRUE FPS?** 8.476 (A=7.518, C=9.433).
8. **Median GPU TRUE FPS?** 11.910 (B=12.029, D=11.790).
9. **Realny zysk GPU vs CPU_REFERENCE (ta sama sesja)?** **+40.5 %**.
10. **Czy ETAP 5G może zostać zamknięty?** Tak — jako **PASS-VISUAL** na czystym
    źródle, bez nowych optymalizacji. **STOP — nie rozpoczynam 5H.**

---

## PLIKI / ARTEFAKTY

- `Raporty/AMD_ETAP0_GOLDEN/golden_pre_etap0.mp4` — czyste źródło (1130 klatek)
- `Raporty/AMD_ETAP5G/VAL/clean_m10.mp4` — re-encode do pipeline'u (Main10 BT.2020/HLG)
- `Raporty/AMD_ETAP5G/VAL/raw_ab_1131_clean.mp4` (+ `.amd_profile.json`) — raw A/B 1130
- `Raporty/AMD_ETAP5G/VAL/hud_cpu_900.mp4`, `hud_gpu_910.mp4` — HUD capture CPU/GPU
- `Raporty/AMD_ETAP5G/VAL/hud_cpu_final_*.png`, `hud_gpu_final_*.png`, `hud_diff_amp8_*.png`
- `Raporty/AMD_ETAP5G/VAL/perf_{A_cpu,B_gpu,C_cpu,D_gpu}.mp4` (+ profiles) — A/B/C/D
- `Raporty/AMD_ETAP5G/VAL/timing_gpu_60.mp4`, `timing_cpu_60.mp4` (+ profiles) — czasy
- `Raporty/AMD_ETAP5G/VAL/unsafe_fallback_clean.mp4` — z-order fallback B
- `Raporty/AMD_ETAP5G/map_{gpu_lanczos,cpu_ref,diff_lanczos}_frame_{30,300,900}.png` — mapa
- `01_python_hud_{30,300,900}.png`, `H_hud_canvas_{30,300,900}.png`, `H_resample_texture.png`,
  `I_map_source_texture.png`, `C_vp_output.png`, `D_after_gpu_hud.png` — diagnostyka klatki 30
- `scratch/test_unsafe_fallback.py`, `scratch/layout_unsafe.json` — test z-order B

**STOP — raport gotowy. Nie wykonuję etapu 5H.**
