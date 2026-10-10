# RAPORT: AMD MAP RELATIVE HEADING & EXPORT SUMMARY STATS FIX

Data wykonania: 2026-09-24  
Środowisko: Windows 11 / AMD Radeon Graphics (Ryzen 7 7730U Barcelo-R / VCN 3.x)  
Gałąź: `amd-bikeridehud`  
Status: **PEŁNY SUKCES (ALL GATES PASS)**

---

## 1. Cel zadania (TASK)

1. **Cel 1: Naprawa kąta wskaźnika pozycji (marker arrow) na mapie w trybie Track-Up**:
   - Mapa obraca się płynnie z inercją / wygładzeniem (`map_rotation_smoothing_s`).
   - Wskaźnik (strzałka kierunkowa) nie może być na sztywno przybity do góry ekranu (`TRACK_UP_ARROW_ALWAYS_UP=False`), lecz musi wskazywać rzeczywisty kierunek ruchu pojazdu względem aktualnej orientacji obróconej mapy:
     $$\text{arrow\_screen\_angle} = (\text{vehicle\_heading} - \text{map\_actual\_rotation} + 180.0) \pmod{360.0} - 180.0$$
   - Przy gwałtownym zakręcie (np. o 180°), dopóki mapa nie dogoni kursu, strzałka musi pokazywać ruch do tyłu/w bok względem mapy (`REAL_BACKWARDS_RELATIVE_CASE=PASS`).
   - Emisja logu diagnostycznego dla każdej klatki:
     `[MAP ORIENTATION] t=... vehicle_heading=... map_target_heading=... map_actual_rotation=... arrow_relative_angle=...`

2. **Cel 2: Naprawa statystyk w oknie podsumowania pojedynczego eksportu (FPS & QP)**:
   - Okno podsumowania pojedynczego eksportu wyświetlało czas łączny, ale w polach wydajności i jakości pokazywało: `Średnia wydajność: brak danych` oraz `Średnie QP: brak danych`.
   - Zdiagnozowanie i usunięcie punktów utraty danych:
     - `FPS_DATA_LOST_AT`: Proces potomny (`amd_child_process.py`) nie przekazywał profilu w komunikacie IPC `"complete"`, a `render_mixin.py` nie zasilał `stats` wartościami `real_export_fps`/`true_fps`/`render_fps`.
     - `QP_DATA_LOST_AT`: Statystyka `qp_avg` z profilu AMF nie trafiała do `stats`, a w oknie brakowało fallbacku do `analyze_qp(output)`.
   - Wymagane bramki: `SINGLE_EXPORT_AVG_FPS_NUMERIC=True`, `AVG_QP_AVAILABLE=True`, `AVG_QP_NUMERIC=True`, `EXPORT_STATS_GENERATION_SAFE=True`.

---

## 2. Stan początkowy (INITIAL STATE)

- Wskaźnik mapy w trybie Track-Up w części ścieżek renderowania był orientowany pionowo do góry (0°), ignorując opóźnienie wygładzania obrotu mapy.
- W natywnym potoku AMD C++ `telem_amd_update_map_marker` nie był zasilany na bieżąco z względnym kątem ekranowym w pętli klatek.
- W module GUI `RenderTab._show_export_finished_popup` parametry `avg_fps` i `qp` nie otrzymywały wartości numerycznych po zakończeniu eksportu potomnego, co skutkowało komunikatem `brak danych`.
- W teście 4K na AMD D3D11 z `AMD_BASE_CONVERT_MODE=COMPUTE_P010_NV12` występował błąd `CreateShaderResourceView1 failed: 0x80070057` z powodu pominięcia kopiowania do tekstury ze `SHADER_RESOURCE` przez `CanUseInputSurface`.

---

## 3. Zmienione pliki (CHANGED FILES)

1. [src/indicators/compositor.py](file:///c:/_DEV/SportCamHUD-amd/src/indicators/compositor.py):
   - Dodano argumenty `vehicle_heading: Optional[float] = None`, `heading: Optional[float] = None` oraz `**extra_kwargs: Any` do sygnatury `compose_overlay`.
   - Zabezpieczono fallback kursu pojazdu i przekazano go do `draw_indicator`.
2. [src/ffmpeg/amd_native_exporter.py](file:///c:/_DEV/SportCamHUD-amd/src/ffmpeg/amd_native_exporter.py):
   - Dodano `last_uploaded_marker_deg` do deklaracji `nonlocal` w `_consume_prepared_frame` i zainicjalizowano na `-9999.0`.
   - Zintegrowano obliczanie względnego kąta strzałki ekranowej według reguły najkrótszego łuku kołowego z rzutowaniem perspektywicznym dla pochylenia mapy.
   - Wprowadzono logowanie per-frame `[MAP ORIENTATION]` oraz zasilanie `telem_amd_update_map_marker`.
   - Zapewniono propagację `avg_qp` w statystykach enkodera AMF.
3. [native/d3d11_amf_pipeline/src/telem_amd_native.cpp](file:///c:/_DEV/SportCamHUD-amd/native/d3d11_amf_pipeline/src/telem_amd_native.cpp):
   - Poprawiono warunek `CanUseInputSurface`: w trybie konwersji obliczeniowej `IsBaseConvertCompute()` powierzchnia dekodera jest zawsze kopiowana do `pDecodedCopyTex` posiadającej flagę `D3D11_BIND_SHADER_RESOURCE`, co pozwala shaderowi `DownscaleCompute` bezbłędnie utworzyć SRV i wykonać konwersję P010 $\to$ NV12.
4. [src/ffmpeg/amd_child_process.py](file:///c:/_DEV/SportCamHUD-amd/src/ffmpeg/amd_child_process.py):
   - W `_child_entry` po zakończeniu eksportu odczytywany jest plik `.amd_profile.json` i dołączany jako `"profile": prof_data` w terminalnym komunikacie IPC `"complete"`.
   - W `run_amd_render_child` profil jest propagowany do słownika wyjściowego.
5. [src/gui/qt/_mixins/render_mixin.py](file:///c:/_DEV/SportCamHUD-amd/src/gui/qt/_mixins/render_mixin.py):
   - Do słownika `stats` zwracanego do GUI wprowadzono: `real_export_fps`, `true_fps`, `render_fps`, `effective_fps`, `avg_qp`, `encoder_stats`, `profile` oraz `generation_id`.
6. [src/gui/qt/tabs/render_tab.py](file:///c:/_DEV/SportCamHUD-amd/src/gui/qt/tabs/render_tab.py):
   - Resetowanie `_last_export_fps = None`, `_last_export_qp = None` w `_start_render`.
   - W `_show_export_finished_popup` odczytywanie numerycznego FPS (`stats["real_export_fps"]` lub `stats["true_fps"]` lub `stats["render_fps"]`) oraz `avg_qp` z profilu AMF lub fallbacku `analyze_qp(output)`.
   - Zapisywanie zmierzonych wartości w polach `_last_export_fps` i `_last_export_qp` na potrzeby testów i audytu.

---

## 4. Wyniki walidacji i bramki jakościowe (TESTS & HARD GATES)

### 4.1. Bramki Target 1 (Track-Up Map Marker Relative Heading)
- `TRACK_UP_ARROW_ALWAYS_UP`: **`False` (PASS)**
- `REAL_BACKWARDS_RELATIVE_CASE`: **`PASS`** (dla kąta pojazdu 180° i kąta mapy 20° względny kąt wynosi dokładnie +160°, strzałka wskazuje w dół/do tyłu względem mapy).
- `MAP_PREVIEW_FINAL_PARITY`: **`PASS`** (podgląd i eksport natywny AMD korzystają z tożsamej formuły wrapowania kąta `(v - m + 180.0) % 360.0 - 180.0`).
- Logowanie `[MAP ORIENTATION]`: **`PASS`** (pełny zapis 30 klatek w `scratch/amd_map_export_stats/map_orientation_trace.txt`).

### 4.2. Bramki Target 2 (Export Summary Popup Stats)
- Rzeczywisty eksport AMD 4K (30 klatek, `Video/GX020079.MP4` + `Video/GX020079.fit`):
  - Kod zakończenia: `0` (sukces bez błędów).
  - Czas trwania eksportu: `1.442 s` (czas zegarowy potoku).
  - Rzeczywisty FPS (`real_export_fps`): **`20.806 FPS`** (render FPS potoku: **`35.065 FPS`**).
  - Formatowany FPS w oknie: **`20.8 FPS`** (`SINGLE_EXPORT_AVG_FPS_NUMERIC=True`, `FPS_MATCH=PASS`).
  - Średnie QP ze sprzętowego enkodera AMF: **`31.93`** (`AVG_QP_AVAILABLE=True`, `AVG_QP_NUMERIC=True`).
  - Weryfikacja niezależnym parserem `qp_analyzer.py`: **`31.70`** (`QP_MATCH=PASS`, różnica < 0.23 QP).
  - Formatowane QP w oknie: **`31.9`**.
  - Zabezpieczenie generacyjne (`EXPORT_STATS_GENERATION_SAFE`): **`True`** (`generation_id=1`).

---

## 5. Wygenerowane artefakty (ARTIFACTS)

Wszystkie artefakty zostały zapisane w katalogu `scratch/amd_map_export_stats/`:
1. `map_orientation_trace.txt` — zapis 30 klatek wykonawczych z logami `[MAP ORIENTATION]`.
2. `real_turn_test.txt` — sekwencja 5 stadiów ostrego zakrętu z potwierdzeniem `REAL_BACKWARDS_RELATIVE_CASE=PASS`.
3. `export_profile.txt` — pełny profil JSON wygenerowany przez moduł eksportu AMD.
4. `export_metrics.txt` — syntetyczne zestawienie metryk eksportu i statusów bramek jakościowych.
5. `qp_analysis.txt` — raport z analizy strumienia HEVC narzędziem `qp_analyzer.py`.
6. `single_export_popup.png` — render graficzny okna dialogowego QMessageBox z wartościami `20.8 FPS` i `31.9 QP`.
7. `modified_files.txt` — lista zmodyfikowanych plików produkcyjnych.
8. `reproduction_commands.txt` — komplet poleceń umożliwiających pełną reprodukcję testów.
9. `ntfy_result.txt` — weryfikacja budżetu czasowego (brak przekroczenia, status HEALTHY).

---

## 6. Izolacja backendów (BACKEND ISOLATION)

- Wszystkie zmiany w C++ i Pythonie dotyczą wyłącznie potoku AMD (`native/d3d11_amf_pipeline/` oraz `src/ffmpeg/amd_*`).
- Zmiany w warstwie GUI (`render_mixin.py`, `render_tab.py`, `compositor.py`) są całkowicie neutralne dla backendów NVIDIA oraz Intel i operują na uogólnionym słowniku statystyk oraz parametrach wywołania z `**extra_kwargs`.

---

## 7. Rozbicie budżetu czasowego (TIME BREAKDOWN)

- `TOTAL_STAGE_WALL_TIME`: ~36 min (limit: target $\le$ 60 min, hard max 90 min)
- `AUDIT_TIME`: ~6 min
- `REPRO_TIME`: ~7 min
- `IMPLEMENTATION_TIME`: ~12 min
- `VALIDATION_TIME`: ~11 min
- `LONGEST_SINGLE_COMMAND_SECONDS`: 23.4 s

---

## 8. Podsumowanie (SUMMARY)

Zadanie zostało w pełni zrealizowane zgodnie ze wszystkimi kryteriami akceptacji i twardymi regułami repozytorium. Wskaźnik mapy w trybie Track-Up prawidłowo odzwierciedla kąt względny względem obróconej mapy, a okno podsumowania eksportu natychmiast po ukończeniu pracy wyświetla poprawne, numeryczne statystyki FPS i QP.
