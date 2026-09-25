# RAPORT: PEŁNY STABILITY GATE POPRAWEK TELEMETRII (DATETIME, CURVPOWER, GPMF TIMELINE)

Data: 2026-09-16  
Gałąź: `amd-bikeridehud`  
Status: **CASE A — TELEMETRY FIXES STABLE IN PREVIEW AND EXPORT**

---

## 1. Cel i zakres bramki stabilności

Weryfikacja integralności całego potoku telemetrycznego po wdrożeniu trzech kluczowych poprawek:
1. **Datetime normalization & signature adapter** (`RAPORT_PREVIEW_TELEMETRY_DATETIME_CRITICAL_FIX.md`)
2. **Developer Field `curVPower` & presentation timeline** (`RAPORT_CURVPOWER_DEVELOPER_FIELD_FIX.md`)
3. **GPMF timeline projection dla `TMPC`, `ISO`, `SHUT`, `ACCL`, `GYRO`** oraz `PROCESSED_CACHE_VERSION=5` (`RAPORT_TEMP_BATTERY_TELEMETRY_FIX.md`)

Bramka potwierdza, że usunięcie sztucznego opóźnienia ~49.7 s oraz unifikacja osi czasu GPMF/FIT nie wprowadziły regresji w podglądzie (preview), synchronizacji mapy, wskaźnikach kąta pochylenia (lean/gyro), wskaźnikach aparatu (ISO/shutter), pamięci podręcznej (cache parity) ani w produkcyjnym eksporcie wideo D3D11 / AMF HEVC.

---

## 2. Podsumowanie wyników testów

### 2.1 TEST A — GX010298 Preview Evaluation
- **Zestaw:** `Video/GX010298.MP4` + `Video/GX010298.fit` + `Video/GX010298.layout.json`
- **Początek klipu:** `2026-09-16 04:30:22.390260 UTC` (lokalny `06:30:22`)
- **Punkty testowe:**
  - `06:30:22` (0.0s): `curVPower = 0 W`, `temp = 21.6 °C`, `GoPro BAT = 58.0%`, `Garmin BAT = 51.0%`, `HR = 90 bpm`, `CAD = --`, `speed = --`, `lean = 0.0°`
  - `06:30:26` (3.6s): `curVPower = 6 W`, `temp = 22.1 °C`, `GoPro BAT = 58.0%`, `Garmin BAT = 51.0%`, `HR = 91 bpm`, `CAD = 52 rpm`, `speed = 5.3 km/h`, `ISO = 1184`, `SHUT = 1/63`, `lean = -0.5°`
  - `06:30:30` (7.6s): `curVPower = 18 W`, `temp = 22.5 °C`, `GoPro BAT = 58.0%`, `Garmin BAT = 51.0%`, `HR = 93 bpm`, `CAD = 54 rpm`, `speed = 9.8 km/h`, `ISO = 1007`, `SHUT = 1/141`, `lean = 0.8°`
  - `06:31:07` (44.6s): `curVPower = 111 W`, `temp = 25.4 °C`, `GoPro BAT = 57.6%`, `Garmin BAT = 50.8%`, `HR = 98 bpm`, `CAD = 57 rpm`, `speed = 12.3 km/h`, `ISO = 495`, `SHUT = 1/124`, `lean = 1.2°`
  - `06:31:12` (49.6s): `curVPower = 0 W`, `temp = 25.6 °C`, `GoPro BAT = 57.5%`, `Garmin BAT = 50.8%`, `HR = 98 bpm`, `CAD = 0 rpm`, `speed = 10.1 km/h`, `ISO = 992`, `SHUT = 1/222`, `lean = -0.2°`
  - `06:31:20` (57.6s): `curVPower = 34 W`, `temp = 25.8 °C`, `GoPro BAT = 57.4%`, `Garmin BAT = 50.8%`, `HR = 97 bpm`, `CAD = 46 rpm`, `speed = 11.4 km/h`, `ISO = 837`, `SHUT = 1/198`, `lean = 0.4°`
- **Wynik:** **PASS** (0 tracebacks, brak sztucznego opóźnienia, 0 pustych `--` dla dostępnych danych).

### 2.2 TEST B — Cache MISS / HIT Parity (GX010298)
- Porównano świeży parse GPMF/FIT (Cache MISS) z deserializacją z `.telemetry.npz` (Cache HIT).
- Wszystkie wskaźniki (`temp`, `gopro_bat`, `garmin_bat`, `curvpower`, `hr`, `cad`, `iso`, `shut`, `speed`, `alt`, `lean`) posiadają identyczne wartości w każdym punkcie czasowym.
- **Wynik:** **PASS (EXACT MATCH)**.

### 2.3 TEST C — Kanoniczny GX020079 Preview
- **Zestaw:** `Video/GX020079.mp4` + `Video/GX020079.fit` + `def_layout.json`
- **Początek klipu:** `2026-08-05 04:55:50.800000 UTC`
- **Weryfikacja w punktach 0s, 1s, 5s, 9s:**
  - `0.0s`: `HR = 82 bpm`, `ALT = 73.8 m`, `TEMP = 37.6 °C`, `speed = --`, `PWR = 0 W`, `lean = 0.0°`
  - `1.0s`: `HR = 82 bpm`, `ALT = 73.8 m`, `TEMP = 37.6 °C`, `speed = --`, `PWR = 0 W`, `lean = 0.0°`
  - `5.0s`: `HR = 81 bpm`, `ALT = 73.8 m`, `TEMP = 37.6 °C`, `speed = 4.8 km/h`, `PWR = 7 W`, `lean = 0.0°`
  - `9.0s`: `HR = 81 bpm`, `ALT = 73.8 m`, `TEMP = 37.6 °C`, `speed = 5.6 km/h`, `PWR = 8 W`, `lean = 0.0°`
- **Wynik:** **PASS** (0 tracebacks, telemetria spójna, brak przesunięcia czasu).

### 2.4 TEST D — Real GUI Export GX020079 (AMD Native Pipeline)
- **Konfiguracja produkcyjna:**
  - `AMD_QUEUE_DEPTH=2`
  - `AMD_CPU_GPU_PIPELINE=ASYNC`
  - `AMD_VP_PROCESSOR_RING_SIZE=1`
  - `AMD_ABOVE_BATCHED=0`
  - `AMD_AFTER_MAP_ALT_VISUAL_GPU=0`
  - `AMD_CPU_WIDGET_CACHE=0`
- **Ścieżka:** `BikeRideHUD.py` -> `MainWindow` -> `RenderTab` -> `AMD Child Process` -> `telem_amd_native.dll` -> `AMF HEVC`
- **Format:** 3840x2160 @ 29.97 fps, 300 klatek (10.0 s).
- **Statystyki wykonania:**
  - Klatki: `300 / 300` klatek (100.0%)
  - Porzucone klatki: `0`
  - Błędy D3D11: `0`
  - Błędy AMF: `0`
  - Kod zakończenia potomka: `0`
  - Całkowity czas potoku: `6.72 s` (`44.62 RENDER FPS`, `37.74 TRUE FPS`)
- **Wynik:** **PASS**.

### 2.5 TEST E — GPMF Timeline Sanity (GX010298)
- Video clip start: `2026-09-16 04:30:22.390260 UTC`
- Doc1 TMPC timestamp: `2026-09-16 04:30:22.353255 UTC` (różnica: `-37.0 ms`)
- Doc1 ISO timestamp: `2026-09-16 04:30:22.353255 UTC` (różnica: `-37.0 ms`)
- Doc1 SHUT timestamp: `2026-09-16 04:30:22.353255 UTC` (różnica: `-37.0 ms`)
- First ACCL timestamp: `2026-09-16 04:30:22.353255 UTC` (różnica: `-37.0 ms`)
- First GYRO timestamp: `2026-09-16 04:30:22.353255 UTC` (różnica: `-37.0 ms`)
- First GPS anchor timestamp: `2026-09-16 04:31:12.000000 UTC`
- Projected stream start: `2026-09-16 04:30:22.353255 UTC`
- **Wniosek:** Wszystkie strumienie GPMF startują natychmiast z początkiem materiału wideo, bez sztucznego opóźnienia do pierwszego GPS FIX (~49.7 s).
- **Wynik:** **PASS**.

---

## 3. Visual Proof

Z wyeksportowanego pliku MP4 `scratch/telemetry_stability_gate/gx020079_10s_export.mp4` wyciągnięto klatki:
- `frame 0` (t=0.00s)
- `frame 50` (t=1.67s)
- `frame 150` (t=5.01s)
- `frame 250` (t=8.34s)
- `frame 299` (t=9.98s)

oraz wygenerowano arkusz podglądu `scratch/telemetry_stability_gate/contact_sheet.png`.

Weryfikacja elementów:
- **Track-Up Map:** Poprawna rotacja mapy i pozycja znacznika GPS w lewym górnym rogu.
- **Speed Gauge:** Płynny ruch wskazówki i wartości cyfrowej (0 -> 4.8 -> 5.4 -> 6.9 km/h).
- **Moc (curVPower):** Poprawny render cyfrowy (0 W -> 7 W -> 8 W -> 11 W).
- **Wykresy i wskaźniki HR / Cadence:** Spójny render AFTER-MAP bez ghostingu.
- **Pasek i podziałka wysokości (Altitude Ruler):** Stabilne 73.80 m.
- **Bateria Garmin / Solar:** Spójne segmenty i stan naładowania (67.00% -> 66.98%).
- **Bateria GoPro / Temperatura:** `BAT: 90.0% -> 89.9%`, `GP: 37.6°C`.
- **Ekspozycja i ISO:** Dynamiczne wartości aparatu (`EXP: 1/581 -> 1/249`, `ISO: 109 -> 94`).

---

## 4. Wymagane Metryki Końcowe

```text
GX010298_PREVIEW=PASS
GX020079_PREVIEW=PASS

CACHE_MISS_STATUS=PASS
CACHE_HIT_STATUS=PASS
CACHE_PARITY=EXACT_MATCH

GPMF_TIMELINE_STATUS=PASS

TRACEBACK_COUNT=0
DATETIME_ERRORS=0
CALLBACK_ERRORS=0

EXPORT_FRAMES=300/300
EXPORT_DROPPED=0
AMF_ERRORS=0
D3D11_ERRORS=0
CHILD_EXITCODE=0

VISUAL_PROOF_FRAMES=0, 50, 150, 250, 299
USER_VISUAL_ACCEPTANCE=PENDING

CASE=CASE A — TELEMETRY FIXES STABLE IN PREVIEW AND EXPORT
```
