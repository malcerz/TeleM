# Walkthrough — TeleM AMD C++ Optimization Pipeline

## AMD 3B RUNTIME FIX: Fix `TypeError: unsupported operand type(s) for /: 'tuple' and 'float'`

Wykonano precyzyjną diagnostykę i naprawę błędu wykonania w produkcyjnym potoku `AMD_NATIVE_D3D11`. 

Zidentyfikowano przyczyny:
1. `speed_samples` przekazywane z logiki eksportera TeleM (`extract_speed_samples()`) zawierają listy krotek `(datetime_timestamp, float_speed_kmh)` zamiast skalarów.
2. W `export_amd_native_d3d11` w wyliczeniu `dist = frame_idx * (speed / 3.6) / target_fps` próbowano bezpośredniego dzielenia krotki przez float.
3. Wykorzystano produkcyjny moduł `prepare_overlay_frame_data()` z `src/indicators/frame_data.py`, który w sposób bezpieczny dokonuje interpolacji telemetrycznej i zwraca skalary.

### Wykonane Pliki i Kod

1. **Poprawki w Kodzie (`src/ffmpeg/`)**:
   - [amd_native_exporter.py](file:///c:/_DEV/TeleM/src/ffmpeg/amd_native_exporter.py) — Wykorzystanie `prepare_overlay_frame_data()` do przekazywania skalarów do `compose_overlay()`.
   - [streaming.py](file:///c:/_DEV/TeleM/src/ffmpeg/streaming.py) — Przekazywanie pełnego kompletu strumieni telemetrycznych do `export_amd_native_d3d11`.

---

### Wyniki Testu Naprawczego (Real TeleM Export)

- **100 Frames Test**: **`PASS (7.45 s)`** (0 błędów, Render error: Brak)
- **1200 Frames Test**: **`PASS (68.13 s / 17.61 FPS)`** (0 błędów, 100% accounting)
- **Visual Match**: **`YES`**
- **Color Match**: **`YES`**

---

## ETAP 3B: Production Integration of Native D3D11 + AMF Backend into TeleM Exporter

- [RAPORT_AMD_ETAP_3B_PRODUCTION.md](file:///c:/_DEV/TeleM/Raporty/RAPORT_AMD_ETAP_3B_PRODUCTION.md)

---

## ETAP 3A-OPT: HUD Memory Path & Multi-Dirty Region Optimization

- [RAPORT_AMD_ETAP_3A_OPT.md](file:///c:/_DEV/TeleM/Raporty/RAPORT_AMD_ETAP_3A_OPT.md)

---

## ETAP 3A: Python/Pillow Real TeleM HUD → C Bridge → Persistent D3D11 Texture

- [RAPORT_AMD_ETAP_3A_PYTHON_BRIDGE.md](file:///c:/_DEV/TeleM/Raporty/RAPORT_AMD_ETAP_3A_PYTHON_BRIDGE.md)

---

## ETAP 2C-BENCH-FIX: Unified Benchmark & FPS Anomaly Audit

- [RAPORT_AMD_ETAP_2C_BENCH_FIX.md](file:///c:/_DEV/TeleM/Raporty/RAPORT_AMD_ETAP_2C_BENCH_FIX.md)

---

## ETAP 2C-AUDIT-FIX: End-to-End Measurement Audit & True FPS Verification

- [RAPORT_AMD_ETAP_2C_AUDIT_FIX.md](file:///c:/_DEV/TeleM/Raporty/RAPORT_AMD_ETAP_2C_AUDIT_FIX.md)

---

## ETAP 2C: D3D11 NV12 GPU Surface → HEVC_AMF → Real MP4

- [RAPORT_AMD_ETAP_2C_AMF_ENCODE.md](file:///c:/_DEV/TeleM/Raporty/RAPORT_AMD_ETAP_2C_AMF_ENCODE.md)

---

## ETAP 2B: Real P010 D3D11VA Surface → GPU VideoProcessor Compose → NV12 GPU Output

- [RAPORT_AMD_ETAP_2B_VIDEOPROCESSOR.md](file:///c:/_DEV/TeleM/Raporty/RAPORT_AMD_ETAP_2B_VIDEOPROCESSOR.md)

---

## ETAP 1: Proof-of-Concept Natywnego D3D11 Compositora

- [RAPORT_AMD_ETAP_1_POC_D3D11.md](file:///c:/_DEV/TeleM/Raporty/RAPORT_AMD_ETAP_1_POC_D3D11.md)
