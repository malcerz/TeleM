# Intel QSV HEVC Main10 HLG — wdrożenie Slice QP

Data: 2026-10-17 · i7-1265U, natywny potok D3D11/QSV · `C:\GoPro\GX010378.MP4` · 40M VBR (TU 7/4/1, VBV/HRD bez zmian)
Poprzedni audyt: `Raporty/RAPORT_INTEL_HEVC_QP_AUDYT_20261017.md`. Surowe dane: `Raporty/intel_hevc_qp_20261017/`.

## 0. Weryfikacja oneVPL (krótko)

Ograniczenie nadal występuje. `mfxExtAVCEncodedFrameInfo.QP` w porównaniu z bitstreamem w każdym presecie (600 klatek): 0 zgodnych, 489–503 niezgodnych, 97–111 zer. `mfxExtEncodeStatsOutput` (średni QP klatki): `MFX_ERR_UNSUPPORTED`. Średni QP klatki nie jest dostępny, więc wdrożono Slice QP.

## 1. Zaimplementowana metoda

Natywny parser w `telem_intel_native.c` działa w wątku drain na buforze `mfxBitstream` po istniejącym `SyncOperation`. Nie dekoduje filmu, nie kopiuje obrazów GPU do CPU, nie dodaje synchronizacji GPU ani osobnego procesu i nie zapisuje plików tymczasowych.

- **NAL:** szybkie wyszukiwanie start code'ów 3/4-bajtowych (skok o 3 bajty) i usuwanie emulation prevention bytes. NAL z `nuh_layer_id≠0` są pomijane, a NAL z `forbidden_zero_bit` odrzucają klatkę.
- **SPS/PPS:** pełne parsowanie pól poprzedzających pola QP:
  - profile_tier_level z sub-layerami, scaling lists, PCM;
  - short-term RPS z pełnym wyprowadzeniem DeltaPoc, także predykcja inter-RPS (H.265 7.4.8);
  - long-term refs, tiles, deblocking.
- **Zmiany parametrów:** nowy SPS/PPS zastępuje poprzedni. Jeśli nie da się go sparsować, wpis jest unieważniany i slice'y z niego nie dają próbki — nigdy nie są liczone na starych wartościach.
- **Slice header:** wszystkie pola warunkowe do `slice_qp_delta` (`num_extra_slice_header_bits`, `output_flag`, `colour_plane`, POC, RPS, long-term, TMVP, SAO, `num_ref_idx` override, lists modification, cabac_init, collocated, pred_weight_table, merge cand). Wynik: `SliceQpY = 26 + init_qp_minus26 + slice_qp_delta`. Odrzucany jest QP spoza zakresu `[-QpBdOffset, 51]` oraz slice IRAP inny niż I.
- **Dependent slice segments** dziedziczą QP slice'a i należą do jego obszaru CTU.
- **Wiele slice'ów:** QP klatki = suma (QP slice × liczba CTU slice'a) / CTU klatki, czyli średni bazowy QP po CTU, a nie zwykła średnia slice'ów. Adresy segmentów muszą rosnąć i zaczynać się od 0.
- **Zasada „brak próbki zamiast zgadywania”:** wystarczy jeden błędny slice albo brak SPS/PPS, a cała klatka jest odrzucana (`rejected_frames`).
- **Typ klatki według struktury predykcji:**
  - I — wszystkie slice'y I;
  - P — tylko referencje z przeszłości (P lub generalized-B; Intel koduje klatki P jako `slice_type=0`);
  - B — referencja do przyszłej klatki (dodatnie DeltaPocS1 używane przez bieżącą klatkę).

## 2. Wartości pochodzą z rzeczywistego bitstreamu

Odczyt pochodzi z gotowych pakietów enkodera w trakcie eksportu. Niezależna weryfikacja: FFmpeg `trace_headers` (osobny parser CBS) na każdej klatce oraz `src/qp_analyzer.py`.

## 3. Wyniki Fast / Balanced / Quality (600 klatek, 4 przebiegi z parserem na preset)

| Preset | Slice QP bieżący / średni / min / max | Klatki I / P / B |
|---|---|---|
| Fast | 26 / 26.0 / 26 / 26 | 10 / 590 / 0 |
| Balanced | 26 / 26.0 / 26 / 26 | 10 / 590 / 0 |
| Quality | 26 / 26.0 / 26 / 26 | 10 / 590 / 0 |

Wartość jest stała, bo enkoder Intel zapisuje `init_qp_minus26=0` i `slice_qp_delta=0`, a dynamiczną kwantyzację realizuje przez `cu_qp_delta` (CABAC, poza zakresem parsera). VBR nie wymusza zmiany Slice QP, a zmienności nie symulowano. Tekst GUI: `Slice QP: 26 | Avg: 26.0 | Min: 26 | Max: 26 | próbki: 600 (odrzucone: 0)`.

## 4. Próbki prawidłowe i odrzucone

Każdy z 12 przebiegów z parserem: 600 prawidłowych, 0 odrzuconych, 0 błędów parsowania.

## 5. Niezależna weryfikacja

- **Eksporty Intel:** 12 × 600 klatek, native vs `trace_headers` — 0 rozbieżności. Typy I/P/B są zgodne z referencją opartą o kolejność POC (pełne POC z MSB, H.265 8.3.1). `qp_analyzer`: 26/26/26.
- **Testy** (`tests/test_intel_hevc_slice_qp_native.py`, referencja per klatka z `trace_headers`):
  - rzeczywiste pakiety Intel QSV Main10;
  - x265 Main10: 4 slice'y na klatkę, B-frames z reorderingiem, zmienny QP (CRF + AQ) — QP i liczby I/P/B zgodne co do klatki;
  - zmiana SPS/PPS w połowie strumienia (inny QP i liczba slice'ów) — zgodne;
  - usunięty PPS — 100% klatek odrzuconych, 0 próbek;
  - obcięte strumienie, losowe uszkodzenia bajtów, losowe dane, pusty bufor — bez awarii, bez wartości spoza zakresu.
- Dependent slice segments są obsługiwane w kodzie, ale nie mam generatora strumienia z nimi (ani Intel, ani x265 ich nie emitują), więc ta ścieżka nie jest pokryta testem na rzeczywistym strumieniu.

## 6. Narzut FPS (A/B, kolejność ABBA × 2, te same materiał/bitrate/HUD/preset, brak SportCamHUD w tle)

| Preset | Parser ON — FPS (śr., przebiegi) | Parser OFF — FPS (śr., przebiegi) | Różnica |
|---|---|---|---|
| Fast | 54.11 (54.2, 54.6, 54.2, 53.4) | 54.07 (54.6, 54.9, 53.7, 53.0) | +0.07% |
| Balanced | 32.03 (32.7, 31.6, 31.4, 32.4) | 31.81 (32.2, 32.1, 31.1, 31.8) | +0.70% |
| Quality | 14.89 (15.3, 15.2, 15.2, 13.9) | 14.58 (15.3, 15.3, 14.4, 13.4) | +2.09% |

Parser nie spowalnia eksportu. Dodatnie różnice to zmienność GPU/temperatury (rozrzut w obrębie wariantu do ±1 FPS), a nie zysk. Czas analizy: średnio 46–122 µs/klatkę, maksymalnie 182–601 µs, w wątku drain poza ścieżką renderowania. Szybkie skanowanie start code'ów obniżyło czas z 130–320 µs w wersji pierwszej.

Smoke test produkcyjnej DLL (Balanced, 300 klatek): 20.6 FPS, poniżej 32 FPS z serii 600-klatkowej. Krótszy przebieg ma większy udział startu, ale tego nie zweryfikowano. W serii A/B oba warianty są równe, więc to nie efekt parsera.

## 7. Kanoniczny harness

`tools/run_intel_hevc_qp_ab.py` (wywołuje `SportCamHUD.py --test-intel-export`): 24/24 przebiegów OK, natywna ścieżka, 0 fallbacków do FFmpeg. Logi: `intel_hevc_qp_20261017/ab/*.log`, dane: `intel_hevc_qp_20261017/ab/summary.json`. Enkoder bez zmian: `rc=2 (VBR) tu=4 target=40000 max=50000 HRD`. Testy jednostkowe Intel: 129 zaliczonych; 3 niezaliczone niezwiązane (2 — brak `pytest.warns` w zastępczym stubie, pytest nie jest zainstalowany; 1 — brak AV1 QSV na tym CPU).

## 8. Zmienione pliki

- `src/native/d3d11_intel_pipeline/telem_intel_native.c` — parser Slice QP, statystyki (prawidłowe/odrzucone, I/P/B, czasy), eksporty `intel_native_get_hevc_slice_qp` i `intel_native_hevc_slice_qp_selftest`.
- `src/ffmpeg/intel_native_exporter.py` — mirror struktury, pola `slice_qp_*`, tekst `Slice QP: …` / `Slice QP: --`. H.264 i inne backendy bez zmian.
- `tests/test_intel_hevc_slice_qp_native.py` (nowy), `tests/test_intel_vbr_control.py`.
- `tools/run_intel_hevc_qp_ab.py` (nowy).
- `runtime/intel/bin/telem_intel_native.dll` — kopie poprzednich: `.bak_pre_hevc_slice_qp` (oryginał), `.bak_slice_qp_v1` (pierwsza wersja parsera).
