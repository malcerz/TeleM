# RAPORT — GUI: płynne paski postępu wczytywania i renderingu

**Etap:** 1 (progress bars wczytywania + jeden wspólny pasek eksportu)
**Data:** 2026-08-23
**Zakres:** wyłącznie GUI i raportowanie postępu — bez zmian logiki pipeline'ów NVIDIA/AMD/Intel, dekodowania, enkodowania, GPU compositing, synchronizacji telemetrii, SmartSync, wskaźników, map ani parametrów FFmpeg.

---

## 1. Jak działał dotychczas progress wczytywania

- Po kliknięciu **„Wczytaj"** (`LoadTab._on_load`) wyłączał się przycisk, a `lbl_info` dostawał tekst „Wczytywanie...".
- Backend (`ProjectMixin._on_files_selected` w wątku tła) emitował przez `sig_progress(percent, text)` **istniejące już wartości etapowe**: `0` („Wczytywanie wideo..."), `15` („Analiza strumienia..."), `30` („Sprawdzanie metadanych..."), `45/50/55/65` („Wczytywanie JSON..."/„Generowanie metadanych..."/„GPMF..."/„ExifTool..."/„Parsowanie danych..."), `70` („Metadane gotowe"), `80` („Budowa interfejsu..."), `100` („Gotowe").
- **Brakowało jednak paska postępu** w zakładce Wczytywanie. `LoadTab` reagował na `sig_progress` tylko po to, by po `100` ponownie włączyć przycisk (`_on_loading_done`). Postęp widoczny był jedynie w pasku statusu głównego okna (`MainWindow._on_progress`), a nie jako szeroki pasek pod przyciskiem.
- Błędy wczytywania nie resetowały przycisku w `LoadTab` — przycisk mógł zostać zablokowany po `sig_error` (zależnie od miejsca błędu).

## 2. Jak działał dotychczas progress renderingu

- `RenderTab._on_render` ustawiał pasek `self.progress` na `0`, pokazywał go i emitował `sig_render_requested`.
- Backend (`RenderMixin._render_pipeline` → `stream_overlay_to_ffmpeg`) raportował postęp **wyłącznie w trakcie właściwego renderowania klatek** przez `sig_render_progress(completed, total, elapsed, fps, hud_state)`.
- `RenderTab._on_render_progress` liczył `pct = completed/total * 100` i ustawiał pasek bezpośrednio (kap na `99` podczas finalizacji).
- **Przed pierwszym raportem klatki pasek stał w miejscu na 0%** — cały okres „Przygotowywanie HUD" (inicjalizacja workera, precompute telemetrii, uruchomienie FFmpeg) był niewidoczny.

## 3. Dlaczego „Przygotowywanie HUD" nie miało progressu

- W `RenderMixin._render_pipeline` istniał tylko `sig_progress.emit(5, "Renderowanie HUD...")`, a `RenderTab._on_progress` (handler `sig_progress`) **celowo nic nie robił** (return), żeby nie mieszać go z danymi klatek.
- Właściwa praca „przygotowania HUD" (geometry HUD, `init_worker`, `build_chart_data`, precompute telemetrii, start FFmpeg) działo się wewnątrz `stream_overlay_to_ffmpeg` **zanim** jakikolwiek `on_render_progress` z liczbą klatek został wyemitowany. Backend nie miał żadnego mechanizmu raportowania postępu tych etapów → GUI nie miało skąd wziąć wartości.

## 4. Zmienione pliki

| Plik | Zakres zmiany |
|---|---|
| `src/gui/qt/tabs/load_tab.py` | Nowy szeroki pasek postępu wczytywania + status + płynna animacja (QTimer) + obsługa błędu. |
| `src/gui/qt/tabs/render_tab.py` | Jeden wspólny pasek eksportu 0–100% (HUD prep → klatki → finalizacja), płynna animacja, obsługa raportów fazy. |
| `src/gui/qt/_mixins/project_mixin.py` | Dodatkowe kamienie milowe postępu wczytywania (75/85/90/95). |
| `src/gui/qt/_mixins/render_mixin.py` | Raport fazy „prep" na starcie `_render_pipeline`. |
| `src/ffmpeg/streaming.py` | Helper `_report_phase` + raporty fazy „prep" (0.05/0.45/0.70/1.0) i „finalize". |
| `src/ffmpeg/amd_native_exporter.py` | 4 raporty fazy (prep 0.3/0.6/1.0 + finalize) w `export_amd_native_d3d11`. |

> Uwaga: w working tree znajdują się także **wcześniejsze, niezwiązane z tym zadaniem** zmiany (Intel ETAP 1: `intel_backend.py`, `src/ffmpeg/__init__.py`, `tests/test_intel_backend.py`, combobox `auto` w `render_tab.py`, `test_render_tab.py`; AMD ETAP 10U: `_ABOVE_UPLOAD_BUFFER_MODE_DEFAULT="DIRECT"`, `test_amd_above_upload_buffer_etap10s.py`, `def_layout.json`). Te pliki NIE zostały zmienione w tym zadaniu.

## 5. Zmienione klasy/funkcje/metody

### `src/gui/qt/tabs/load_tab.py` — `LoadTab`
- `__init__`: stan `_loading`, `_load_target`, `_load_display`, `QTimer(30 ms)`.
- `_build_ui`: `load_progress` (QProgressBar pod przyciskami) + `lbl_load_status`.
- `_start_loading()` — pokazuje pasek, startuje animację.
- `_on_load_progress(percent, text)` — ustawia `target_progress` (nigdy nie cofa) i status.
- `_finish_loading_success()` — 100% dopiero przy realnym sukcesie.
- `_on_load_error(msg)` — status „Błąd", bez fałszywego 100%.
- `_load_tick()` — płynna interpolacja display → target.
- `_reset_loading_ui()` — powrót do idle (m.in. przy „Wyczyść").
- `_connect_local_signals` — podpięcie `sig_progress`/`sig_error` z flagą `_loading`.

### `src/gui/qt/tabs/render_tab.py` — `RenderTab`
- Stałe zakresów wspólnego paska: `_HUD_PREP_START/END`, `_RENDER_START/END`, `_FINALIZE_START/END`.
- `__init__`: `_render_target`, `_render_display`, `_render_timer(30 ms)`.
- `_on_render` — reset targetu i start animacji.
- `_on_render_progress` — rozróżnia raport fazy (`"phase"` w `hud_state`) od raportu klatki; mapuje na wspólny zakres.
- `_on_render_phase(hud_state, elapsed)` — mapa fazy na 0–10% / 98–100%.
- `_render_tick()` — płynna animacja.
- `_on_finished` / `_end_render` — finalizacja do 100%, stop timera.

### `src/gui/qt/_mixins/project_mixin.py` — `ProjectMixin._on_files_selected`
- Dodane emisje `sig_progress`: `75` („Przygotowywanie danych..."), `85` („Przygotowywanie podglądu..."), `90` („Pobieranie klatki..."), `95` („Składanie podglądu...").

### `src/gui/qt/_mixins/render_mixin.py` — `RenderMixin._render_pipeline`
- Emisja raportu fazy: `sig_render_progress(0,0,0,0, {"phase":"prep","pct":0.0,"label":"Przygotowywanie HUD..."})`.

### `src/ffmpeg/streaming.py`
- Nowy `_report_phase(on_render_progress, phase, pct, label, elapsed)` — czysty kontrakt raportowania.
- `stream_overlay_to_ffmpeg`: raporty „prep" (0.05 po `total_overlay_frames`, 0.45 po geometrii HUD, 0.70 po `init_worker`, 1.0 po starcie FFmpeg) i „finalize" (przed drain/mux).

### `src/ffmpeg/amd_native_exporter.py` — `export_amd_native_d3d11`
- Raporty fazy: „prep" 0.3 (po starcie), 0.6 (po precompute), 1.0 (przed pętlą klatek), „finalize" (po pętli, przed flush/mux).

## 6. Jak teraz liczony jest progress wczytywania

Backend nadal emituje **rzeczywiste wartości etapowe** przez `sig_progress` (0 → 15 → 30 → 45 → 50/55/65 → 70 → 75 → 80 → 85 → 90 → 95 → 100), pokrywające:

- 0–15% inicjalizacja i analiza strumienia (ffprobe),
- 30–70% sprawdzanie metadanych / GPMF / ExifTool / JSON / parsowanie,
- 75% przygotowanie danych (GPX/FIT),
- 80% budowa strumieni danych,
- 85–95% przygotowanie i złożenie podglądu,
- 100% dopiero, gdy materiał jest w pełni gotowy.

Dla MP4 z istniejącym JSON/cache ścieżka jest krótsza (45 „Wczytywanie JSON..." zamiast generowania) — pasek po prostu szybciej dochodzi do końca, bez sztucznego spowalniania.

## 7. Jak teraz liczony jest progress przygotowywania HUD

„Przygotowywanie HUD" ma przypisany **przedział 0–10%** wspólnego paska. Backend raportuje kamienie milowe fazy przez `on_render_progress(0,0,elapsed,0.0, {"phase":"prep","pct":x,"label":...})`:

- `pct=0.00` — start `_render_pipeline` (render_mixin),
- `pct=0.05` — po obliczeniu ramek (streaming),
- `pct=0.30` — po inicjalizacji AMD native / geometrii,
- `pct=0.45` — po geometrii HUD (streaming),
- `pct=0.60` — po precompute (AMD native),
- `pct=0.70` — po `init_worker` (streaming),
- `pct=1.00` — tuż przed pętlą klatek („Renderowanie klatek...").

GUI przelicza: `overall = 0 + pct * 10` (0–10%). Pomiędzy kamieniami milowymi pasek płynnie przesuwa się (animacja display → target), więc **podczas „Przygotowywanie HUD" pasek działa i się rusza**.

## 8. Jak mapowany jest progress właściwego renderingu

Rendering klatek zajmuje **10–98%** wspólnego paska:

```text
overall = 10 + (completed/total) * 88
```

- `completed`/`total` — rzeczywiste klatki z pipeline'u (`_report_stream_progress`, `sig_render_progress`).
- Gdy `completed >= total` (wszystkie klatki wypisane, trwa mux/flush): `overall` kapowany na `98`, status „Finalizacja...".
- Faza „finalize" (raport `{"phase":"finalize","pct":0}`) mapowana na **98–100%**; 100% ustawiane **wyłącznie w `_on_finished`**, po realnym zakończeniu (zapis pliku).

## 9. Jak zrealizowana jest płynność paska

- Rozdzielono `target_progress` (backend, rzeczywisty/etapowy) od `display_progress` (GUI).
- Osobny `QTimer` co **30 ms** interpoluje: `display += max((target-display)*0.2, 0.3)` (pasek wczytywania) / `0.25` (pasek renderingu), z dokładnym dociągnięciem gdy `delta ≤ 0.2`.
- `display_progress` **nigdy nie rośnie ponad target** i nie cofa się (target monotoniczny przez `max()`).
- Żadnych `sleep()` ani sztucznych opóźnień; szybka operacja → szybki pasek.
- GUI aktualizowane ~33×/s (30 ms), nie per klatka — brak obciążenia CPU i blokady event loop.

## 10. Cancel i Error

- **Cancel (rendering):** `_on_cancel` → `sig_render_cancelled` → `render_cancel_event`; worker kończy pętlę i przez `sig_render_stopped` potwierdza; `_on_stopped` → status „Anulowano", `_end_render` (stop timera, powrót do idle). Podczas `_cancelling` raporty postępu są ignorowane — **pasek nigdy nie dochodzi do 100%**.
- **Cancel w trakcie HUD prep:** po `init_worker` i w pętlach jest sprawdzany `cancel_event`; zatrzymanie wraca przez `sig_render_stopped`.
- **Error (wczytywanie):** `sig_error` → `_on_load_error` → status „Błąd", przycisk włączony, pasek zostaje poniżej 100% (nie udaje sukcesu).
- **Error (rendering):** `sig_error` → `_on_error` → status „Błąd: …", `_end_render`.
- Po błędzie/anulowaniu GUI wraca do stanu umożliwiającego ponowne rozpoczęcie operacji (przyciski włączone, timer zatrzymany).
- Istniejący mechanizm raportowania wyjątków i logowania zachowany (traceback + `sig_error`).

## 11. Czy dotknięto pipeline NVIDIA, AMD lub Intel

**Tak, ale wyłącznie w zakresie dodania callbacków raportowania postępu — zero zmian logiki renderingu:**

- `src/ffmpeg/streaming.py` — dodano `_report_phase` i wywołania `on_render_progress` z fazami. Nie zmieniono: wyboru dekodera/enkodera, komend FFmpeg, geometrii, SHM, kolejki, finalizacji, `_report_stream_progress` (kontrakt klatek bez zmian).
- `src/ffmpeg/amd_native_exporter.py` — 4 wywołania `on_render_progress` (tylko raportowanie). Nie zmieniono pipeline'u AMD native (D3D11/AMF), enkodowania ani muxowania.
- `src/gui/qt/_mixins/render_mixin.py` — dodatkowa emisja `sig_render_progress` (faza prep) przed `stream_overlay_to_ffmpeg`.
- Pipeline NVIDIA/Intel — bez zmian w tym zadaniu; NVIDIA objęta wspólnym kontraktem faz przez `stream_overlay_to_ffmpeg`. Intel (INTEL_FORCE) działa na standardowej ścieżce i również otrzymuje raporty faz/klatek.

**Zachowane:** wybór backendu, dekoder/encoder, NVENC/AMF/QSV config, D3D11/CUDA init, frame ownership, GPU↔CPU sync, frame pooling, kompozycja, telemetria, mapy, wskaźniki.

## 12. Testy wykonane

- `pytest tests/test_render_tab.py tests/test_mp4_inspector.py tests/test_qp_analyzer.py tests/test_nvidia_regression_chart_preview.py tests/test_export_lifecycle_p1_fixes.py tests/test_intel_backend.py -q` → **76 passed**.
- `pytest tests/test_gpmf_cache.py -q` → **3 passed**.
- `pytest tests/test_amd_above_upload_buffer_etap10s.py tests/test_render_tab.py -q` → **27 passed**.
- Offscreen smoke test (`QT_QPA_PLATFORM=offscreen`) nowej logiki: start wczytywania pokazuje pasek, target nie cofa się przy starszym raporcie, animacja osiąga 80→100, błąd nie daje 100%; rendering: prep 0.0→5→10, klatka 50/100 → 54, ostatnia klatka → 98, finalize → 98, animacja do 98, cancel resetuje stan bez 100%, finish → 100. **Wszystkie asercje przeszły.**
- `get_errors` na wszystkich zmienionych plikach → brak błędów.
- Import-check całej aplikacji (`application.main`, `MainWindow`, `AppController`, `LoadTab`, `RenderTab`, `streaming`, `amd_native_exporter`) → OK.

## 13. Testy ręczne do wykonania w GUI na realnym materiale

1. **TEST 1 — Nowy MP4 bez JSON/cache:** `Video/GX010115.MP4` (usuń/uszuń odpowiedni `.json` przy wideo), kliknij **Wczytaj** → pasek pojawia się natychmiast, pokazuje aktualny etap („GPMF: czytanie strumienia...", „Parsowanie danych..."), porusza się płynnie, 100% dopiero gdy aplikacja przełącza się na Projekt i pokazuje podgląd.
2. **TEST 2 — MP4 z istniejącym JSON/cache:** wczytanie szybsze, pasek nadal poprawny (szybkie 45→70), bez sztucznego spowolnienia.
3. **TEST 3 — Rendering:** ustaw encoder/rozdzielczość, **EKSPORTUJ** → pasek startuje od 0%, „Przygotowywanie HUD" ma widoczny ruch (0–10%), bez resetu przechodzi w „Renderowanie klatek" (10–98%), finalizacja, 100% dopiero po zapisie pliku.
4. **TEST 4 — Cancel:** anuluj podczas przygotowywania HUD oraz podczas renderowania → status „Anulowano", pasek poniżej 100%, GUI responsywne, można renderować ponownie.
5. **TEST 5 — Error:** spróbuj eksportu z usuniętym plikiem JSON przy wideo (backend zgłosi „Brak pliku metadanych JSON") → status „Błąd", pasek bez 100%, przycisk wraca.
6. **Regresja wizualna:** porównać klatkę przed/po (np. `wzor/00000.png` vs podgląd) — wyłącznie prezentacja postępu, output identyczny.

## Podsumowanie (AGENTS.md)

### Changed
`load_tab.py`, `render_tab.py`, `project_mixin.py`, `render_mixin.py`, `streaming.py`, `amd_native_exporter.py` — patrz sekcje 4–5.

### Preserved
- Pipeline NVIDIA/AMD/Intel: bez zmian logiki; dodane wyłącznie callbacki postępu.
- `_report_stream_progress` / kontrakt klatek `sig_render_progress` bez zmian.
- Z-order, kompozycja, telemetria, mapy, wskaźniki, FFmpeg parametry — nietknięte.
- GUI: FPS/ETA/Czas/Frame w `lbl_stats` zachowane (w trakcie prep: `FPS: —`, `ETA: —`).

### Tested
Patrz sekcja 12 (76+3+27 passed, smoke offscreen, import-check, get_errors).

### Not tested
- Rzeczywisty eksport GPU (AMD native / NVIDIA NVENC / Intel QSV) na sprzęcie — wymaga realnego materiału i GPU; raporty faz zweryfikowane statycznie i w testach jednostkowych kontraktu.
- NVIDIA path preserved statically; runtime validation was not possible on this machine (AMD).

### Risks / Remaining issues
- Ścieżka „NO HUD" (AMD `direct_gpu_passthrough`) nie raportuje postępu klatek (brak klatek do policzenia) — pasek po prep (10%) przechodzi wprost do 100% na końcu. Edge case bez HUD, bez wpływu na standardowy dashboard.
- Drobna zmiana tekstów statusu w pasku statusu głównego okna (nowe kamienie milowe wczytywania) — wyłącznie prezentacja.
