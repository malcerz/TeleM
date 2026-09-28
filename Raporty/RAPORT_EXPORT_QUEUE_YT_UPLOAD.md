# RAPORT: Export Queue + YouTube Upload

**Data:** 2026-09-21
**Branch:** main
**Status:** PASS

---

## TASK

Zaimplementuj funkcję kolejki eksportu z automatycznym uploadem na YouTube:
- Użytkownik dodaje joby renderowania do kolejki (snapshot bieżących ustawień)
- Kolejka przetwarza je jeden po drugim (MAX_CONCURRENT_RENDERS=1)
- Po każdym renderze, jeśli yt_enabled=True, upload YouTube odbywa się równolegle z kolejnym renderem
- Persystencja na dysk (JSON, atomic replace) — joby przeżywają restart aplikacji
- UI panel w zakładce Eksport: lista jobów, opcje YT, przyciski Start/Pauza/Dodaj/Usuń

---

## ZMIENIONE PLIKI

| Plik | Zmiana |
|---|---|
| src/gui/export_queue.py | NOWY — ExportJob (dataclass), ExportQueue (scheduler), YouTubeUploader |
| src/gui/qt/signals.py | Dodano sig_queue_job_updated, sig_queue_started, sig_queue_paused |
| src/gui/qt/_mixins/render_mixin.py | Hook _notify_queue w worker() |
| src/gui/qt/tabs/render_tab.py | Panel UI kolejki, metody dispatch/refresh, inicjalizacja lazy |
| tests/test_export_queue_basic.py | NOWY — 23 testy jednostkowe |

---

## TESTY

```
23/23 PASSED — 0.87s
```

Pokrycie:
- add/remove jobs
- snapshot immutability
- JSON persistence (roundtrip, running->queued reset, upload_running->waiting reset)
- MAX_CONCURRENT_RENDERS=1 scheduler
- notify_render_done state transitions (success/failure/yt_disabled)
- is_done() state machine (8 parametrów)
- _safe_output_path collision avoidance

Naprawiony deadlock w testach: get_jobs() wewnątrz with q._lock -> deadlock z threading.Lock
(non-reentrant). Zamieniono na bezpośredni dostęp q._jobs[i].

---

## NOT TESTED

- End-to-end: Dodaj -> Render -> Upload YT (brak credentials YT)
- UI: widoczność panelu kolejki w działającej aplikacji (wymaga GUI smoke)
- YouTube OAuth flow (pierwsze uruchomienie)
- _start_render_from_options vs _on_render drift

---

## RYZYKI

1. Drift _start_render_from_options — duplikacja logiki z _on_render
2. YouTube OAuth na Windows — InstalledAppFlow otwiera przeglądarkę
3. Backend isolation — hook jest no-op dla normalnych renderów przez EKSPORTUJ

---

## FINAL SUMMARY

TASK:        Export Queue + YouTube Auto-Upload
STATUS:      PASS (infrastructure + unit tests)

CHANGED:
  src/gui/export_queue.py             (NEW)
  src/gui/qt/signals.py               (+3 signals)
  src/gui/qt/_mixins/render_mixin.py  (+_notify_queue hook)
  src/gui/qt/tabs/render_tab.py       (+queue panel + dispatch logic)
  tests/test_export_queue_basic.py    (NEW, 23 tests)

TESTED:      23/23 unit tests PASS
NOT TESTED:  YT OAuth flow, end-to-end render->upload, GUI smoke
PERFORMANCE: brak regresji AMD pipeline (hook jest no-op dla normalnych renderow)
RISKS:       _start_render_from_options drift vs _on_render; YT OAuth on Windows
