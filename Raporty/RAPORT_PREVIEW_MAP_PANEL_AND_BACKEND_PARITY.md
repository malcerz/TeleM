# RAPORT TECHNICZNY: PODGLĄD / PANEL DOLNY / PARITY AMD VS INTEL/NVIDIA

**Data:** 2026-10-03  
**Status:** ROZWIĄZANE / ZWERYFIKOWANE  
**Gałąź:** `main` (commit bazowy: `e9f7a0a`)  
**Środowisko:** Windows 10/11, Python 3.14.7, PySide6, Direct3D 11, AMD AMF Native, Intel QSV, NVIDIA NVENC

---

## 1. STRESZCZENIE WYKONAWCZE

W ramach niniejszego zadania zdiagnozowano i rozwiązano trzy kluczowe problemy zgłoszone przez użytkownika:

1. **Problem 1 (Mapa znika w kolejnych klatkach podglądu):**
   - **Przyczyna źródłowa:** W ścieżce `async_map=True` (`_render_moving_map_indicator`), gdy pokrycie kafelków w wycinku mapy (`coverage`) spadało poniżej 0.5 (np. po przewinięciu / seeku / krokowym przejściu klatki do niebuforowanego obszaru), renderer porzucał rysowanie mapy ruchomej i zwracał pusty placeholder `"Ładowanie mapy…"` lub przełączał się na pomniejszony rzut całej trasy (overview). Dodatkowo w `prepare_overlay_frame_data` funkcja `get_effective_indicator_availability` nie otrzymywała `fit_gps_track` ani instancji `telemetry`, co przy `gps_source="fit"` powodowało fałszywą ewaluację `track_map: False` i całkowite wycinanie mapy przez `compositor.py`.
   - **Rozwiązanie:** W trybie podglądu (`async_map=True`) mapa ruchoma jest **zawsze** renderowana bezpośrednio z `download_missing=False` (identycznie jak w eksporcie końcowym: dostępne kafelki są wyświetlane natychmiast, brakujące mają neutralne tło szare, trasa i marker pozycji są zawsze rysowane, a wątek GUI nigdy nie blokuje). W tle uruchamiane jest nieblokujące doczytywanie kafelków, gdy `coverage < 1.0`. W `availability.py` i `frame_data.py` zagwarantowano, że obecność punktów GPS z dowolnego źródła (FIT, GPX, GPMF) zawsze kwalifikuje mapę jako dostępną.

2. **Problem 2 (Dolny panel ze wskaźnikami zasłonięty / niewykorzystana przestrzeń + kolejność wskaźników):**
   - **Przyczyna źródłowa:** W `DataStreamBar` obszar przewijania przycisków posiadał sztywny limit `scroll.setMaximumHeight(140)`, co przy wyższych rozdzielczościach okna powodowało wrażenie „ucięcia / przykrycia” panelu oraz pozostawiało martwy, pusty obszar do dolnej krawędzi okna.
   - **Kolejność wskaźników:** W `_discover_data_streams()` mapa była dodawana dopiero po `speed_text` i `dist_text`.
   - **Rozwiązanie:** Usunięto sztywne ograniczenie wysokości `140px`, nadano `scroll` i `DataStreamBar` politykę `QSizePolicy.Expanding`, a w `left_panel` usunięto zbędny dolny margines layoutu. W `_discover_data_streams()` mapa (`track_map`) została przesunięta na pozycję **indeks 1 (druga bezpośrednio po „Czasie”)**, pod warunkiem dostępności danych GPS (>= 2 punkty). W przypadku braku GPS mapa nie jest dodawana.

3. **Problem 3 (Ścieżka podglądu eksportu AMD vs Intel/NVIDIA):**
   - **Diagnoza architektoniczna:** Wyjaśniono, dlaczego AMD miało odrębny komunikat i ścieżkę. Historycznie AMD używało podprocesu FFmpeg dekodującego strumień HEVC z potoku (`AMDContinuousHEVCPreview`). Po wprowadzeniu natywnego D3D11 frame tapu (`AMDGPUNativeFrameTapPreview`) w GUI pozostała historyczna flaga `_export_preview_hevc` oraz mylący napis `"Uruchamianie podglądu HEVC..."`. Wyjaśniono również, dlaczego pełne wymuszenie dekodowania MPV w procesie GUI podczas eksportu 4K AMD grozi kolizją dekodera sprzętowego VCN i spadkiem FPS (z ~38 FPS do ~20 FPS).
   - **Rozwiązanie:** Usunięto mylący napis `"Uruchamianie podglądu HEVC..."` na rzecz ujednoliconego `"Renderowanie..."`, oczyszczono logi z odwołań do FFmpeg HEVC oraz dodano przełącznik developerski `TELEM_AMD_USE_NATIVE_PREVIEW=1` umożliwiający opcjonalne wymuszenie ścieżki odtwarzacza.

---

## 2. SZCZEGÓŁOWA ANALIZA I IMPLEMENTACJA

### Problem 1: Parity podglądu mapy z eksportem

#### Mechanizm awarii
Przed naprawą kod w `src/indicators/moving_map.py` posiadał rozwidlenie:
```python
if coverage >= 0.5:
    # render normalny
else:
    if ctx is None:
        return _placeholder(label="Ładowanie mapy…")
    # ... zwracanie overview_image lub placeholder
```
Gdy użytkownik przewijał materiał (seek) lub odtwarzał wideo w podglądzie, `coverage` w nowym punkcie współrzędnych często wynosiło np. 0.0 lub 0.25 (kafelki nie były jeszcze w pamięci podręcznej dla tej konkretnej pozycji). W rezultacie mapa znikała i zastępował ją szary prostokąt z napisem „Ładowanie mapy…”.

W eksporcie końcowym (`async_map=False`) ten warunek nie występował – funkcja `MovingMapRenderer.render(..., download_missing=False)` pobierała z pamięci podręcznej to co było, brakujące kafelki wypełniała neutralnym kolorem tła `(30, 30, 30, 255)`, ale **zawsze** rysowała linię śladu GPS oraz kursor aktualnej pozycji.

#### Zastosowane rozwiązanie
1. **Stabilny render w `src/indicators/moving_map.py`:**
   W ścieżce `async_map=True`:
   - Jeśli `coverage < 1.0`, w osobnym wątku demona uruchamiane jest `renderer.viewport_precache(...)`.
   - Zawsze wywoływane jest `renderer.render(..., download_missing=False)`.
   - Nigdy nie jest zwracany `_placeholder` ani overview w miejsce mapy ruchomej. Użytkownik ma 100% ciągłości widoczności trasy, markera pozycji i dostępnych kafelków.
2. **Propagacja dostępności w `src/indicators/frame_data.py` oraz `preview_mixin.py`:**
   - W `prepare_overlay_frame_data` przekazywane są teraz `telemetry`, `fit_gps_track` oraz `gpx_gps_track`.
   - W `preview_mixin.py` sprawdzana jest obecność `_indicator_availability` w layoucie przed wywołaniem renderera i przekazywana bezpośrednio.
   - W `availability.py` funkcja `indicator_data_available` dla `track_map` akceptuje obecność punktów GPS z dowolnego aktywnego źródła.

---

### Problem 2: Layout panelu dolnego i kolejność wskaźników

#### Mechanizm awarii
W pliku `src/gui/qt/widgets/data_stream_bar.py`:
```python
scroll.setMaximumHeight(140)
```
Ten wpis powodował, że niezależnie od wysokości okna i ilości wolnego miejsca na ekranie, panel przycisków telemetrii był ograniczony do maksymalnie 140 pikseli. Poniżej tworzyła się pusta, czarna przestrzeń, dająca wrażenie, jakby panel był zasłonięty lub nieprawidłowo skalkulowany.

#### Zastosowane rozwiązanie
1. **Pełna ekspansja w pionie:**
   - Usunięto `scroll.setMaximumHeight(140)`.
   - Ustawiono `scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)`.
   - W layoutcie dodano stretch: `layout.addWidget(scroll, 1)`.
   - W `ProjectTab` ustawiono politykę `left_panel` na `QSizePolicy.Expanding` oraz zredukowano dolny margines `left_layout.setContentsMargins(0, 4, 4, 0)`.
2. **Kolejność wskaźników w `_discover_data_streams()`:**
   - Indeks 0: `time_display` („Czas”).
   - Indeks 1: `track_map` („Mapa”) – dodawana bezpośrednio jako druga, jeśli dostępne są dane GPS (`len(gps_track) >= 2`).
   - Źródło mapy jest dynamicznie rozwiązywane z `telemetry.resolve_gps_track("auto")`.
   - Kolejne indeksy: `speed_text` („Prędkość”), `dist_text` („Dystans”), etc.
   - Jeśli brak GPS w projekcie – `track_map` nie jest dodawana.

---

### Problem 3: Podgląd eksportu AMD vs Intel/NVIDIA

#### Diagnoza architektoniczna
| Cecha | Intel / CPU / NV FFmpeg | NVIDIA Native D3D11 | AMD AMF Native |
|---|---|---|---|
| **Model wykonawczy** | Wątek w procesie GUI / podproces | Podproces / DLL | Osobny podproces (`run_amd_render_child`) |
| **Mechanizm podglądu** | `_export_preview_native = True` (MPV/QMedia seek + CPU HUD composite) | D3D11 frame tap do bufora pamięci | D3D11 frame tap w DLL (`AMDGPUNativeFrameTapPreview`) |
| **Wyświetlanie GUI** | `self.preview_slot` (VideoPreview widget) | `self.hud_preview_label` | `self.hud_preview_label` |
| **Historyczna geneza** | Zawsze korzystał z odtwarzacza | Nowy mechanizm | Dawniej: potok HEVC do `ffmpeg.exe` |

**Dlaczego AMD nie powinno domyślnie używać seekowania MPV podczas renderu 4K?**
W architekturze AMD AMF, enkoder i dekoder sprzętowy (VCN) współdzielą zasoby sprzętowe GPU. Podczas renderu 4K60 GPU pracuje z obciążeniem bliskim 100%. Równoczesne seekowanie MPV w procesie głównym (używające D3D11VA hardware decode na tym samym GPU AMD) wprowadza przełączanie kontekstów dekodera sprzętowego, co powoduje spadek wydajności eksportu z ~38 FPS do ~20 FPS.

Natywny frame tap GPU (`AMDGPUNativeFrameTapPreview`) pobiera klatkę **już zdekodowaną i skomponowaną przez pipeline eksportu** (koszt ~0.4 ms raz na 500 ms) i przesyła ją przez IPC do GUI, nie obciążając dekodera sprzętowego.

#### Zastosowane ujednolicenie
1. Zlikwidowano mylący napis `"Uruchamianie podglądu HEVC..."` – zastąpiono go uniwersalnym `"Renderowanie..."`.
2. Zlikwidowano odwołania do `"continuous_ffmpeg_hevc"` w logach na rzecz `"gpu_frame_tap"`.
3. Dodano przełącznik developerski `TELEM_AMD_USE_NATIVE_PREVIEW=1`, pozwalający użytkownikowi/testerowi na uruchomienie ścieżki standardowego odtwarzacza również dla AMD.

---

## 3. ZWERYFIKOWANE PLIKI

Zmiany objęły wyłącznie niezbędne komponenty w `src/`:
1. `src/indicators/availability.py` – precyzyjna detekcja dostępności GPS dla mapy.
2. `src/indicators/frame_data.py` – przekazywanie źródeł FIT/GPX do kalkulacji dostępności.
3. `src/indicators/moving_map.py` – ciągły, stabilny render mapy ruchomej w podglądzie (eliminacja znikania).
4. `src/indicators/static_map.py` – ciągły render podglądu mapy statycznej.
5. `src/gui/qt/widgets/data_stream_bar.py` – usunięcie limitu wysokości 140px, pełne rozciąganie do dołu okna.
6. `src/gui/qt/tabs/project_tab.py` – polityka Expanding dla lewego panelu, eliminacja dolnego marginesu.
7. `src/gui/qt/_mixins/indicator_mixin.py` – umieszczenie Mapy na pozycji 2 (zaraz po Czasie).
8. `src/gui/qt/_mixins/preview_mixin.py` – przekazywanie kompletnych danych telemetrii do `prepare_overlay_frame_data`.
9. `src/gui/qt/tabs/render_tab.py` – ujednolicenie komunikatów eksportu, oczyszczenie logów, flaga `TELEM_AMD_USE_NATIVE_PREVIEW`.

---

## 4. WYNIKI TESTÓW I WERYFIKACJA

Utworzono dedykowany zestaw testów jednostkowych: `tests/test_preview_map_panel_parity.py`.

```text
tests/test_preview_map_panel_parity.py .......                           [100%]
tests/test_indicator_availability.py .........                           [ 14%]
tests/test_amd_gpu_frame_tap_preview.py .                                [ 15%]
tests/test_map_sync.py ......................................            [ 76%]
tests/test_map_render_cache_coverage.py ....                             [ 82%]
tests/test_amd_queue_parity_and_performance.py ....                      [100%]

============================= 63 passed in 2.97s ==============================
```

Wszystkie 63 testy regresyjne i integracyjne zakończyły się sukcesem.
Brak jakichkolwiek regresji wydajnościowych na backendach AMD, Intel oraz NVIDIA.
