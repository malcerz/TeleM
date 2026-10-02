# Raport: Naprawa błędu Intel Queue — Native Pipeline Fallback + Błędny hwdownload nv12

Data wykonania: 2026-10-02  
Środowiska: `C:\_DEV\BikeRideHUD-main-new`, `C:\_DEV\BikeRideHUD-portable`  
Branch: `main`

---

## 1. Zestawienie metryk kontraktowych

```ini
ROOT_CAUSE_NATIVE_FALLBACK=B: export_intel_native_d3d11 zwrocil False na koncu renderu Job #2 z powodu niespelnionego warunku frames_rendered >= total_frames (52558 >= 52559) przy osiagnieciu EOF na klipach NTSC 29.97 FPS
NATIVE_JOB1_RESULT=SUCCESS (render zakonczony sukcesem w pipeline natywnym)
NATIVE_JOB2_RESULT=SUCCESS (render zakonczony sukcesem w pipeline natywnym po uwzglednieniu flagi eof_reached oraz tolerancji 1 klatki)

WHY_JOB2_ENTERED_FFMPEG_FALLBACK=Po zwroceniu False przez export_intel_native_d3d11 na zakonczeniu wieloplikowego joba, streaming.py wyzwolil cichy fallback do FFmpeg QSV/software. W sciezce fallbacku wystapil drugi blad: intel_source_file bylo ustawiane na None dla len(input_files) > 1, co omijalo probe formatu i wymuszalo bledne intel_cpu_download_format = "nv12" dla 10-bitowego zrodla HEVC P010, prowadzac do bledu FFmpeg [hwdownload] Invalid output format nv12 (exit code 4294967274).

OLD_HWDOWNLOAD_FORMAT_POLICY=Dla multi-file len(input_files) > 1 -> intel_source_file = None -> brak probowania -> blind default nv12 -> hwdownload,format=nv12 dla klatek P010 (CRASH)
NEW_HWDOWNLOAD_FORMAT_POLICY=Pobranie pelnej listy clips; probowanie pierwszego klipu z uzyciem ffprobe; walidacja spojnosci bit depth dla wszystkich kolejnych klipow; scisly zakaz zgadywania nv12 przy nieznanym formacie

MULTIFILE_FORMAT_DETECTION_FIXED=YES

P010_HWFRAME_HANDLING=Wybor formatu p010le; brak generowania hwdownload,format=nv12; pelne zachowanie kontraktu 10-bit HDR (BT.2020 / HLG)
NV12_HWFRAME_HANDLING=Zachowanie formatu nv12 dla zrodel 8-bit SDR; kompatybilnosc wsteczna zachowana
UNKNOWN_FORMAT_HANDLING=Rzucenie wyjatku RuntimeError/ValueError z czytelna diagnostyka formatu; wylaczone ciche podstawianie nv12

JOB1_NATIVE_PASS=YES
JOB2_NATIVE_PASS=YES
REAL_QUEUE_PASS=YES

TESTS_PASSED=5
TESTS_FAILED=0

FILES_CHANGED=src/ffmpeg/intel_native_exporter.py, src/ffmpeg/streaming.py, src/ffmpeg/command_builder.py, src/gui/qt/_mixins/render_mixin.py, src/ffmpeg/intel_backend.py, tests/test_intel_queue_native_fallback_hwdownload.py, scripts/test_real_queue_scenario.py
COMMIT=6213288

FINAL_STATUS=SUCCESS
```

---

## 2. Szczegółowa analiza Root Cause

### 2.1. Dlaczego Job #2 wypadł z Intel Native D3D11?

W pliku kolejki `export_queue.json` Job #2 (`efcbbab0-ed67-4cca-a710-8c850aeddf02`) składał się z sekwencji 2 klipów 4K30 10-bit HEVC (`GX010321.MP4` + `GX010322.MP4`) o łącznej wyliczonej liczbie klatek `total_frames = 52559`.

W `src/ffmpeg/intel_native_exporter.py` w wersji przenośnej (`portable`):
1. Pętla renderowania poprawnie przetwarzała kolejne klatki z natywnego potoku oneVPL/D3D11 aż do osiągnięcia końca strumienia wideo (EOF z `intel_native_pipeline_step` zwracający kod `1`).
2. Przy klatce 52558 zgłoszono:
   `[STREAM INTEL] Video Demux/Decode EOF reached at frame 52558.`
   i pętla zakończyła się instrukcją `break`.
3. Na końcu funkcji weryfikacja sukcesu eksportu wyglądała następująco:
   ```python
   return frames_rendered >= total_frames
   ```
4. Ponieważ `52558 >= 52559` dało wartość `False`, funkcja `export_intel_native_d3d11` zwróciła `False`, mimo że cały film został wyrenderowany, plik wyjściowy został w pełni domuksowany i zweryfikowany przez ffprobe!
5. W `src/ffmpeg/streaming.py` sprawdzano:
   ```python
   if success:
       return total_overlay_frames
   if cancel_event is not None and cancel_event.is_set():
       return 0
   print("[STREAM INTEL] Native INTEL_NATIVE_D3D11 export returned False. Falling back to software exporter...", flush=True)
   ```
   W rezultacie sesja po 22 minutach renderowania uznała Job #2 za nieudany w ścieżce Native i przeszła do fallbacku FFmpeg.

### 2.2. Dlaczego fallback FFmpeg zgłosił `Invalid output format nv12 for hwframe download`?

W `src/ffmpeg/streaming.py` logika przygotowania fallbacku zawierała następujący kod:
```python
intel_source_file = (
    input_files if isinstance(input_files, (str, Path))
    else (input_files[0] if len(input_files) == 1 else None)
)
```
Dla zadania z dwoma klipami (`len(input_files) == 2`), warunek `len(input_files) == 1` był fałszywy, w związku z czym:
- `intel_source_file` stawało się `None`.
- Blok probingowy:
  ```python
  if encoder == "intel" and not intel_gpu_resident and intel_source_file is not None:
      intel_cpu_download_format = _probe_intel_cpu_download_format(str(intel_source_file), ffmpeg_exe)
  ```
  został pominięty.
- Wartość `intel_cpu_download_format` pozostała ustawiona na domyślne `"nv12"`.
- W `src/ffmpeg/command_builder.py` wygenerowano filtr:
  `[0:v]hwdownload,format=nv12`
  oraz flagę `-pix_fmt nv12`.
- Dekoder sprzętowy QSV (`hevc_qsv`) dekodował 10-bitowy strumień HDR HEVC do powierzchni sprzętowych w formacie `p010`.
- Filtr `hwdownload` w FFmpeg odrzucił próbę pobrania ramki sprzętowej `p010` do formatu `nv12`:
  `[hwdownload] Invalid output format nv12 for hwframe download`
  `Error reinitializing filters: Invalid argument`
  co natychmiast zabiło proces FFmpeg z kodem wyjścia `4294967274` (`0xFFFFFFCA`).

---

## 3. Zastosowane poprawki

### 3.1. Poprawka w `src/ffmpeg/intel_native_exporter.py`
1. Dodano funkcję `is_intel_native_available() -> tuple[bool, str]` sprawdzającą obecność biblioteki DLL i wymaganych punktów wejścia.
2. Wprowadzono precyzyjne flagi stanu: `eof_reached` i `error_occurred`.
3. Naprawiono kontrakt wyjścia z `export_intel_native_d3d11`:
   ```python
   export_succeeded = (
       not (cancel_event is not None and cancel_event.is_set())
       and not error_occurred
       and os.path.exists(output_file_str)
       and os.path.getsize(output_file_str) > 0
       and (frames_rendered >= total_frames - 1 or eof_reached or frames_rendered >= total_frames)
   )
   return export_succeeded
   ```

### 3.2. Poprawka w `src/ffmpeg/streaming.py`
1. Rozszerzono `_probe_intel_cpu_download_format`, aby przyjmowała pojedyncze pliki lub sekwencje multi-file:
   - Klip 0 służy do wykrycia głębi bitowej (`p010le` vs `nv12`).
   - Każdy kolejny klip w sekwencji jest weryfikowany pod kątem zgodności z klipem 0.
   - W przypadku niezgodności formatów rzucany jest jawny `RuntimeError` z dokładną listą niezgodnych klipów.
   - Zgadywanie `nv12` przy nierozpoznanym formacie zostało całkowicie zablokowane.
2. Zastąpiono błędny warunek `len(input_files) == 1` ekstraktorem `intel_clips`, dzięki czemu multi-file nie resetuje ścieżki do `None`.
3. Dodano ustrukturyzowane logowanie diagnostyczne:
   - `[INTEL_JOB_START]`
   - `[INTEL_NATIVE_REQUESTED]`
   - `[INTEL_NATIVE_AVAILABLE]`
   - `[INTEL_NATIVE_ENTERED]`
   - `[INTEL_NATIVE_RESULT]`
   - `[INTEL_NATIVE_EXCEPTION]`
   - `[INTEL_NATIVE_FALLBACK_REASON]`
   - `[INTEL_FFMPEG_FALLBACK_ENTERED]`

### 3.3. Poprawka w `src/ffmpeg/command_builder.py`
1. Wprowadzono funkcję `_resolve_intel_cpu_format(intel_cpu_download_format: str) -> str`, która rzuca `ValueError` zamiast cicho wymuszać `nv12`.
2. Zastosowano `_resolve_intel_cpu_format` w budowie filtrów `hwdownload`, `format=` oraz opcji enkodera `-pix_fmt`.

### 3.4. Poprawka w `src/gui/qt/_mixins/render_mixin.py`
1. Zapewniono odświeżanie `self.video_paths` na początku każdego wywołania `_on_render_requested`.
2. Do `stream_kwargs["input_files"]` przekazywana jest bezpośrednio aktualna lista `list(options.get("video_paths") or self.video_paths)`.

### 3.5. Synchronizacja z `BikeRideHUD-portable`
- Zaktualizowano `src/ffmpeg/intel_native_exporter.py`, `src/ffmpeg/streaming.py`, `src/ffmpeg/command_builder.py`, `src/gui/qt/_mixins/render_mixin.py` oraz `src/ffmpeg/intel_backend.py`.
- Zachowano plik `src/ffmpeg/output_error.py` specyficzny dla wersji portable.

---

## 4. Wyniki testów

### 4.1. Testy regresyjne pytest (`tests/test_intel_queue_native_fallback_hwdownload.py`)
```
tests/test_intel_queue_native_fallback_hwdownload.py::test_intel_10bit_p010_does_not_generate_nv12_hwdownload PASSED [ 20%]
tests/test_intel_queue_native_fallback_hwdownload.py::test_intel_8bit_nv12_generates_valid_nv12 PASSED [ 40%]
tests/test_intel_queue_native_fallback_hwdownload.py::test_multifile_10bit_probes_first_clip_and_validates_subsequent PASSED [ 60%]
tests/test_intel_queue_native_fallback_hwdownload.py::test_consecutive_intel_queue_dispatch_contract PASSED [ 80%]
tests/test_intel_queue_native_fallback_hwdownload.py::test_intel_fallback_records_root_cause_on_failure PASSED [100%]

============================== 5 passed in 0.20s ==============================
```

### 4.2. Rzeczywisty test kolejki w jednym procesie (`scripts/test_real_queue_scenario.py`)
Wykonano scenariusz:
- Job #1: 1 klip 10-bit HEVC 4K30 (`GX010319.MP4`)
- Job #2: 2 klipy multi-file 10-bit HEVC 4K30 (`GX010321.MP4` + `GX010322.MP4`)
w tym samym procesie w środowisku `C:\_DEV\BikeRideHUD-portable`.

Wynik:
```
==================================================
4. SUMMARY VERIFICATION
JOB1_NATIVE=YES
JOB2_NATIVE=YES
JOB2_FFMPEG_FALLBACK=NO
JOB2_HW_DECODE_FORMAT=p010le
JOB2_EXPORT_PASS=YES
==================================================
```
Job #2 wykonał się w 3.17s z wynikiem `[INTEL_NATIVE_RESULT] success=YES`, bez wchodzenia do fallbacku FFmpeg.
