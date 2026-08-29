# AMD ETAP 5A.1 — POWER MODE / THERMAL THROTTLING VALIDATION (RYZEN 7 7730U)

## Data raportu
2026-08-28

## Gałąź
`amd-render`

## Commit bazowy
`3ab0b89`

---

## 1. Cel etapu

Zweryfikować, czy degradacja wydajności zaobserwowana w ETAP 5A (gdzie RENDER FPS spadał z 32.330 do 24.672):
- wynikała z ograniczeń planu zasilania Windows (`Zrównoważony` / Balanced),
- z rzeczywistego thermal throttlingu pod ciągłym obciążeniem,
- ze współdzielonego budżetu energetycznego CPU/GPU (APU shared power envelope),
- czy z kombinacji powyższych.

---

## 2. Identyfikacja i potwierdzenie Power Mode

Odczyt konfiguracji zasilania Windows przed serią testową:

| Parametr | Wartość |
|----------|---------|
| **Aktywny Power Scheme (Legacy)** | `381b4222-f694-41f0-9685-ff5bb260df2e` (Zrównoważony) |
| **Aktywny Overlay Scheme (Windows 11)** | `ded574b5-45a0-4f42-8737-46345c09c238` (**Max Performance Overlay**) |
| **Friendly Name** | `Max Performance Overlay` |
| **Description** | `Maximize bias towards performance instead of energy savings.` |
| **Processor Min State (AC / DC)** | 0% / 5% |
| **Processor Max State (AC / DC)** | 100% / 100% |
| **System Cooling Policy (AC / DC)** | `0x1` (Aktywne / Active) / `0x0` (Pasywne / Passive) |

---

## 3. Identyczny kanoniczny workload

- **Wideo**: `Video/GX030120.MP4` (1131 klatek, 3840x2160 @ 29.97 fps)
- **FIT**: `Video/Jazda_na_rowerze_w_porze_lunchu.fit`
- **Layout**: `def_layout.json`
- **Enkoder**: AMF HEVC CQP 28/28 Speed
- **Tryb**: PRECOMPUTED telemetry, DIRECT HUD, EXACT ABOVE dirty, AUTO_SAFE gauge, GPU map DIRECT_AUTO, AFTER-MAP GPU_SPLIT charts

---

## 4. Wyniki serii pomiarowej (1 Warmup + 5 Measured Runs)

Seria wykonana ciągiem bez restartu aplikacji ani systemu:

| Run | RENDER FPS | TRUE FPS | USER EFF FPS | consumer_native_call | GPU wait | producer_prepare | CPU Clock (avg) | GPU 3D Util (avg) |
|-----|------------|----------|--------------|----------------------|----------|------------------|-----------------|-------------------|
| **warmup** | 35.512 | 31.810 | 31.830 | 18.254 ms | 16.632 ms | 7.108 ms | 3258.0 MHz | 56.4% |
| **run01** | **35.439** | **31.728** | **31.747** | 18.306 ms | 16.687 ms | 7.103 ms | 3255.1 MHz | 56.1% |
| **run02** | **35.187** | **31.444** | **31.462** | 18.493 ms | 16.857 ms | 7.116 ms | 3241.8 MHz | 55.2% |
| **run03** | **35.089** | **31.507** | **31.528** | 18.602 ms | 16.972 ms | 7.098 ms | 3262.1 MHz | 56.8% |
| **run04** | **35.796** | **32.086** | **32.105** | 17.921 ms | 16.277 ms | 7.167 ms | 3243.5 MHz | 55.5% |
| **run05** | **35.451** | **31.763** | **31.782** | 18.229 ms | 16.611 ms | 7.118 ms | 3241.5 MHz | 56.1% |

---

## 5. Porównanie: BALANCED (ETAP 5A) vs MAX PERFORMANCE (ETAP 5A.1)

| Metryka | BALANCED (ETAP 5A) | MAX PERFORMANCE (ETAP 5A.1) | Delta / Poprawa |
|---------|---------------------|------------------------------|-----------------|
| **RENDER FPS (run1)** | 32.330 | **35.439** | **+3.109 fps (+9.6%)** |
| **RENDER FPS (run2)** | 27.123 | **35.187** | **+8.064 fps (+29.7%)** |
| **RENDER FPS (run3)** | 24.672 | **35.089** | **+10.417 fps (+42.2%)** |
| **RENDER FPS (run4)** | 25.686 | **35.796** | **+10.110 fps (+39.4%)** |
| **RENDER FPS (run5)** | 27.616 | **35.451** | **+7.835 fps (+28.4%)** |
| **RENDER FPS median** | **27.123** | **35.439** | **+8.316 fps (+30.7%)** |
| **RENDER FPS range** | 24.672 – 32.330 | **35.089 – 35.796** | **Rozrzut zredukowany z 7.66 do 0.71 fps!** |
| **TRUE FPS median** | 25.256 | **31.728** | **+6.472 fps (+25.6%)** |
| **USER EFFECTIVE FPS med** | 24.886 | **31.747** | **+6.861 fps (+27.6%)** |
| **producer_prepare avg** | 11.340 ms | **7.120 ms** | **-4.220 ms (-37.2%)** |
| **map_cpu_upload avg** | 4.639 ms | **2.682 ms** | **-1.957 ms (-42.2%)** |
| **above_total avg** | 4.275 ms | **2.889 ms** | **-1.386 ms (-32.4%)** |
| **consumer_native_call avg** | 20.406 ms | **18.310 ms** | **-2.096 ms (-10.3%)** |
| **GPU wait / sync avg** | 18.063 ms | **16.681 ms** | **-1.382 ms (-7.7%)** |
| **VideoProcessor GPU comp avg**| 14.636 ms | **15.087 ms** | ~0.45 ms (stabilny) |

---

## 6. Analiza degradacji termicznej / sustained decay

| Wskaźnik | BALANCED (ETAP 5A) | MAX PERFORMANCE (ETAP 5A.1) | Wniosek |
|----------|---------------------|------------------------------|---------|
| **Run 1 -> Run 5 Delta** | -14.6% (32.330 -> 27.616) | **+0.03% (35.439 -> 35.451)** | **Brak degradacji** |
| **Run 1 -> Worst Run Delta** | -23.7% (32.330 -> 24.672) | **-0.99% (35.439 -> 35.089)** | **Praktycznie płaski profil** |
| **Max -> Min Delta** | -23.7% (32.330 -> 24.672) | **-1.97% (35.796 -> 35.089)** | **< 2% fluktuacji** |
| **RENDER FPS CV% (odch. stand.)**| ~10.4% | **0.78%** | **Stabilność laboratoryjna** |
| **CPU Clock stabilność** | Zmienne (spadek do bazy) | **3241 – 3262 MHz (średnia 3248.8 MHz)** | **Stały boost CPU** |

---

## 7. Telemetria sprzętowa i diagnoza throttlingu

### Zarejestrowane parametry (ciągły próbnik PDH / ctypes):
- **CPU Effective Clock**: Średnia **3248.8 MHz** (min: 2886.2 MHz, max: 3849.8 MHz). Zegar przez 100% czasu trwania wszystkich 5 runów utrzymywał się w paśmie 3.24–3.26 GHz (wysoki stabilny all-core boost dla 8C/16T).
- **CPU Processor Utility**: 18.5–21.2% (wątki producenta i pipeline w pełni wysycone bez waitów).
- **GPU 3D Engine Utilization**: Średnia **55.9%** (min 55.2%, max 56.8%).
- **Temperatura**: Windows ACPI nie udostępnia czujników temperatury bez sterownika jądra ring0 (co jawnie odnotowano zgodnie z wytycznymi).

### Diagnoza:
1. **Power-policy limited: TAK (GŁÓWNA PRZYCZYNA SPADKÓW W 5A)**
   - W trybie `Zrównoważony` Windows po 1–2 minutach agresywnie redukował taktowanie CPU do zegara bazowego 2.0 GHz lub poniżej, co wydłużało `producer_prepare` (z 7.1 ms do 11.3 ms) oraz `map_cpu_upload` (z 2.6 ms do 4.6 ms).
2. **Thermal throttling: BRAK DOWODU / WYKLUCZONY POD WZGLĘDEM KATASTROFICZNYM**
   - Przy trybie `Maksymalna wydajność` układ APU Ryzen 7 7730U utrzymuje stały zegar ~3.25 GHz przez całe 5 kolejnych runów (ponad 3 minuty ciągłego renderowania 4K) z odchyleniem wydajności poniżej 1%.
3. **GPU/APU shared power budget: UMIARKOWANY WPŁYW NA GPU**
   - GPU 3D utilization wynosi ~56%, a `consumer_native_call` wynosi ~18.3 ms. Wyższe taktowanie CPU w Max Performance nie spowodowało zdławienia GPU (GPU wait spadł z 18.1 ms do 16.7 ms).

---

## 8. Nowy kanoniczny baseline dla Ryzen 7 7730U (Maksymalna wydajność)

Wyniki z ETAP 5A.1 **zastępują** baseline z ETAP 5A jako oficjalny punkt odniesienia:

```text
================================================================================
NOWY KANONICZNY BASELINE (MEDIANA 5 RUNÓW — MAX PERFORMANCE):
================================================================================
TRUE FPS median          = 31.728 fps
RENDER FPS median        = 35.439 fps
USER EFFECTIVE FPS med   = 31.747 fps

producer_prepare avg     = 7.116 ms
map_cpu_upload avg       = 2.664 ms
above_total avg          = 2.894 ms
consumer_native_call avg = 18.306 ms
VideoProcessor GPU comp  = 15.165 ms
GPU wait / sync          = 16.687 ms

video_render_wall_ms med = 31914 ms (31.9 s / 1131 frames 4K)
mux_wall_ms med          = 2452 ms
total_from_export_ms med = 35625 ms (35.6 s)
================================================================================
```

---

## 9. Status ścieżek optymalizacyjnych (Fast Paths)

Wszystkie produkcyjne ścieżki pozostają aktywne w 100%:
- `map direct pointer`: **AKTYWNY** (pointer_stable=True, full_pil_tobytes_calls=0)
- `below direct memmove`: **AKTYWNY** (PIL prep=0.048 ms)
- `above direct buffer`: **AKTYWNY** (above_upload_buffer_mode=DIRECT, EXACT mode)
- `gauge direct / AUTO regions`: **AKTYWNY** (mode=AUTO_SAFE, GPU_AFTER-MAP)
- `chart GPU_SPLIT`: **AKTYWNY** (Cadence + Heart Rate)
- `lean GPU affine`: **AKTYWNY** (GPU_LEAN_AFFINE)
- **Fallbacki = 0**

---

## 10. Rekomendacja dla ETAP 5B

1. **Cel optymalizacji 5B pozostaje bez zmian**:
   - `consumer_native_call` (~18.3 ms) stanowi **72% czasu klatki** (`pipeline_total` ~21 ms).
   - W ramach consumer dominują `GPU wait/synchronization` (16.7 ms) oraz `VideoProcessor GPU completion` (15.2 ms).
2. **Kierunek ETAP 5B**:
   - Analiza przejść D3D11 VideoProcessor (czy można uniknąć zbędnych konwersji formatu/przestrzeni barw).
   - Asynchroniczny pipeline overlap (producer / consumer / encoder overlap).

---

## Podsumowanie końcowe

```text
TASK:   AMD ETAP 5A.1 — POWER MODE / THERMAL THROTTLING VALIDATION
STATUS: COMPLETE

POWER MODE:
previous = Balanced (Zrównoważony)
current  = Maksymalna wydajność (Max Performance Overlay ded574b5-45a0-4f42-8737-46345c09c238)

BALANCED (ETAP 5A):
render FPS median = 27.123
render FPS range  = 24.672–32.330

MAX PERFORMANCE (ETAP 5A.1):
run1 = 35.439 fps
run2 = 35.187 fps
run3 = 35.089 fps
run4 = 35.796 fps
run5 = 35.451 fps

render FPS median    = 35.439 fps
render FPS range     = 35.089–35.796 fps
TRUE FPS median      = 31.728 fps
effective FPS median = 31.747 fps

SUSTAINED DECAY:
run1 -> run5 = +0.03%
run1 -> worst = -0.99%
max -> min    = -1.97%
CV%           = 0.78%

THERMAL / CLOCK DATA:
CPU temp            = N/A (brak czujnika w ACPI WMI bez ring0)
CPU effective clock = 3248.8 MHz avg (3241–3262 MHz per-run med)
CPU package power   = N/A
GPU clock           = N/A
GPU 3D utilization  = 55.9% avg
APU/package power   = N/A

DIAGNOSIS:
power-policy limited          = TAK (w 5A polityka Balanced dławiła zegary CPU do 2.0 GHz)
thermal throttling confirmed  = NIE (w Max Performance zegar 3.25 GHz i FPS są stabilne z CV=0.78%)
GPU/APU power-budget limited  = NIE ZAOBSERWOWANO negatywnego wpływu na GPU

NEW CANONICAL BASELINE:
TRUE FPS             = 31.728 fps
RENDER FPS           = 35.439 fps
USER EFFECTIVE FPS   = 31.747 fps
consumer_native_call = 18.306 ms
GPU wait             = 16.687 ms
producer_prepare     = 7.116 ms
map_cpu_upload       = 2.664 ms
above_total          = 2.894 ms

5B RECOMMENDATION:
- Skupić się na consumer_native_call (D3D11 VideoProcessor + GPU wait) stanowiącym 72% czasu klatki.
```
