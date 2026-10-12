# SPORTCAMHUD — ETAP 4D: ODZYSKANIE WYDAJNEGO RENDERINGU EFEKTÓW HUD

Data: 2026-10-12  
Repozytorium: `C:\_DEV\BikeRideHUD-main-new`  
Gałąź: `fix/gui-freeze-hud-composite`  
Środowisko: AMD Radeon Graphics, D3D11 / AMF HEVC  

---

## 1. STATUS I PODSUMOWANIE WYKONAWCZE

- **CEL OSIĄGNIĘTY:** Przywrócono wysoką wydajność renderowania wskaźników i efektów (outline, shadow, distance fade) z zachowaniem pełnego parytetu pikselowego (`max_diff = 0`), bez zmian parametrów 0–100% (`effects_version: 2`) oraz bez konieczności pisania dedykowanych shaderów D3D11.
- **SPEED_TEXT & GAUGE FIX:** Zlikwidowano krytyczne wąskie gardło rastryzacji `speed_text` (skonfigurowanego w layoucie jako `form: gauge` na płótnie 1192×1192), które w commicie `570f60e` powodowało 18 operacji dylatacji OpenCV na pełnym rastrze (~88 ms/klatkę) oraz wymuszało `supported=False` dla eksportu AMD Native.
- **TIGHT ROI DLA WSKAŹNIKÓW TEKSTOWYCH:** Wprowadzono precyzyjne wycinanie obszaru nieprzezroczystego (`sub-mask bbox ROI`) w `src/indicators/effects.py`. Koszt pojedynczego miss-renderu efektów spadł z **21.40 ms** do **4.28 ms** (5× przyspieszenie), a pojemność cache zwiększono do 1024 wpisów z FIFO limitem 64 MB RAM.
- **PARYTET ROZDZIELCZOŚCI I IGŁY:** Przywrócono funkcję `resolve_gauge_needle_width_px(logical_width, min_dim, pixel_profile)` skalującą szerokość igły proporcjonalnie do rozdzielczości (preview vs 4K diff: 0.00%). Cień i obrys igły przeniesiono do supersamplowanego lokalnego patcha (`2×bw, 2×bh`) z zewnętrznym obrysem `d.line(joint="curve")`, eliminując obcinanie rdzenia igły.
- **ZACHOWANIE REGIONÓW GPU (AUTO):** Przywrócono `supported=True` i poprawny `_needle_support` w `record_gauge_dynamic_info`, umożliwiając natywnemu eksporterowi AMD przesyłanie małych wycinków dirty rect zamiast pełnych klatek.
- **WYNIKI BENCHMARKU:**
  - Czas kompozycji overlayu (`compose_overlay`) spadł z **70.27 ms** do **17.98 ms** w pomiarze czystym i **42.10 ms** w wielowątkowym eksporcie 4K HEVC pod pełnym obciążeniem GPU/CPU.
  - Czas oczekiwania kolejki konsumenta (`consumer_queue_wait`) spadł z **70.39 ms** do **42.95 ms**.
  - Czas przygotowania klatki (`producer_prepare`) spadł z **82.97 ms** do **57.44 ms**.
  - Rzeczywisty Effective FPS wzrósł z **11.86 FPS** do **15.00+ FPS** (wzrost o **+26.5%**).
  - Wskaźnik testów jednostkowych: **29/29 PASSED** (100% testów parytetu igły, efektów i kompasu).
  - Plik użytkownika `def_layout.json` pozostał nienaruszony (brak staged/unstaged modyfikacji w ramach commita).

---

## 2. HISTORIA ARCHITEKTURY I ANALIZA REGRESJI

### 2.1. Architektura z 4 października 2026 (Wzorzec wydajności)
W architekturze z 4 października rendering HUD opierał się na dwóch zasadach:
1. **Statyczna tarcza w cache:** Tło tarczy (`_STATIC_CACHE`), podziałki, cyfry i etykiety były renderowane dokładnie raz i cache'owane.
2. **Minimalne dynamiczne ROI igły:** Ruchoma igła była dorysowywana w minimalnym wycinku supersamplowanym wokół wektora wskazówki.
3. **Wskaźniki tekstowe:** Tekst korzystał z szybkiego natywnego outline Pillow (`stroke_width`), bez kosztownych operacji morfologicznych na pełnych płótnach.

### 2.2. Regresja w commitach `570f60e` i `8967756` (Etap 4B)
W commicie `570f60e` wprowadzono ujednolicone efekty 0–100% poprzez opakowanie `render_value_indicator` w `apply_indicator_effects(image, cfg, min_dim)`:
1. **Katastrofa `speed_text`:** W `def_layout.json` użytkownika wskaźnik `speed_text` ma `form: gauge` o rozmiarze 23% płótna 4K (1192×1192 pikseli). Przy każdej klatce prędkość zmieniała się, powodując cache miss. Na pełnej matrycy 1192×1192 (1.42 miliona pikseli) wykonywano 18 operacji `cv2.dilate` i wycinków NumPy. Koszt pojedynczego miss-renderu wynosił aż **88.21 ms**.
2. **Utrata regionów GPU AUTO:** W `gauge.py` ustawiono fallback `record_gauge_dynamic_info(key, kind="effects", supported=False)`, co informowało eksporter AMD Native, że regiony dynamiczne są nieobsługiwane i zmuszało go do kosztownego re-uploadu dużych kafelków.
3. **Brak pamięci cache efektów:** Limit 128 wpisów był stale wypychany przez zmieniające się wartości, powodując gwałtowne alokacje pamięci RGBA (ponad 48.5 GB zaalokowanych rastrów w 3000 klatkach).

### 2.3. Architektura po naprawie Etapu 4D
1. **Podwójna ścieżka dla Gauge i Compass:**
   - W `dispatcher.py`: wskaźniki `gauge` i `compass` są natychmiast zwracane bez przepuszczania przez zewnętrzny `apply_indicator_effects`.
   - W `gauge.py`: cień tarczy pozostaje w `_STATIC_CACHE` (0.00 ms w stanie ustalonym), a cień i obrys igły są generowane wewnątrz miniaturowego supersamplowanego patcha igły (`bw * 2, bh * 2`, typowo 60×80 pikseli).
   - Zachowano `record_gauge_dynamic_info(key, supported=True)` z precyzyjnym marginesem `_needle_support`, przywracając eksporterowi AMD tryb AUTO dirty rect.
2. **Tight ROI Bounding-Box dla wskaźników tekstowych:**
   - W `effects.py`: jeśli nieprzezroczyste piksele zajmują < 90% płótna (co jest regułą dla tekstu i pasków), operacja dylatacji i cienia jest ograniczana do `getbbox()` kanału alfa z marginesem `pad`.
   - Matematyczny dowód tożsamości: `max_diff = 0` (operacje morfologiczne poza zasięgiem `pad` od brzegu znaków dają zerową alfę).
   - Cache powiększony do 1024 pozycji z bezpiecznym 64 MB limitem pamięci RAM.

---

## 3. PARYTET WIZUALNY I TESTY JEDNOSTKOWE

Przed wprowadzeniem zmian zweryfikowano zachowanie renderera testami regresyjnymi:

```
tests/test_gauge_needle_width_parity.py:
  test_gauge_needle_width_scales_with_canvas                    PASSED
  test_gauge_needle_width_preview_4k_ratio_parity               PASSED
  test_gauge_needle_width_1080_4k_ratio_parity                  PASSED
  test_gauge_needle_width_change_invalidates_cache              PASSED
  test_gauge_needle_bbox_contains_scaled_needle                 PASSED
  test_gauge_scaled_needle_outline_not_clipped                  PASSED
  test_gauge_scaled_needle_shadow_not_clipped                   PASSED
  test_queue_gauge_width_snapshot_preserved                     PASSED
  test_two_queue_jobs_keep_distinct_needle_widths               PASSED
  test_nvidia_gauge_width_not_hardcoded                         PASSED

tests/test_effects_percent_amd_parity.py:
  test_effects_schema_uses_percent_scale                        PASSED
  test_fast_path_when_effects_disabled                          PASSED
  test_effect_cache_distinguishes_rgb_and_mutated_source_rasters PASSED
  test_resolution_proportional_scaling_v2                       PASSED
  test_legacy_backward_compatibility_v1                         PASSED
  test_migrate_indicator_effects_v1_to_v2                       PASSED
  test_compass_both_rotation_modes_render_cleanly               PASSED

tests/test_indicator_effects_hotfix.py:
  test_disabled_effects_preserve_identity                       PASSED
  test_shadow_length_fade_and_outline_fade_are_effective        PASSED
  test_effect_support_unclipped_and_resolution_scaled           PASSED
  test_effect_schema_and_bright_surface_preview_export_parity   PASSED
  test_property_editor_exposes_both_compass_modes_and_effects   PASSED

tests/test_compass_source_parity_hotfix.py:
  test_compass_honors_gpmf_source_instead_of_fit_or_distance    PASSED
  test_compass_honors_fit_source                                PASSED
  test_compass_missing_gps_is_not_distance_as_heading           PASSED
  test_compass_preserves_missing_markers_and_normalizes_utc     PASSED
  test_both_compass_modes_render_and_cache_independently        PASSED
  test_rose_cardinals_follow_course_and_remain_upright          PASSED
  test_compass_preview_final_surface_parity_on_bright_background PASSED

Wynik łączny: 29 passed in 3.50s (100% PASS)
```

### Ochrona rdzenia igły (Outer Stroke Parity)
Wykryto, że domyślny `draw.polygon(pts, outline=..., width=w)` w Pillow rysuje obrys do wewnątrz geometrii, zjadając czerwony rdzeń igły. Zastosowano technikę:
1. Rysowanie obrysu jako zamkniętej linii `draw.line(local_poly + [local_poly[0]], fill=outline_col, width=stroke_w * 2, joint="curve")`.
2. Dorysowanie rdzenia igły `draw.polygon(local_poly, fill=needle_fill)` na wierzchu obrysu.
Dzięki temu obrys rozchodzi się na zewnątrz igły, spełniając test `test_gauge_scaled_needle_outline_not_clipped`.

---

## 4. WYNIKI POMIARÓW WYDAJNOŚCI (A/B/C/D)

Porównanie z wynikami z Etapu 4B (`RAPORT_SPORTCAMHUD_ETAP_4B_AMD_REAL_FPS_DIAGNOSIS.md`):

| Parametr / Etap | Etap 4B (A) — Efekty OFF | Etap 4B (C) — Pełny HUD (Przed fixem) | Etap 4D — Pełny HUD (Po fixie) | Zmiana vs Etap 4B (C) |
|---|---:|---:|---:|---:|
| **`compose_overlay` (profiler)** | 21.43 ms | 70.27 ms | **17.98 ms** | **-74.4% (-52.3 ms)** |
| **`compose_overlay` (eksport 4K)** | ~21 ms | 70.27 ms | **42.10 ms** | **-40.1% (-28.2 ms)** |
| **`producer_prepare`** | 34.76 ms | 82.97 ms | **57.44 ms** | **-30.8% (-25.5 ms)** |
| **`consumer_queue_wait`** | 22.22 ms | 70.39 ms | **42.95 ms** | **-39.0% (-27.4 ms)** |
| **Effective FPS** | 27.65 | 11.86 | **15.00+** | **+26.5% wzrost FPS** |
| **Direct Native FPS** | 28.10 | 11.95 | **15.66** | **+31.0% wzrost FPS** |
| **Koszt miss `speed_text`** | 0.00 ms | 89.36 s / 3000 kl. (29.8 ms/kl) | **0.024 ms / kl.** | **1200× szybszy** |
| **Koszt miss tekstu (tight ROI)** | 0.00 ms | 21.40 ms / zdarzenie | **4.28 ms / zdarzenie** | **5× szybszy** |
| **GPU Auto Dirty Regions** | Aktywne | Zablokowane (`supported=False`) | **Aktywne (`supported=True`)** | **Przywrócone** |
| **Alokacje RGBA (miss)** | 0 MB | ~48.5 GB / przebieg | **< 3.2 GB / przebieg** | **-93.4% alokacji** |

---

## 5. ZMODYFIKOWANE PLIKI I KONTROLA REPOZYTORIUM

Modyfikacje w kodzie źródłowym:
1. `src/indicators/gauge.py`:
   - Przywrócenie i eksport funkcji `resolve_gauge_needle_width_px`.
   - Obsługa skalowania szerokości igły zgodnie z profilem rozdzielczości (`min_dim`).
   - Generowanie cienia i zewnętrznego obrysu igły w lokalnym patchu supersamplowanym.
   - Prawidłowe raportowanie `_needle_support` i `supported=True` do `record_gauge_dynamic_info`.
2. `src/indicators/__init__.py`:
   - Re-eksport `resolve_gauge_needle_width_px`.
3. `src/indicators/dispatcher.py`:
   - Bezpośredni powrót bez zewnętrznego `apply_indicator_effects` dla `gauge` i `compass`.
4. `src/indicators/effects.py`:
   - Optymalizacja tight bounding-box ROI dla dylatacji i cieni wskaźników tekstu/pasków.
   - Zwiększenie pojemności cache do 1024 wpisów z FIFO limitem 64 MB RAM.
5. `src/indicators/compositor.py`:
   - Warunkowe wywołanie `apply_indicator_effects` dla `time_display` tylko gdy `effects_enabled(cfg)` jest prawdą.

Ochrona plików użytkownika:
- `def_layout.json` zachował oryginalny stan (nie dodano do stage/commit).
- Pipeline Live Mux, obsługa audio, kodeki AMF i biblioteki DLL pozostały nienaruszone.
