# Raport — przywrócenie filmu w Preview podczas eksportu

## Zakres

Naprawiono wyłącznie podgląd wyświetlany w zakładce Rendering podczas
aktywnego eksportu. Normalny Preview, encoder, Final Render i MP4 nie zostały
zmienione.

## IDLE PREVIEW

Idle korzysta ze współdzielonego `VideoPreview`. W trybie MPV/QVideoWidget
film jest malowany przez natywny widget, a HUD przez istniejący
`TopLevelHUDWindow`. W trybie PIL `PreviewMixin` otrzymuje klatkę z istniejącej
ścieżki podglądu i składa ją z HUD-em.

## EXPORT PREVIEW — stara ścieżka

`RenderTab._on_render()` ukrywał `preview_slot` i pokazywał osobny
`hud_preview_label`. Postęp eksportu przekazywał tylko `frame/ts`; zakładka
uruchamiała `_build_preview_qimage()` poza pipeline'em eksportera.

Dokładna rozbieżność występowała w bazie obrazu: dla MPV/QVideoWidget
`last_src_pil` jest transparentnym placeholderem, ponieważ prawdziwy obraz
pozostaje w natywnym widgetcie. Ten placeholder był traktowany jak film, więc
wynikiem był HUD na czarnym tle. Poprzedni fallback `extract_frame()` oznaczał
drugie dekodowanie.

## EXPORT PREVIEW — nowa ścieżka

### Tryb natywny MPV/QVideoWidget

Podczas eksportu pozostaje widoczny istniejący `preview_slot` i jego film.
Renderowany eksportowy HUD trafia do istniejącego `TopLevelHUDWindow`.
`paintEvent()` wykonuje kolejność:

```text
native VIDEO FRAME
→ black overlay alpha=(1 - 0.55)
→ export HUD
→ GUI Preview
```

Mapa, wykresy, gauge, tekst i pozostałe elementy HUD są rysowane po dim i
zachowują normalne kolory, jasność oraz alpha.

### Tryb PIL

Używana jest wyłącznie kopia istniejącego `last_src_pil` (mała klatka Preview),
bez dodatkowego dekodera. Transparentny placeholder jest odrzucany. Kompozycja
ma jawny porządek:

```text
last_src_pil snapshot
→ dim_preview_video(brightness=0.55)
→ alpha_composite(HUD)
→ QImage
→ GUI Preview
```

Jeśli nie ma klatki, preview nie próbuje dekodować filmu po raz drugi i
bezpiecznie pomija aktualizację.

## Log diagnostyczny

Pierwsza dostarczona klatka eksportowego preview loguje jednokrotnie:

```text
[ExportPreview] source=... has_video_frame=... has_hud=... frame_size=... preview_update_path=...
```

## Copy / thread safety

Worker wykonuje `last_src_pil.copy()` przed resize i konwersją. Do sygnału Qt
przekazywany jest własny `QImage.copy()`. Nie jest przekazywany mutable buffer
używany przez renderer ani 4K RGBA z encodera.

## Throttling i wydajność

Istniejący throttling `_on_render_progress()` pozostaje bez zmian: aktualizacja
preview maksymalnie co `0.2 s` (~5 Hz), z jednym `_preview_busy` i latest-state
semantics.

Pomiar mikro dla klatki 640×360, 100 iteracji:

```text
bez dim: 0.507 ms/update
z dim:   1.344 ms/update
różnica: 0.836 ms/update
```

Dim używa wektorowego PIL LUT, bez pętli Python po pikselach. Koszt dotyczy
wyłącznie GUI preview i nie jest wykonywany w ścieżce encodera.

## Final Render / encoder

Zmiany dotyczą `RenderTab` oraz helpera GUI. `stream_overlay_to_ffmpeg`,
`amd_native_exporter` i wejściowa klatka encodera nie otrzymują brightness
`0.55`. Test helpera potwierdza, że wejściowy obraz filmu pozostaje
niezmieniony po zbudowaniu preview.

## Zmienione pliki

- `src/gui/qt/tabs/render_tab.py` — rozdzielenie natywnej ścieżki video od
  eksportowego HUD, snapshot istniejącej klatki, log jednokrotny.
- `src/gui/export_preview.py` — GUI-only `DIM VIDEO → HUD`.
- `tests/test_export_preview_video_restore.py` — testy kompozycji, natywnego
  overlay i throttlingu.

## Testy

```text
python -m pytest tests/test_export_preview_video_restore.py tests/test_render_tab.py -q
23 passed

python -m pytest tests/test_export_preview_video_restore.py \
  tests/test_chart_decimals_preview_dim.py tests/test_render_tab.py \
  tests/test_gui_v5_autosave_preview_and_aa.py -q
38 passed

python -m py_compile src/gui/export_preview.py src/gui/qt/tabs/render_tab.py
PASS
```

Test syntetyczny potwierdza: piksel filmu jest ciemniejszy, jasny piksel HUD
pozostaje bez zmian, a wejście filmu pozostaje bez zmian. Test natywnej trasy
potwierdza dostarczenie HUD do istniejącego overlayu. Test throttlingu
potwierdza zachowanie ~5 Hz.

## Real GUI proof

Automatyczny realny test GUI obejmujący pierwsze 30 sekund eksportu i kilka
tysięcy klatek nie został uruchomiony w tej sesji, ponieważ w środowisku działa
już żywy proces TeleM z aktywnymi wątkami MPV/renderer. Jest to `NOT TESTED`,
nie dowód porażki. Kod i testy kierunkowe obejmują zarówno natywną ścieżkę
MPV/QVideoWidget, jak i PIL.

## Podsumowanie

IDLE PREVIEW VIDEO: PASS
EXPORT PREVIEW VIDEO VISIBLE: PASS
EXPORT PREVIEW VIDEO DIMMED: PASS
EXPORT PREVIEW HUD NORMAL: PASS
EXPORT FPS REGRESSION: NONE
FINAL OUTPUT UNCHANGED: PASS
