# RAPORT SPORTCAMHUD v1.14 — NVIDIA NATIVE FPS + AUDIO LIVE MUX FIX

**Status zadania:** IMPLEMENTED — NOT HARDWARE TESTED  
**Projekt:** SportCamHUD v1.14 (kod źródłowy TeleM)  
**Gałąź Git:** `fix/gui-freeze-hud-composite`  
**Środowisko audytowe:** Maszyna deweloperska z AMD Radeon Graphics (brak fizycznego procesora graficznego NVIDIA)  
**Środowisko docelowe weryfikacji sprzętowej:** Komputer z kartą graficzną NVIDIA GeForce RTX 5070 Ti  
**Data implementacji:** 2026-10-11  

---

## 1. Status i środowisko

Zgodnie z wytycznymi zadania wprowadzono komplet poprawek architektonicznych i implementacyjnych w kodzie backendu **NVIDIA Native D3D11/NVENC** bez uruchamiania testów sprzętowych na maszynie deweloperskiej (na której brak GPU NVIDIA).

- **Zakaz kompilacji / testów:** W trakcie prac NIE kompilowano biblioteki C++ DLL dla NVIDIA, NIE uruchamiano renderingu próbnego, benchmarków ani symulacji wyników.
- **Brak ingerencji w inne potoki:** Żadne pliki backendu AMD (`amd_native_exporter.py`, `amd_native_preview.py`) ani Intel (`intel_native_exporter.py`) nie zostały zmodyfikowane.
- **Czystość kodu:** Wszystkie zmodyfikowane moduły Python przechodzą pomyślnie walidację składni (`python -m py_compile`).

---

## 2. Analiza błędu sztywnego FPS (Hardcoded 29.97 FPS)

### Diagnoza problemu
W pliku `src/ffmpeg/nvidia_native_exporter.py` znajdowały się sztywne przypisania klatkażu:
```python
# POPRZEDNI BŁĘDNY KOD:
fps_num = 30000
fps_den = 1001
fps = fps_num / float(fps_den)
...
cmd_mux = [
    "ffmpeg", "-y",
    "-f", v_fmt, "-r", "30000/1001", "-i", "-",
    ...
]
```
Dodatkowo w próbkowaniu wykresów telemetrii występowało sztywne pobieranie próbek co 30 klatek:
```python
chart_samples_dict = {
    "cadence": [st.cadence_rpm for st in states[::30]],
    "heart_rate": [st.heart_rate_bpm for st in states[::30]],
}
```

### Konsekwencje błędu dla materiałów innych niż 29.97 FPS:
1. **Materiały 59.94 / 60 FPS:** Nagranie 60 fps eksportowane jako 29.97 fps trwało 2 razy dłużej, liczba klatek eksportu i wyliczenia czasu ulegały rozjechaniu, a audio rozsynchronizowywało się o 100%.
2. **Materiały 25 / 50 FPS (PAL):** Przeliczanie czasu i klatek ulegało ciągłemu dryfowi PTS/DTS, powodując zacięcia i artefakty mikrostutteringu.
3. **Materiały 23.976 / 24 FPS (Film):** Zawyżanie prędkości odtwarzania wideo w stosunku do strumienia audio.
4. **Wykresy HUD:** Próbkowanie `states[::30]` dla materiału 60 fps dawało próbki co 0.5 sekundy zamiast standardowego 1 Hz, zniekształcając przebieg profilu wysokościowego i tętna.

---

## 3. Nowa architektura Rational FPS

Wprowadzono funkcję `parse_rational_fps` w `src/ffmpeg/nvidia_native_exporter.py`:

```python
def parse_rational_fps(fps_val: Any) -> tuple[int, int]:
    """Parse FPS value (string fraction, float, int, tuple) into exact (fps_num, fps_den).

    Guarantees positive numerator and denominator, precise rational mapping for standard
    NTSC rates (23.976, 29.97, 59.94, 119.88), integer frame rates, and Fraction fallback.
    """
    if fps_val is None:
        return 30000, 1001

    if isinstance(fps_val, (tuple, list)) and len(fps_val) >= 2:
        try:
            num, den = int(fps_val[0]), int(fps_val[1])
            if num > 0 and den > 0:
                return num, den
        except (ValueError, TypeError):
            pass
        return 30000, 1001

    if isinstance(fps_val, str):
        val = fps_val.strip()
        if not val or val in ("0/0", "0"):
            return 30000, 1001
        if "/" in val:
            parts = val.split("/")
            try:
                num, den = int(parts[0]), int(parts[1])
                if num > 0 and den > 0:
                    return num, den
            except ValueError:
                pass
        try:
            fps_float = float(val)
        except ValueError:
            return 30000, 1001
    elif isinstance(fps_val, (int, float)):
        fps_float = float(fps_val)
    else:
        return 30000, 1001

    if fps_float <= 0.0:
        return 30000, 1001

    # Exact checks for standard NTSC rates
    if abs(fps_float - 29.97002997) < 0.005 or abs(fps_float - 29.97) < 0.005:
        return 30000, 1001
    if abs(fps_float - 59.94005994) < 0.005 or abs(fps_float - 59.94) < 0.005:
        return 60000, 1001
    if abs(fps_float - 23.976023976) < 0.005 or abs(fps_float - 23.976) < 0.005:
        return 24000, 1001
    if abs(fps_float - 119.88011988) < 0.01 or abs(fps_float - 119.88) < 0.01:
        return 120000, 1001

    # Integer rates (24, 25, 30, 48, 50, 60, 100, 120, etc.)
    if abs(fps_float - round(fps_float)) < 1e-4:
        return int(round(fps_float)), 1

    frac = Fraction(str(fps_float)).limit_denominator(100100)
    if frac.numerator <= 0 or frac.denominator <= 0:
        return 30000, 1001
    return frac.numerator, frac.denominator
```

### Właściwości resolvera:
- Obsługa ułamków łańcuchowych bezpośrednio z kontenera (`"30000/1001"`, `"60000/1001"`, `"24000/1001"`, `"60/1"`, `"25/1"`).
- Dokładne odwzorowanie NTSC dla wartości float (`29.97` -> `30000/1001`, `59.94` -> `60000/1001`, `23.976` -> `24000/1001`, `119.88` -> `120000/1001`).
- Obsługa klatkaży całkowitych (`24`, `25`, `30`, `50`, `60`, `120` -> mianownik 1).
- Bezpieczny fallback przy użyciu `fractions.Fraction.limit_denominator(100100)`.
- Gwarancja mianownika i licznika > 0 — zabezpieczenie przed dzieleniem przez zero.

---

## 4. Przepływ FPS przez cały łańcuch przetwarzania

Poprawki objęły wszystkie etapy przekazywania parametrów w architekturze:

```
[GUI / RenderMixin]
      │  (wykrywa r_frame_rate/avg_frame_rate -> target_fps)
      │  (rejestruje target_fps w gui_snapshot["gui_options"])
      ▼
[nvidia_child_process.py / run_nvidia_render_child]
      │  (serializuje target_fps w job_args)
      ▼
[_child_main]
      │  (przekazuje target_fps i inline_gpmf_plan do export_nvidia_native_d3d11)
      ▼
[nvidia_native_exporter.py / export_nvidia_native_d3d11]
      ├── 1. parse_rational_fps(target_fps) -> target_fps_num, target_fps_den
      ├── 2. Skanowanie klipów -> TelemVideoClipDesc(fps_num=clip_num, fps_den=clip_den)
      ├── 3. Sprawdzenie spójności klatkaży (Guard condition)
      ├── 4. compute_fast_telemetry_states(fps=effective_target_fps)
      ├── 5. Próbkowanie wykresów: states[::max(1, round(effective_target_fps))]
      ├── 6. TelemNvencConfig(fps_num=target_fps_num, fps_den=target_fps_den)
      │        │
      │        ▼
      │   [NVIDIA C++ DLL: telem_nvenc_configure]
      │        (NVENC initParams.frameRateNum = m_config.fps_num)
      │        (NVENC initParams.frameRateDen = m_config.fps_den)
      │
      └── 7. cmd_mux (FFmpeg Live Muxer):
               ffmpeg -y -f <v_fmt> -r <target_fps_num>/<target_fps_den> -i -
               ... -t <duration_s> ...
```

---

## 5. Obsługa klatkaży materiałów wejściowych i guard dla mixed-FPS

Natywny dekoder C++ D3D11 (`AcquireDecoderFrame`) w `native/d3d11_nvenc_pipeline` czyta ramki z kolejnych klipów sekwencyjnie 1-do-1 w oparciu o sprzętowy dekoder D3D11VA, nie posiadając wewnętrznego resamplera czasowego (frame rate interpolator).

Dlatego w `export_nvidia_native_d3d11` zaimplementowano jawny guard:
```python
for c_info in probed_clips_info:
    clip_fps = c_info["clip_fps"]
    if abs(clip_fps - effective_target_fps) > 0.05:
        raise RuntimeError(
            f"NVIDIA Native D3D11 nie obsługuje jeszcze resamplingu klatek pomiędzy różnymi wartościami FPS "
            f"(klip '{c_info['path'].name}': źródło {clip_fps:.3f} FPS [{c_info['clip_fps_num']}/{c_info['clip_fps_den']}], "
            f"docelowo {effective_target_fps:.3f} FPS [{target_fps_num}/{target_fps_den}]). "
            f"Użyj materiałów o zgodnym klatkażu."
        )
```
Zapobiega to cichemu zniekształceniu osi czasu lub desynchronizacji audio/wideo.

---

## 6. Całkowita eliminacja ADTS i audio cache

Wyeliminowano wszystkie przestarzałe mechanizmy buforowania i demuxowania audio:
- `CACHE_DIR = Path("scratch/audio_cache")` — **USUNIĘTY**
- `get_cached_clip_adts()` — **USUNIĘTY**
- `parse_adts_packets()` — **USUNIĘTY**
- `PacedAudioFeeder` — **USUNIĘTY**
- `build_streaming_audio_slice()` — **USUNIĘTY**
- Faza przygotowawcza `"audio_slice"` w `HudPrepProgressTracker` — **USUNIĘTA** (przyspieszenie fazy preflight)

### Dowód weryfikacji w kodzie źródłowym:
Polecenie:
```powershell
git grep -n "PacedAudioFeeder\|get_cached_clip_adts\|parse_adts_packets\|build_streaming_audio_slice\|audio\.adts\|audio_cache" src/
```
Zwróciło kod wyjścia `1` (0 dopasowań w całym drzewie `src/`).

---

## 7. Nowa architektura Single-Pass Live Audio Mux

Wdrożono architekturę identyczną ze sprawdzonym rozwiązaniem w potoku AMD (`amd_native_exporter.py`):

1. **Wykrycie obecności audio:**
   Funkcja `_probe_clip_audio_stream` sprawdza obecność strumienia `a:0` za pomocą `ffprobe`.
2. **Pojedynczy klip bez cięć od zera:**
   Audio przekazywane bezpośrednio z oryginalnego pliku MP4:
   `-i <clip_path>`
3. **Pojedynczy klip z cięciem (`start_frame > 0` lub `local_start_s > 0`):**
   Audio przekazywane bezpośrednio ze znacznikiem:
   `-ss <local_start_s:.6f> -i <clip_path>`
4. **Wiele klipów lub zakresy pocięte w osi czasu (`video_timeline`):**
   Generowany jest lekki tekstowy plan demuxera concat FFmpeg (np. `<output>.tmp.audio.concat.txt`) z wpisami:
   ```
   file '<sciezka_do_oryginalnego_mp4>'
   inpoint <start_s>
   outpoint <end_s>
   ```
   Przekazywany do FFmpeg:
   `-copyts -avoid_negative_ts make_zero -f concat -safe 0 -i <audio_concat_path>`
5. **Kopiowanie strumieniowe (Stream Copy):**
   `-map 0:v -map 1:a? -c:v copy -c:a copy`
   Audio NIE jest ponownie kodowane (brak ponownego kodowania AAC, zerowa degradacja jakości).
6. **Materiały bez audio:**
   Jeśli plik źródłowy nie zawiera ścieżki dźwiękowej, FFmpeg uruchamiany jest z flagą `-an`, a indeksy GPMF są automatycznie przesunięte z wejścia 2 na 1.
7. **Sprzątanie pliku planu:**
   Plik `.audio.concat.txt` jest automatycznie usuwany w bloku `finally:`.

---

## 8. Korekta próbkowania wykresów HUD

W `export_nvidia_native_d3d11`:
```python
# Krok próbkowania dynamicznie powiązany z docelowym FPS
chart_step = max(1, int(round(effective_target_fps)))
chart_samples_dict = {
    "cadence": [st.cadence_rpm for st in states[::chart_step]],
    "heart_rate": [st.heart_rate_bpm for st in states[::chart_step]],
}
```
Zapewnia to dokładne próbkowanie wykresów z częstotliwością 1 Hz dla dowolnego klatkażu (23.976, 24, 25, 29.97, 30, 50, 59.94, 60, 120 FPS).

---

## 9. Zestawienie zmodyfikowanych plików

| Plik | Zakres zmian |
|---|---|
| `src/ffmpeg/nvidia_native_exporter.py` | Implementacja `parse_rational_fps`, usunięcie ADTS i `PacedAudioFeeder`, implementacja planu concat audio, obsługa `target_fps` w `TelemNvencConfig` i `cmd_mux`, guard dla mixed FPS, próbkowanie wykresów `states[::chart_step]`. |
| `src/ffmpeg/nvidia_child_process.py` | Dodanie parametru `target_fps` do `run_nvidia_render_child`, serializacja do `job_args`, przekazanie `target_fps` i `inline_gpmf_plan` w `_child_main`. |
| `src/gui/qt/_mixins/render_mixin.py` | Odczyt `fps_stream_text` z kontenera, wyznaczenie `target_fps`, przekazanie `target_fps` do `run_nvidia_render_child` i `export_nvidia_native_d3d11`, zapis do `gui_snapshot`. |
| `src/ffmpeg/nvidia_payload_dump.py` | Obsługa parametru `target_fps` w `dump_canonical_payload` oraz rejestracja w strukturze zrzutu diagnostycznego. |
| `src/ffmpeg/nvidia_native_preview.py` | Obsługa `target_fps` w `NvidiaNativePreviewRenderer`, parsowanie przez `parse_rational_fps` do konfiguracji podglądu. |

---

## 10. Instrukcja weryfikacji sprzętowej na NVIDIA RTX 5070 Ti

Po przełączeniu na komputer wyposażony w kartę NVIDIA GeForce RTX 5070 Ti wykonać poniższą procedurę testową:

1. **Sprawdzenie obecności DLL:**
   ```powershell
   python -c "from src.ffmpeg.nvidia_config import get_native_dll_path; p = get_native_dll_path(); print('DLL:', p, 'Exists:', p.exists())"
   ```
2. **Kompilacja biblioteki C++ (jeśli wymagana aktualizacja nagłówków/kodu):**
   Użyć skryptu budowania pipeline w katalogu `native/d3d11_nvenc_pipeline/build.bat`.
3. **Test weryfikacyjny eksportu 59.94 / 60 FPS:**
   Wybrać nagranie 60 FPS (np. GoPro 4K 60fps) i wykonać render 300 klatek:
   Zweryfikować w pliku wynikowym za pomocą `ffprobe`:
   ```powershell
   ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate,avg_frame_rate,duration -of json output.mp4
   ffprobe -v error -select_streams a:0 -show_entries stream=codec_name,duration -of json output.mp4
   ```
   Potwierdzić:
   - `r_frame_rate` zgodny z materiałem (np. `60000/1001` lub `60/1`),
   - Czas trwania audio identyczny z czasem trwania wideo (brak dryfu),
   - Brak plików `.adts` w `scratch/`.
4. **Test weryfikacyjny eksportu 29.97 FPS (regresja):**
   Zweryfikować standardowe nagranie 29.97 FPS (np. `GX010361.MP4`) — eksport powinien zachować pełną stabilność i synchronizację A/V.
