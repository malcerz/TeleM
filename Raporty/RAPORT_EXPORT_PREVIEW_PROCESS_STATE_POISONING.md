# Raport — EXPORT PREVIEW process-state poisoning

Data audytu: 2026-09-07  
Branch: `integration/intel-amd`  
HEAD: `59277b4c920e0bb8a9642e4a574a32db0edcfacc`

## Zakres i ograniczenia

Był to audyt lifecycle, bez GPU-tap. Nie zmieniano natywnego pipe writera,
Stage A/B/C, komendy FFmpeg mux, AMF lifecycle ani kompozytora D3D11. Nie
przebudowywano DLL i nie wykonywano commit/push. Worktree zawierał szeroki,
wcześniejszy dirty state; zmiany tego audytu ograniczają się do lifecycle
Preview, diagnostyki oraz harnessu testowego.

Zmodyfikowane w ramach audytu: `src/video_helpers.py`,
`src/gui/qt/tabs/render_tab.py`, `scratch/run_background_preview_audit.py`,
`tests/test_video_helpers.py` oraz `tests/test_amd_background_preview_audit.py`.
Nie zmodyfikowano źródeł native ani DLL.

## Ustalenia lifecycle

| Zasób | Create/owner | Stop / close / destroy | Stan po teardown |
|---|---|---|---|
| Preview worker | `RenderTab._trigger_async_preview`, własny `threading.Event` | `_stop_export_preview()` ustawia event, czeka na `join(3s)`, usuwa referencję | brak worker thread |
| Preview generation | `_start_export_preview_generation()` | nowy identyfikator dla każdego renderu; stare payloady są odrzucane | brak stale callbacku |
| OpenCV `VideoCapture` | `extract_frame()` | Export Preview używa `cache_capture=False`; lokalny capture jest zwalniany w `finally`; teardown dodatkowo `clear_capture_cache()` | cache=0, active decoders=0 |
| PIL/QImage preview cache | `RenderTab` | czyszczony przy stopie; sygnał zawiera generation i jest walidowany przed paint | brak pending frame |
| FFmpeg snapshot helper | worker `subprocess.run` | proces jest synchroniczny i nie pozostaje po workerze | brak preview child PID |
| MPV/QMedia/D3D11/MF Preview | nieużywane w obecnym lekkim AMD Export Preview | brak utworzonych zasobów w ścieżce testowej | `false` / `0` |
| Render cancel/pump/native state | właściciel eksportera renderu, nie Preview | Preview nie współdzieli eventu z nową generacją | `render_cancel_event=false` w snapshotach |

## Znaleziona przyczyna lifecycle Preview

Pierwotnie globalny `_CV2_CAP_CACHE` w `src/video_helpers.py` przechowywał
`cv2.VideoCapture` po zakończeniu renderu/Preview. Preview nie miało pełnego
teardownu: wyłączenie checkboxa tylko blokowało kolejne update'y. To był realny
wyciek zasobu i mógł utrzymywać dekoder oraz uchwyty do następnego renderu.

Wprowadzono minimalny lifecycle fix:

* każdy render dostaje świeży Preview generation, event, pending state i worker;
* snapshot decode nie używa globalnego cache (`cache_capture=False`) i zawsze
  zwalnia lokalny `VideoCapture`;
* Preview OFF oraz koniec renderu wykonują stop/join, czyszczenie pending,
  zamknięcie capture cache i `gc.collect()`;
* queued QImage z poprzedniej generacji jest odrzucany;
* fault workera jest izolowany i nie ustawia render cancel event.

## Snapshoty zasobów

Wartości pochodzą z `[PREVIEW RESOURCE SNAPSHOT]`. RSS/private/commit są
raportowane przez PowerShell `Get-Process` (w środowisku testowym brakowało
modułu `psutil`).

| Punkt | RSS | Private/Commit | Threads | Handles | Preview worker | OpenCV cache | FFmpeg preview | cancel |
|---|---:|---:|---:|---:|---:|---:|---|---|
| A fresh | 156.6 MB | 663.9 MB | 21 | 365 | 0 | 0 | none | false |
| B Preview ON | 1015.6 MB | 1889.0 MB | 44 | 1062 | 1 | 0 | render child alive (not Preview decoder) | false |
| C after injected Preview fault | 1029.5 MB | 1906.3 MB | 44 | 971 | 1/stop set | 0 | render child alive (not Preview decoder) | false |
| D after Preview OFF | 975.3 MB | 1845.6 MB | 36 | 807 | 0 | 0 | none | false |
| E before next Preview-OFF render | 975.3 MB | 1845.6 MB | 36 | 807 | 0 | 0 | none | false |

Snapshot B/C pokazuje koszt aktywnego renderu i sterownika, ale po OFF nie ma
Preview workera, capture ani Preview child process. Nie ma dowodu, że Preview
pozostawia aktywny decoder po teardownie.

## Testy macierzowe (jedna instancja QApplication)

Wszystkie przebiegi miały 1000/1000 klatek, czysty exit FFmpeg, brak
`ERROR_NO_DATA`/`ERROR_BROKEN_PIPE`; `ffprobe` potwierdził HEVC 3840x2160,
1000 klatek i 33.386667 s dla każdego wymienionego MP4.

| Sekwencja | Wynik | Render FPS / Effective FPS |
|---|---|---|
| Preview OFF → OFF → OFF | PASS / PASS / PASS | 38.013 / 40.262; 40.098 |
| Preview ON → OFF → OFF | PASS / PASS / PASS | 39.248 / 35.119; 42.894 / 39.869; 43.056 / 40.140 |
| Preview fault → OFF | PASS / PASS | 42.796 / 37.845; 43.090 / 40.184 |

Fault injection wygenerował kontrolowany `RuntimeError: preview fault injection`.
Drugi render w tej samej instancji zakończył się PASS; cancel event pozostał
`false`.

## Ważne rozdzielenie: niezależny leak renderera/native

Wymóg „brak monotonicznego wzrostu” nie przechodzi nawet w sekwencji bez
Preview. Snapshoty po trzech kolejnych renderach Preview OFF wyniosły:

| Punkt | RSS | Private/Commit | Threads | Handles |
|---|---:|---:|---:|---:|
| A | 156.7 MB | 663.8 MB | 21 | 365 |
| po OFF-1 | 977.5 MB | 1847.6 MB | 36 | 805 |
| po OFF-2 | 1397.8 MB | 2610.4 MB | 40 | 980 |
| po OFF-3 | 1817.9 MB | 3342.9 MB | 40 | 1157 |

Każdy render mimo tego wygenerował poprawny MP4 i PASS. Wzrost obejmuje wątki
i uchwyty procesu, więc nie jest wyjaśniany samym stale Preview. Najbardziej
prawdopodobny obszar dalszego, odrębnego audytu to native D3D11/AMF/MF/driver
resource lifetime (w szczególności obiekty utrzymywane poza Pythonem). Nie
zmieniano go w tym zadaniu zgodnie z zakresem.

## Ocena kryteriów

* PREVIEW ON RENDER: **PASS**
* NEXT PREVIEW OFF RENDER SAME PROCESS: **PASS**
* THIRD RENDER SAME PROCESS: **PASS**
* FAULTED PREVIEW DOES NOT POISON NEXT RENDER: **PASS**
* NO DECODER LEAK (Preview): **PASS** — cache/active decoders=0 po OFF
* NO THREAD LEAK (Preview): **PASS** dla workerów; **FAIL** dla całego procesu
  (niezależny wzrost po OFF-only)
* NO HANDLE LEAK (Preview): **PASS** dla Preview; **FAIL** dla całego procesu
* NO MONOTONIC COMMIT GROWTH: **FAIL** — udowodniony native/render leak
* NO PIPE FAILURE: **PASS** w testach 1000f

## Wniosek / następny krok

Preview miało niepełny teardown i ten błąd został naprawiony diagnostycznie w
minimalnym zakresie. Obecne testy nie potwierdzają jednak gotowości całego
procesu, ponieważ OFF-only ujawnia monotoniczny wzrost pamięci, uchwytów i
wątków. To może tłumaczyć historyczne `0x8007000e` po kilku renderach, ale
call-chain do konkretnego obiektu native nie został jeszcze dowiedziony.

**READY: NO**  
**NOT READY — wymagany osobny, izolowany audyt native D3D11/AMF/MF lifecycle.**

## Weryfikacja techniczna

`py_compile`: PASS  
Focused pytest: **36 passed, 2 deselected**. Dwa pominięte testy dotyczą
wcześniejszej, niezwiązanej różnicy Intel rotation (`null` versus oczekiwany
filter) i nie były zmieniane.
