# Raport: ETAP 10U — finalna walidacja `AMD_ABOVE_UPLOAD_BUFFER_MODE=DIRECT`

**Data pomiaru:** 2026-08-23
**Typ zadania:** `WALIDACJA GPU` (final A/B COPY vs DIRECT + flip produkcyjnego defaultu)
**Agent:** GitHub Copilot (DeepSeek V4 Flash)
**Preset bazowy:** `presets/cycling_dashboard_v10.json`
**Materiał testowy:** `Video/GX010115.MP4` + `Video/GX010115.json` + `Video/Jazda_na_rowerze_w_porze_lunchu.fit` (offset +2.000 s, nie uruchamiano ponownie SmartSync)
**Benchmark:** AMD Native D3D11VA + AMF HEVC, 1280×720 @ 60 FPS, 120 klatek, `AMD_ABOVE_DIRTY_MODE=EXACT`
**Status:** `AMD ABOVE DIRECT UPLOAD: VALIDATED + DEFAULT`

---

## 1. Aktualny kod 10S (potwierdzony, nie przepisany)

```python
_ABOVE_DIRTY_MODE_DEFAULT = "EXACT"
_ABOVE_UPLOAD_BUFFER_MODE_DEFAULT = "DIRECT"   # (flip w tym etapie, patrz §22/§23)

def _resolve_above_upload_buffer_mode() -> str:  # COPY | DIRECT; unknown -> COPY (fail-safe)
def _above_region_pointer(r_bytes, mode):        # DIRECT: cast(c_char_p(bytes), POINTER(c_uint8)); COPY: from_buffer_copy
```

Kontrakt natywny (bez zmian): `telem_amd_update_above_region` → `UpdateAboveRegion` → `UpdateSubresource` kopiuje dane synchronicznie przed return; wskaźnik żyje tylko na czas wywołania, `r_bytes` referencjonowane przez zmienną pętli. ABI/argtypes/DLL bez zmian.

---

## 2. GPU availability

W 10S `ID3D11VideoDevice` był niedostępny. W 10U **GPU jest dostępne** — znany-dobry harness `benchmark_etap10g_amd.py` ukończył pełny eksport:

```text
Encoded frames: 120, Muxed frames: 120, TRUE FPS: 14.27, RENDER FPS: 39.26, Result: True
```

Brak `D3D11CreateDevice failed` / `ID3D11VideoDevice unavailable` / `telem_amd_create NULL`.

---

## 3. COPY determinism (§6)

```text
COPY#1 vs COPY#2 (encoder determinism control):
  frames_diff = 0/120
  diff_pixels = 0/110592000 (0.00000%)
  max_delta   = 0
```

**PASS** — finalne video jest deterministyczne i może służyć jako byte-parity oracle.

---

## 4. COPY vs DIRECT region parity (§8)

Dla każdego runu identyczne (profil `etap8n`):

```text
regions_per_frame        = 1.0
candidate_pixels_per_frame = 622700
uploaded_pixels_per_frame = 543600
uploaded_bytes_per_frame  = 2174400   (2.17 MB)
stride                   = rw * 4     (ta sama geometria regionu)
```

**PASS** — COPY == DIRECT dla count/x/y/w/h/pixels/bytes/stride.

---

## 5. COPY vs DIRECT final GPU parity (§7)

Decoded RGBA, wszystkie 120 klatek:

```text
COPY#1 vs DIRECT#1 (final parity):        frames_diff=0/120 diff_pixels=0 max_delta=0
COPY#2 vs DIRECT#2 (cross-check):         frames_diff=0/120 diff_pixels=0 max_delta=0
DIRECT#1 vs DIRECT#2 (direct determinism): frames_diff=0/120 diff_pixels=0 max_delta=0
```

**PASS** — finalny raster (video + mapa z AA + HUD + ABOVE) identyczny we wszystkich 120 klatkach.

---

## 6. Byte integrity (§9)

Runtime verification w harnessie (`--verify`, monkeypatch `_above_region_pointer` w DIRECT): dla **każdej z 120 klatek** odczyt `ctypes.string_at(ptr, len(r_bytes)) == r_bytes`:

```text
frames_checked = 120
errors         = 0
```

**PASS** — bajty widziane przez wskaźnik DIRECT są identyczne z `r_bytes` (length, zawartość) bezpośrednio przed natywnym wywołaniem. Weryfikacja wyłącznie diagnostyczna (harness), nie w pętli produkcyjnej.

---

## 7. Lifetime contract (§11)

- `r_bytes` (immutable bytes) referencjonowane przez zmienną pętli przez całe wywołanie natywne.
- Natywne `UpdateSubresource` kopiuje synchronicznie przed return → wskaźnik nie jest używany po wywołaniu.
- Brak przechowywania wskaźnika do późniejszego użycia; ABI bez zmian.
- Runtime verify (120/120) potwierdza brak use-after-free/invalidation.

---

## 8. Embedded-zero test (§10)

Test 10S `test_direct_pointer_byte_integrity_with_embedded_zeros` (payload ~3 MB z wbudowanymi `0x00`) — PASS. Runtime verify 10U na prawdziwym payloadzie 2 174 400 B (zawiera zera RGBA) — PASS. Natywna strona używa jawnej długości `rw*rh*4`, nie semantyki null-terminated.

---

## 9. Ghosting (§12)

Final GPU parity byte-identyczny (COPY == DIRECT) → `ClearPreviousAboveMap` kasuje identyczne obszary. Objęte przypadki w realnym materiale: marker Distance, marker Slope, kursor HR/Cadence, Compass, dynamiczna szerokość tekstu. **Brak ghostingu / stale pixels** (diff_pixels=0 w finalnym rastrze).

---

## 10. Segment Bar regression (§13)

Pełny v10 zawiera aktualne Segment Bars (10T/10T2). COPY vs DIRECT parity 120/120 byte-identyczne → Segment Bar rendering **niezależny** od trybu uploadu. Renderer Segment Bar niezmieniony w tym etapie.

## 11. Map regression (§14)

Mapa z ETAPU 10T (track AA, outline) zawarta w finalnym rastrze; COPY vs DIRECT 120/120 identyczne → map/track line/track AA/map-under-ABOVE bez wpływu trybu uploadu.

---

## 12. Frame accounting (§15)

Wszystkie runy (COPY#1/#2, DIRECT#1/#2, SCAN+DIRECT):

```text
requested = 120, decoded = 120, native_processed = 120,
amf_submitted = 120, amf_output = 120, muxed = 120
→ 120 / 120 / 120 / 120 / 120 / 120 (PASS)
```

Zero drop/duplicate/missing.

---

## 13–16. Benchmark interleaved (§16)

Kolejność (determinism control wymaga dwóch COPY obok siebie; interleave C,D,D,C):

```text
COPY#1   (determinism + baseline)
COPY#2   (determinism)
DIRECT#1 (byte-integrity verify — timing zafałszowany przez string_at, wyłączony z timingu)
DIRECT#2 (czysty DIRECT timing)
```

### 13. COPY run1
```text
above_upload_buffer_prepare  avg=0.744  med=0.737  p95=0.942
above_region_upload          avg=0.292
above_region_to_bytes        avg=0.924  med=0.854  p95=1.277
above_exact_crop             avg=0.644
above_total                  avg=12.885 med=11.742 p95=23.968
RENDER FPS = 39.89   TRUE FPS = 13.84
```

### 14. DIRECT run1 (verify — tylko dowód byte integrity, nie timing)
```text
frames_checked=120 errors=0
```

### 15. DIRECT run2 (czysty)
```text
above_upload_buffer_prepare  avg=0.017  med=0.016  p95=0.022
above_region_upload          avg=0.367
above_region_to_bytes        avg=0.829  med=0.763  p95=1.167
above_exact_crop             avg=0.589
above_total                  avg=12.634 med=10.990 p95=24.142
RENDER FPS = 41.74   TRUE FPS = 14.56
```

### 16. COPY run2
```text
above_upload_buffer_prepare  avg=0.702  med=0.702  p95=0.913
above_region_upload          avg=0.289
above_region_to_bytes        avg=0.936  med=0.768  p95=1.457
above_exact_crop             avg=0.609
above_total                  avg=13.102 med=11.281 p95=26.313
RENDER FPS = 38.92   TRUE FPS = 14.29
```

---

## 17. Upload-buffer timings (§18) — najważniejsza metryka

```text
COPY   above_upload_buffer_prepare:  avg ≈ 0.72 ms/frame   (0.744 / 0.702)
DIRECT above_upload_buffer_prepare:  avg ≈ 0.017 ms/frame  (0.0165)
```

**Zysk w samym prepare: ≈ 0.70 ms/frame** (zgodne z mikroprofilem 10S ~0.59–0.74 ms).

## 18. Real ms/frame delta (§19)

```text
above_total:  COPY avg (12.885+13.102)/2 = 12.99 ms
              DIRECT avg                 = 12.63 ms
              Δ ≈ −0.36 ms/frame (szum między runami w above_region_upload)
```

## 19. RENDER FPS delta

```text
COPY   ≈ 39.40 fps (avg 39.89 / 38.92)
DIRECT ≈ 41.74 fps
Δ ≈ +2.3 fps
```

## 20. TRUE FPS delta

```text
COPY   ≈ 14.07 fps (avg 13.84 / 14.29)
DIRECT ≈ 14.56 fps
Δ ≈ +0.5 fps
```

Zysk end-to-end jest **realny ale umiarkowany**: wąskim gardłem pozostaje `above_compose` (~11–12 ms) i pipeline encode, nie prepare bufora.

---

## 21. SCAN+DIRECT smoke (§25)

```text
AMD_ABOVE_DIRTY_MODE=SCAN, AMD_ABOVE_UPLOAD_BUFFER_MODE=DIRECT
decoded=120 submitted=120 encoded=120 muxed=120
above_upload_buffer_prepare avg = 0.0145 ms
RENDER FPS = 42.65  TRUE FPS = 14.43
```

**PASS** — DIRECT nie jest związany tylko z EXACT. CANDIDATE nie benchmarkowany (§26).

---

## 22. Changed production files

| Plik | Zmiana |
|---|---|
| `src/ffmpeg/amd_native_exporter.py` | `_ABOVE_UPLOAD_BUFFER_MODE_DEFAULT = "COPY"` → `"DIRECT"` + komentarz 10U. |
| `tests/test_amd_above_upload_buffer_etap10s.py` | test defaultu zaktualizowany: `test_default_mode_is_direct_after_gpu_parity_validated`. |

**Brak innych zmian produkcyjnych** (§29 — diff = flip defaultu + komentarz).

---

## 23. Final default (§22)

```python
_ABOVE_UPLOAD_BUFFER_MODE_DEFAULT = "DIRECT"
```

Ustawione po przejściu wszystkich bramek: COPY determinism PASS, COPY vs DIRECT final GPU parity PASS (120/120), region geometry parity PASS, byte integrity PASS (120/120), ghosting PASS, map parity PASS, frame accounting PASS, SCAN+DIRECT smoke PASS.

## 24. Fallback behavior (§23/§24)

```text
AMD_ABOVE_UPLOAD_BUFFER_MODE=COPY  → COPY  (manual fallback, zachowany)
AMD_ABOVE_UPLOAD_BUFFER_MODE=direct→ DIRECT
AMD_ABOVE_UPLOAD_BUFFER_MODE=XYZ   → COPY  (fail-safe, warning; decyzja konserwatywna §24)
```

Testy 10S (`test_copy_and_direct_modes_accepted`, `test_unknown_mode_falls_back_to_copy`) — PASS.

---

## 25. Remaining major bottleneck

```text
above_compose   ≈ 11–12 ms/frame   (CPU_ABOVE_MAP; dominuje całkowity budżet)
above_region_to_bytes ≈ 0.83–0.94 ms   (RGBA → bytes; cel na przyszłość, poza zakresem 10U §20)
```

`above_compose` pozostaje głównym celem (zgodnie z AGENTS §36 — po zamknięciu chart seek/history). Zgodnie z poleceniem **nie przechodzę do `above_compose`**.

---

## NVIDIA (§27)

```
NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.
```

---

## 31. Final status

```text
AMD ABOVE DIRECT UPLOAD: VALIDATED + DEFAULT
```

(Wszystkie correctness gates PASS, default przełączony na DIRECT. Zysk end-to-end umiarkowany — FPS bounded przez compose/encode — ale prepare spada z ~0.72 ms do ~0.017 ms/frame.)

---

## 32. Repo safety

- `git diff --check` → PASS (tylko pre-existing LF/CRLF warnings).
- Tymczasowe pliki (harness, compare, extractor, MP4, profile JSON) **usunięte** przed zakończeniem.
- Zmienione pliki wyłącznie: `amd_native_exporter.py` (default), `test_amd_above_upload_buffer_etap10s.py`.
