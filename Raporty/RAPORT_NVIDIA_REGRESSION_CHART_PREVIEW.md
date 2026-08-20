# TeleM — NVIDIA: regresje chartów i preview

Data audytu: 2026-08-20  
Materiał: `GX030120.MP4` + `Popoludniowa_jazda_na_rowerze_solar_battery.fit`  
Video: 5400 klatek, 29.970 FPS

## 1. Chart regression root cause

Surowy FIT nie zawierał `None` dla badanych pól:

| pole | próbki | `None` | rzeczywiste `0` | kolejność timestampów |
|---|---:|---:|---:|---|
| cadence | 1741 | 0 | 288 | rosnąca |
| heart rate | 1754 | 0 | 0 | rosnąca |

Zera cadence są prawidłowymi pomiarami postoju i pozostały niezmienione.

W obu seriach FIT występuje długa luka czasowa:

- cadence: 1885 s między `13:03:20` i `13:34:45`;
- heart rate: 1879 s między `13:03:20` i `13:34:39`.

Poprzedni renderer rysował jedną polilinię przez tę lukę. Powodowało to sztuczne połączenie od końca jednego segmentu do początku następnego. Dodatkowe pionowe przejścia cadence przy wartościach `0.0` są obecne w FIT i nie są regresją transportu ani precompute.

## 2. Etap, na którym dane stają się błędne

Nie stają się błędne w pipeline danych:

- raw FIT → `chart_data` OFF: identyczne timestampy, wartości, stany missing i kolejność;
- `chart_data` OFF → cache PRECOMPUTE ON: identyczne dane;
- dla cadence: `1741 == 1741`, `288` zer zachowane;
- dla HR: `1754 == 1754`, brak zer i `None` zachowany;
- nie znaleziono konwersji `None → 0`, duplikatów timestampów, sliding window ani obcięcia początku historii.

Kontrolne klatki `0, 1350, 2700, 4050, 5399` zachowały pełną historię. Pierwszy timestamp był stały i równy początkowi aktywności FIT, liczba próbek nie malała, a zmieniało się tylko `current_position`.

Minimalna poprawka jest w `src/indicators/chart_utils.py`: polilinia i wypełnienie są dzielone przy `None` oraz przy długiej luce czasowej. Zera nie powodują podziału segmentu.

## 3. Preview regression root cause

Call graph:

```text
stream_overlay_to_ffmpeg
  → _report_stream_progress
    → on_render_progress
      → sig_render_progress
        → RenderTab._on_render_progress
          → _trigger_async_preview (~5 Hz limit)
            → _build_preview_qimage
              → render_preview
                → sig_export_preview_ready
                  → preview widget
```

`RenderTab` posiadał już asynchroniczny renderer preview i limit częstotliwości. Preview przestał działać, ponieważ `_report_stream_progress()` przekazywał do GUI zawsze `hud_state=None`. Warunek uruchamiający `_trigger_async_preview()` nigdy nie był spełniony.

## 4. Zależność preview od Direct-Region / full canvas

Preview nie został przywrócony przez powrót do produkcyjnego full-canvas HUD. Poprawka przekazuje jedynie snapshot:

```python
{"frame": frame_index, "ts": frame_index / target_fps}
```

GUI rekonstruuje podgląd osobno, w mniejszym rozmiarze i w tle. Produkcyjny worker pozostaje niezależny od tego renderowania.

W bieżącym benchmarku badanego layoutu atlas miał `74.6%` powierzchni i zgodnie z istniejącą logiką wybrano `FULL_FRAME`. Nie zmieniano progu ani geometrii. Direct-Region pozostał aktywną ścieżką implementacji i nie został wyłączony ani cofnięty.

## 5. Minimalne poprawki

Zmieniono tylko:

- `src/indicators/chart_utils.py` — brak łączenia odcinków przez missing/time gap;
- `src/ffmpeg/streaming.py` — przekazanie timestampu eksportu w `hud_state`;
- `tests/test_nvidia_regression_chart_preview.py` — testy kontraktu danych, luk i preview snapshot;
- plik audytu i benchmarku w `scratch/`.

Nie zmieniano zer cadence, telemetry precompute, source resolvera, workerów, `MAX_IN_FLIGHT`, NVDEC/NVENC, geometrii atlasu ani architektury Direct-Region.

## 6. Testy regresyjne

```text
pytest -q tests/test_nvidia_regression_chart_preview.py
3 passed
```

Testy obejmują:

- `None` pozostaje `None`, a `0.0` pozostaje rzeczywistym zerem;
- brak linii przez missing/time gap;
- zero cadence nie rozcina segmentu jako missing;
- zachowanie kolejności timestampów;
- generowanie snapshotu preview z poprawną klatką i timestampem.

## 7. Preview performance cost

W istniejącym GUI preview jest limitowany do około 5 Hz i wykonywany asynchronicznie. Producent wysyła snapshot co 50 klatek; w eksporcie osiągnięto około 2.9–3.1 aktualizacji/s. Nie jest wykonywany pełny kosztowny HUD preview dla każdej klatki.

Headless benchmark nie mierzy czasu samego renderowania Qt widgetu, ale potwierdza, że callback pipeline dostarczył `108/108` snapshotów w każdym z trzech eksportów. Izolowany koszt produkcyjnego handoffu to utworzenie małego słownika i wywołanie callbacku, bez dodatkowego obrazu RGBA.

## 8. Produkcyjny benchmark

Trzy eksporty po poprawce, ten sam materiał i ustawienia:

| run | FRAME_PIPELINE | REAL_EXPORT | preview updates | preview FPS |
|---:|---:|---:|---:|---:|
| 1 | 161.5 FPS | 154.1 FPS | 108 | 3.08 |
| 2 | 156.6 FPS | 150.8 FPS | 108 | 3.02 |
| 3 | 151.0 FPS | 145.6 FPS | 108 | 2.91 |
| mediana | — | **150.8 FPS** | 108 | **3.02** |

`PRODUCTION_TOTAL` wyniósł odpowiednio `35.04 s`, `35.82 s`, `37.08 s`.

Ten wynik nie jest porównaniem z baseline `203.8 FPS`, ponieważ dla wskazanego layoutu bieżący atlas wyniósł `74.6%` i renderer wybrał `FULL_FRAME`. Nie przypisuję tej różnicy preview; jest to osobny, wcześniej znany problem geometrii transportu.

## Konkluzja

- Czy błędne pionowe linie istnieją już w FIT? **Częściowo tak:** rzeczywiste zejścia cadence do `0.0` są w FIT i są poprawne. Sztuczne łączenie przez długą lukę powstawało w rendererze.
- Jeżeli nie, gdzie były wprowadzane? **W rysowaniu jednej polilinii przez lukę czasową**, nie w precompute.
- Czy ETAP 5E spowodował regresję chartów? **Nie w danych ani precompute.** Bieżący kod wymagał korekty rendererowej dotyczącej luk; nie stwierdzono zmiany `None/0` ani sliding window.
- Dlaczego zniknął preview? **`_report_stream_progress()` przekazywał `hud_state=None`, więc GUI nie uruchamiało `_trigger_async_preview()`.**
- Czy Direct-Region pozostał aktywny? **Tak jako normalna ścieżka implementacji; w tym konkretnym układzie fallback wybrał FULL_FRAME przy atlasie 74.6%.**
- Ile FPS kosztuje przywrócenie preview? **Nie wykazano mierzalnego kosztu pipeline handoffu; preview działa asynchronicznie i ogranicza się do około 3 aktualizacji/s. Benchmarku nie należy interpretować jako czystego A/B preview ON/OFF, bo równocześnie działał fallback FULL_FRAME.**

Etap zatrzymany. Nie kontynuowano optymalizacji 5E.
