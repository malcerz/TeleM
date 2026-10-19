# Intel QSV HEVC Main10 HLG — odczyt QP podczas eksportu

Data: 2026-10-17 · Sprzęt: Intel Core i7-1265U, natywny potok D3D11/QSV · Materiał: `C:\GoPro\GX010378.MP4` · Bitrate: 40M VBR

## 1. Przyczyna braku QP w HEVC

- Enkoder Intel HEVC zapisuje w każdym slice `init_qp_minus26 = 0` oraz `slice_qp_delta = 0` (SliceQpY = 26 zawsze), a całą regulację kwantyzacji realizuje przez `cu_qp_delta_enabled_flag = 1` (`diff_cu_qp_delta_depth = 3`), czyli delty QP kodowane w CABAC na poziomie jednostek kodowania. Potwierdzone niezależnie przez FFmpeg `trace_headers` (`trace_fast_headers.log`).
- `mfxExtAVCEncodedFrameInfo.QP` jest podpięty poprawnie (bufor na `mfxBitstream`, Query = `MFX_ERR_NONE`), ale zwracane wartości są niewiarygodne:
  - przez pierwsze ~60 klatek 28–31, potem głównie 0–3 (to były obserwowane „0–2”);
  - klatki 50→51 i 58→59 mają prawie identyczny rozmiar (~155–172 KB), a raportowany QP skacze 31↔0 — rzeczywisty spadek QP o ~30 zwielokrotniłby bitrate;
  - `FrameOrder` = 0 dla każdej klatki (prawdopodobnie echo niewypełnionego `FrameOrder` wejścia), więc nie pomaga w przypisaniu.
  - Wniosek: to nie błąd synchronizacji ani podpięcia buforów po naszej stronie — wartości są sprzeczne ze strumieniem. Nie udowodniono, że to błąd sterownika; przyczyna po stronie runtime pozostaje nieustalona.
- `mfxExtEncodeStatsOutput` (udokumentowane, eksperymentalne; zawiera średni QP klatki): Query zwraca `MFX_ERR_UNSUPPORTED` (-3) na tym runtime.

## 2. Faktyczne źródło danych QP

Natywny parser nagłówków HEVC (VPS/SPS/PPS + `slice_segment_header` do `slice_qp_delta`) działający w wątku drain na skompresowanym bitstreamie, który jest już w pamięci systemowej po `SyncOperation`. Brak dekodowania, brak dostępu do GPU, brak nowego punktu synchronizacji, brak kolejek i procesów.

## 3. Poziom metryki

**Slice** — `Slice QP` = SliceQpY (bazowy QP slice, domena natywna, bez QpBdOffset). Przy wielu slice'ach klatka jest ważona liczbą CTU; tutaj 1 slice na klatkę. QP CU / średni QP klatki: `--` z przyczyną (`quant_reason`). Pola klasyczne (`avg_qp`, `quant_*`) dla HEVC pozostają `None`.

## 4. Dowód wiarygodności

- Niezależny analizator `src/qp_analyzer.py` na wszystkich 6 plikach wyjściowych z telemetrią: avg/min/max = 26/26/26, `SLICE_ONLY` — zgodne z odczytem natywnym.
- 0 błędów parsowania w 600 klatkach na przebieg.
- Cross-check oneVPL vs Slice QP (Fast): 600 raportów, 0 zgodnych, 503 niezgodne, 97 zer.

## 5. Wyniki QP dla presetów

| Preset | Slice QP bieżący / średni / min / max | QP CU |
|---|---|---|
| Fast | 26.0 / 26.0 / 26 / 26 | `--` |
| Balanced | 26.0 / 26.0 / 26 / 26 | `--` |
| Quality | 26.0 / 26.0 / 26 / 26 | `--` |

Wartość 26 jest stałą zapisywaną przez enkoder, nie miarą jakości.

## 6. Narzut wydajnościowy (A/B, 600 klatek, kolejność ABBA)

| Preset | Telemetria ON (FPS) | Telemetria OFF (FPS) | Odniesienie użytkownika |
|---|---|---|---|
| Fast | 52.8 / 49.1 | 53.2 / 51.9 | ~55 |
| Balanced | 28.0 / 27.2 | 22.1 / 22.8 | ~35 |
| Quality | 15.3 / 13.5 | 15.2 / 14.6 | ~15 |

Parser: 130–320 µs/klatkę w wątku drain (poza ścieżką renderowania). Różnice ON/OFF w granicach szumu. Balanced odbiega od pomiaru użytkownika (22–28 vs ~35) w obu wariantach jednakowo — nie traktuję tego jako regresji wynikającej z telemetrii (temperatura/obciążenie; nie zbadane).

Pełny QP per CU wymagałby pełnego dekodowania entropijnego CABAC. Jednowątkowy programowy dekoder HEVC na wyjściu: ~7 FPS; szacunkowo sam parser składni wymagałby 2–3 rdzeni przy 55 FPS (szacunek, niezmierzony). Niezaimplementowane — wymaga akceptacji.

## 7. Wyniki harnessu

- `tools/run_intel_hevc_qp_ab.py`: 12/12 przebiegów OK, natywna ścieżka, bez fallbacku do FFmpeg (wyniki: `ab/summary.json`, logi `ab/*.log`).
- Pierwszy przebieg A/B wykrył błąd (oznaczenie `compression_active=True` przy pustych polach QP powodowało wyjątek w `_report_stream_progress` i fallback do FFmpeg) — naprawione, pełny przebieg powtórzony.
- Smoke test produkcyjnej DLL (120 klatek, Fast): OK, natywna ścieżka.
- Testy jednostkowe Intel: 124 zaliczone; 3 niezaliczone niezwiązane (2 — brak `pytest.warns` w zastępczym stubie, bo pytest nie jest zainstalowany; 1 — AV1 QSV niedostępne na tym CPU).

## 8. Zmienione pliki

- `src/native/d3d11_intel_pipeline/telem_intel_native.c` — parser Slice QP, eksport `intel_native_get_hevc_slice_qp`, cross-check oneVPL, diagnostyczne Query encode-stats.
- `src/ffmpeg/intel_native_exporter.py` — odczyt statystyk, pola `slice_qp_*`, tekst GUI.
- `tests/test_intel_vbr_control.py` — 2 nowe testy.
- `tools/run_intel_hevc_qp_ab.py` — nowy harness A/B.
- `runtime/intel/bin/telem_intel_native.dll` — nowa wersja (kopia poprzedniej: `telem_intel_native.dll.bak_pre_hevc_slice_qp`).

Nie zmieniono: VBR/TargetKbps/MaxKbps/VBV/HRD, presetów, GOP/B-frames/lookahead, potoku D3D11, kompozytora HUD, pochylenia mapy, backendów AMD/NVIDIA, live mux audio.
