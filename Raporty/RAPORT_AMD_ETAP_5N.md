# RAPORT AMD — ETAP 5N: Precomputed telemetry frame cache

**STATUS: ⚠️ NO-GAIN** — poprawność 100% (exactness + identyczne wyjście), ale
**brak zysku na całkowitym czasie eksportu** w reżimie GPU/enkoder-bound.

Implementacja: `AMD_TELEMETRY_MODE=REFERENCE|PRECOMPUTED` (REFERENCE = fallback,
bez zmian). Renderery/GPU/AMF nietknięte. **Nie wykonano 5O.**

---

## AUDIT — determinizm `prepare_overlay_frame_data`

Każde pole sklasyfikowane:

### A. PRECOMPUTABLE PER EXPORT (stałe dla eksportu)
| pole | powód |
|---|---|
| max_distance_m / max_speed_kmh / min_alt / max_alt | zależne tylko od próbek+layout (range cache) |
| chart_data | budowane raz w `init_worker` |
| gps_track | stała lista trasy |
| start_dt_utc | konfiguracja eksportu |
| extra_indicators: unit/label + "remaining dynamic" (val 0.0) | zależne tylko od layout |
| current_position | czysta funkcja `frame_idx/(total_frames-1)` |

### B. PRECOMPUTABLE PER FRAME (zależne tylko od frame timeline)
| pole | powód |
|---|---|
| date_text / time_text | `f(target_dt, tz)` |
| speed_value / distance_m / alt_value (+ indicator_values speed/dist/alt per-source) | `interpolate_*(samples, target_dt)` |
| iso / exposure / temp | `interpolate_*(GPMF, target_dt)` |
| FIT: cadence / enhanced_speed / gopro_battery / heart_rate | `resolve_cache_value(field, target_dt)` |
| power/atemp/hr/cad/battery (standard) | `resolve_cache_value(field, target_dt)` — None w tym layout |
| elapsed_seconds / avg_speed_kmh / target_dt | `f(target_dt, start_dt, distance)` |

### C. MUST REMAIN LIVE
- **Żadne** pole wyniku `prepare_overlay_frame_data` nie zależy od poprzedniej
  klatki, mutowalnego stanu renderera, layout mutation w trakcie, UI state ani
  side effects — wszystkie są czystymi funkcjami `(frame timeline, export config)`.
- Pozostaje LIVE: same renderery (`compose_overlay`), z-order guards, dirty
  extraction, GPU/AMF — poza zakresem 5N.
- **Guard bezpieczeństwa VFR:** w PRECOMPUTED, jeśli rzeczywisty PTS klatki
  odbiega od założonego CFR (`|sample_time_seconds − frame_idx/target_fps| > 1e-6`),
  klatka jest liczona na żywo (fallback). Dla źródła CFR (1131, 30000/1001)
  nie aktywuje się nigdy.

---

## CACHE

| parametr | wartość |
|---|---|
| frames | **1131** |
| fields (per frame w rekordzie) | 14 primitives + indicator_values + fit_vals |
| fields porównywane (dict lookup) | 26 kluczy / klatka |
| **build time (standalone)** | **~2.2 s** (production 2.6–4.7 s — CPU contention) |
| **memory** | **0.175 MiB** (1131 × `slots` FrameRec + współdzielony static) |
| structure | **C: list[slots-FrameRec] + wspólny static** (wybrano po analizie A/B/C) |
| build | 1-wątkowa pętla (1131 klatek — threading zbędny) |

---

## CALL COUNTS (hot path)

| | resolver/frame | interpolation/frame | FIT lookup/frame | GPMF lookup/frame |
|---|---|---|---|---|
| **REFERENCE** | 4 | 9 | 4 | 3 |
| **PRECOMPUTED (lookup)** | **0** | **0** | **0** | **0** |

- FIT lookup 4 → 0 (cadence, enhanced_speed, gopro_battery, heart_rate).
- GPMF lookup 3 → 0 (iso, exposure, temperature).
- Interpolacja 9 → 0 (6 × speed/dist/alt + 3 GPMF).
- **Duplicate consumers:** plan 5B (set `active_fit_fields`) + per-frame dedup —
  wartość każdego unikalnego pola liczona **raz** (nie ma duplikacji per widget).

---

## VALUE EXACTNESS

| | |
|---|---|
| frames compared | **1131** |
| fields compared | **29 406** |
| **mismatches** | **0** |
| first mismatch | — |
| max numerical difference | **0.0** |
| boundary frames (0,1,30,300,600,900,1129,1130) | wszystkie równe |
| None-handling (power/atemp/hr/cad/battery) | poprawne (None) |
| alternate layout (`fit_fractional_cadence_text`) | mismatches=0, pole obecne w cache |
| duplicate consumers | brak duplikacji |

---

## MICROBENCH (1131 frames, 5 powtórzeń, standalone)

| | median | P95 | P99 |
|---|---|---|---|
| **REFERENCE** | 1.794 ms | 2.692 ms | 3.110 ms |
| **PRECOMPUTED lookup** | **0.005 ms** | 0.011 ms | 0.017 ms |
| **speedup** | **630×** | | |

Separate: cache build ~2.2 s (standalone).

---

## FULL A/B (production 1131, pełny GPU pipeline, profiling OFF)

| Run | mode | cache build | render wall | total wall | TRUE FPS | telemetry med | drops |
|---|---|---|---|---|---|---|---|
| **A** | REFERENCE | — | 58.40 s | 58.40 s | 20.00 | 3.39 ms | 0 |
| **B** | PRECOMPUTED | 4.68 s | 68.15 s | 72.83 s | 16.04 | 0.036 ms | 0 |
| **C** | REFERENCE | — | 63.10 s | 63.10 s | 18.46 | 3.27 ms | 0 |
| **D** | PRECOMPUTED | 2.56 s | 59.87 s | 62.43 s | 18.66 | 0.036 ms | 0 |

| metryka | wartość |
|---|---|
| **REF median total wall** | **60.75 s** |
| **PRE median total wall** | **67.63 s** |
| **TOTAL GAIN** | **−11.32 %** (regresja) |
| RENDER-LOOP FPS (REF med) | 19.23 |
| RENDER-LOOP FPS (PRE med, bez build) | 17.67 |
| PRE median render wall (bez build) | 64.0 s |

> **Ważne:** sesja A/B/C/D działała w stanie **termicznie zdegradowanym**
> (16–20 FPS, po ~10 eksportach back-to-back; 5M baseline chłodnego GPU = 27 FPS).
> Absolutne FPS nie są porównywalne z 5M; porównanie REF↔PRE w tej samej sesji
> jest miarodajne. Dryf termiczny (A 58.4 → C 63.1 dla REF) jest większy niż
> sygnał — ale nawet **najlepszy PRE (D render 59.9 s) nie jest szybszy niż
> najszybszy REF (A 58.4 s)**: telemetry nie jest na critical path.

---

## REALTIME

| | |
|---|---|
| Source | 29.97 FPS |
| PRE equivalent total throughput | 1131 / 67.63 s = **16.72 FPS** (ta sesja, thermal) |
| Realtime factor | **0.558×** |
| Margin | **−44.2 %** |

> Zastrzeżenie: wartości z sesji termicznie zdegradowanej. Nawet chłodny 5M
> baseline (27.17 FPS = 0.907×) pozostaje poniżej realtime.

---

## BOTTLENECKS AFTER 5N (w reżimie GPU/enkoder-bound)

1. **AMF HEVC 4K drenaż / GPU thermal throttle** — wyznacza TRUE FPS (16–20 FPS
   pod obciążeniem); nie jest mierzalny per-frame (AMF submit niski, drenaż w tle).
2. **compose_overlay** (~11.3 ms CPU) — nadal największy stage CPU, ale **nie na
   critical path** gdy GPU/enkoder jest limiterem.
3. **map CPU** (~2.8 ms).
4. **gauge tobytes+upload** (~1.3 ms).
5. **HUD dirty extract + PIL/prep** (~2.0 ms).

> 5N udowodnił: redukcja 200× kosztu telemetry (7.9 ms → 0.04 ms) **nie**
> przyspieszyła wall — to twardy dowód, że CPU-side (telemetry, a prawdopodobnie
> i compose) nie jest aktualnym limiterem.

---

## ODPOWIEDZ WPROST

1. **Ile cache zajmuje pamięci?** → **0.175 MiB** (1131 slots records + static).
2. **Ile trwa jego budowa?** → **~2.2 s** standalone; **2.6–4.7 s** w production (contention).
3. **Ile resolverów/interpolacji usunięto z hot path?** → resolver **4→0**,
   interpolacja **9→0**, FIT lookup **4→0**, GPMF **3→0** (wszystkie na klatkę).
4. **Czy wszystkie wartości exact?** → **TAK** — 1131 klatek, 29 406 pól,
   mismatches=0, max diff 0.0; **framemd5 REF ≡ PRE** (identyczny hash wyjścia).
5. **Ile kosztowało telemetry BEFORE?** → **7.9 ms** production (3.3 ms w A/B/C/D;
   1.79 ms standalone).
6. **Ile kosztuje telemetry lookup AFTER?** → **0.036 ms** production (0.005 ms standalone).
7. **Zysk render-loop?** → **~0** (PRE render 64.0 s vs REF 60.8 s; w granicach szumu
   termicznego — brak mierzalnego zysku, bo telemetry nie jest na critical path).
8. **Zysk całkowitego czasu eksportu?** → **NEGATYWNY** (−11.3% w tej sesji:
   build + brak zysku render-loop).
9. **Stabilny equivalent FPS po uwzględnieniu build?** → w tej sesji 16.7 FPS;
   bezpośrednie porównanie z 5M (27 FPS) nieuprawnione (thermal drift).
10. **Czy TeleM przekracza realtime 29.97?** → **NIE** (0.56× w tej sesji; 5M
    chłodny = 0.91×).
11. **Największy bottleneck po 5N?** → **AMF HEVC 4K drenaż / thermal GPU** —
    nie telemetry.
12. **Następny etap: compose czy zmierzyć encoder drain?** → **NAJPIERW zmierzyć
    encoder drain (5O)**. 5N dostarczył dowód: 200× redukcja CPU na telemetry nie
    dała zysku wall, bo pipeline jest GPU/enkoder-bound. Dopóki nie naprawimy
    drenażu/thermal enkodera, optymalizacje CPU (compose, telemetry) nie
    przyniosą zysku na całkowitym czasie eksportu.

---

## KRYTERIA PASS

| # | kryterium | wynik |
|---|---|---|
| 1 | telemetry semantics bez zmian | ✅ |
| 2 | 1131-frame comparison mismatch=0 | ✅ (29406 pól, 0) |
| 3 | alternate layout działa | ✅ (fractional_cadence, mismatches=0) |
| 4 | duplicate consumers bez duplikacji | ✅ |
| 5 | cache invalidation per-export | ✅ (budowany świeżo w każdym eksporcie) |
| 6 | reference fallback | ✅ (AMD_TELEMETRY_MODE=REFERENCE domyślny) |
| 7 | GPU pipeline bez zmian | ✅ |
| 8 | final output bez regresji | ✅ (framemd5 identical) |
| 9 | 1131/1131 | ✅ |
| 10 | drops=0 | ✅ |
| 11 | **total export wall nie regresuje** | ❌ (−11.3% w tej sesji) |

**STATUS: ⚠️ NO-GAIN** — poprawność kompletna, ale brak zysku wydajnościowego
(kryterium #11 niespełnione). Kod PRECOMPUTED pozostaje jako opt-in infrastruktura
(REFERENCE = default, bez zmian w produkcji); przyniesie zysk dopiero, gdy
pipeline stanie się CPU-bound (np. po naprawie enkodera / na szybszym GPU).

---

## ARTEFAKTY

- Moduł: `src/telemetry_precompute.py`; integracja: `src/ffmpeg/amd_native_exporter.py`
  (`AMD_TELEMETRY_MODE`, sekcja `etap5n` w profilu).
- Testy: `scratch/etap5n_exactness.py`, `etap5n_microbench.py`,
  `etap5n_output_regression.py`, `etap5n_ab.py`.
- Wyniki: `Raporty/AMD_ETAP5G/etap5n_exactness.json` (w stdout),
  `etap5n_output_regression.json`, `etap5n_ab.json`; eksporty
  `l5n_full_{ref,pre}.mp4`, `l5n_ab_{A,B,C,D}.mp4`.

> Zgodnie z dyrektywą: **NIE** wykonano 5O, **NIE** zmieniono rendererów/GPU/AMF,
> wyłącznie warstwa telemetry + opt-in mode.
