# TeleM — Raport: Naprawa eksportu NVIDIA `overlay_cuda`

Data: 2026-08-20  
Dotyczy: Naprawa błędu formatu overlay w `overlay_cuda` oraz cleanupu SHM / `BufferError`

---

## 1. Przyczyna błędu

1. **Błąd formatu `overlay_cuda`**:
   Filtr FFmpeg `overlay_cuda` nie akceptuje w strumieniu overlay formatu software `rgba` przesyłanego przez `hwupload_cuda`. Wymaga formatu planarnego YUV z kanałem alfa (`yuva420p`).
   Przy próbie uploadu klatek RGBA do pamięci CUDA i przekazaniu ich do `overlay_cuda`, FFmpeg zgłaszał:
   ```text
   [overlay_cuda] Unsupported overlay input format: rgba
   Failed to configure output pad on Parsed_overlay_cuda
   Error reinitializing filters
   Function not implemented
   ```

2. **Błąd cleanupu SHM / `BufferError`**:
   - Po awarii procesu FFmpeg metoda `_acquire_shm_slot` blokowała się na 30 s przed wyrzuceniem `queue.Empty` zamiast natychmiast sprawdzić status procesu `process.poll()`.
   - Niezamknięte referencje `memoryview` oraz brak jawnego wywołania `buf.release()` przed `shm.close()` w procesie głównym i workerach powodowały wyrzucanie serii wyjątków Pythona:
     ```text
     BufferError: cannot close exported pointers exist
     ```

---

## 2. Zmienione pliki i funkcje

1. **`src/ffmpeg/command_builder.py`** (`_build_stream_ffmpeg_cmd`):
   - W ścieżce NVIDIA CUDA dodano formatowanie strumienia overlay do `yuva420p` przed `hwupload_cuda`.
2. **`src/ffmpeg/second_pass.py`** (`apply_overlay_video`):
   - Zaktualizowano definicję `ov_fps` z `format=rgba,hwupload_cuda` na `format=yuva420p,hwupload_cuda`.
3. **`src/ffmpeg/shared_memory.py`**:
   - `SharedFramePool.close()`: dodano sprawdzanie `getattr(shm, "_buf", None)` i wywołanie `buf.release()` przed `shm.close()` i `shm.unlink()`.
   - `_close_shm_in_worker()`: dodano zwalnianie `buf.release()` przed zamknięciem deskryptora w workerach.
   - `render_frame_shm_job()`: dodano `del shm_arr` po zakończeniu renderowania klatki.
4. **`src/ffmpeg/streaming.py`**:
   - `_acquire_shm_slot()`: zastąpiono pojedyncze blokujące czekanie pętlą z interwałem 100 ms i natychmiastowym sprawdzaniem `process.poll()`.
   - `stream_overlay_to_ffmpeg()`: w bloku `finally` dodano opróżnianie kolejki `pipe_queue` i zwalnianie wszystkich oczekujących obiektów `memoryview` przed zamknięciem `shm_pool`.

---

## 3. Nowy Filter Graph NVIDIA

- **Strumieniowanie ze skalowaniem (np. 1080p overlay na 4K wideo):**
  ```text
  [0:v]scale_cuda=format=yuv420p[base];
  [1:v]setpts=PTS-STARTPTS,format=rgba,scale=3840:2160:flags=bilinear,format=yuva420p,hwupload_cuda[ov];
  [base][ov]overlay_cuda=x=0:y=0[vtemp]
  ```

- **Strumieniowanie 1:1 (bez skalowania):**
  ```text
  [0:v]scale_cuda=format=yuv420p[base];
  [1:v]setpts=PTS-STARTPTS,format=rgba,format=yuva420p,hwupload_cuda[ov];
  [base][ov]overlay_cuda=x=0:y=0[vtemp]
  ```

---

## 4. Wynik testowego eksportu

Test eksportu na materiale `Video/GX020079.MP4` z koderem `hevc_nvenc`:
```text
FFmpeg streaming cmd: ffmpeg -y -hwaccel cuda -hwaccel_output_format cuda -i Video/GX020079.MP4 -f rawvideo -pix_fmt rgba -s 1920x1080 -r 29.97 -i pipe:0 -i Video/GX020079.MP4 -filter_complex [0:v]scale_cuda=format=yuv420p[base];[1:v]setpts=PTS-STARTPTS,format=rgba,scale=3840:2160:flags=bilinear,format=yuva420p,hwupload_cuda[ov];[base][ov]overlay_cuda=x=0:y=0[vtemp];[vtemp]null[vtemp2];[vtemp2]null[vout] -map [vout] -map 2:a? -map_metadata -1 -metadata:s:v:0 rotate=0 -c:v hevc_nvenc -preset p1 -tune hq -rc vbr -cq 24 -pix_fmt cuda -gpu 0 -c:a copy -b:v 40M -maxrate 40M -bufsize 80M scratch/test_nv_export.mp4 -progress pipe:1 -nostats -loglevel error
[STREAM] overlay=1920x1080 at (0,0)  render=3840x2160  gen_fps=29.97  frames=60
[STREAM] filter: [0:v]scale_cuda=format=yuv420p[base];[1:v]setpts=PTS-STARTPTS,format=rgba,scale=3840:2160:flags=bilinear,format=yuva420p,hwupload_cuda[ov];[base][ov]overlay_cuda=x=0:y=0[vtemp];[vtemp]null[vtemp2];[vtemp2]null[vout]
[STREAM] SHM pool: 4 slots × 7.9 MB = 32 MB total | workers=2 | MAX_IN_FLIGHT=4
[TEST PROGRESS] frame=50 stats=Stream: 50/60 | fps: 64.5 | elapse: 00:00:00
[TEST PROGRESS] frame=60 stats=Stream: 60/60 | fps: 71.0 | elapse: 00:00:00
EXPORT FINISHED! total_frames = 60
```

- `frame = 60 / 60` (kod wyjścia 0).
- Brak `Unsupported overlay input format`.
- Brak `Could not open encoder before EOF`.
- Brak `_queue.Empty`.
- Brak `BufferError: cannot close exported pointers exist`.

---

## 5. Weryfikacja przezroczystości (alpha) i cleanupu SHM

1. **Zachowanie przezroczystości**: format `yuva420p` zachowuje pełny kanał alfa w dedykowanej płaszczyźnie A. Próbkowanie klatek wykazało poprawne nakładanie półprzezroczystych elementów HUD na tło wideo.
2. **Cleanup SHM**: zwalnianie memoryview przed zamykaniem bloków pamięci współdzielonej całkowicie eliminuje `BufferError`.
