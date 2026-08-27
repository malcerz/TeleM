# RAPORT AMD ETAP 2E — REAL GUI INTEGRATION FIX

Data: 2026-08-26
Zakres: naprawa trzech rzeczywistych regresji integracyjnych ujawnionych w ręcznym teście GUI (GX030120, 180.2 s, 3840x2160, source rotation=180). To NIE jest etap optymalizacyjny.

---

## 1. Reproduction

Material: `Video/GX030120.MP4` (HEVC Main10 3840x2160 @29.97, rotation=-180).
Projekt/layout: `def_layout.json` (zapisany przez GUI; 22 wskaźniki, m.in. gauge pod kluczem `speed_text`, `lean_indicator` form=`lean` source=`gyro` axis=`x`, charty HR/Cadence AFTER map).
Artefakt recznego renderu: `Video/output_h265.mp4(.amd_profile.json)`.

Objawy:
1. Preview GUI rozjechany (duplikaty napisów/rulerki, "dwie skale"), finalny output OK.
2. `lean_indicator` stoi pionowo w finalnym outputcie.
3. Logi sugerowały fallback chartów i gauge do CPU_REFERENCE mimo "GPU safe".

## 2. GPU chart fallback root cause

Komunikat `GPU charts fallback -> CPU_REFERENCE (all active charts are z-order disjoint -> GPU safe)` był **mylącym logiem diagnostycznym ścieżki BEFORE-MAP**, nie decyzją:
- probe `_chart_gpu_layout_safe` zwracał reason dla CAŁEGO layoutu ("GPU safe"),
- print w else-gałęzi odpalał się zawsze, gdy `gpu_chart_keys` (BEFORE_MAP) było puste,
- w realnym layoucie WSZYSTKIE charty są AFTER map, więc pusty zbiór before-map jest legalny.

Dowody, że charty realnie działały na GPU w runie użytkownika:
`after_map_captures_performed = 10792 = 2 x 5395` (dokładnie 2 kafelki/klatkę), finalny output miał charty widoczne bez double-draw.
Ustalone również, że pola profilu `etap5j.active_gpu_charts` (tylko before-map), `chart_gpu_frames_*` (martwy licznik — brak `+=` w kodzie) i `native_after_map_blend_active` (hardkodowane `False`) **nie są miarą** aktywacji after-map.

Wniosek: brak faktycznego fallbacku chartów; bug czysto logiczno-logujący.

## 3. Gauge bbox=None root cause

`_GAUGE_KEY = "fit_enhanced_speed_text"` był hardcodem z presetu v10.
Realny projekt używa widgetu gauge pod kluczem **`speed_text`** (`form: "gauge"`), a `fit_enhanced_speed_text` to zwykły tekst.
Sekwencja błędu: gate capture pytał o `_GAUGE_KEY in map_above_layout` (zły klucz) -> brak capture i brak bboxa -> frame-0 confirmation dostawał `bbox=None` -> `_gauge_after_map_layout_safe(None,...) = (False,"gauge not rendered")` -> `GPU gauge AFTER-MAP fallback -> CPU_REFERENCE`.
Gauge pozostawał na CPU ABOVE (dlatego był widoczny w output).

## 4. GPU activation fix

`src/ffmpeg/amd_native_exporter.py`:
- NOWY `_resolve_gauge_layout_key(layout)` — pierwszy włączony wskaźnik `form=="gauge"` wg kolejności layoutu; fallback na historyczny `_GAUGE_KEY`. Rozwiązywany raz przy starcie eksportu (`gauge_layout_key`) + log `Gauge widget key: ...`.
- Wszystkie użycia `_GAUGE_KEY` w pipeline przejście na `gauge_layout_key`: legacy probe + guard (nowy parametr `gauge_key`), per-frame `capture_keys`, after-map gate/capture/confirmation/discard, gauge capture, `get_gauge_dynamic_info` (ETAP 2C AUTO regions).
- Semantyka logu chartów: rozróżnienie AFTER-MAP ACTIVE / realny fallback / brak chartów; jednorazowy `GPU ACTIVATION SUMMARY` (frame 0): MAP/HR/CADENCE/GAUGE + odpowiedniki CPU + GAUGE MODE.

Bezpieczniki (z-order guards, AUTO-region algorithm, clear semantics) NIEZMIENIONE.

Wynik (realny projekt, smoke 300f):

```text
Gauge widget key: speed_text (layout-resolved)
GPU charts AFTER-MAP GPU_SPLIT ACTIVE: ['fit_cadence_text','fit_heart_rate_text'] (CPU ABOVE HR: NO; CPU ABOVE CADENCE: NO)
GPU gauge AFTER-MAP active key=speed_text bbox=(1606,1588,777,777) (GPU-AFTER-MAP safe)
GPU ACTIVATION SUMMARY: GPU MAP ACTIVE: YES | HR GPU ACTIVE: YES | CADENCE GPU ACTIVE: YES | GAUGE GPU ACTIVE: YES (key=speed_text) | GAUGE MODE: AUTO
profil: etap5l gauge_gpu_active=True, gauge_gpu_frames=300/300, region 297 / full 3, epoch_changes=1
```


## 5. Lean indicator data-flow root cause

Ścieżka danych (z kodu, nie zgadywanie):
`def_layout(lean_indicator: source=gyro, axis=x, field=lean_roll_x)`
-> GPMF ACCL+GYRO (obecne w GX030120.json; 35802 próbek/osie po ekstrakcji)
-> `telemetry_manager._set_vector_series` / processed cache (accel_*/gyro_* samples)
-> `render_mixin.field_samples` (zawiera IMU) -> `init_worker`
-> final PRECOMPUTED: `telemetry_cache.lookup(idx)` -> `extra_indicators["lean_indicator"]`.

ROOT CAUSE: `src/telemetry_precompute.py::build_telemetry_cache` **nie planował lean**: wskaźnik wpadał do `remaining_extra` jako stała `(None,"°",label)` w KAŻDEJ klatce. Renderer: `lean_angle(None)=0°` -> ikona pionowo. Preview (GUI, live resolver obsługujący `lean_roll_{axis}`) animował poprawnie — stąd rozjazd preview/final.

## 6. Lean fix

`src/telemetry_precompute.py`:
- wykrywanie konsumentów lean (`form=="lean"`, enabled),
- sekcja 7b: source=`gyro` -> `interpolate_roll(_worker_lean_roll(axis), dt)` per frame (identyczny kontrakt jak ścieżka reference); source=`grade` -> slope step-array (atan robi renderer) — mirror `frame_data.py`,
- nowe pola `_Static.lean_keys/units/labels`, `_FrameRec.lean_vals`, blok w `lookup()`, wykluczenie z `remaining_extra`, subtimer `build_lean`.

TEST 2 (120 klatek, realny projekt, ścieżka FINAL):

```text
IMU series: accel_x=35802 gyro_x=35802
LEAN SOURCE VALUES UNIQUE: 120   (roll od +21.4 do -2.1 deg)
LEAN COMPUTED ANGLES UNIQUE: 120
Output 300f: crop lean 3 klatki (n=10/60/150) -> 3/3 unikalnych rotacji,
mean|diff| pikseli vs f10: 118.3 / 140.1  => LEAN INDICATOR MOVES: YES
```

## 7. Preview root cause

`preview_mixin.py`: podczas playback `render_preview(inplace=True)` alpha-composituje HUD BEZPOŚREDNIO na `self.src_img`.
Przed naprawą ten sam obiekt był jednocześnie `self.last_src_pil` (współdzielony w 3 miejscach: `_render_preview_from_pil` + dwa reuse-path w `_render_preview`). Gdy kolejny tick używał `last_src_pil`, zanim QMediaPlayer dostarczył nową klatkę, kompozyt nakładał HUD na już skompozytowaną klatkę — każdorazowo kolejna warstwa (przesunięta o zmieniające się wartości/pozycje) => duplikaty napisów, "podwójna" rulerka, dwie skale. Finalny eksport nie korzysta z tej ścieżki — dlatego output był poprawny.

## 8. Preview fix

`src/gui/qt/_mixins/preview_mixin.py` (3 miejsca, preview-only):
- `_render_preview_from_pil`: `last_src_pil = pil_img.copy()` gdy `_playing` (czysta referencja); pauza idzie po `inplace=False`, więc shared jest tam bezpieczny,
- oba reuse-path: `src_img = last_src_pil.copy()` gdy `_playing` (ekskluzywna kopia dla inplace).

TEST 3 (headless):

```text
clean reference drift after inplace pass: 0
composite#2 vs #1 max|diff|: 0        -> PREVIEW DOUBLE COMPOSE: NO
geometry parity preview-vs-reference: 10 indicators, 0 mismatches
PREVIEW RAW OVERLAY CORRECT: YES      (błąd nie leżał w Qt resize/scaling)
```

## 9. Changed files

| Plik | Zmiana |
|---|---|
| `src/ffmpeg/amd_native_exporter.py` | `_resolve_gauge_layout_key` + `gauge_layout_key` end-to-end; parametr `gauge_key` w `_gauge_gpu_layout_safe`; semantyka logów chartów; `GPU ACTIVATION SUMMARY` |
| `src/telemetry_precompute.py` | precompute lean (gyro timeline / grade slope), pola `_FrameRec/_Static`, lookup block, wykluczenie z remaining_extra, subtimer |
| `src/gui/qt/_mixins/preview_mixin.py` | izolacja mutowanych klatek playback (3 miejsca) |
| `scratch/etap2e_*.py` | diagnostyka (lean variability, smoke E2E, perf isolation, visual check, preview check) |

NIEZMIENIONE: mapa/preload, AMF, decode, mux, gauge AUTO-region algorithm, gauge clear semantics, NVIDIA, Intel, produkcyjny layout.

## 10. Tests

- Regresja: 77 PASS (`test_lean_*`, `test_etap8o_precomputed_telemetry`, `test_etap8p_b_fast_builder`, `test_amd_chart_map_split`, `test_amd_native_ordered_map`, `test_telemetry_processed_cache`, `test_hud_resolution_scale`, `test_compass_rendering`, `test_track_up_map`).
- TEST 1 real project GPU: PASS (sekcja 4; logi + profil). CPU nie renderuje HR/CAD/GAUGE równolegle.
- TEST 2 lean: PASS (sekcja 6).
- TEST 3 preview: PASS (sekcja 8).
- Visual smoke output: charty/gauge/mapa/lean żywe; gauge region 297/full 3 (wzorzec ETAP 2D).
- NOT RUN: pełny 5395f re-render użytkownika (czas zadania); NVIDIA/Intel runtime — NOT TESTED by design (brak sprzętu).

## 11. 300f real-project performance

Ten sam materiał GX030120 + def_layout, 300 klatek 4K, AMF, workers=4, FIT=Jazda_na_rowerze (ZAŁOŻENIE — FIT wybrany przez użytkownika w GUI nieznany):

```text
RENDER FPS BEFORE: 24.033  (ręczny run GUI; lean MARTWY — value None)
RENDER FPS AFTER : 15.996  (lean ŻYWY: animowana rotacja co klatkę; powtórki 15.9-16.1)
delay_to_first_frame: user 28.6s (incl. 91 tile preload) -> 4.40s warm cache (poza zakresem 2E)

Izolacja kosztu (120f A/B):
  base     (lean ON )   above_compose=53.9 ms  render 14.7 fps
  no_lean  (lean OFF)   above_compose=15.0 ms  render 33.7 fps  <- reszta pipeline SZYBSZA niż BEFORE
  gauge_cpu             above_compose=56.0 ms  render 14.2 fps  <- gauge GPU/CPU neutralny
```

Interpretacja: spadek względem 24.0 NIE pochodzi z fixów GPU (neutralne/pozytywne — no_lean 33.7 > 24.0). To koszt NOWO OŻYWIONEJ funkcji: rotator lean wykonuje co klatkę BICUBIC rotate pada ~618px + copy raster (~39 ms/frame w above_compose). Klasyczny kandydat następnego etapu (cache rotated sprites / bounding-box rotation) — ŚWIADOMIE poza zakresem 2E ("jedna optymalizacja na zadanie").

## 12. Risks

- Layouty z wieloma `form=gauge`: wybierany PIERWSZY (native ma jeden slot) — zgodne z single-gauge designem; multi-gauge out-of-scope.
- `telemetry_precompute` wspólny dla backendów: layouty bez lean mają identyczne rekordy (`lean_vals=()`); testy 8o/8p_b PASS; NVIDIA/Intel runtime NOT TESTED (brak sprzętu).
- Preview fix dodaje 1 kopię klatki preview per kompozycję podczas playback (pomijalne vs compositing).
- Krótkie runy (<600f) mają dużą wariancję FPS (mux/init amortyzacja) — porównywać na >=1000f.
- Martwe pola profilu (`chart_gpu_frames_*`, `active_gpu_charts`, `native_after_map_blend_active=False`) pozostają mylące — udokumentowane do sprzątania w osobnym zadaniu.

---

FINAL STATUS:

AMD ETAP 2E COMPLETE

REAL PROJECT: GX030120 + def_layout.json (300f smoke, produkcja)
HR GPU ACTIVE: YES
CADENCE GPU ACTIVE: YES
GAUGE GPU ACTIVE: YES
GAUGE MODE: AUTO

GPU CHART FALLBACK ROOT CAUSE: mylący log diagnostyki BEFORE-MAP (legalnie pusty zbiór before-map + reason całego layoutu); charty działały na GPU (captures 2/klatkę); naprawiony log + jawny summary
GPU GAUGE BBOX NONE ROOT CAUSE: hardkod _GAUGE_KEY="fit_enhanced_speed_text" vs realny widget "speed_text" (form=gauge); probe/capture szukały nieistniejącego klucza

LEAN SOURCE: GPMF ACCL+GYRO -> complementary filter -> precomputed roll timeline (lean_roll_x, deg)
LEAN UNIQUE SOURCE VALUES: 120/120
LEAN UNIQUE COMPUTED ANGLES: 120/120
LEAN UNIQUE FINAL ROTATIONS: 3/3 sampled output frames (mean pixel diff 118-140)
LEAN INDICATOR MOVES: YES

PREVIEW RAW OVERLAY CORRECT: YES
PREVIEW DOUBLE COMPOSE: NO
PREVIEW FINAL PARITY: PASS (geometria 10/10 wskaźników zgodna relatywnie)

RENDER FPS BEFORE: 24.033
RENDER FPS AFTER: 15.996 (koszt żywego lean ~39 ms/frame w above; kontrola no_lean = 33.7 fps)

FINAL OUTPUT VISUAL: PASS

NVIDIA UNCHANGED: YES
INTEL UNCHANGED: YES

