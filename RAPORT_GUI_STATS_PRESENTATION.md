# RAPORT — Statystyki renderowania + pasek postępu (poprawka prezentacji)

**Zakres:** wyłącznie wygląd (prezentacja) statystyk renderowania i paska postępu w zakładce Rendering.
Backend / progress logic / HUD Preview / pipeline AMD-NVIDIA-Intel **niezmienione**.

---

## 1. Przyczyna migania

Przy każdym evencie progressu **dwa** handlery ustawiały tekst `lbl_stats`:

- `_on_progress` (legacy `sig_progress`) → `lbl_stats.setText(text)`, gdzie `text` to **1-liniowy**
  string z eksportera (`"Render: 57% (645/1131) | 34.2 FPS | ..."`),
- `_on_render_progress` → `_set_stats` → `lbl_stats.setText(...)` z **6-liniowym** formatem
  (`Frame:\nProgress:\nFPS:\nElapsed:\nETA:\nStatus:`).

QLabel przełączał się więc między tekstem 1-liniowym a 6-liniowym w tej samej iteracji event loop →
zmieniała się jego wysokość → **ciągły re-layout pionowy** (przeskakiwanie/rozmazanie) → migotanie.
Dodatkowo brak `wordWrap=False`, brak stabilnej wysokości i `AlignTop` wzmacniały efekt.

## 2. Plik / klasa zmodyfikowana

`src/gui/qt/tabs/render_tab.py` — klasa `RenderTab`, metody `_build_ui`, `_on_progress`, `_set_stats`.

## 3. Sposób usunięcia migania

- **Jeden autorytatywny źródło tekstu**: `_on_progress` już **nie** ustawia tekstu (no-op) — tekst
  statystyk pochodzi wyłącznie z `_set_stats` (przez `sig_render_progress`). Koniec podwójnego `setText`.
- **Stała wysokość**: `lbl_stats` ma `sizePolicy (Expanding, Fixed)` + `wordWrap=False` → wysokość
  = wysokość pojedynczej linii i **nie zmienia się** między update'ami (zero reflow pionowego).
- **Brak hide/show, brak czyszczenia tekstu, brak przebudowy layoutu, brak `adjustSize()`** podczas renderowania.
- **Stabilna szerokość**: label jest `Expanding` (wypełnia szerokość) + `AlignLeft|AlignVCenter` →
  zmiana wartości nie przesuwa layoutu.

## 4. Finalny kolor tekstu

**`color: black`** (`QLabel { color: black; font-size: 12px; }`) — GUI jest jasne (brak globalnego
dark stylesheet), więc czarny tekst jest w pełni czytelny. Bez szarości/transparencji/disabled.

## 5. Finalny format jednej linii

```
Frame: 645 / 1131   |   57.0%   |   FPS: 34.2   |   Czas: 00:18   |   ETA: 00:14   |   Renderowanie...
```

- jedna linia, **bez `\n`**, `wordWrap = False`, separator `   |   `,
- statusy: `Renderowanie...` / `Finalizacja...` / `Gotowe` / `Błąd` / `Anulowano` (bez zmiany logiki),
- koniec: `ETA: 00:00`, `100%`, `Gotowe` (logika bez zmian — tylko format).

## 6. Wysokość paska postępu

**10 px** w stylesheet (`min-height: 10px`) + `setMinimumHeight(10)`; z borderami efektywnie
**12 px** (raportowane przez Qt). ≥ wymagane 8 px, w preferowanym zakresie 10–12 px.
Styl: zaokrąglony, tło `#eee`, chunk zielony — wyłącznie wygląd, logika progressu bez zmian.

## 7. Potwierdzenie — logika renderowania niezmieniona

- Nie zmieniono: liczenia procentu, `completed_frames`, `total_frames`, FPS, ETA, HUD Preview,
  eksportera, render thread, AMD native, GPU pipeline, sygnałów.
- Zmiana dotyczy wyłącznie: stylu `lbl_stats`, formatu tekstu, grubości paska, usunięcia
  redundantnego `setText` w `_on_progress` (GUI thread).

---

## TEST

Smoke test (offscreen, bez eksportu — `scratch/smoke_stats_present.py`):

| Kryterium | Wynik |
|---|---|
| brak migania (geometria stabilna między update'ami) | h 12→12, w 1184→1184 — **stabilne** |
| tekst czarny | `color: black` — **tak** |
| wszystkie dane w jednej linii | `\n` nieobecny — **tak** |
| `wordWrap=False` | **tak** |
| linia nie przeskakuje przy zmianie wartości | geometria stała — **tak** |
| pasek ≥ 8 px | **12 px** (efektywne) |
| progress działa poprawnie | pełny render 1131 klatek: milestones 25/50/75/100 → 290/570/850/1131, `progress_ok=True` |
| rendering nie traci wydajności | TRUE FPS 29.2 w tym przebiegu — znana wariancja termiczna (w tej sesji 34.0–38.1 FPS; ETAP 5M: zakres 26–38 FPS, spread 8.82%). Zmiana prezentacyjna nie dotyka wątku roboczego eksportera — bez regresji z konstrukcji |

Pełny render (harness `scratch/gui_render_headless.py`): `muxed=1131, amf_sub=1131, amf_out=1131,
vp=1131, dropped=0, input_full=0`.

**STOP.** Nie wykonano innych zmian GUI.
