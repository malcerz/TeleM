# RAPORT AMD — ETAP 5L-FINAL-VALIDATION: pełny dowód poprawności GPU speed gauge

**STATUS: ✅ PASS-EXACT**

Pełny, 1131-klatkowy dowód poprawności GPU compositingu speed gauge
(`fit_enhanced_speed_text`, ETAP 5L) — wyłącznie correctness, bez optymalizacji,
bez ETAPU 5M.

- **RAW gauge (1131):** determinizm 1131/1131, CPU-composite parity `mismatches=0`, `max=0`.
- **GPU composite (1131):** readback A/B **MAE=0, MAX=0, n>0=0** na wszystkich klatkach.
- **Final output:** framemd5 CPU_REFERENCE ≡ GPU gauge (hash identyczny).
- **Wykryto i naprawiono realny bug produkcyjny** (gauge bbox poza granicami HUD).

---

## 1. METODA WALIDACJI (`scratch/l5_final_validation.py`)

| Faza | Zakres | Kryterium |
|---|---|---|
| **A** — RAW gauge | 1131 klatek, czysty Python | determinizm, dirty zeros, pokrycie alpha, parity z `alpha_composite` |
| **B** — GPU composite | 1131 klatek, `AMD_GAUGE_AB_READBACK=1` | readback GPU bbox vs CPU_REFERENCE (raw + drop dirty zeros) |
| **C** — Final output | CPU_REFERENCE vs GPU gauge | framemd5 strumienia wideo |

---

## 2. FAZA A — RAW GAUGE 1131 (pure Python)

| Metryka | Wynik | Oczekiwane | Status |
|---|---|---|---|
| Klatki | 1131 | 1131 | ✅ |
| Mismatches determinizmu | **0** | 0 | ✅ |
| Dirty zeros — klatki z DZ | **1131** | — (dowód pokrycia) | ✅ |
| Dirty zeros — piksele łącznie | **425 256** | — | — |
| Dirty zeros — max/frame | **376** | — | — |
| Alpha min / max | **0 / 255** | 0 / 255 | ✅ |
| Klatki z partial alpha | **1131** | — (dowód antyaliasingu) | ✅ |
| CPU-composite parity (raw drop-DZ vs Pillow `alpha_composite`) | **mismatches=0, max=0** | 0 / 0 | ✅ |

> Parity CPU potwierdza, że **CPU_REFERENCE = raw gauge z wyzerowanym RGB tam,
> gdzie α=0** (dirty zeros → przezroczyste). To dokładnie kontrakt shadera GPU
> (tryb 3 — blend z drop dirty zeros).

---

## 3. FAZA B — GPU COMPOSITE 1131 (diagnostic readback)

`rc=0`, `elapsed=111.1s`.

Readback bbox gauge z HUD (GPU) vs CPU_REFERENCE, per-pixel, 1131 klatek:

| Metryka | avg | median | p95 | p99 | Wymóg EXACT |
|---|---|---|---|---|---|
| **MAE** | 0.0 | 0.0 | 0.0 | 0.0 | = 0 ✅ |
| **MAX** | 0.0 | 0 | 0.0 | 0.0 | = 0 ✅ |
| **n>0** (mismatches px) | 0.0 | 0 | 0.0 | 0.0 | = 0 ✅ |
| n>1 / n>2 / n>4 / n>8 | 0.0 | 0 | 0.0 | 0.0 | ✅ |

**Pokrycie przypadków granicznych (dowód, że test jest istotny):**

| Cecha | avg | median | p95 | p99 |
|---|---|---|---|---|
| Dirty zeros / frame | 2913.3 | 2925 | 2926.0 | 2926.0 |
| Partial alpha px / frame | 6243.1 | 6225 | 6343.0 | 6369.0 |

> Wszystkie 1131 klatek zawiera **dirty zeros** (RGB≠0 przy α=0) **i** piksele
> o **częściowej alfie** (0<α<255) — test realnie ćwiczy kod ścieżki drop-DZ
> oraz interpolację alfa, a nie tylko nieprzezroczyste wnętrze gauge.

**GPU composite: MAE=0, MAX=0, mismatches=0/1131 → EXACT.**

---

## 4. FAZA C — FINAL OUTPUT (CPU_REFERENCE vs GPU gauge)

| Wariant | rc | czas |
|---|---|---|
| CPU_REFERENCE | 0 | 55.9 s |
| GPU gauge | 0 | 52.8 s |

| Hash framemd5 | Wartość |
|---|---|
| CPU | `ff0e8b5c8cca35e9a78a431bf01c5a48257afc46df625fd922e5d737a8202a04` |
| GPU | `ff0e8b5c8cca35e9a78a431bf01c5a48257afc46df625fd922e5d737a8202a04` |
| **Identyczne** | **TAK ✅** |

> Finalny strumień wideo z GPU gauge jest **bitowo identyczny** z CPU_REFERENCE
> na wszystkich 1131 klatkach.

---

## 5. FRAME ACCOUNTING (1131 klatek)

| Licznik | CPU_REFERENCE | GPU gauge |
|---|---|---|
| source_frames | 1131 | 1131 |
| requested_frames | 1131 | 1131 |
| decoded_frames | 1131 | 1131 |
| mf_d3d11_surfaces | 1131 | 1131 |
| native_processed | 1131 | 1131 |
| vp_processed | 1131 | 1131 |
| hud_frames | 1131 | 1131 |
| native_hud_updates | 1131 | 1131 |
| cadence_gpu | 1131 | 1131 |
| hr_gpu | 1131 | 1131 |
| amf_submitted | 1131 | 1131 |
| amf_output | 1131 | 1131 |
| muxed_frames | 1131 | 1131 |
| mf_null_samples / drops | **0** | **0** |

> `map_gpu=0` — mapa pozostaje na ścieżce CPU i jest poza zakresem ETAPU 5L
> (walidacja gauge). Brak zgubionych/zdublowanych klatek w obu wariantach.

---

## 6. WYKRYTY I NAPRAWIONY BUG PRODUKCYJNY

**Objaw:** przy `AMD_GAUGE_AB_READBACK=1` readback zwracał pusty wynik
(`gauge_ab = null`), mimo poprawnego uploadu.

**Przyczyna (root cause):**

```
Gauge bbox = (1544, 1632, 648, 648)
gauge bottom = 1632 + 648 = 2280  >  HUD height 2160
```

- Native `GetHUDCanvasRegionReadback` ma bounds-check (`x+w > hudWidth || y+h > hudHeight`)
  → zwracał `False` → brak danych.
- `BlendGauge` (shader tryb 3) zapisywał poza granicami HUD — D3D11 UAV
  nadmiarowe zapisy odrzuca sprzętowo, ale to **latent UB**.
- CPU `Pillow.alpha_composite` **przycina** gauge do granic HUD — GPU musi
  zachować identyczną semantykę.

**Fix (`src/ffmpeg/amd_native_exporter.py`, blok uploadu gauge):**

- Klip bbox gauge do granic HUD:
  `cx0,cy0 = max(0,gx), max(0,gy)`, `cx1,cy1 = min(W, gx+gw), min(H, gy+gh)`.
- Crop obrazu gauge do przyciętego bbox **przed** `tobytes`/upload
  (zachowane 1:1 texel, bez resamplingu).
- Readback A/B używa przyciętych wartości (`gauge_ab_bbox` / `gauge_ab_img`).

**Weryfikacja fixu:** smoke test (31 klatek) i pełny przebieg (1131 klatek)
→ readback MAE=0 / MAX=0 / n>0=0.

> Efektywny obszar gauge: 648×648 → **648×528** (dół 120 px poza HUD,
> w pełni przezroczysty — wycinany bez zmiany wyniku).

---

## 7. FINAL STATUS

| Kryterium spec | Wynik | Wymóg | Status |
|---|---|---|---|
| RAW gauge: MAE=0, MAX=0, mismatches=0/1131 | determinizm 0, parity 0/0 | =0 | ✅ |
| GPU composite: MAE=0, MAX=0, mismatches=0/1131 | 0 / 0 / 0 | =0 | ✅ |
| Final output: CPU ≡ GPU | hash identyczny | identyczne | ✅ |
| Frame accounting: 1131, drops=0 | 1131 / 0 | 1131 / 0 | ✅ |

**FINAL STATUS: ✅ PASS-EXACT**

---

## 8. ARTEFAKTY

- Raport JSON: `Raporty/AMD_ETAP5G/l5_final_validation.json`
- Skrypt walidacji: `scratch/l5_final_validation.py`
- Eksport GPU (readback): `Raporty/AMD_ETAP5G/l5_final_gpu_ab.mp4`
- Eksport CPU_REFERENCE: `Raporty/AMD_ETAP5G/l5_final_cpu.mp4`
- Eksport GPU gauge: `Raporty/AMD_ETAP5G/l5_final_gpu.mp4`
- Klatki diagnostyczne gauge: `Raporty/AMD_ETAP5G/l5_gauge_{gpu,cpu,diff}_*.png`

> Zgodnie z dyrektywą: **NIE** wykonano ETAPU 5M, **NIE** optymalizowano,
> **NIE** zmieniano kodu produkcyjnego poza jedyną poprawką realnego bugu
> (klip bbox gauge do granic HUD).
