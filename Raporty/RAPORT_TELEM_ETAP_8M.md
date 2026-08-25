# RAPORT — TeleM — ETAP 8M: Naprawa `track_map` oraz kontraktu rozdzielczości eksportu

**Data wykonania:** 2026-08-19  
**Status etapu:** `SUCCESS` / `CLOSED`  
**Autor:** Antigravity AI Agent  
**Środowisko:** Windows 11, AMD Radeon RX 7900 XTX, Direct3D 11, AMF HEVC Hardware Encoder, Media Foundation D3D11VA Decoder, Python 3.14.7  

---

## A. Map clipping root cause

W toku audytu pipeline mapy zidentyfikowano dwa powiązane źródła problemu z zawartością mapy:

1. **Plik `src/indicators/moving_map.py` (funkcja `render_map_working_image`):**
   - Podczas generowania klatki mapy instancja `MovingMapRenderer` była tworzona bez wywołania `background_precache()`, a wywołanie metody `renderer.render()` miało na sztywno wpisany parametr `download_missing=False`.
   - Jeśli kafelki satelitarne dla efektywnego poziomu zoom (np. zoom 16 dla 4K lub zoom 15 dla 1080p) nie znajdowały się jeszcze w lokalnej bazie cache SQLite, funkcja zwracała czarne/szare tło `(30, 30, 30, 255)`, na którym rysowany był jedynie wąski czerwony ślad GPS.
   - **Poprawka:** W `render_map_working_image` dodano wywołanie `renderer.background_precache(margin=2, zooms=[effective_zoom])` przy tworzeniu renderera oraz przekazanie `download_missing=getattr(renderer, '_is_first_render', False)` na pierwszej klatce.

2. **C++ Native VideoProcessor `SourceRect` vs `DestRect` (`native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp`):**
   - Przy zmianie rozdzielczości z 4K na mniejszą (np. 1080p), `m_videoContext->VideoProcessorSetStreamSourceRect` używał struktury `fullRect = {0, 0, m_width, m_height}` (czyli $1920\times 1080$) zamiast wymiarów tekstury wejściowej dekodera ($3840\times 2160$). Powodowało to wycinanie lewego górnego rogu 4K zamiast całego kadru i rozciąganie mapy.
   - **Poprawka:** Rozdzielono `srcRect = { 0, 0, (LONG)inDesc.Width, (LONG)inDesc.Height }` od `dstRect = { 0, 0, (LONG)m_width, (LONG)m_height }`.

---

## B. Map pipeline dimensions

Dla testowej klatki 30 zmierzono wymiary, krok (stride) i objętość bajtów na każdym etapie przetwarzania:

| Stage | Width | Height | Stride / Format | Bytes | BBox / Destination |
|---|:---:|:---:|:---:|:---:|:---:|
| `MovingMapRenderer.render()` (4K) | 692 | 692 | 2768 (RGBA) | 1 915 456 B | (0, 0, 692, 692) |
| `apply_map_shape('square')` (4K) | 692 | 692 | 2768 (RGBA) | 1 915 456 B | (0, 0, 692, 692) |
| `render_map_working_image` dst_bbox | 691 | 691 | — | — | `[3035, 137, 691, 691]` |
| `telem_amd_update_map` upload | 692 | 692 | 2768 (RGBA) | 1 915 456 B | Texture 2D RGBA UNORM |
| `ResampleAndBlendMap` GPU shader | 691 | 691 | GPU Dispatch (16x16) | VRAM Target | Destination HUD canvas `[3035, 137]` |
| `Final Destination Blit` (4K) | 3840 | 2160 | NV12 Frame | VRAM Target | `[3035, 137, 691, 691]` |

---

## C. Before/after map artifacts

Wygenerowano i zapisano artefakty diagnostyczne w `scratch/etap8m_diag/` oraz `scratch/validation_exports/`:
- `01_map_renderer_raw.png`: Pełny raster wygenerowany przez `MovingMapRenderer` ($692\times 692$, RGBA).
- `02_map_after_crop.png`: Raster po nałożeniu maski kształtu `apply_map_shape` ($692\times 692$, RGBA).
- `03_map_upload_source.png`: Dokładny bufor przekazywany do `telem_amd_update_map` ($692\times 692$, RGBA).
- `map_crop_30_4k.png`: Wycinek obszaru mapy z klatki 30 wideo 4K ($691\times 691$).
- `map_crop_30_1080p.png`: Wycinek obszaru mapy z klatki 30 wideo 1080p ($346\times 346$).
- `map_crop_30_720p.png`: Wycinek obszaru mapy z klatki 30 wideo 720p ($230\times 230$).

---

## D. Preview / CPU / AMD map content parity

Porównano wycinki mapy z podglądu GUI Preview, renderera CPU Reference oraz GPU AMD Native D3D11:

| Środowisko | Wymiary wycinka | Proporcja Aspect Ratio | Średnia jasność (Mean) | Status |
|---|:---:|:---:|:---:|:---:|
| GUI Preview | $173 \times 173$ | $1.00$ (kwadrat) | 68.8 | **MATCH** |
| CPU Reference | $691 \times 691$ | $1.00$ (kwadrat) | 69.4 | **MATCH** |
| AMD GPU Native (4K) | $691 \times 691$ | $1.00$ (kwadrat) | 69.59 | **MATCH** |
| AMD GPU Native (1080p) | $346 \times 346$ | $1.00$ (kwadrat) | 69.91 | **MATCH** |
| AMD GPU Native (720p) | $230 \times 230$ | $1.00$ (kwadrat) | 69.98 | **MATCH** |

Brak ucięć krawędzi, brak efektu wąskiego paska, pełne tło satelitarne widoczne na całej powierzchni kwadratu.

---

## E. Resolution setting root cause

Zidentyfikowano dwie luki w propagacji rozdzielczości z GUI do backendu:

1. **`src/gui/qt/_mixins/render_mixin.py` (linia 85–86 oraz 182–184):**
   - `render_mixin.py` pobierało opcję `resolution = options.get("resolution", "source")`, ale wymiary `w` i `h` były na sztywno odczytywane ze strumienia wejściowego `ffprobe_stream_info(self.video_path)` ($3840\times 2160$).
   - Parametry `render_w=w, render_h=h` były przekazywane bez mapowania `resolution` na wartości z `RESOLUTION_MAP`.
2. **`src/ffmpeg/streaming.py` (linia 248–249):**
   - Przy wywołaniu `export_amd_native_d3d11` przekazywano `video_width=render_w, video_height=render_h` bez uprzedniego rozwiązania `resolution_name`.

---

## F. GUI → Backend resolution propagation

| Warstwa / Plik | Wejście | Transformacja | Wyjście |
|---|---|---|---|
| `RenderTab` (`render_tab.py`) | Wybór w `cmb_resolution` (np. `"1080p"`) | `options["resolution"] = "1080p"` | Emisja sygnału `sig_render_requested(options)` |
| `RenderMixin` (`render_mixin.py`) | `options["resolution"]` + probe wideo | `RESOLUTION_MAP.get("1080p") -> (1920, 1080)` | `render_w=1920, render_h=1080`, `ov_w=1920, ov_h=1080` |
| `streaming.py` | `render_w=1920, render_h=1080` | Walidacja `target_res` | `export_amd_native_d3d11(video_width=1920, video_height=1080)` |
| `amd_native_exporter.py` | `video_width=1920, video_height=1080` | Konfiguracja canvasu HUD i DLL | `telem_amd_create(..., 1920, 1080, ...)` |
| `telem_amd_native.cpp` | `width=1920, height=1080` | Inicjalizacja VP & AMF | `vpPipeline.Initialize(1920, 1080)`, `amfEncoder.Initialize(1920, 1080)` |

---

## G. Source vs output dimensions contract

- **`source_width` / `source_height`**: Fizyczna rozdzielczość dekodowanego wideo źródłowego (np. $3840\times 2160$ z pliku GoPro MP4/P010).
- **`output_width` / `output_height`** (`video_width` / `video_height`): Rozdzielczość docelowa wybrana przez użytkownika w GUI (np. $1920\times 1080$ lub $1280\times 720$).
- **Skalowanie:** Odbywa się w 100% sprzętowo na GPU wewnątrz Direct3D 11 `VideoProcessorBlt` podczas konwersji próbki P010 do NV12.

---

## H. Native VP configuration

W pliku `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp`:
- `SetupVideoProcessor`:
  ```cpp
  contentDesc.InputWidth = (m_width > 3840u) ? m_width : 3840u;
  contentDesc.InputHeight = (m_height > 2160u) ? m_height : 2160u;
  contentDesc.OutputWidth = m_width;
  contentDesc.OutputHeight = m_height;
  ```
- `ProcessFrame`:
  ```cpp
  RECT srcRect = { 0, 0, (LONG)inDesc.Width, (LONG)inDesc.Height };
  RECT dstRect = { 0, 0, (LONG)m_width, (LONG)m_height };
  m_videoContext->VideoProcessorSetStreamSourceRect(m_videoProcessor, 0, TRUE, &srcRect);
  m_videoContext->VideoProcessorSetStreamDestRect(m_videoProcessor, 0, TRUE, &dstRect);
  ```

---

## I. AMF output configuration

- `D3D11AMFEncoder::Initialize`:
  - Przekazywane wymiary: `width = output_width, height = output_height`.
  - Powierzchnie wejściowe AMF tworzone są w formacie `NV12` o wymiarach `output_width × output_height`.
  - Strumień H.265 / HEVC SPS nagłówka zawiera prawidłowe wymiary wyjściowe.

---

## J. 4K validation

- **Wybrana rozdzielczość w GUI:** `4k` ($3840\times 2160$)
- **Plik wynikowy:** `scratch/validation_exports/export_4k.mp4`
- **ffprobe stream width x height:** $3840 \times 2160$
- **Mapa:** $691 \times 691$ pikseli, pełne tło satelitarne, brak ucięć.

---

## K. 1080p validation

- **Wybrana rozdzielczość w GUI:** `1080p` ($1920\times 1080$)
- **Plik wynikowy:** `scratch/validation_exports/export_1080p.mp4`
- **ffprobe stream width x height:** $1920 \times 1080$
- **Mapa:** $346 \times 346$ pikseli (dokładnie $18\%$ z $1920$), aspect ratio $1.00$, pełne tło satelitarne.

---

## L. Third-resolution validation (720p)

- **Wybrana rozdzielczość w GUI:** `720p` ($1280\times 720$)
- **Plik wynikowy:** `scratch/validation_exports/export_720p.mp4`
- **ffprobe stream width x height:** $1280 \times 720$
- **Mapa:** $230 \times 230$ pikseli (dokładnie $18\%$ z $1280$), aspect ratio $1.00$, pełne tło satelitarne.

---

## M. ffprobe results

```json
// export_1080p.mp4
{
    "streams": [
        {
            "width": 1920,
            "height": 1080,
            "r_frame_rate": "30000/1001",
            "avg_frame_rate": "1000000/33367"
        }
    ],
    "format": {
        "duration": "179.989333"
    }
}
```

```json
// export_720p.mp4
{
    "streams": [
        {
            "width": 1280,
            "height": 720,
            "r_frame_rate": "30000/1001",
            "avg_frame_rate": "1000000/33367"
        }
    ],
    "format": {
        "duration": "179.989333"
    }
}
```

```json
// export_4k.mp4
{
    "streams": [
        {
            "width": 3840,
            "height": 2160,
            "r_frame_rate": "30000/1001",
            "avg_frame_rate": "1000000/33367"
        }
    ],
    "format": {
        "duration": "179.989333"
    }
}
```

---

## N. HUD scaling parity

Wszystkie wskaźniki TeleM są definiowane procentowo względem szerokości/wysokości canvasu (`helpers.s(percent, canvas_size)`):
- **Tekst i wskaźniki cyfrowe:** Skalowane proporcjonalnie do wysokości i szerokości canvasu wyjściowego.
- **Wykresy (`fit_cadence_text`, `fit_heart_rate_text`):** Szerokość i wysokość skalują się proporcjonalnie bez ucięć i przesunięć.
- **Speed Gauge:** Średnica $216\times 216$ w 720p, $324\times 324$ w 1080p, $648\times 648$ w 4K.
- **Track Map:** Zachowuje stałą proporcję kwadratową $1.00$ ($230\times 230$ w 720p, $346\times 346$ w 1080p, $691\times 691$ w 4K).
- **CPU_ABOVE_MAP (`Solar Pct`, `Battery`):** Pozycjonowanie i rozmiar skalują się proporcjonalnie.

---

## O. FPS / PTS / Audio regression

- **FPS:** $29.97\text{ FPS}$ ($30000/1001$) zachowane we wszystkich testowanych rozdzielczościach.
- **PTS:** Równe kroki PTS ($333666\text{ 100ns units} = 33.3666\text{ ms}$).
- **Audio:** Dźwięk AAC Stereo $48000\text{ Hz}$ poprawnie remuxowany do wszystkich plików wynikowych.
- **Czas trwania:** Dokładnie zgodny z materiałem źródłowym.

---

## P. Tests

Utworzono dedykowany zestaw testów jednostkowych i regresyjnych `tests/test_etap8m_resolution_and_map.py`:
- `test_resolution_map_definitions`: **PASS**
- `test_map_geometry_scaling_across_resolutions`: **PASS**
- `test_map_render_plan_aspect_and_zoom`: **PASS**
- `test_hud_composition_at_multiple_resolutions`: **PASS**

Testy powiązane:
- `tests/test_map_sync.py`: **38 PASSED**
- `tests/test_gpu_compositor.py`: **5 PASSED**
- `tests/test_amd_native_ordered_map.py`: **4 PASSED**
- `tests/test_amd_native_ordered_map_clear.py`: **4 PASSED**
- `tests/test_etap8e_full_activity_charts.py`: **4 PASSED**

---

## Q. Full suite

Wynik pełnego pakietu `pytest`:
```text
347 passed, 3 failed, 17 skipped in 20.31s
```
- Brak jakichkolwiek nowych niepowodzeń (3 znane historyczne failure'y nie powiązane z ETAPEM 8M).

---

## R. Git diff scope

Zmodyfikowane pliki produkcyjne:
1. `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp`: Poprawka `srcRect` i `dstRect` w `ProcessFrame` oraz `contentDesc` w `SetupVideoProcessor`.
2. `src/gui/qt/_mixins/render_mixin.py`: Rozwiązanie `resolution` przez `RESOLUTION_MAP` i przekazanie `render_w, render_h`.
3. `src/ffmpeg/streaming.py`: Rozwiązanie `resolution_name` przed wywołaniem `export_amd_native_d3d11`.
4. `src/ffmpeg/amd_native_exporter.py`: Logowanie `SOURCE VIDEO`, `REQUESTED OUTPUT`, `VP OUTPUT`, `AMF OUTPUT`.
5. `src/indicators/moving_map.py`: Precache kafelków i `download_missing` na pierwszej klatce w `render_map_working_image`.
6. `tests/test_etap8m_resolution_and_map.py`: Nowy zestaw testów regresyjnych.

---

## S. Final classification

- **`TRACK_MAP CONTENT/CROP`**: **`PASS`**
- **`EXPORT RESOLUTION CONTRACT`**: **`PASS`**
- **`1080P REAL GUI EXPORT`**: **`PASS`**
- **`MULTI-RES HUD GEOMETRY`**: **`PASS`**

---

## T. Recommended ETAP 8N

Zalecany zakres kolejnego etapu (**ETAP 8N**):
1. Naprawa fallbacku `None` $\rightarrow$ `0.0` w `src/indicators/compositor.py` (linia 249) dla brakujących pól telemetrii.
2. Dodanie mapowania aliasu `battery` $\rightarrow$ `battery_pct` w `worker_cache.py`.
3. Włączenie domyślnego `AMD_TELEMETRY_MODE=PRECOMPUTED` w eksporcie GUI (oszczędność ~11.3 ms CPU na klatkę).
4. Optymalizacja kadrowania `CPU_ABOVE_MAP` dla wielu rozproszonych wskaźników (multi-region / per-widget cropping, oszczędność ~5.5 ms CPU na klatkę).
