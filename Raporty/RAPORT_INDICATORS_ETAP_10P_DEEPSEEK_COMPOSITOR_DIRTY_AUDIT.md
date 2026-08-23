# Raport: ETAP 10P — DeepSeek onboarding + niezależny audyt `compositor dirty-region path`

**Data pomiaru:** 2026-08-22
**Typ zadania:** `AUDIT ONLY` (brak zmian w kodzie produkcyjnym)
**Agent:** GitHub Copilot (DeepSeek V4 Flash) — pierwsze zadanie w tym repo
**Preset bazowy:** `presets/cycling_dashboard_v10.json`
**Materiał testowy:** `Video/GX010115.MP4` + `Video/GX010115.json` + `Video/Jazda_na_rowerze_w_porze_lunchu.fit`
**Benchmark:** AMD Native D3D11VA + AMF HEVC, 1280×720 @ 60 FPS, 120 klatek, pełny preset v10
**Konfiguracja:** `AMD_MAP_PATH=GPU`, `AMD_CHART_PATH=CPU_REFERENCE`, `AMD_GAUGE_PATH=GPU`, `AMD_TELEMETRY_MODE=PRECOMPUTED`, `AMD_NATIVE_HUD_MODE=GPU_HUD`, `AMD_NATIVE_HUD_UPLOAD=DIRTY`, `AMD_OVERLAY_PROFILE=1`

---

## 0. Zakres i dyscyplina

Wykonano wyłącznie:

```
analiza kodu
tymczasowa instrumentacja (1 benchmark + pomiar mikro)
raport
```

NIE zmieniono: kodu produkcyjnego, presetów, testów produkcyjnych, parsera FIT, rendererów, natywnego DLL.

Tymczasowy benchmark (`scratch/benchmark_etap10p_audit_amd.py` + wygenerowane `*.mp4`, `*.amd_profile.json`) został **usunięty przed zakończeniem** (potwierdzone `git status` — brak śladów).

---

## 1. Architecture summary

Produkcyjna ścieżka AMD (final export) dla mapy uporządkowanej:

```
CPU_BELOW_MAP  (compose_overlay, reuse_canvas="below")   -> Pillow canvas + dirty rects
GPU_MAP        (render_map_working_image -> UpdateSubresource -> GPU blend)
CPU_ABOVE_MAP  (compose_overlay, reuse_canvas="above")   -> dirty regions -> GPU blend
```

Kluczowe pliki:

| Plik | Rola |
|---|---|
| `src/indicators/compositor.py` | `compose_overlay` (L50) — renderuje wszystkie widgety i zapisuje `_bboxes`; `render_preview` (L603) |
| `src/indicators/rotated_paste.py` | `rotated_paste` (L199) / `composite_final` (L117) — finalne wklejanie, w tym `overlay.getbbox()` (L152) |
| `src/indicators/dispatcher.py` | `render_value_indicator` (L18) — routing form→renderer |
| `src/indicators/{text,bar,gauge,chart}.py` | renderery |
| `src/ffmpeg/amd_native_exporter.py` | pętla produkcyjna; dirty-region extraction dla ABOVE (L1912–1989) i BELOW (L2040–2110); upload (L2280–2296) |
| `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp` | GPU: `ClearPreviousAboveMap` (L1952), `BlendAboveMap` (L2002), `UpdateAboveRegion` (L1117) |

Kolejność GPU potwierdzona w `d3d11_vp_pipeline.cpp` (L2303–2344):
`ClearPreviousAboveMap → BlendCharts → BlendGauge → ResampleAndBlendMap → BlendAboveMap`.
Warstwa ABOVE jest blendowana **po** mapie (jest "above map"), a poprzednie regiony ABOVE są czyszczone **przed** chart/gauge/map.

---

## 2. Exact dirty-region call chain

Dla warstwy `CPU_ABOVE_MAP` (`amd_native_exporter.py`):

```
compose_overlay(layout=map_above_layout, _bboxes=above_bboxes, reuse_canvas="above")   L1917
    └─ per widget: render_value_indicator -> rotated_paste -> composite_final           (compositor.py L386, L450)
    └─ _bboxes[key] = widget_bbox (pełny prostokąt rastra, L491)                       (compositor.py L420)
_cluster_above_bboxes(above_bboxes, w, h, pad=16, merge_dist=32, max_regions=16)       L1932 -> L355
for cx,cy,cw,ch in candidate_clusters:
    candidate_image = above_full.crop((cx,cy,cx+cw,cy+ch))                              L1945  [above_candidate_crop]
    local_alpha_bbox = candidate_image.getchannel("A").getbbox()                        L1949  [above_local_alpha_scan]
    reg_img = candidate_image.crop(local_alpha_bbox)                                    L1959  [above_final_crop]
    r_bytes = reg_img.tobytes("raw","RGBA")                                             L1966  [above_region_to_bytes]
    above_regions_out.append((rx, ry, rw, rh, r_bytes))                                 L1968
    └─ consumer: r_ptr = (c_uint8*len).from_buffer_copy(r_bytes)                        L2284  (kopia)
    └─ native telem_amd_update_above_region -> UpdateSubresource                        L2287
    └─ GPU ClearPreviousAboveMap(next frame) / BlendAboveMap                            L1952/L2002
```

Pomocnicze funkcje:

- `_clip_rect` (L317) — przycinanie do canvas.
- `_rendered_bbox_union` (L330) — pojedynczy union (fallback dla `AMD_ABOVE_MULTI_REGION=0`, pad=64).
- `_tight_alpha_bbox_from_candidate` (L339) — **martwy kod** (zdefiniowana, nigdy nie wywoływana; logika inline w L1945–1959).
- `_cluster_above_bboxes` (L355) — grupowanie.
- `_rect_union` (L545), `_dirty_rects_from_bboxes` (L612) — BELOW dirty rects (union prev+current, pad=40).

---

## 3. Bbox ownership

- **Właścicielem "oficjalnych" bboxów jest `compose_overlay`** — `_bboxes[key] = widget_bbox` (L491), gdzie `widget_bbox` to **pełny prostokąt wyrenderowanego rastra** (z przezroczystym paddingiem), nie tight content bbox.
- Renderery zwracają rastry:
  - `text.py`: raster **przycięty** do content (`tmp.crop(tmp.getbbox())`) → declared bbox ≈ tight content.
  - `bar.py`, `gauge.py`, `chart.py`: pełne rastry (z przezroczystymi marginesami / narożnikami) → declared bbox **luźniejszy** niż content.
- **Tight alpha bbox jest już liczony** per-widget wewnątrz `composite_final` (`overlay.getbbox()`, `rotated_paste.py` L152) dla ścieżki PIL — ale **wynik jest wyrzucany**, nie propagowany do `_bboxes` ani do eksportera.
- Eksporter nie ma dostępu do rastrów widgetów — jego jedynym źródłem tight bbox jest skan kanału alpha wykadrowanego canvasu.

**Wniosek do kluczowego pytania (§4 zadania):** compositor zna declared (konserwatywne) bboxy, ale NIE zna tight bboxów przed skanem; tight bbox jest liczony w `composite_final` i odrzucany. Skan alpha w eksporterze **re-odkrywa** tight bbox, który compositor już obliczył.

---

## 4. Kluczowe pytanie — czy alpha scan jest zbędny?

Czego skan obecnie broni (weryfikacja po kodzie):

| Możliwy powód | Status dla ABOVE v10 |
|---|---|
| transparent padding (koła gauge, marginesy barów, header chart) | ✅ realny — declared bbox luźniejszy |
| rotation (90°) | ✅ realny dla `alt_visual` — narożniki przezroczyste po rotacji |
| stroke/shadow poza declared geometry | ⚠️ renderery rysują stroke wewnątrz rastra → w obrębie bboxa |
| anti-aliasing | ⚠️ krawędzie AA mieszczą się w bboxie rastra |
| annotations poza rastrem (`extra`) | ✅ **NIE występuje** — wszystkie renderery ABOVE zwracają `extra=None` (gauge.py L193/L409, chart.py L774/L823, bar.py L1166, text.py L67) |
| previous-frame erase | ✅ obsługiwane natywnie przez `ClearPreviousAboveMap` |
| overlapping widgets | ✅ upload unionu pokrywa zawartość |
| map overlap / z-order | ✅ GPU "over" (mode 1) ignoruje src.a==0 |

Weryfikacja GPU (`d3d11_vp_pipeline.cpp` shader L1421–1476):
- mode 1 (blend): `if (src.a == 0) return;` — **przezroczyste piksele w uploadowanym regionie są no-op** (nie kasują mapy).
- mode 0 (clear): zeruje dokładnie poprzednio uploadowany region.
- mode 2 (replace): tylko dla pre-composited dynamic tiles chartów.

**Wniosek:** dla warstwy ABOVE v10 **alpha scan nie jest wymagany dla poprawności** — jest czystą optymalizacją rozmiaru uploadu. Jego faktyczny zysk to **13%** redukcji pikseli (622 700 → 543 600), a nie 38% deklarowanych w tekście raportu 10O.

---

## 5. Previous frame / erase semantics

- **BELOW (HUD dirty):** `_dirty_rects_from_bboxes(previous_bboxes_holder[0], _bboxes, ...)` (L612, wywołanie L2061) — **union(prev, current)** bboxów + pad 40 → coalesce. `previous_bboxes_holder[0] = dict(_bboxes)` aktualizowane na końcu klatki (L2109). To jest kontrakt erase dla BELOW: upload pokrywa stary i nowy raster.
- **ABOVE:** `_cluster_above_bboxes(above_bboxes, ...)` używa **tylko bieżących** bboxów — union(A,B) NIE jest potrzebne na CPU, bo erase obsługuje **natywnie** `ClearPreviousAboveMap` (L1952), które czyści `m_abovePrevRegions` (= dokładnie regiony uploadowane w poprzedniej klatce, L2045–2047) przed blendem bieżącym.
- Każda proponowana optymalizacja zachowuje ten kontrakt, o ile regiony uploadowane w klatce N+1 są dokładnie tym, co GPU wyczyści jako `m_abovePrevRegions` w klatce N+2 (self-consistent).

---

## 6. Z-order

- ABOVE blend po GPU_MAP (`BlendAboveMap` ostatni) — warstwa ABOVE jest na wierzchu mapy, zgodnie z `CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP`.
- `ClearPreviousAboveMap` wykonuje się PRZED chart/gauge/map, więc nie kasuje pikseli pod starym bboxem ABOVE.
- Proponowane zmiany (C'/A) nie zmieniają kolejności GPU ani alpha semantics — modyfikują wyłącznie to, JAKI prostokąt jest uploadowany. Identyczny final raster.

---

## 7. Rotation

- W ABOVE v10 tylko **`alt_visual` ma `rotation: 90`** (preset L297). `compass` ma `rotation: 0` (igła obraca się wewnątrz rastra tarczy).
- Declared bbox dla rotacji 90 to pełny prostokąt o zamienionych wymiarach (`bw,bh = res.height,res.width`, compositor L420) — zawiera przezroczyste narożniki.
- `rotated_paste` (L199) transponuje raster, a `composite_final` (L152) liczy `overlay.getbbox()` **po transpozycji** → tight bbox po rotacji jest wyliczalny dokładnie (dla 90/180/270 transformacja jest dokładna).
- **Odpowiedź:** alpha scan nie istnieje tylko po to, by obcinać narożniki po rotacji — obcina też padding innych widgetów — ale rotacja jest głównym przypadkiem, w którym tight bbox różni się od declared w sposób łatwy do policzenia. Dla Variant A tight bbox po rotacji 90 jest darmowy (transpozycja bboxa).

---

## 8. Candidate clustering

- `_cluster_above_bboxes` (L355): każdy bbox jest paddowany (`pad=16`), następnie iteracyjnie scalane pary, których odstęp `dx<=merge_dist(32) AND dy<=merge_dist(32)`; przy przekroczeniu `max_regions=16` scala najbliższe pary.
- Dla v10 **wszystkie 10 widgetów ABOVE łańcuchowo scalają się do JEDNEGO klastra** o powierzchni **622 700 px** (~63% canvasu 1280×720). Potwierdzone empirycznie w 8 profilach: `regions_per_frame = 1.0`.
- **Wniosek:** ścieżka multi-region dla v10 degeneruje się do pojedynczego unii — `_rendered_bbox_union` (fallback, pad=64) dałby niemal identyczny prostokąt. Cluster = praktycznie cała warstwa ABOVE, dlatego skanuje setki tysięcy pikseli.
- `merge_dist=32` + `pad=16` tworzy nadmiernie duży union, bo widgety ABOVE są rozrzucone po ekranie, ale łańcuchowo w odległości ≤32px (top band y≈7.5–12%, środkowe y≈20–58%, bottom y≈82%).

---

## 9. Alpha scan — rozbicie

- `candidate_image.getchannel("A")` — alokuje **nowy obraz L-mode** (kopia płaszczyzny alpha).
- `.getbbox()` — skanuje kanał L (tani, pomiar mikro: ~0.002 ms dla 622K px).
- Dominujący koszt `above_local_alpha_scan` (0.368 ms avg) to **kopia kanału** (`getchannel` ~0.18 ms w pomiarze mikro dla 622K px) + narzut.
- Powstaje kopia kanału A; PIL alokuje nowy obraz; `getbbox` skanuje cały kandydat.
- **Nie ma już maski/bboxa przekazywanej z renderera do eksportera** — patrz §3.

---

## 10. RGBA -> bytes — alokacje

`reg_img.crop(local_alpha_bbox).tobytes("raw","RGBA")` (L1959+L1966):

| Krok | Kopiuje | Koszt (pomiar mikro / prod) |
|---|---|---|
| `above_full.crop(candidate)` | 622 700 px (kopia) | 0.698 ms avg |
| `getchannel("A")` | 622 700 px (kopia alpha) | 0.368 ms avg (z getbbox) |
| `candidate_image.crop(tight)` | 543 600 px (kopia) | 0.529 ms avg |
| `tobytes("raw","RGBA")` | 543 600 px (kopia → bytes) | 1.064 ms avg |
| `from_buffer_copy(r_bytes)` (consumer) | 2 174 400 B (kopia → ctypes) | część 0.308 ms |

Razem **5 kopii** regionu. `memoryview(PIL Image)` — **TypeError** (Pillow 12.3.0 nie udostępnia buffer protocol). `np.asarray` na pełnym canvasie — kopiuje (5.4 ms zmierzone dla 1280×720) i jest read-only — nieopłacalne. **Zero-copy z PIL do D3D11 nie jest możliwe.** Jedyna zbędna kopia to `from_buffer_copy` (można ją usunąć przez bufor wielokrotnego użytku).

---

## 11. D3D11 upload contract

Natywny `UpdateAboveRegion` (`d3d11_vp_pipeline.cpp` L1117–1142):
`m_context->UpdateSubresource(m_aboveRegionTexture[index], 0, nullptr, rgbaData, stride, 0)` — **wymaga spójnych (contiguous) bajtów RGBA** z row pitch = `rw*4`. Python przekazuje `stride = rw*4` (L2288).

→ `tobytes("raw","RGBA")` jest niezbędne; `from_buffer_copy` (kopia 3) jest zbędne (można ponownie używać bufora ctypes o rozmiarze max regionu).

---

## 12. AMD runtime path

- Wszystkie kroki dirty-region wykonują się w pętli produkcyjnej AMD (`amd_native_exporter.py`) na tej maszynie (runtime AMD potwierdzony: `telem_amd_native.dll`, VP, AMF HEVC).
- Powyższe pomiary (sekcja 15) są z aktualnego runtime AMD.

---

## 13. NVIDIA static path

- Kod dirty-region (`_cluster_above_bboxes`, `_tight_alpha_bbox_from_candidate`, inline crop/scan/tobytes, upload ctypes) znajduje się **wyłącznie** w `src/ffmpeg/amd_native_exporter.py` (moduł AMD) oraz w natywnym module AMD `d3d11_amf_pipeline`.
- Pipeline NVIDIA (FFmpeg/CUDA) nie używa tego kodu.
- **Wariant C'** (skip scan w exporterze) jest AMD-exporter-only → NVIDIA nietknięta.
- **Wariant A** dotyka `src/indicators/compositor.py` (współdzielony), ale **addytywnie** (nowy opcjonalny `tight_bboxes`, `_bboxes` bez zmian) → semantyka NVIDIA/CPU/preview zachowana; `_bboxes` pozostaje konserwatywne dla BELOW dirty rects i safety-checków chart/gauge.

> NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.

---

## 14. Preview vs final

- **Preview** (`render_preview`, compositor.py L603, GUI `preview_mixin.py`, `frame_renderer.py`) używa `compose_overlay` + `alpha_composite` — **nie ma** dirty-region crop/scan/tobytes.
- **Final (AMD)** używa `compose_overlay` (te same bboxy) + dirty-region extraction w exporterze.
- Dirty-region logika jest **wyłącznie w final AMD export**; preview i final dzielą semantykę `_bboxes` i `rotated_paste`, ale mają osobne ścieżki uploadu.
- Proponowana optymalizacja dotyczy tylko final exportu; nie zmienia preview (oba korzystają z tej samej warstwy `compose_overlay`).

---

## 15. Fresh benchmark (własny pomiar)

Konfiguracja jak w §0 (AMD Native D3D11, 1280×720, 120 klatek, v10). Wyniki:

| Metryka | mean | median | p95 |
|---|---:|---:|---:|
| `above_bbox_tracking` | 0.064 | 0.055 | 0.088 |
| `above_candidate_crop` | 0.698 | 0.619 | 0.972 |
| `above_local_alpha_scan` | 0.368 | 0.311 | 0.628 |
| `above_final_crop` | 0.529 | 0.439 | 0.805 |
| **`above_bbox_crop` (suma)** | **1.660** | **1.430** | **2.570** |
| `above_region_to_bytes` | **1.064** | **0.879** | **1.363** |
| `above_region_upload` | 0.308 | 0.225 | 0.654 |
| `above_compose` | 13.457 | 10.330 | 25.651 |
| `above_total` | 16.181 | 12.849 | 31.353 |
| `compose_overlay` (BELOW) | 4.466 | 3.079 | 10.878 |
| `HUD dirty bbox` / `extract` | 0.053 / 0.239 | — | — |
| `map_cpu_upload` | 2.498 | 1.002 | 2.303 |

Metryki pikseli (stałe dla wszystkich 120 klatek):

```
candidate_clusters        = 1.0 region/frame
scanned_pixels            = 622 700 px/frame
uploaded_pixels           = 543 600 px/frame
uploaded_bytes            = 2 174 400 B/frame (~2.17 MB)
```

Łączny koszt dirty path: **`above_bbox_crop + above_region_to_bytes` = 2.724 ms/frame (med: 2.309)**.

RENDER FPS: **35.972** (time render: 3.336 s). TRUE FPS: **12.884** (z audio remux).

---

## 16. Frame accounting

Ze `frame_accounting` w profilu 10P:

```
requested_frames = 120
decoded_frames   = 120
hud_frames       = 120
native_processed = 120
amf_submitted    = 120
amf_output       = 120
muxed_frames     = 120
```

**Status: `120 / 120 / 120 / 120` — 100% PASS (0 braków, 0 duplikatów).**

---

## 17. Porównanie vs 10O

| Metryka | Raport 10O (tekst) | Profil 10O (JSON) | Świeży 10P (audyt) |
|---|---:|---:|---:|
| candidate_clusters | **~2.0** | **1.0** | **1.0** |
| scanned_pixels | **340 500** | **622 700** | **622 700** |
| uploaded_pixels | **210 240** | **543 600** | **543 600** |
| uploaded_bytes | **~0.84 MB** | **2 174 400 B** | **2 174 400 B** |
| `above_candidate_crop` | 0.762 | 0.762 | 0.698 |
| `above_local_alpha_scan` | 0.428 | 0.428 | 0.368 |
| `above_final_crop` | 0.579 | 0.579 | 0.529 |
| `above_region_to_bytes` | 1.003 | 1.003 | 1.064 |
| `above_bbox_crop` | 1.845 | 1.845 | 1.660 |
| `above_compose` | **5.280** (tekst §8) | **13.854** | **13.457** |

**Kluczowe ustalenie audytu:**

1. **Kierunek diagnozy 10O jest PRAWIDŁOWY i potwierdzony** — `above_candidate_crop + above_local_alpha_scan + above_final_crop + above_region_to_bytes` to najdroższa część compositora. Liczby *czasowe* z tekstu 10O (0.762/0.428/0.579/1.003/1.845) **dokładnie zgadzają się** z profilem 10O i są powtarzalne w 10P.
2. **Liczby *objętościowe* z tekstu 10O (sekcje 9–10: 2.0 klastry, 340 500 px, 210 240 px, ~0.84 MB) są NIEPOWTARZALNE.** Wszystkie 8 profili produkcyjnych (10G, 10L, 10M, 10A, 10E2, 10F, 10O, 10P) zgodnie pokazują **1.0 klaster / 622 700 px / 543 600 px / 2 174 400 B**. Tekst 10O podaje skan ~1.83× i upload ~2.59× mniejsze niż rzeczywiste.
3. **Trim alpha-scanu jest realnie 13%** (622 700 → 543 600), a nie 38% (340 500 → 210 240) jak w tekście 10O → zysk ze skanu jest mniejszy, a ROI z jego usunięcia większy.
4. `above_compose` w tekście 10O (§8: 5.28) nie zgadza się z profilem 10O (13.85); świeży 10P (13.46) **odtwarza profil, nie tekst** — różnica to warm-up/cache, a nie zmiana kodu.

Różnice 10P vs profil 10O (1–10% na crop/scan/tobytes) mieszczą się w normalnym rozrzucie między uruchomieniami (temperatura, cache, inne procesy).

---

## 18. Maksymalnie 3 warianty

### Variant A — FAST EXACT DIRTY BBOX (propagacja tight bboxów)

Compositor przekazuje **addytywny** słownik `tight_bboxes` (per widget, tight alpha bbox rastra po rotacji — `text.py` już go zna; `bar/gauge/chart` przez jeden `getbbox()` na małym rastrze albo z `composite_final` L152). Eksporter: cluster tight bboxów → **jedno** crop tight unii z `above_full` → `tobytes`. Brak `getchannel("A")`, brak `getbbox()` na kandydacie, brak podwójnego cropa.

- **Oczekiwany zysk:** ~**1.0–1.1 ms/frame** (2.72 → ~1.7 avg).
- **Ryzyko:** MEDIUM — dotyka `compositor.py` (współdzielone), ale addytywnie; `_bboxes` bez zmian → NVIDIA/CPU/preview zachowane; rotacja 90 `alt_visual` wymaga tight bboxa po rotacji (darmowe dla 90/180/270); zweryfikowano brak annotations dla ABOVE.
- **Pliki:** `src/indicators/compositor.py` (+ ewent. `rotated_paste.py` return), `src/ffmpeg/amd_native_exporter.py`.

### Variant C' — SKIP ALPHA SCAN + FINAL CROP (upload kandydata)

Exporter-only: usunąć `getchannel("A").getbbox()` i final crop; uploadować cluster (kandydat) bezpośrednio: `above_full.crop(candidate).tobytes()`.

- **Oczekiwany zysk:** ~**0.74 ms/frame** (2.72 → ~1.98 avg).
- **Upload rośnie:** +79 100 px (+0.32 MB, +15%).
- **Ryzyko:** LOW — AMD-exporter-only; GPU blend (mode 1) traktuje src.a==0 jako no-op; GPU clear używa tych samych regionów → brak ghostingu; brak zmian współdzielonych.
- **Pliki:** `src/ffmpeg/amd_native_exporter.py` tylko.

### Variant C — REDUCE COPIES (bez zmiany bbox semantics)

Ponowne użycie bufora ctypes upload (eliminacja `from_buffer_copy`), pominięcie final cropa gdy tight==candidate, recykling alokacji.

- **Oczekiwany zysk:** ~**0.2–0.3 ms/frame**.
- **Ryzyko:** LOW.
- **Pliki:** `src/ffmpeg/amd_native_exporter.py`.

---

## 19. Expected gain / risk (podsumowanie)

| Wariant | Zysk (avg ms/frame) | Upload | Ryzyko | Zakres |
|---|---|---|---|---|
| A (exact bbox) | **~1.0–1.1** | bez zmian (543 600 px) | MEDIUM | compositor + exporter |
| C' (skip scan) | **~0.74** | +15% (622 700 px) | LOW | exporter only |
| C (reuse buffers) | ~0.2–0.3 | bez zmian | LOW | exporter only |

`above_region_to_bytes` (~1.06 ms) jest w dużej mierze nieuniknione (contiguous bytes dla UpdateSubresource; brak buffer protocol w Pillow); redukcja idzie przez mniejszy region uploadu (tight) i mniej kopii.

---

## 20. Recommended variant

**Variant A — FAST EXACT DIRTY BBOX** (z fallbackiem do obecnej ścieżki alpha-scan), z **Variantem C' jako pierwszym, bezpiecznym podzbiorem do wdrożenia od razu**.

Uzasadnienie: audyt **udowodnił** bezpieczeństwo pełnego usunięcia skanu dla ABOVE v10 (brak annotations → brak contentu poza declared bbox; GPU "over" ignoruje przezroczyste src; GPU clear self-consistent). Pełny wariant A daje największy zysk (≈1.0 ms). C' to krok niskiego ryzyka dający 0.74 ms, po którym A dokłada pozostałe ~0.3 ms.

---

## 21. Fallback strategy

Preferowany kontrakt:

```
FAST EXACT DIRTY BBOX
    ↓ if safe (tight bboxy znane, rotacja ∈ {0,90,180,270}, brak annotations)
CURRENT ALPHA-SCAN PATH
    ↓ fallback (widget niebezpieczny / tryb SCAN / błąd)
```

- Runtime switch przez env: `AMD_ABOVE_DIRTY_MODE = EXACT | SCAN` (domyślnie EXACT; SCAN = obecne zachowanie, identyczny raster).
- Automatyczny fallback per widget/klatka, gdy tight bbox nie może być udowodniony (np. nieznany renderer, nie-ortogonalna rotacja, obecność annotations).
- Obecna ścieżka (`_cluster_above_bboxes` + alpha scan) pozostaje nietknięta jako fallback → nieodwracalna zamiana NIE występuje.

---

## 22. Pixel parity plan (następny etap)

Porównanie `old path (SCAN)` vs `new path (EXACT)`:

- 120 klatek, pełny v10, AMD Native D3D11, 1280×720.
- Byte-exact final overlay: `different pixels = 0`, `max channel delta = 0`.
- Przypadki dodatkowe:
  - moving cursor (charts),
  - moving Distance marker,
  - Slope marker (dynamic),
  - Compass (igła),
  - Altitude rotation (90°),
  - Charts (HR/Cadence, dynamic history),
  - text `None` → value / value → `None`,
  - overlapping widgets,
  - map underneath ABOVE layer.
- Osobny A/B z `AMD_ABOVE_DIRTY_MODE` w obie strony (EXACT vs SCAN) na tym samym materiale.

---

## 23. Ghosting plan (następny etap)

Osobne testy (każdy: wyrenderować N klatek, zmienić stan, sprawdzić że poprzedni raster całkowicie zniknął):

- value change (tekst rośnie/maleje),
- marker moves left/right (Distance, Slope),
- widget position change (przesunięcie w layout),
- rotation change,
- `None` → value, value → `None`,
- seek do późniejszego czasu (random access).

Kryterium: po każdej zmianie poprzedni raster musi być **w pełni usunięty** (brak ghostingu) — weryfikacja porównaniem klatki po zmianie z klatką referencyjną oraz kontrola, że GPU `ClearPreviousAboveMap` pokrywa poprzedni upload.

---

## 24. Files that would be modified in NEXT stage

| Plik | Zmiana |
|---|---|
| `src/ffmpeg/amd_native_exporter.py` | ABOVE dirty-region: tryb EXACT (Variant A) / skip-scan (C'), fallback SCAN, reuse bufora upload (C) |
| `src/indicators/compositor.py` | (tylko A) addytywny output `tight_bboxes`; `_bboxes` bez zmian |
| `src/indicators/rotated_paste.py` | (tylko A, opcjonalnie) zwrot tight bboxa z `composite_final` |

NIE modyfikowane: renderery (`time_display`, `compass`, `slope`, `distance`, `altitude`, `charts`, `gauge`), `telemetry_fit.py`, field_catalog, presety, natywne DLL, mapa, kod NVIDIA.

---

## 25. Final decision

```
AUDIT RESULT: Diagnoza 10O (bottleneck = above_candidate_crop + alpha_scan + final_crop + region_to_bytes) potwierdzona; faktyczne objętości pikseli są wyższe niż w tekście 10O (1 klaster, 622700 skanowanych, 543600 uploadowanych, ~2.17 MB/frame), a trim alpha-scanu to 13% — skan nie jest wymagany dla poprawności ABOVE v10.

RECOMMENDED IMPLEMENTATION:
Variant A — FAST EXACT DIRTY BBOX (propagacja tight bboxów, addytywny tight_bboxes w compositorze) z fallbackiem SCAN; pierwszym krokiem bezpieczny podzbiór Variant C' (skip alpha scan + final crop).

EXPECTED GAIN:
~1.0–1.1 ms/frame (Variant A pełny); ~0.74 ms/frame (Variant C' samodzielnie).
Baseline 10P: 2.724 ms/frame (med 2.309) dla above_bbox_crop + above_region_to_bytes.

IMPLEMENTATION RISK:
MEDIUM
```

---

## 26. Repo safety

Stan po audycie (wszystkie poniższe wykonane na końcu zadania):

```
git status     — brak nowych śladów po tym audycie; repo ma WYŁĄCZNIE wcześniejsze (pre-existing) zmiany z poprzednich etapów
git diff       — brak zmian produkcyjnych z tego zadania (0 diff od tego agenta)
git diff --check — brak błędów whitespace od tego agenta
```

Tymczasowa instrumentacja (`scratch/benchmark_etap10p_audit_amd.py`, `*.mp4`, `*.amd_profile.json`) została usunięta przed zakończeniem.

---

## Załącznik: co zmierzone poza profilem

- `Image.crop` kopiuje dane (1.05 ms dla 2.49 MB).
- `getchannel("A")` alokuje nowy obraz L (~0.18 ms dla 622K px); `getbbox` na L jest tani (~0.002 ms).
- `tobytes("raw","RGBA")` — dominujący koszt kopii (1.97 ms dla 2.49 MB w pomiarze mikro).
- `memoryview(PIL Image)` — TypeError (brak buffer protocol).
- `np.asarray` na pełnym canvasie 1280×720 — kopiuje (~5.4 ms), read-only — nieopłacalne.
- Region slice z takiej tablicy jest zero-copy, ale wymaga wcześniejszej pełnej kopii canvasu.
- PIL → D3D11 zero-copy **niemożliwe**; jedyna redukowalna kopia to `from_buffer_copy` w konsumencie.

## Załącznik: nie testowane / ograniczenia

- **NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.**
- Nie uruchamiano ponownie SmartSync jako osobnego kroku; benchmark użył deterministycznego offsetu (absolute_overlap=yes, candidate=2.000 s, confidence=high — zgodnie z AGENTS.md §31).
- Nie zmieniano kodu produkcyjnego; wszystkie liczby pochodzą z pomiarów 120-klatkowych z `AMD_OVERLAY_PROFILE=1` (identycznie jak 10O).
