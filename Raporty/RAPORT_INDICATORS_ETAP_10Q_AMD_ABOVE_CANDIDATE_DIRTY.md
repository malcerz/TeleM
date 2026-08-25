# Raport: ETAP 10Q — AMD ABOVE dirty-region — bezpieczny CANDIDATE path

**Data pomiaru:** 2026-08-22
**Typ zadania:** `IMPLEMENTACJA` (pierwszy etap implementacyjny po audycie 10P)
**Agent:** GitHub Copilot (DeepSeek V4 Flash)
**Preset bazowy:** `presets/cycling_dashboard_v10.json`
**Materiał testowy:** `Video/GX010115.MP4` + `Video/GX010115.json` + `Video/Jazda_na_rowerze_w_porze_lunchu.fit`
**Benchmark:** AMD Native D3D11VA + AMF HEVC, 1280×720 @ 60 FPS, 120 klatek
**Zakres:** `src/ffmpeg/amd_native_exporter.py` + nowe targetowane testy (wyłącznie)

---

## 1. Implementation summary

Wdrożono runtime contract `AMD_ABOVE_DIRTY_MODE` dla warstwy `CPU_ABOVE_MAP`:

- `SCAN` — historyczna ścieżka alpha-scan (candidate crop → `getchannel("A")` → `getbbox()` → tight crop → `tobytes`). **Produkcyjny default.**
- `CANDIDATE` — candidate crop → `tobytes` (pomija alpha scan i final crop). **Env-opt-in DIAGNOSTYCZNY — ETAP 10Q udowodnił, że NIE jest bezpieczny produkcyjnie.**

Zmiany produkcyjne (tylko `amd_native_exporter.py`):

1. `_extract_above_regions(above_full, candidate_clusters, mode)` — wydzielona, testowalna funkcja ekstrakcji regionów ABOVE (SCAN/CANDIDATE), z semantyką identyczną do inline'owego kodu sprzed 10Q dla `SCAN`.
2. `_ABOVE_DIRTY_MODE_DEFAULT = "SCAN"` + `_resolve_above_dirty_mode()` — parsowanie env z fail-safe (nieznana wartość oraz zarezerwowany `EXACT` → `SCAN` + pojedynczy warning).
3. Pętla produkcyjna ABOVE wywołuje `_extract_above_regions`; startup print `AMD_ABOVE_DIRTY_MODE: <mode>`.
4. Profil JSON (`etap8n`) zawiera `above_dirty_mode`.

`SCAN` jest kompletnie zachowany (byte-identical z kodem sprzed 10Q — potwierdzone testem). Kod alpha scan NIE został usunięty. `EXACT` (Variant A) zarezerwowany w dokumentacji, bez martwej implementacji.

---

## 2. SCAN contract

```
above_full
→ crop(candidate)
→ getchannel("A")
→ getbbox()
→ crop(tight)
→ tobytes()
→ ctypes copy
→ UpdateSubresource
```

Jest to dokładnie historyczna ścieżka produkcyjna (pre-10Q). Test `test_scan_path_matches_legacy_inline_logic` potwierdza byte-identyczność z ręcznie odtworzoną logiką inline.

---

## 3. CANDIDATE contract

```
above_full
→ crop(candidate)
→ tobytes()
→ ctypes copy
→ UpdateSubresource
```

Pomija `getchannel("A")`, `getbbox()`, `crop(tight)`. Uploaduje pełny candidate region (bbox + pad 16).

---

## 4. Fallback behavior

- `AMD_ABOVE_DIRTY_MODE` nieustawione → `SCAN` (default).
- `SCAN` / `CANDIDATE` (dowolna wielkość liter) → tryb zgodny.
- `EXACT` (zarezerwowane) → warning + `SCAN`.
- Nieznana wartość (np. `XYZ`) → warning + `SCAN` (fail-safe, brak crash).
- `SCAN` pozostaje kompletna ścieżka fallback; alpha scan nie jest usuwany.

---

## 5. Changed production code

| Plik | Zmiana |
|---|---|
| `src/ffmpeg/amd_native_exporter.py` | `_extract_above_regions` (nowa), `_ABOVE_DIRTY_MODE_DEFAULT`, `_resolve_above_dirty_mode`, wywołanie w pętli ABOVE, startup diagnostic, pole `above_dirty_mode` w `etap8n`. |

NIE zmieniono: `compositor.py`, `rotated_paste.py`, rendererów, natywnego DLL, C++, NVIDIA, FIT, GUI, presetów, mapy, SmartSync.

---

## 6. A/B visual parity — CPU (deterministyczny pre-encode point)

**Punkt porównania:** deterministyczny pre-encode output — canvas `above_full` (CPU) + regiony ekstrahowane dokładnie produkcyjną funkcją `_extract_above_regions` na realnych 120 klatkach v10. To najniższy wspólny punkt deterministyczny reprezentujący finalny raster warstwy ABOVE (encode MP4 jest w pełni deterministyczny — potwierdzone kontrolą, patrz §7).

**Wynik (120 klatek, realne telemetry):**

```
parity_fail = 0
ghost_fail  = 0
```
- Oba tryby rekonstruują identyczny overlay ABOVE (`recon.tobytes() == above_full.tobytes()`).
- Każdy nieprzezroczysty piksel CANDIDATE jest wewnątrz regionu SCAN (CANDIDATE = SCAN content + padding).
- Padding CANDIDATE ma `alpha == 0` (zero nieprzezroczystych pikseli poza tight regionem).

**Canvas determinizm:** zrzuty `above_full` dla klatki 30 w trybie SCAN i CANDIDATE są **byte-identical** (potwierdzone diagnostyką).

---

## 7. A/B visual parity — FINAL raster (GPU) = **FAILED**

Porównano finalne klatki MP4 (decoded RGBA) między `SCAN` a `CANDIDATE`.

**Kontrola determinizmu enkodera:** `SCAN#1 vs SCAN#2` (dwa świeże procesy) → **byte-identical** (`different_bytes=0, max_delta=0` dla klatek 30/60/90). Enkodowanie AMF + mapa + HUD są deterministyczne.

**SCAN vs CANDIDATE (świeże procesy):**

```
frame 30: different_bytes=1899677/3686400  max_delta=199
frame 60: different_bytes=1673522/3686400  max_delta=255
frame 90: different_bytes=1660154/3686400  max_delta=255
```

**Lokalizacja różnicy (frame 30):**
- różnica skoncentrowana w **padding candidate** (57 982 z 79 100 px = **73%** paddingu).
- `alpha` kanału identyczny; różnica wyłącznie RGB.
- różnica poza regionem ABOVE (propagacja enkodera) = 217 124 px.

**Kluczowa obserwacja (frame probe):**
```
frame 0:  total_diff=0      padding_diff=0      ← pierwsza klatka (brak clear poprzedniej)
frame 1:  total_diff=6799   padding_diff=2565
frame 30: total_diff=738192 padding_diff=57982
```
Klatka 0 jest **identyczna** — różnica pojawia się dopiero od klatki 1 i rośnie. To jednoznacznie wskazuje na interakcję z **`ClearPreviousAboveMap`** (erase region), a NIE z uploadem/blendem zawartości.

**Root cause (mechanizm):**
1. W `CANDIDATE` region uploadowany w klatce N = duży prostokąt candidate (958×650; SCAN: tight 906×600).
2. Na GPU `m_abovePrevRegions = m_aboveRegions` (dokładnie to, co uploadowano) → w klatce N+1 `ClearPreviousAboveMap` zeruje **większy** obszar candidate.
3. Redraw mapy (`ResampleAndBlendMap`) pokrywa tylko `map_dst`; padding poza `map_dst` NIE jest odtwarzany.
4. Blend ABOVE (mode 1) traktuje `src.a == 0` jako no-op → padding pozostaje wyzerowany → w tym obszarze final raster różni się od SCAN (gdzie padding nigdy nie był czyszczony).

Wniosek: **sama no-op semantyka blendu nie wystarcza** — większy region uploadu zmienia kontrakt kasowania GPU (`ClearPreviousAboveMap`), co łamie parity finalnego rastra.

---

## 8. Ghosting tests

- CPU-level (deterministyczny): `uploaded region ⊇ content` dla obu trybów, 120 klatek, w tym:
  - content rośnie / maleje (wąski → szeroki, szeroki → wąski),
  - `None → value` / `value → None` (test: region pokrywa poprzedni content → GPU clear kasuje stary raster).
- GPU-level: **FAILED przez mechanizm z §7** — eraze region w CANDIDATE kasuje obszar, którego nie odtwarza mapa; w praktyce to forma rozjechania się "previous-frame clearing" z mapą (kasowanie większego obszaru niż w SCAN). Nie jest to klasyczny ghosting ABOVE (stara zawartość ABOVE jest kasowana), ale jest to zmiana finalnego rastra → traktowane jako niezgodność erase kontraktu.

---

## 9. None transitions

CPU: przetestowane — `value → None` daje w SCAN brak regionu (nic nie rysowane), w CANDIDATE region z zerami (transparent, GPU no-op). `None → value` pokryte coverage testem. Brak starej zawartości na poziomie CPU. GPU-level: objęte §7 (failure nie dotyczy samych przejść None, tylko eraze regionu).

W oknie 2 s realnego materiału (120 klatek) nie zaobserwowano przejścia None (wartości ciągłe) — sprawdzone i zaraportowane.

---

## 10. Overlap

CPU test `test_pixel_parity_overlapping_widgets`: 2 nakładające się widgety → 1 klaster → oba tryby rekonstruują identyczny overlay. GPU-level objęte §7 (failure mechanizmu eraze, nie overlap).

---

## 11. Altitude rotation = 90

CPU test `test_pixel_parity_rotation_90`: widget z rotation=90 (swapped raster, transparent corners) → oba tryby identyczny overlay; SCAN przycina narożniki (`uploaded < candidate`). Realny `alt_visual` obecny w 120/120 klatek parity run. GPU-level objęte §7.

---

## 12. Map underneath ABOVE

CPU test `test_map_underneath_transparent_padding_preserved`: transparentny padding CANDIDATE nie zmienia warstwy pod spodem (symulowana mapa). **Jednak to GPU-level interakcja z `ClearPreviousAboveMap` (kasowanie mapy pod paddingiem poza `map_dst`) jest dokładnie źródłem failure** — patrz §7. To jest najważniejszy wniosek: "map underneath" jest bezpieczne dla blendu (src.a==0 → no-op), ale NIE jest bezpieczne dla eraze poprzedniej klatki, gdy region rośnie.

---

## 13. SCAN benchmark (świeży pomiar, 120 klatek, v10)

```
above_bbox_tracking      avg=0.059 med=0.054 p95=0.083
above_candidate_crop     avg=0.649 med=0.616 p95=0.858
above_local_alpha_scan   avg=0.324 med=0.287 p95=0.546
above_final_crop         avg=0.462 med=0.426 p95=0.683
above_region_to_bytes    avg=0.910 med=0.831 p95=1.274
above_region_upload      avg=0.277 med=0.222 p95=0.378
above_bbox_crop          avg=1.494 med=1.395 p95=2.248
above_total              avg=14.675 med=12.501 p95=25.176

regions_per_frame        = 1.0
candidate_pixels         = 622700
scanned_pixels           = 622700
uploaded_pixels          = 543600
uploaded_bytes           = 2174400 (~2.17 MB)

RENDER FPS = 38.646     TRUE FPS = 13.775
```

---

## 14. CANDIDATE benchmark (świeży pomiar, ta sama sesja)

```
above_bbox_tracking      avg=0.064 med=0.055 p95=0.084
above_candidate_crop     avg=0.645 med=0.607 p95=0.785
above_local_alpha_scan   avg=0.000 med=0.000 p95=0.000   ← pominięte
above_final_crop         avg=0.000 med=0.000 p95=0.000   ← pominięte
above_region_to_bytes    avg=1.024 med=0.965 p95=1.277
above_region_upload      avg=0.292 med=0.241 p95=0.390
above_bbox_crop          avg=0.709 med=0.662 p95=0.858
above_total              avg=14.149 med=12.347 p95=25.437

regions_per_frame        = 1.0
candidate_pixels         = 622700
scanned_pixels           = 0
uploaded_pixels          = 622700
uploaded_bytes           = 2490800 (~2.49 MB)

RENDER FPS = 40.495     TRUE FPS = 14.607
```

---

## 15. Uploaded pixel/byte delta

```
uploaded_pixels:  543600 → 622700   (+79 100 px, +14.6%)   (zgodnie z oczekiwaniem 10P)
uploaded_bytes:   2174400 → 2490800 (+0.32 MB, +14.6%)
scanned_pixels:   622700 → 0                                 (alpha scan całkowicie pominięty)
```

---

## 16. CPU time delta

```
above_bbox_crop:      1.494 → 0.709  (Δ = −0.785 ms/frame avg; med −0.733)
above_region_to_bytes: 0.910 → 1.024  (Δ = +0.114 ms/frame, większy region)
NET (bbox_crop+tobytes): 2.404 → 1.733 (Δ = −0.671 ms/frame avg)
above_region_upload:   0.277 → 0.292  (Δ = +0.015, więcej bajtów)
```

Zysk **0.671 ms/frame avg** mieści się w oczekiwanym zakresie 0.6–0.8 ms (zadanie §21: "nie wymagaj dokładnie 0.74").

---

## 17. RENDER FPS delta

```
RENDER FPS: 38.646 → 40.495   (Δ = +1.85 FPS, +4.8%)
```

## 18. TRUE FPS delta

```
TRUE FPS:   13.775 → 14.607   (Δ = +0.83 FPS, +6.0%)
```

---

## 19. Frame accounting

Oba tryby:

```
decoded = 120   submitted = 120   encoded = 120   muxed = 120
→ 120 / 120 / 120 / 120  (100% PASS, 0 braków, 0 duplikatów)
```

---

## 20. Tests

Nowy plik: `tests/test_amd_above_dirty_mode_etap10q.py` (12 testów) + regresja istniejących:

```
tests/test_amd_above_dirty_mode_etap10q.py     12 passed
tests/test_amd_native_above_dirty_bbox.py      (regresja) passed
tests/test_etap8n_multi_region_above.py        (regresja) passed
tests/test_amd_native_ordered_map.py           (regresja) passed
tests/test_amd_native_ordered_map_clear.py     (regresja) passed
SUMA: 37 passed
```

Pokrycie testów (zadanie §28): parsowanie trybów, nieznany tryb → fallback SCAN + warning, `EXACT` zarezerwowany, SCAN zachowany byte-identical, CANDIDATE pomija alpha scan, parity pikseli, ghosting (coverage), None transitions, Altitude rotation=90, overlap, map-underneath, frame accounting (z benchmarku).

Nie uruchamiano pełnego suite (zgodnie z §28 "Nie uruchamiaj pełnego suite").

---

## 21. Final default mode

```
AMD_ABOVE_DIRTY_MODE_DEFAULT = "SCAN"
```

**SCAN pozostaje produkcyjnym defaultem** (zadanie §5: "Jeżeli jakikolwiek test poprawności nie przejdzie: default = SCAN i raportuj problem"). `CANDIDATE` pozostaje dostępny przez env jako tryb diagnostyczny (z wyraźnym ostrzeżeniem w kodzie, że NIE jest bezpieczny).

---

## 22. Remaining bottleneck

Po ETAP 10Q pozostaje:

```
above_candidate_crop  ~0.65 ms
above_local_alpha_scan ~0.32 ms   (SCAN)
above_final_crop       ~0.46 ms   (SCAN)
above_region_to_bytes  ~0.91 ms
above_bbox_crop        ~1.49 ms   (SCAN, avg)
```

Główny bottleneck bez zmian: `above_bbox_crop + above_region_to_bytes ≈ 2.40 ms/frame` w SCAN (produkcyjnym).

---

## 23. Recommendation whether Variant C or Variant A is worth doing next

**Variant C' (CANDIDATE — upload candidate bez skanu): NIE jest opłacalny/wykonalny bez zmiany GPU clear contract.** Zysk 0.671 ms jest realny, ale łamie parity finalnego rastra przez `ClearPreviousAboveMap` (kasowanie większego obszaru niż odtwarza mapa). Wymagałby zmian w natywnym DLL (osobny kontrakt eraze: clear = tight region, upload = candidate) — poza obecnym zakresem.

**Variant C (redukcja kopii — reuse bufora ctypes `from_buffer_copy`): nadal wart ~0.2–0.3 ms, ortogonalny do eraze — można łączyć z A.**

**Variant A (EXACT tight bbox propagation): TO jest rekomendowany następny etap.** Kluczowy wniosek z 10Q: bezpieczny jest wyłącznie upload **tight** regionów (identyczny geometrycznie ze SCAN → identyczny `ClearPreviousAboveMap` → bezpieczny eraze). Variant A usuwa koszt alpha scan (~0.32 ms) i final crop (~0.46 ms) oraz redukuje podwójny crop, uploadując tight region policzony bez skanowania. Oczekiwany zysk ~1.0–1.1 ms/frame (z 10P), bez zmiany kontraktu GPU.

**Rekomendacja:** następny etap = **Variant A** (exact tight bbox), a NIE CANDIDATE.

---

## 24. Final status

```
AMD ABOVE CANDIDATE DIRTY: FAILED — SCAN REMAINS DEFAULT
```

Uzasadnienie:
- **pixel parity (final GPU raster): FAIL** — deterministyczna, rosnąca różnica w padding candidate (73% paddingu w klatce 30), spowodowana wzrostem eraze regionu `ClearPreviousAboveMap` ponad pokrycie mapy (`map_dst`).
- **ghosting / erase contract: FAIL** — eraze kasuje obszar nieodtwarzany przez mapę.
- **frame accounting: PASS** (120/120/120/120).
- **performance: PASS** (zysk 0.671 ms/frame, RENDER FPS +4.8%, TRUE FPS +6.0%).

Ponieważ istnieje różnica wizualna, zgodnie z zadaniem §31 obowiązuje:

```
AMD ABOVE CANDIDATE DIRTY: FAILED — SCAN REMAINS DEFAULT
```

---

## Repo safety

```
git status     — brak śladów po tym zadaniu poza: zmiana amd_native_exporter.py, nowy test, raport; temp scratch usunięte
git diff       — tylko zamierzone zmiany ETAP 10Q (potwierdzone)
git diff --check — brak błędów whitespace
```

Tymczasowa instrumentacja (benchmark, parity, control, diag dump, MP4/profile/JSON) została **usunięta przed zakończeniem** (potwierdzone `Get-ChildItem scratch -Filter etap10q*` → 0).

NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.
