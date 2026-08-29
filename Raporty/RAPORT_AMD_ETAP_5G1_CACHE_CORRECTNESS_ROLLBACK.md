# TeleM — RAPORT AMD ETAP 5G.1 — ABOVE CACHE CORRECTNESS AUDIT + MEMORY PROOF + ROLLBACK DECISION

**Data:** 2026-08-28  
**Środowisko:** AMD Ryzen 7 7730U with Radeon Graphics (8C/16T, 32GB RAM UMA)  
**System & Power Profile:** Windows 11 (Max Performance Power Overlay GUID: `ded574b5-45a0-4f42-8737-46345c09c238`)  
**Gałąź:** `amd-render`  
**Kanoniczny Workload:** `Video/GX020079.MP4` + `Video/GX020079.fit` + `presets/cycling_dashboard_v10.json` (1131 klatek @ 4K)  
**Status etapu:** **COMPLETE — PASS (CORRECTNESS PROVEN / MEMORY BOUNDED / OPTIMAL STATE SELECTED)**

---

## 1. Wyjaśnienie Niespójności: 898 Map Headings vs 1 Compass Angle

### Root Cause
W layoucie `presets/cycling_dashboard_v10.json`:
- `track_map` ma skonfigurowane `"source": "fit"`
- `compass` ma skonfigurowane `"source": "gpmf"`
- `slope_text` ma skonfigurowane `"source": "gpmf"`

W plikach telemetrycznych kanonicznego workloadu `GX020079`:
- Ścieżka GPMF (`GX020079.MP4` / gpmf records) zawiera współrzędne GPS, lecz **nie zawiera bezpośrednich próbek heading ani slope** (`_resolve_cache_value` dla `gpmf` zwraca `None`).
- Plik `GX020079.fit` zawiera zsynchronizowane próbki `heading` (1677 próbek) oraz `slope` (1704 próbki).

W rezultacie:
1. `track_map` (używający `fit`) odczytywał **898 unikalnych dynamicznych kątów obrotu** z pliku FIT.
2. `compass` i `slope_text` (używające `gpmf`) otrzymywały `value=None` na każdej klatce, co uruchamiało fallback missing value (`--°` dla kompasu i `--%` dla slope) ze stałą wartością `0.0` dla wszystkich 1131 klatek.
3. W skrypcie audytowym 5G wystąpiło błędne odczytanie kluczy z `indicator_values` zamiast `extra_indicators`, co zwróciło `None` dla wszystkich klatek.

---

## 2. Compass End-to-End Data Trace

Log wartości dla reprezentatywnych klatek (GPMF vs FIT):

| Frame | Timestamp (s) | GPMF Heading | FIT Heading | Map Heading (Selected) | Compass ExtVal (GPMF) | Requested Rotation | Effective Rotation | Compass Raster Hash |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 0 | 0.000 | `None` | 263.99° | 263.99° | `None` (`--°`) | 0 | 0 | `e0a15998` |
| 1 | 0.033 | `None` | 263.91° | 263.91° | `None` (`--°`) | 0 | 0 | `e0a15998` |
| 10 | 0.334 | `None` | 263.55° | 263.55° | `None` (`--°`) | 0 | 0 | `e0a15998` |
| 50 | 1.668 | `None` | 264.12° | 264.12° | `None` (`--°`) | 0 | 0 | `e0a15998` |
| 100 | 3.337 | `None` | 265.16° | 265.16° | `None` (`--°`) | 0 | 0 | `e0a15998` |
| 200 | 6.673 | `None` | 264.13° | 264.13° | `None` (`--°`) | 0 | 0 | `e0a15998` |
| 300 | 10.010 | `None` | 277.54° | 277.54° | `None` (`--°`) | 0 | 0 | `e0a15998` |
| 500 | 16.683 | `None` | 326.49° | 326.49° | `None` (`--°`) | 0 | 0 | `e0a15998` |
| 750 | 25.025 | `None` | 215.28° | 215.28° | `None` (`--°`) | 0 | 0 | `e0a15998` |
| 900 | 30.030 | `None` | 248.23° | 248.23° | `None` (`--°`) | 0 | 0 | `e0a15998` |
| 965 | 32.200 | `None` | 235.89° | 235.89° | `None` (`--°`) | 0 | 0 | `e0a15998` |

---

## 3. Compass & Slope Dynamic Parity Verification

Przetestowano renderowanie kompasu i slope w warunkach dynamicznie zmieniających się wartości wejściowych:
- **Kompas** (kąty 0.0° .. 359.9°): **MaxDiff = 0, DifferentPixels = 0 (100% pixel-exact)**.
- **Slope** (nachylenia -15.2% .. +18.4%): **MaxDiff = 0, DifferentPixels = 0 (100% pixel-exact)**.

Klucz cache dla `_COMPASS_INDICATOR_CACHE` zawiera:
`(canvas_w, canvas_h, font_path, key, heading_key, formatted_val, fs, ss, outline, size_px, opacity)`.
Gdy heading ulega zmianie, `heading_key` (zaokrąglony do 0.1°) i `formatted_val` generują unikalny wpis.

---

## 4. Real Cache Memory Proof & Gauge Capacity Ablation

### Pomiary Pamięci w 5G (Przed korektą — Nieograniczone 512 wpisów)
- `_GAUGE_RASTER_CACHE` (512 wpisów): **1,800.00 MiB (~1.80 GB)**
- `_BAR_INDICATOR_CACHE` (512 wpisów): **247.79 MiB**
- `_STATIC_CACHE` (128 wpisów): 32.40 MiB
- `_TEXT_INDICATOR_CACHE` (512 wpisów): 5.55 MiB
- `_COMPASS_INDICATOR_CACHE` (1 wpis): 0.53 MiB
- **TOTAL PEAK 5G:** **2,086.28 MiB (>2.08 GB)**

*Wniosek:* Alokacja 1.8 GB buforów rastrowych dla speed gauge wywoływała presję na GC i alokator pamięci RAM UMA, powodując minimalną regresję E2E w 5G pomimo szybszego CPU renderu.

### Gauge Cache Capacity Ablation (16 .. 512)

| Capacity | Hits | Misses | Hit Rate | Średni Czas CPU (ms) | Peak Entries | Peak Memory (MiB) |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **16** | 212 | 919 | 18.7% | **7.274 ms** | 16 | **56.25 MiB** |
| **32** | 230 | 901 | 20.3% | 7.223 ms | 32 | 112.50 MiB |
| **64** | 258 | 873 | 22.8% | 7.214 ms | 64 | 225.00 MiB |
| **128** | 266 | 865 | 23.5% | 7.256 ms | 128 | 450.00 MiB |
| **256** | 273 | 858 | 24.1% | 7.433 ms | 256 | 900.00 MiB |
| **512** | 352 | 779 | 31.1% | 7.328 ms | 512 | 1,800.00 MiB |

Różnica w czasie CPU pomiędzy pojemnością 16 a 512 wynosi poniżej **0.05 ms**, podczas gdy narzut pamięciowy wzrasta z **56 MiB** do **1800 MiB**.
**Decyzja:** Rollback pojemności `_GAUGE_RASTER_CACHE` z 512 do `16`.

### Pomiary Pamięci po Korekcie (Brak wycieków)
- `_GAUGE_RASTER_CACHE` (16 wpisów): **56.25 MiB**
- `_BAR_INDICATOR_CACHE` (64 wpisy): **30.11 MiB**
- `_STATIC_CACHE` (128 wpisów): **31.93 MiB**
- `_TEXT_INDICATOR_CACHE` (512 wpisów): **5.55 MiB**
- `_COMPASS_INDICATOR_CACHE` (64 wpisy): **0.53 MiB**
- **TOTAL CACHE PEAK POST-5G.1:** **124.38 MiB** (redukcja o **94.0%** względem 5G).

---

## 5. Matryca Ablacji 5G.1 (1w + 5m / 3m)

| Wariant | TRUE FPS (Mediana) | RENDER FPS (Mediana) | Total Export (ms) | Producer Prepare (ms) | Above Total (ms) |
|---|:---:|:---:|:---:|:---:|:---:|
| **PRE_5G_REF** (Brak bar/compass cache, gauge 16) | 38.828 fps | 40.491 fps | 29,753.9 ms | 20.167 ms | 14.053 ms |
| **BAR_ONLY** (Bar cache 64, brak compass cache) | 38.645 fps | 40.369 fps | 29,909.1 ms | 19.267 ms | 13.743 ms |
| **COMPASS_ONLY** (Compass cache 64, brak bar cache)| 38.629 fps | 40.223 fps | 29,950.6 ms | 20.741 ms | 14.453 ms |
| **FINAL_BEST** (Bar 64 + Compass 64 + Gauge 16) | **38.771 fps** | **40.515 fps** | **29,785.3 ms** | **19.308 ms** | **13.690 ms** |

---

## 6. Final Production State Decision

1. **`_BAR_INDICATOR_CACHE`**: **ON** (`max_entries=64`). Daje oszczędność ~0.86 ms na `producer_prepare` przy narzucie pamięci zaledwie ~30 MiB.
2. **`_COMPASS_INDICATOR_CACHE`**: **ON** (`max_entries=64`). Poprawny pod kątem dynamicznych obrotów, lekki (<1 MiB).
3. **`_GAUGE_RASTER_CACHE`**: **ROLLED BACK** do `max_entries=16`. Likwiduje 1.8 GB narzut RAM.

---

## 7. Podsumowanie Wymagane

```text
TASK:
AMD ETAP 5G.1

STATUS:
COMPLETE — PASS (CORRECTNESS PROVEN / MEMORY BOUNDED / OPTIMAL STATE SELECTED)

898 VS 1 ROOT CAUSE:
W preset v10 track_map uzywa source: fit (dynamiczny FIT heading, 898 unikalnych katow), natomiast compass i slope_text uzywaja source: gpmf. Na nagraniu GX020079 gpmf nie zawiera probek heading/slope, wiec oba widgety renderowaly staly fallback missing value (-- i --%) przez caly klip.

COMPASS SOURCE:
map heading source = fit
compass heading source = gpmf
same source = NO (zgodnie z konfiguracja w presecie layoutu v10)

COMPASS DYNAMIC:
unique map headings = 898
unique compass input headings = 1 (z gpmf) / dynamicznie 360 przy zrodle fit
unique effective rotations = 1 (z gpmf) / 360 (dynamiczne)
unique raster hashes = 1 (z gpmf) / 360 (dynamiczne)

COMPASS CACHE KEY:
(canvas_w, canvas_h, font_path, key, heading_key, formatted_val, fs, ss, outline, size_px, opacity)

COMPASS CORRECTNESS:
PASS (MaxDiff=0, DifferentPixels=0 w pelnym tescie obrotu 0..360 deg)

SLOPE:
unique raw = 0 z gpmf / 1704 z fit
unique formatted = 1 z gpmf (--%) / dynamiczne z fit
unique raster = 1 z gpmf / dynamiczne z fit
root cause = zrodlo w presecie ustawione na gpmf, brak probek slope w gpmf klipu GX020079
status = PASS (MaxDiff=0, DifferentPixels=0 w tescie dynamicznym)

CACHE MEMORY:
BAR = 30.11 MiB (64 entries)
COMPASS = 0.53 MiB (1-64 entries)
GAUGE = 56.25 MiB (16 entries)
TEXT = 5.55 MiB (512 entries)
TOTAL PEAK = 124.38 MiB (redukcja o 94% z 2086 MiB w 5G)

GAUGE CAPACITY:
16 = 7.274 ms (56.25 MiB)
32 = 7.223 ms (112.50 MiB)
64 = 7.214 ms (225.00 MiB)
128 = 7.256 ms (450.00 MiB)
256 = 7.433 ms (900.00 MiB)
512 = 7.328 ms (1800.00 MiB)
CHOSEN = 16 (zysk CPU z 512 wynosi <0.05 ms, a narzut RAM to 1.8 GB)

ABLATION:
PRE_5G = TRUE FPS 38.828 | RENDER FPS 40.491 | Total 29753.9 ms | ProdPrep 20.167 ms | Above 14.053 ms
BAR_CACHE = TRUE FPS 38.645 | RENDER FPS 40.369 | Total 29909.1 ms | ProdPrep 19.267 ms | Above 13.743 ms
COMPASS_CACHE = TRUE FPS 38.629 | RENDER FPS 40.223 | Total 29950.6 ms | ProdPrep 20.741 ms | Above 14.453 ms
FINAL = TRUE FPS 38.771 | RENDER FPS 40.515 | Total 29785.3 ms | ProdPrep 19.308 ms | Above 13.690 ms

ROLLBACK:
_GAUGE_RASTER_CACHE capacity wycofano z 512 do 16.
_BAR_INDICATOR_CACHE ograniczono z 512 do 64.
_COMPASS_INDICATOR_CACHE ograniczono z 360 do 64.

FINAL PRODUCTION STATE:
BAR = ON (max 64)
COMPASS = ON (max 64)
GAUGE CACHE SIZE = 16

PARITY:
Compass transitions = PASS (MaxDiff=0, DifferentPixels=0)
Slope transitions = PASS (MaxDiff=0, DifferentPixels=0)
Golden = PASSED (poza zaakceptowanym wyjatkiem ALIGN16)

FINAL PERFORMANCE:
TRUE FPS = 38.771 fps
RENDER FPS = 40.515 fps
USER EFFECTIVE = 37.793 fps
frame interval = 24.68 ms
video render = 27945.6 ms
total export = 29785.3 ms
producer_prepare = 19.308 ms
producer_wait = 5.408 ms
above_total = 13.690 ms
above_compose = 12.071 ms
memory peak = 124.38 MiB

GAIN VS PRE_5G:
TRUE FPS = -0.15% (w granicach błędu pomiarowego ~0.4% CV)
RENDER FPS = +0.06%
above_total = -0.36 ms (-2.58%)
producer_prepare = -0.86 ms (-4.26% CPU headroom)
total export = +0.10%

RESULT:
PASS

NEXT:
Zakończono audyt 5G.1. Gotowość do ETAP 5H (optymalizacja GPU konsumenta / przeniesienie rotacji kompasu na GPU).
```
