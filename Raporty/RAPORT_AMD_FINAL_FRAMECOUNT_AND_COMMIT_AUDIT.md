# Raport z Audytu: TeleM AMD Frame Count Off-By-One i Integralność Commitów

**Data:** 4 września 2026  
**Repozytorium:** `C:\_DEV\TeleM-integration`  
**Branch:** `integration/intel-amd`  
**Autor:** Antigravity Agent  
**Cel:** Wyjaśnienie rozbieżności 1000 requested vs 1001 rendered w testach akceptacyjnych AMD, audyt kontraktu liczby klatek (single & multi-file) oraz weryfikacja integralności commitów przełącznika GUI GPU/CPU i poprawki wyścigu HUD (`f63a850`).

---

## 1. Aktualny Stan HEAD i Historia Commitów

```text
HEAD commit: da3f59940334e5d0d98f8dbac63083285c238172
Short hash:  da3f599
Branch:      integration/intel-amd (up to date with origin/integration/intel-amd)
```

Ostatnie commity w gałęzi:
```text
da3f599 docs(amd): update RAPORT_AMD_ABOVE_HUD_ASYNC_RACE_FIX with user acceptance, commit hash, and final verdict
f63a850 fix(amd): stabilize async HUD buffers and finalize decode selector
e6b875e docs: add AMD final checkpoint report
b4047ab perf(amd): finalize async AMF pipeline and AMD decode path
47ee0b4 feat(gui): finalize layout persistence, preview controls and indicator parity
```

---

## 2. Wyjaśnienie Zagadki: 1000 Requested vs 1001 Rendered

### A. Gdzie pojawiło się 1001 klatek?
W logu z raportu `RAPORT_AMD_ABOVE_HUD_ASYNC_RACE_FIX.md` dla testu akceptacyjnego 1000 klatek (`scratch/run_test_full_production.py ASYNC 2 1000 res_async2_1000f v10`) odnotowano:
```text
[AMD AMF QUEUE DIAGNOSTICS]
  submitted_frames:       1001
  received_frames:        1001
=== RENDER COMPLETE ===
Frames: 1001
```

Jednocześnie ffprobe na wygenerowanym pliku MP4 pokazał:
```text
nb_frames=1000
nb_read_packets=1000
```

### B. Analiza Przyczyny Źródłowej (Root Cause)
1. **Skrypt testowy:**
   W `scratch/run_test_full_production.py`:
   ```python
   FRAMES = int(sys.argv[3]) if len(sys.argv) > 3 else 300  # FRAMES = 1000
   DURATION_S = FRAMES / 29.97                              # DURATION_S = 33.366700033366705
   export_amd_native_d3d11(..., duration_s=DURATION_S)     # video_timeline=None
   ```
2. **Arytmetyka zmiennoprzecinkowa IEEE 754:**
   Wartość `29.97` nie ma dokładnej reprezentacji binarnej. W Pythonie:
   ```python
   duration_s = 1000 / 29.97
   product = duration_s * 29.97
   # product == 1000.0000000000001 (o 1e-13 większe niż 1000)
   ```
3. **Naiwne `math.ceil` w gałęzi fallback exportera (`amd_native_exporter.py` linia 1791):**
   ```python
   total_frames = max(1, math.ceil(duration_s * target_fps))
   ```
   Dla `product = 1000.0000000000001`, `math.ceil()` zwracało **1001**!
   Dotyczy to liczb $N \in \{125, 250, 500, 1000, \dots\}$ przy FPS `29.97`.
4. **Dlaczego plik wynikowy miał 1000 klatek?**
   Podczas muxowania exporter przekazał do ffmpeg argument `-t f"{duration_s:.6f}"` (`-t 33.366700`). Muxer ffmpeg obciął strumień wideo na granicy 33.3667s, zapisując dokładnie 1000 klatek.
   Jednak pętla renderująca przygotowała, przesłała do GPU i zakodowała w AMF 1001 klatek — ostatnia klatka została odrzucona przez muxer.

---

## 3. Produkcyjny Kontrakt Zakresu Klatek (Frame-Range Contract)

W systemie TeleM istnieją dwie ścieżki obliczania liczby klatek:

1. **Ścieżka Produkcyjna GUI / Multi-File (`video_timeline` obecne):**
   - Zdefiniowana w `src/multifile.py` (linia 575):
     ```python
     return max(0, int(round(self.duration_s * target_fps)))
     ```
   - W `amd_native_exporter.py` (linie 1787-1789):
     ```python
     if video_timeline is not None and getattr(video_timeline, "clip_count", 0) > 0:
         per_clip_requested_frames = video_timeline.output_frame_counts(target_fps)
         total_frames = max(1, sum(per_clip_requested_frames))
         duration_s = total_frames / target_fps
     ```
   - W tej ścieżce zaokrąglenie `round()` jest odporne na błędy zmiennoprzecinkowe IEEE 754:
     `round(1000.0000000000001) == 1000`.
     Kontrakt jest półotwarty `[start_frame, end_frame)`: żądanie $N$ klatek daje dokładnie $N$ klatek.

2. **Ścieżka Single-File Fallback (gdy `video_timeline is None`):**
   - Przed poprawką: `total_frames = max(1, math.ceil(duration_s * target_fps))` bez normalizacji `duration_s`.
   - Z powodu braku tolerancji epsilon/round, `math.ceil` produkowało $N+1$ klatek dla określonych wielokrotności $1/29.97$.

---

## 4. Minimalna Poprawka Off-by-One w `amd_native_exporter.py`

Zgodnie z zasadą minimalnej ingerencji (AGENTS.md) i ujednolicenia z kanonicznym kontraktem `src/multifile.py`:

```diff
--- a/src/ffmpeg/amd_native_exporter.py
+++ b/src/ffmpeg/amd_native_exporter.py
@@ -1788,7 +1788,8 @@ def export_amd_native_d3d11(
         total_frames = max(1, sum(per_clip_requested_frames))
         duration_s = total_frames / target_fps
     else:
-        total_frames = max(1, math.ceil(duration_s * target_fps))
+        total_frames = max(1, int(round(duration_s * target_fps)))
+        duration_s = total_frames / target_fps
         per_clip_requested_frames = [total_frames]
```

### Skutki poprawki:
1. Pętla producenta/konsumenta renderuje dokładnie tyle klatek, ile wynika z zaokrąglonego iloczynu czasu i FPS (`round` zgodny z `multifile.py`).
2. Czas `duration_s` zostaje znormalizowany do `total_frames / target_fps`, dzięki czemu pętla GPU, koder AMF oraz demuxer/muxer ffmpeg (`-t`) operują na identycznej, spójnej wartości.

---

## 5. Wyniki Testów Liczby Klatek (1, 2, 10, 100, 1000 frames)

Pomiary wykonane na teście single-file (`Video/GX010115.MP4`, D3D11VA GPU decode, ASYNC depth 2, HEVC AMF):

| Żądana liczba klatek ($N$) | duration_s ($N/29.97$) | Producer Frames | Submitted AMF | Received AMF | Muxed `nb_frames` (ffprobe) | Status |
|---|---|---|---|---|---|---|
| **1** | 0.033367 s | 1 | 1 | 1 | **1** | PASS |
| **2** | 0.066733 s | 2 | 2 | 2 | **2** | PASS |
| **10** | 0.333667 s | 10 | 10 | 10 | **10** | PASS |
| **100** | 3.336670 s | 100 | 100 | 100 | **100** | PASS |
| **1000** | 33.366700 s | 1000 | 1000 | 1000 | **1000** | PASS |

Diagnostyka kolejki AMF po poprawce dla 1000 klatek:
```text
[AMD AMF QUEUE DIAGNOSTICS]
  submitted_frames:       1000
  received_frames:        1000
  in_flight_frames:       2
  max_in_flight:          2
=== RENDER COMPLETE ===
Frames: 1000
Render FPS: 43.213
Effective FPS: 41.440
PROBE OUTPUT:
nb_frames=1000
nb_read_packets=1000
```
**Zbieżność 100%:** `requested == producer == submitted == received == muxed == 1000`.

---

## 6. Weryfikacja Multi-File Boundary Frame Count

Test na łączeniu klipów `Video/GX010114.MP4` oraz `Video/GX010115.MP4`:
- 150 ostatnich klatek klipu GX010114
- 150 pierwszych klatek klipu GX010115
- Oczekiwana suma: **dokładnie 300 klatek** (ani 299, ani 301).

Wyniki testu (`scratch/run_boundary_proof.py`):
```text
================================================================================
Boundary Correctness Proof (014 -> 015, ASYNC depth 2)
Per-clip frame counts: [150, 150] (Total: 300)
================================================================================
[AMD DIRECT MUX] mode=multi clips=2 video=pipe audio=concat output=.part
[AMD DIRECT MUX] source_switch 1->2 global_frame=150

[AMD AMF QUEUE DIAGNOSTICS]
  submitted_frames:       300
  received_frames:        300
=== RENDER COMPLETE ===
Frames: 300
Render FPS: 42.208
Effective FPS: 36.915

ffprobe:
nb_frames=300
nb_read_packets=300
```
**Status: PASS.** Przełączenie źródeł zachowuje ciągłość co do jednej klatki.

---

## 7. Problem B: Integralność Commitów f63a850 i GUI Switch

### A. Weryfikacja commita `f63a850`
Polecenie `git show --stat f63a850` ujawnia:
```text
commit f63a8507ceba28f3282f269d7fee2f1406fd73e0
Author: Malcerz <malcerz@10g.pl>
Date:   Fri Sep 4 09:33:13 2026 +0200

    fix(amd): stabilize async HUD buffers and finalize decode selector
    
    * detach ABOVE/BELOW dirty regions from mutable Pillow canvases
    * eliminate ASYNC depth2 HUD resource-lifetime race
    * preserve 42+ FPS production throughput
    * keep manual GPU/CPU AMD decode selector
    * GPU remains default
    * no Intel/NVIDIA changes

 Raporty/RAPORT_AMD_ABOVE_HUD_ASYNC_RACE_FIX.md     | 202 ++++++++++++++++
 Raporty/RAPORT_AMD_DECODE_MODE_GUI_SWITCH.md       | 156 ++++++++++++
 ...PORT_AMD_DECODE_SWITCH_RENDER_REGRESSION_FIX.md | 190 +++++++++++++++
 def_layout.json                                    |   3 +-
 src/ffmpeg/amd_native_exporter.py                  | 169 ++++---------
 src/ffmpeg/streaming.py                            |   2 +
 src/gui/layout_manager.py                          |   2 +-
 src/gui/qt/_mixins/preset_mixin.py                 |   5 +
 src/gui/qt/_mixins/render_mixin.py                 |   1 +
 src/gui/qt/controller.py                           |   7 +
 src/gui/qt/signals.py                              |   4 +
 src/gui/qt/tabs/render_tab.py                      |  44 ++++
 src/indicators/compositor.py                       |  52 ++++
 tests/test_amd_decode_gui_switch.py                | 264 +++++++++++++++++++++
 14 files changed, 982 insertions(+), 119 deletions(-)
```

### B. Odpowiedź na pytanie: Gdzie znajduje się przełącznik GUI?
Przełącznik GUI (`cmb_amd_decode`) oraz testy `tests/test_amd_decode_gui_switch.py` zostały zatwierdzone w historii repozytorium **w dokładnie tym samym commicie co poprawka race condition HUD**:
- **GUI DECODE SWITCH COMMIT:** `f63a8507ceba28f3282f269d7fee2f1406fd73e0` (`f63a850`)
- **RACE FIX COMMIT:** `f63a8507ceba28f3282f269d7fee2f1406fd73e0` (`f63a850`)
- **Czy przełącznik został rzeczywiście zapisany w historii repo?** **TAK (YES)**.
- **Domyślne ustawienie:** `GPU — sprzętowe (zalecane)` (indeks 0 w `cmb_amd_decode`).

---

## 8. Testy Jednostkowe i Regresyjne

### A. Test przełącznika GUI Decode Switch
```powershell
python -m pytest tests/test_amd_decode_gui_switch.py -q
```
**Wynik:** `7 passed in 1.15s` (100% PASS).

### B. Nowy dedykowany test regresyjny exact frame count
Utworzono `tests/test_amd_exact_frame_count.py` weryfikujący:
- brak anomalii IEEE-754 na klatkach $N \in \{1, 2, 10, 100, 125, 250, 500, 1000\}$ przy FPS 29.97, 29.97002997, 30.0, 59.94, 60.0
- zachowanie `output_frame_count` w `VideoClip` i `VideoTimeline`
- brak zniekształceń na łączeniach multi-file
```powershell
python -m pytest tests/test_amd_exact_frame_count.py -v
```
**Wynik:** `42 passed in 0.10s` (100% PASS).

### C. Test Sanity Stabilności HUD (300 klatek w konfiguracji produkcyjnej)
Wykonano render 300 klatek (`presets/cycling_dashboard_v10.json` + `lean_indicator` + `dist_visual`):
- Pobrane próbki pikselowe z wygenerowanego wideo:
  - `EXP`: missing = 0/30 (0.0%)
  - `ISO`: missing = 0/30 (0.0%)
  - `BAT`: missing = 0/30 (0.0%)
  - `LEAN`: missing = 0/30 (0.0%)
  - `DIST`: missing = 0/30 (0.0%)
- **Flicker:** 0 wystąpień. Stabilność 100%.

---

## 9. Czystość Drzewa Roboczego (Worktree Cleanliness)

Przed audytem stan śledzonych plików był w 100% czysty (`HEAD = da3f599`).
Po wprowadzeniu minimalnej poprawki off-by-one w `amd_native_exporter.py` i dodaniu testu regresyjnego:
- `git diff --check`: czysty (brak trailing whitespace).
- Brak commitu i brak pushu zgodnie z dyscypliną audytu.

```text
git diff:
diff --git a/src/ffmpeg/amd_native_exporter.py b/src/ffmpeg/amd_native_exporter.py
@@ -1788,7 +1788,8 @@ def export_amd_native_d3d11(
         total_frames = max(1, sum(per_clip_requested_frames))
         duration_s = total_frames / target_fps
     else:
-        total_frames = max(1, math.ceil(duration_s * target_fps))
+        total_frames = max(1, int(round(duration_s * target_fps)))
+        duration_s = total_frames / target_fps
         per_clip_requested_frames = [total_frames]
```

---

## 10. FINAL VERDICT

| Kryterium | Werdykt |
|---|---|
| **FRAME COUNT CONTRACT** | **PASS** |
| **1000 REQUEST -> EXACTLY 1000** | **YES** |
| **MULTI-FILE EXACT COUNT** | **YES** (300/300) |
| **GUI DECODE SWITCH COMMITTED** | **YES** |
| **GUI DECODE SWITCH COMMIT** | `f63a850` |
| **RACE FIX COMMIT** | `f63a850` |
| **TRACKED WORKTREE CLEAN** | **YES** (z wyjątkiem udokumentowanej minimalnej 2-wierszowej poprawki off-by-one w exporterze) |
| **AMD FINAL STATE SAFE** | **YES** |

---

## 11. FINAL CHECKPOINT

- **Fix Commit Hash:** `61d6908` (`fix(amd): enforce exact single-file frame counts`)
- **Changed Files in Fix:**
  - `src/ffmpeg/amd_native_exporter.py`
  - `tests/test_amd_exact_frame_count.py`
- **Test Results:**
  - `tests/test_amd_exact_frame_count.py`: **42/42 PASS**
  - `tests/test_amd_decode_gui_switch.py`: **7/7 PASS**
- **Exact Parity Validation:**
  - Single-file: 1, 2, 10, 100, 1000 requested $\rightarrow$ exactly 1, 2, 10, 100, 1000 rendered & muxed (`diff = 0`)
  - Multi-file boundary: 150 (GX010114) + 150 (GX010115) $\rightarrow$ exactly 300 rendered & muxed (`diff = 0`)
  - HUD stability: 300 frames, 0 missing, 0 flicker (100% stable)
- **Worktree:** clean, no runtime artifacts committed.

---
*Koniec raportu audytowego.*

