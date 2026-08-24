# RAPORT — Audyt IMU GoPro + rzeczywisty kąt przechyłu Lean

**Etap:** 13 (IMU AUDIT + REAL ROLL ANGLE)
**Data:** 2026-08-23
**Baseline:** ETAP 12 (`RAPORT_INDICATORS_ETAP_12_SLOPE_LEAN_UPORZADKOWANIE.md`).
**Zakres:** audyt danych IMU GoPro, fizycznie poprawny kąt przechyłu (complementary filter + precompute deterministyczny), kalibracja montażu (offset/invert), sensitivity na kącie, clamp, FIT grade przez `atan`, uczciwe nazewnictwo (deg/s ≠ deg), diagnostyka. **Bez zmian** pipeline'ów AMD/NVIDIA/Intel, FFmpeg, SmartSync, map, BAR/Ruler.

---

## 1. Jakie strumienie IMU GoPro znaleziono

Audyt parsera GPMF (`src/telemetry_gpmf_new.py` — to on generuje JSON używany w runtime przez `gpmf_to_exiftool_json`) i ekstrakcji (`src/telemetry_extract.py`):

| Stream | Osie | Jednostka | Sampling | Parser | Dostępny runtime? |
|---|---|---|---|---|---|
| `GYRO` | X/Y/Z (kanoniczne) | **rad/s** | ~200 Hz, realne STMP/TSMP | `_extract_gpmf_vector_samples` | **TAK** (`gyro_x/y/z_samples`) |
| `ACCL` | X/Y/Z (kanoniczne) | **m/s²** | ~200 Hz, realne STMP/TSMP | `_extract_gpmf_vector_samples` | **TAK** (`accel_x/y/z_samples`) |
| `GRAV` / `CORI` / `IORI` / `MAGN` / quaternion | — | — | — | `telemetry_gpmf_new` umie je dekodować | **BRAK w JSON runtime** (nie ma ich w danych testowych) |
| GPS-derived orientation | — | — | — | `heading` | TAK (heading, nie roll) |

Wniosek: TeleM ma **ACCL + GYRO** (pełne wektory 3-osiowe z timestampami). **Brak gotowej orientacji/quaternionu/wektora grawitacji** w danych — roll trzeba wyliczyć samodzielnie.

## 2. Jednostki i częstotliwość

- **ACCL: m/s².** Empirycznie (realne `GX010115`): `|accel| ≈ 8.96`, a ~8.9 na jednej osi (wektor grawitacji).
- **GYRO: rad/s.** Empirycznie: maks. ~0.42 rad/s podczas spokojnej jazdy (gdyby to były deg/s, byłyby śmiesznie małe).
- **Częstotliwość:** ~117 728 próbek na strumień w ~9,8 min klipu (~200 Hz). Timestampy są **realne** (STMP/TSMP), nie zakładane z FPS filmu.

## 3. Układ osi

- GPMF zgłasza surową kolejność **ZXY**; parser przestawia na kanoniczne **XYZ** (`vector = [v[1], v[2], v[0]]`).
- Empirycznie: po reordery grawitacja ląduje na **kanonicznej osi Z** (~ -8.9 m/s²) dla testowego montażu → **oś Z = „góra"**.
- Dlatego sensownymi osiami przechyłu (roll) dla tego montażu są **X i Y** (grawitacja przemieszcza się między Z a osią boczną). Oś Z (== oś grawitacji) jest zdegenerowana dla accel (nie mierzy roll wokół własnej osi).
- `compute_roll_timeline` **automatycznie wykrywa oś „góra"** (`_detect_up_axis`, oś o największej średniej |grawitacji|) — wzory accel są poprawne niezależnie od montażu.

## 4. Czy istnieje gotowa orientacja / quaternion / gravity

**Nie w danych runtime.** `telemetry_gpmf_new` potrafi dekodować GRAV/CORI/IORI/MAGN, ale te strumienie **nie występują w pliku testowym** (`GX010115.json`) — JSON zawiera wyłącznie ACCL i GYRO (obok GPS/kamery). Brak więc gotowego kąta przechyłu GoPro → konieczny własny filtr.

## 5. Dlaczego algorytm z ETAP 12 był fizycznie niepoprawny

ETAP 12 robił:
```
GYRO raw [rad/s] * 180/π  →  °  → sensitivity  →  clamp  →  obrót
```
`rad/s × 180/π` to **deg/s — prędkość kątowa**, nie kąt. Przedstawianie tego jako „roll angle [°]" było błędem. Wartość 1 rad/s * 180/π = 57,3 **na sekundę**, a nie kąt 57,3°.

## 6. Jak teraz liczony jest rzeczywisty roll

```
GPMF ACCL [m/s²] + GPMF GYRO [rad/s]
      ↓ complementary filter (src.telemetry_imu)
precompute: timestamp → fused roll [deg]   (deterministyczny timeline)
      ↓ interpolate_roll(frame_ts)
roll_angle_deg
      ↓ lean_visual_angle:
      roll - zero_offset → invert → sensitivity → clamp ±max_angle
      ↓ obrót grafiki + odczyt [°]
```
Roll jest **prekomputowany raz** dla materiału i tylko interpolowany na klatkę.

## 7. Jak liczony jest accel roll

- Z wektora grawitacji: `roll_acc = atan2(lateral, -up)` w stopniach, gdzie `up` = oś niosąca grawitację (auto-detekcja), `lateral` = oś prostopadła nie będąca osią „góra".
- Gdy oś przechyłu == oś „góra" (degen.): używana jest udokumentowana konwencja `atan2(perp_b, -perp_a)` (słaba referencja accel — dominuje gyro).
- Zweryfikowane testem: znany przechył 10° → `accel_roll ≈ 10°`.

## 8. Jak działa integracja gyro

```
gyro_rate_deg_s = gyro[roll_axis] * 180/π
roll += gyro_rate_deg_s * dt
```
`dt` bierze się z **realnych timestampów IMU** (różnica próbek), nie z FPS filmu. Przerwy `dt > max_gap_s (0.5 s)` nie są integrowane bezkrytycznie (TEST 15).

## 9. Jak działa sensor fusion

Complementary filter:
```
roll = alpha * (roll_prev + gyro_rate_deg_s*dt) + (1-alpha) * accel_roll
```
`alpha` domyślnie 0.98 (gyro odpowiada za dynamikę, accel koryguje dryf). Parametr techniczny (nie wystawiany w GUI). Deterministyczny: ta sama tablica próbek → ten sam timeline (czysta funkcja).

## 10. Jak rozwiązano drift

- Dryf integracji gyro koryguje **accel** przez `(1-alpha) * accel_roll`.
- TEST: stały bias gyro 0.05 rad/s (bez korekcji dałby ~11.5° dryfu) przy stabilnym accel → filtr trzyma kąt < 3°.
- Przy braku accel (tylko gyro) — uczciwie: integracja od zera, dryf możliwy (opisane w ograniczeniach).

## 11. Jak rozwiązano przyspieszenia dynamiczne

- Filtr komplementarny waży gyro dla krótkoterminowej dynamiki, a accel tylko jako wolna korekta — więc boczne przyspieszenie w zakręcie nie „wywraca" natychmiast kąta.
- **Ograniczenie (opisane uczciwie):** w długim, stałym zakręcie przyspieszenie boczne może biasować accel_roll; nie jest to idealny pomiar lean (bez fuzji z GPS/heading). Użytkownik ma offset/invert do kalibracji.

## 12. Jak działa precompute timeline

- `compute_roll_timeline(accel, gyro, roll_axis, alpha, max_gap_s)` → `[(timestamp, roll_deg)]`, liczone **raz** z pełnych tablic próbek.
- Buforowane per oś: GUI (`TelemetryDataManager._lean_roll_cache`) i worker finalny (`WORKER_CACHE["_lean_roll"]`).
- Fuzja jest czystą funkcją (bez stanu globalnego między klatkami).

## 13. Jak zapewniono seek determinism

- Wartość lean dla chwili `t` = `interpolate_roll(precomputed_timeline, t)` — **funkcja samego timestampu**, nie poprzedniej klatki.
- Seek do przodu/tyłu, świeża sesja zaczynająca od `t`, final/random-access render — **ten sam wynik** (TEST 6).
- Preview i final używają tej samej ścieżki rozwiązywania `lean_roll_{axis}` (manager / worker_cache) → ten sam timeline.

## 14. Jak działa offset

`zero_offset_deg` (GUI: „Offset zerowy [°]"): `visual = roll - zero_offset`. Domyślnie 0.0; użytkownik kalibruje montaż (np. kamera zamontowana lekko przekrzywiona).

## 15. Jak działa invert

`invert_axis` (bool, „Odwróć kierunek"): `visual = -visual`. Poprawia „skręt w lewo → grafika w prawo" bez zmiany parsera/osi.

## 16. Jak działa sensitivity

- Działa **na wyliczonym kącie fizycznym**: `visual = roll * sensitivity` (po offset/invert).
- Domyślnie **1.0** → 1° realnego roll = 1° obrotu grafiki. Użytkownik może wzmocnić (2.0, 3.0) lub osłabić.

## 17. Jak działa clamp

`max_angle` („Maks. kąt wychyłu [°]", domyślnie 30°): clamp **po** roll → offset → invert → sensitivity. Grafika nigdy nie obraca się dalej niż ±max_angle.

## 18. Jak poprawiono FIT grade % → °

```
angle_deg = degrees(atan(grade_percent / 100.0))
```
- 5% → ~2.86°, 10% → ~5.71°, 20% → ~11.31° (NIE 1:1 jak w ETAP 12).
- GUI nadal jasno oznacza źródło jako „FIT Grade / nachylenie terenu" (nie przechył roweru).

## 19. Jakie pliki / funkcje zmieniono

| Plik | Zmiana |
|---|---|
| `src/telemetry_imu.py` (NOWY) | `gyro_rate_deg_s`, `accel_roll_deg` (z auto-detekcją `_detect_up_axis`), `grade_to_angle_deg`, `compute_roll_timeline` (complementary filter, precompute), `interpolate_roll`, `merge_axis_samples`, `lean_diagnostic` (debug). |
| `src/gui/telemetry_manager.py` | `_get_lean_roll_samples(axis)` (cache timeline), `resolve_value` obsługuje `lean_roll_{axis}`, `_lean_roll_cache`, wywołanie `lean_diagnostic`. |
| `src/ffmpeg/worker_cache.py` | `_worker_lean_roll(axis)` (final path), `_resolve_cache_value` obsługuje `lean_roll_{axis}`. |
| `src/indicators/frame_data.py` | lean_indicator: źródło IMU rozwiązuje `lean_roll_{axis}` (prekomputowany roll, jednostka °) zamiast surowego `gyro_{axis}`. |
| `src/indicators/lean.py` | `lean_visual_angle` (offset→invert→sensitivity→clamp), `lean_angle` interpretuje źródło (grade przez atan; IMU = roll prekomputowany), domyślne max_angle 30°. |
| `src/gui/qt/models.py` | schema lean: `zero_offset`, `invert_axis`, `sensitivity=1.0`, `max_angle=30.0`, domyślna oś `x`, etykieta źródła „IMU GoPro (żyroskop + akcelerometr)". |
| `src/gui/qt/_mixins/indicator_mixin.py` | defaulty tworzenia lean (oś x, offset 0, invert False, sensitivity 1.0, max_angle 30). |
| `tests/test_lean_indicator_contract.py` | aktualizacja TEST 4 (nowa fizyka), TEST 3 (pole `lean_roll_*`), TEST 8 (etykiety). |
| `tests/test_lean_imu_contract.py` (NOWY) | TEST 1–15. |

## 20. Jakie testy dodano

`tests/test_lean_imu_contract.py` (15 testów):
- **TEST 1** — gyro = deg/s (prędkość), nie kąt.
- **TEST 2** — integracja: 1 rad/s × 0.1 s → ~5.73° na próbkę.
- **TEST 3** — zero gyro + stabilny accel → brak dryfu.
- **TEST 4** — accel roll dla znanego 10° → ~10°.
- **TEST 5** — complementary filter koryguje dryf gyro.
- **TEST 6** — seek determinism (ten sam timestamp → ten sam roll; czysta funkcja).
- **TEST 7** — preview/final parity (manager & worker ten sam roll; widget identyczny).
- **TEST 8** — invert: +10° → -10°.
- **TEST 9** — offset: 12° - 2° → 10°.
- **TEST 10** — sensitivity: 10° × 1.5 → 15°.
- **TEST 11** — clamp: 40° → ±20°.
- **TEST 12** — FIT grade: 10% → ~5.71° (nie 10°).
- **TEST 13** — brak accel → gyro-only (bez crasha, dryf opisany).
- **TEST 14** — brak gyro → accel-only (bez crasha).
- **TEST 15** — duża luka czasowa nie daje gigantycznego skoku kąta.

## 21. Wyniki testów

- Nowe `test_lean_imu_contract.py` (15) + zaktualizowany `test_lean_indicator_contract.py` (16) → **31 passed**.
- Zestaw dotkniętych (lean, orientation, slope, tick, distance, parity, telemetry, fit_gui itd.) → **269 passed**.
- **Pełny test suite** → **954 passed, 17 skipped, 9 failed**.
- **9 failures = wszystkie pre-existing** (identyczne jak w ETAP 11B/12, potwierdzone stash-em): `test_amd_native_etap5b`, `test_etap5e1` (2), `test_etap5e3`, `test_etap8m7`, `test_etap8q`, `test_etap8s`, `test_etap8t_b`, `test_static_indicator_cache::test_slope_dynamic_marker_and_static_style_miss`.
- `get_errors` na zmienionych plikach → brak błędów.

## 22. Czy preview/final mają parity

**Tak — potwierdzone runtime i testem.** Oba przechodzą przez tę samą ścieżkę `prepare_overlay_frame_data → compose_overlay`; `lean_roll_{axis}` jest rozwiązywany identycznie w GUI (`TelemetryDataManager`) i workerze finalnym (`worker_cache`) z tych samych próbek → ten sam prekomputowany timeline → ten sam kąt. Smoke na realnych danych: FINAL i PREVIEW mają identyczny bbox i raster wskaźnika; TEST 7 blokuje parity.

## 23. Czy dotknięto AMD/NVIDIA/Intel

**Nie.** Pipeline'y AMD/NVIDIA/Intel, FFmpeg, SmartSync, mapy, BAR/Ruler — nietknięte. Zmiany są w: nowym module telemetry_imu, wspólnych ścieżkach rozwiązywania (telemetry_manager, worker_cache — używane przez wszystkie backendy przez `compose_overlay`) i wskaźniku lean. NVIDIA path preserved statically; runtime NVIDIA nie był możliwy na tej maszynie (AMD).

## 24. Jakie ograniczenia nadal pozostają

- **Lean to roll z fuzji ACCL+GYRO**, nie ground-truth. W długim, stałym zakręcie boczne przyspieszenie może biasować accel_roll (człon `(1-alpha)`); bez fuzji z GPS/heading nie jest to idealny pomiar lean.
- **Oś przechyłu zależy od montażu** — dla testowego materiału (grawitacja na Z) sensowne są X/Y; użytkownik wybiera oś i kalibruje offset/invert.
- **Brak accel → gyro-only** (dryf możliwy, uczciwie opisany); **brak gyro → accel-only** (szum).
- **Brak multi-video/chapters** — timeline jest budowany dla pojedynczego materiału; architektura używa absolutnych timestampów GPMF (nie sekund od początku jednego MP4), więc jest gotowa na przyszłe scalanie.
- **Smoothing (EMA)** nie dodany — filtr komplementarny już wygładza; ewentualny EMA można dodać później bez maskowania fizyki.
- **Kalibracja**: fizyczny kąt bezwzględny wymaga ustawienia `zero_offset` dla montażu (kamera może być lekko przekrzywiona).

## 25. Co sprawdzić ręcznie na realnym materiale GoPro

1. Dodaj `Przechył` → ustaw **Źródło: IMU GoPro**, **Oś przechyłu: X** (dla testowego montażu), Sensitivity 1.0, Max. kąt 30.
2. Podczas jazdy po zakrętach grafika (rower) powinna wychylać się w granicach ~±10–20° zgodnie z przechyłem; odczyt w ° pod grafiką.
3. Przetestuj pozostałe osie (Y, Z) — wybierz tę, która daje naturalny ruch (zależne od montażu).
4. Jeśli skręt w lewo daje wychył w prawo → włącz **Odwróć kierunek**.
5. Jeśli kamera zamontowana lekko przekrzywiona → ustaw **Offset zerowy** tak, by na prostej było ~0°.
6. Mnożnik > 1 wzmacnia ruch; Max. kąt ogranicza maksymalny wychył (clamp).
7. **Seek**: przeskocz w różne miejsca timeline — kąt jest identyczny jak przy odtwarzaniu sekwencyjnym w tej samej chwili.
8. **Preview vs Render**: dla tej samej chwili grafika w tym samym położeniu.
9. Źródło **FIT Grade** → grafika pokazuje kąt nachylenia terenu (np. 10% → ~5.7°), wyraźnie inny od przechyłu.
10. Diagnostyka: ustaw `TELEM_LEAN_DEBUG=1` i obejrzyj log `LEAN IMU: ...` (gyro_raw, gyro_deg_s, accel, accel_roll, fused_roll, offset, inverted, sensitivity, final_angle) — bez zaśmiecania GUI.

---

## Podsumowanie (AGENTS.md)

### Changed
`src/telemetry_imu.py` (nowy — complementary filter, precompute, diagnostyka), `telemetry_manager.py` (lean_roll + cache), `worker_cache.py` (lean_roll final), `frame_data.py` (rozwiązywanie lean_roll), `lean.py` (lean_visual_angle: offset/invert/sensitivity/clamp; grade przez atan), `models.py` + `indicator_mixin.py` (GUI: zero_offset, invert_axis, sensitivity 1.0, max_angle 30, oś x), aktualizacja `test_lean_indicator_contract.py`, nowy `test_lean_imu_contract.py`.

### Preserved
- Architektura ETAP 12 (osobny wskaźnik `Przechył`, wybór osi, grafika obracana, preview/final parity, compat legacy).
- BAR/Ruler, pipeline'y AMD/NVIDIA/Intel, FFmpeg, SmartSync, mapy — bez zmian.
- `wzor/rower_ico.png` — nietknięty (używany jako grafika Lean).

### Tested
31 (lean) + 269 (dotknięte) + pełny suite 954 passed / 17 skipped. 9 failures — wszystkie pre-existing. Smoke real-data: roll w granicach ~3–10° (sensowne kąty przechyłu), preview==final, seek deterministyczny.

### Not tested
- Runtime GPU (AMD/NVIDIA/Intel) eksportu — ścieżka wspólna, nie uruchamiana. NVIDIA preserved statically.

### Risks / Remaining issues
- Opisane w pkt. 24 (bias przy długich zakrętach, zależność od montażu, fallbacki gyro/accel-only, brak multi-video, wymagana kalibracja offset).
- Pre-existing failures: 9 (lista w pkt. 21).
