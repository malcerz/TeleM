# Raport — synchronizacja filmu z HUD podczas eksportu

## Zadanie

Naprawiono Preview eksportu, w którym tło filmu pozostawało na pierwszej
zapamiętanej klatce, podczas gdy HUD przechodził przez kolejne timestampy.

## Root cause

`RenderTab._build_preview_qimage()` korzystał z `controller.last_src_pil`.
Podczas eksportu nie było żądania nowej klatki filmu dla `hud_state["ts"]`,
a dla natywnego overlayu generowano tylko przezroczystą warstwę HUD. W efekcie
MPV/QMedia pozostawał na pierwszej lub ostatniej klatce.

## Implementacja

Przy każdym throttled snapshotcie eksportera:

```text
exporter HUD timestamp
  → _sync_export_video_to_timestamp(ts)
  → video decoder seek(local timestamp)
  → HUD overlay update
```

- MPV używa `seek(..., reference="absolute+exact")` i jest pauzowany na
  dokładnej klatce eksportu.
- QMediaPlayer dostaje pozycję w milisekundach i jest uruchamiany tylko po to,
  by QVideoSink dostarczył nową klatkę.
- Przy braku aktywnego dekodera fallback dekoduje `ts` przez istniejące
  `extract_frame`, zamiast używać starego `last_src_pil`.
- Kompozycja pozostaje: film → dim video → HUD. Final Render nie korzysta z
  tej ścieżki.

## Wydajność

Synchronizacja wykonuje najwyżej jeden seek na throttled update HUD (~5 Hz),
bez pętli po pikselach i bez zmian eksportera. Pomiar realnego kosztu na
projekcie użytkownika: `NOT TESTED`.

## Zmienione pliki

- `src/gui/qt/tabs/render_tab.py` — synchronizacja dekodera z timestampem HUD
  oraz właściwy fallback decode.
- `tests/test_export_preview_video_restore.py` — regresja MPV seek do bieżącej
  klatki HUD.

## Testy

```text
python -m pytest tests/test_export_preview_video_restore.py \
  tests/test_render_progress_single_source.py tests/test_render_tab.py \
  tests/test_export_lifecycle_p1_fixes.py -q
37 passed, 2 skipped
```

Test rzeczywistego projektu z wizualną obserwacją całego filmu podczas
eksportu: `NOT TESTED`.

## Podsumowanie

```text
VIDEO NO LONGER FIXED TO FIRST FRAME: PASS (test + code path)
VIDEO TIMESTAMP FOLLOWS HUD: PASS (test + code path)
MPV PREVIEW SYNC: PASS
QMEDIA PREVIEW SYNC: PASS (code path, real GUI NOT TESTED)
NO VIDEO FRAME FALLBACK: PASS
FINAL RENDER UNCHANGED: PASS (path isolation)
REAL PROJECT VISUAL PROOF: NOT TESTED
```
