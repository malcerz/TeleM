# RAPORT — Rendering GUI: realny progress + HUD Preview 1 Hz + nowy layout

**Zakres:** przebudowa zakładki Rendering (GUI) — podgląd samego HUD bez filmu (1 Hz),
rzeczywisty progress z autorytatywnego licznika pipeline'u, nowy layout, statystyki.

**STOP** — nie wykonano żadnej dalszej optymalizacji pipeline'u.

---

## STATUS: PASS

Wszystkie bramki zaliczone:
- BRAMKA 2 (progress): **PASS** — milestones 25/50/75/100 przy ~290/570/850/1131, 100% dopiero po faktycznym końcu.
- BRAMKA 3 (wydajność A/B): **PASS** — Δ TRUE FPS = **−0.11%** (w granicach szumu), 1131/1131, drops=0.
- BRAMKA 4 (poprawność): **PASS** — framemd5 OFF == ON (1131/1131 identyczne), audio obecne, brak green/magenta.

---

## AUDIT

- **old progress source:** `sig_progress(int, str)` ← `RenderMixin` `progress_cb` ← eksporter AMD
  `progress_cb(frame_idx + 1, stats_str)` — **pierwszy argument to LICZBA KLATEK, nie procent**.
  GUI `_on_progress(percent, text)` robiło `progress.setValue(percent)` z zakresem 0–100.
- **reason 100% too early:** `setValue(frame_count)` z zakresem 0–100 klampuje do 100%,
  gdy tylko licznik klatek przekroczy 100 (~3 s przy 34 FPS). Prawdziwy procent istniał
  wyłącznie wewnątrz tekstu `stats_str`.
- **new authoritative counter:** `frame_idx + 1` / `expected_progress_frames` w pętli głównej
  eksportera AMD (klatka faktycznie przeszła production pipeline: D3D11VA → VP → HUD → AMF).
  Dostarczany przez backend-agnostic kontrakt `on_render_progress(completed, total, elapsed, fps, hud_state)`.
  Ścieżka software: `total_piped` / `total_overlay_frames` (licznik faktycznie przepuszczonych klatek).
- **total frame source:** dla AMD **dokładna liczba klatek źródła** z ffprobe
  (`_stream_frame_count`), NIE `ceil(duration×fps)`: `expected_progress_frames = source_frames`
  = **1131** (potwierdzone w teście). Ścieżka software używa liczby faktycznie generowanych klatek.

---

## LAYOUT

- **Export button:** old = pełna szerokość na dole okna → **new = prawa strona, bezpośrednio pod
  panelem „Ustawienia eksportu"** (czerwony `EKSPORTUJ`, pod nim `Anuluj`).
- **HUD preview:** lewa strona (~75%), czarne tło, **bez filmu**; widoczny tylko podczas
  renderingu (checkbox „Podgląd HUD podczas renderowania", default **ON**). W trybie idle
  w tym miejscu wraca współdzielony podgląd wideo (do wyboru IN/OUT) — bez regresji.
- **Progress:** dół okna, pełna szerokość — rzeczywisty pasek `completed/total` (0–99% w trakcie).
- **Stats:** pod paskiem progress (dół), 6 linii: `Frame / Progress / FPS / Elapsed / ETA / Status`.

---

## PROGRESS TEST (BRAMKA 2)

Materiał: `GX020079.mp4`, dokładnie **1131 klatek** (30000/1001 fps). Pełny eksport przez
`RenderMixin._render_pipeline` (headless, czyste AMD_* env → production defaults).

| %      | klatki (zmierzone) | oczekiwane (spec) | FPS w punkcie |
|--------|--------------------|-------------------|---------------|
| 0%     | start              | —                 | —             |
| ~25%   | **290** (25.6%)    | ~283              | 33.3          |
| ~50%   | **570** (50.4%)    | ~566              | 34.8          |
| ~75%   | **850** (75.2%)    | ~848              | 35.2          |
| ~99%   | ostatni przed końcem (cap 99%) | —      | —             |
| 100%   | **1131** (100.0%)  | dopiero 1131      | 35.7          |

- `sig_render_progress` events: **114** (co ~10 klatek → ~3–4×/s, płynniej niż 1 Hz).
- **finalization handling:** GUI trzyma **99%** + status **„Finalizacja..."** dopóki pipeline
  nie zgłosi końca (drain/mux); **100% + „Gotowe"** ustawiane wyłącznie w `_on_finished`.
- Błąd/anulowanie: procent zostaje na faktycznej wartości, status „Błąd"/„Anulowano" (bez „Gotowe").

---

## HUD PREVIEW (BRAMKA 3 + architektura)

- **refresh interval:** **maks. 1×/s** — eksporter dusi snapshoty `hud_state` przez
  `time.monotonic()` (`last_hud_report`, 1 s); GUI renderuje wyłącznie gdy `hud_state` nie jest `None`.
  Obserwowane: 28 snapshotów (przebieg BRAMKA 2), 26 (finalny A/B) — ≤ 1 Hz.
- **resolution:** dynamiczna do rozmiaru widgetu (16:9), min. **960 px** szerokości,
  proporcje wg layoutu (np. 960×540); NIE 3840×2160.
- **render thread blocked:** **NO** — eksporter wysyła tylko lekki immutable snapshot
  (`frame`, `ts`) z wątku roboczego; `sig_render_progress` to sygnał Qt (queued → wątek GUI).
  HUD renderowany na czarnym tle (PIL) **poza krytyczną pętlą** — exporter nigdy nie czeka na GUI.
- **GPU readback:** **NO** — brak staging/`Map()`/`CopyResource`/GPU sync/`GetData`.
  Preview = czysta nakładka CPU (ten sam layout, te same wartości, proporcjonalne skalowanie).
- **queue:** **latest-state / single slot** — brak kolejki; `self._hud_ts` nadpisywany każdym
  snapshotem; starsze stany porzucane. **Zero backpressure.**
- **preview updates:** 26 w finalnym A/B (≈0.85/s przy ~38 FPS).

---

## PERFORMANCE (BRAMKA 3 — finalny A/B, ten sam AMD production path)

pool8 · 5Q OPT · GPU map (LANCZOS) · GPU_SPLIT charts · GPU gauge · AMF · D3D11VA · profiler OFF.

| Wariant | TRUE FPS | wall (GUI) | preview updates |
|---------|----------|------------|-----------------|
| A — OFF | **38.108** | 30.598 s   | 0               |
| B — ON  | **38.066** | 30.593 s   | **26**          |
| **Δ**   | **−0.11%** | −0.02%     | —               |

- Próg: spadek <1% (≤2% przy wariancji termicznej) → **Δ = −0.11% → PASS**.
- Dla przejrzystości: wcześniejsze przebiegi (zimny GPU / kolejność) wykazywały wariancję
  34.0–35.2 FPS; finalna para (ciepły, ustabilizowany GPU) daje Δ ≈ 0. HUD Preview (26 renderów
  PIL ~30–50 ms w wątku GUI przez 30.6 s) nie ma mierzalnego wpływu na eksport.
- **GUI responsywne:** praca preview (~50 ms/1 s) na wątku GUI nie zatrzymuje renderera;
  okno pozostaje odpowiedzialne.

---

## CORRECTNESS (BRAMKA 4)

Finalny eksport z HUD Preview ON **identyczny** z OFF:

- **frames:** **1131/1131** (A i B, muxed = amf_out = vp = 1131).
- **drops:** **0** (`dropped_submissions=0`, `input_full=0`, retries=0).
- **audio:** obecne (**AAC**) w obu plikach (strumień wideo HEVC + audio AAC).
- **framemd5:** **OFF == ON — 1131/1131 identyczne** (ścieżka deterministyczna; HUD Preview
  to czysta warstwa UI, nie dotyka eksportu).
- **green/magenta:** brak uszkodzeń — próbki 2/18/34 s: green <0.07%, magenta <0.02%
  (naturalne kolory sceny).
- **brak brakujących widgetów:** klatki zawierają pełny HUD (GPU map/chart/gauge frames = 1131,
  HUD frames = 1131, uploads = 1131).

---

## ODPOWIEDZ WPROST

1. **Dlaczego stary progress osiągał 100% za szybko?**
   Bo `_on_progress` robiło `progress.setValue(percent)`, a backend przekazywał w tym argumencie
   **liczbę ukończonych klatek** (nie procent) — `setValue` z zakresem 0–100 klampował do 100%
   po ~100 klatkach (~3 s). Prawdziwy procent był tylko w tekście statusu.

2. **Jaki licznik jest teraz źródłem progressu?**
   `completed_frames / total_frames` z kontraktu `on_render_progress` — dla AMD to `frame_idx+1`
   faktycznie przetworzonych klatek pipeline'u (D3D11VA→VP→HUD→AMF) względem dokładnej liczby
   klatek źródła z ffprobe (1131); dla software to licznik faktycznie przepuszczonych klatek.

3. **Czy 100% pojawia się dopiero po faktycznym końcu?**
   **Tak.** W trakcie pasek jest ograniczony do 99% (status „Finalizacja..." przy drain/mux);
   100% + „Gotowe" ustawiane tylko w `_on_finished`.

4. **Gdzie znajduje się teraz przycisk Export?**
   Na prawej stronie, bezpośrednio pod panelem „Ustawienia eksportu" (czerwony `EKSPORTUJ`),
   pod nim `Anuluj`.

5. **Gdzie znajduje się progress i statystyki?**
   Na dole okna (pełna szerokość): pasek progress, a pod nim statystyki
   (Frame / Progress / FPS / Elapsed / ETA / Status).

6. **Jak często aktualizowany jest HUD Preview?**
   **Maksymalnie raz na sekundę** (eksporter dusi `hud_state` do 1 Hz przez `time.monotonic()`).
   Obserwowane: 26–28 aktualizacji na ~31 s.

7. **Czy Preview korzysta z GPU→CPU readback?**
   **Nie.** Zero readbacku: brak staging/`Map()`/`CopyResource`/GPU sync. Preview to nakładka CPU
   (PIL) na czarnym tle w małej rozdzielczości (min. 960 px), poza pętlą eksportera.

8. **Czy renderer może czekać na Preview?**
   **Nie.** Eksporter wysyła tylko lekki immutable snapshot (`frame`, `ts`) i nigdy nie czeka.
   Render preview odbywa się w wątku GUI (sygnał queued); przy zaległości starsze stany są
   porzucane (latest-state, zero backpressure).

9. **Ile kosztuje Preview w FPS?**
   **Δ = −0.11%** (38.108 → 38.066 FPS) — poniżej progu 1%, w granicach wariancji termicznej.
   Praktycznie zero: 26 renderów PIL ~30–50 ms przez 30.6 s w wątku GUI, niezależnym od eksportera.

10. **Czy finalny rendering pozostaje identyczny?**
    **Tak.** framemd5 OFF == ON (1131/1131 identyczne klatki), audio obecne, brak green/magenta,
    wszystkie widgety HUD obecne. Nie zmieniono pipeline'u (AMD/AMF/D3D11VA/pool8/5Q/shadery).

11. **Czy GUI pozostaje responsywne?**
    **Tak.** Renderer działa w wątku roboczym i nie jest blokowany przez GUI; preview (~50 ms
    co 1 s) i repaint okna nie zatrzymują eksportu.

12. **Czy zadanie można uznać za zakończone?**
    **Tak (PASS).** Realny progress potwierdzony (BRAMKA 2), wydajność A/B bez degradacji
    (BRAMKA 3), poprawność OFF==ON potwierdzona (BRAMKA 4), layout i statystyki zgodne ze spec.

---

## Pliki zmienione

- `src/gui/qt/tabs/render_tab.py` — nowy layout (HUD Preview lewa / ustawienia+eksport prawa /
  progress+statystyki dół), realny progress (`sig_render_progress`), statystyki, HUD preview 1 Hz
  (latest-state, bez readbacku), checkbox „Podgląd HUD" (default ON), zachowane IN/OUT i settings.
- `src/ffmpeg/amd_native_exporter.py` — parametr `on_render_progress` + snapshot `hud_state` 1 Hz.
- `src/ffmpeg/streaming.py` — parametr `on_render_progress` (AMD + 3 miejsca ścieżki software).
- `src/gui/qt/signals.py` — `sig_render_progress(int, int, float, float, object)`.
- `src/gui/qt/_mixins/render_mixin.py` — emisja `sig_render_progress`.
- `scratch/gui_render_headless.py`, `scratch/gui_render_ab.py` — harnessy testowe (BRAMKA 2/3).

## Wyniki (pliki)

- `Raporty/AMD_ETAP5G/l5_rendergui_a_off.mp4` — eksport A (HUD OFF).
- `Raporty/AMD_ETAP5G/l5_rendergui_b_on.mp4` — eksport B (HUD ON).
- `scratch/rendering_task_spec.txt` — kopia pełnej specyfikacji zadania.
