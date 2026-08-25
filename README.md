# Dokumentacja modułów projektu TeleM

Projekt TeleM to aplikacja do nakładania telemetrii GoPro (prędkość, wysokość, mapa GPS, dane FIT/GPX) na wideo, z GUI w PySide6.

## Struktura ogólna

Repozytorium dzieli się na katalogi: `src/gui` (interfejs PySide6), `src/indicators` (renderowanie wskaźników overlayu), pliki telemetryczne na poziomie głównym repo, oraz `tests/` i `archive/`.

## Moduł startowy

| Plik | Rola | Zależności |
|---|---|---|
| TeleMGP0.py | Launcher aplikacji — uruchamia GUI PySide6 z zakładkami; re-eksportuje funkcje telemetrii dla kompatybilności testów | src.telemetry_extract, src.gui.qt.application |

## Moduły telemetryczne (root)

| Plik | Do czego służy | Zależności |
|---|---|---|
| telemetry_fit.py | Parsuje pliki FIT (Garmin) — odczytuje pola liczbowe z rekordów `record`, konwertuje semicircles→stopnie, m/s→km/h, synchronizuje z osią czasu wideo | fitparse (opcjonalna), pathlib, math |
| telemetry_gpx.py | Parsuje pliki GPX (trkpt), obsługuje rozszerzenia Garmina (power, atemp, hr, cad), liczy prędkość i dystans metodą haversine | xml.etree.ElementTree |
| video_preview_new.py | Widget podglądu wideo PySide6 z suwakiem osi czasu, przeciąganiem wskaźników myszką i przyciskami wycinania (cut/undo/restore) | PySide6, src.gui.qt.signals, src.gui.qt.widgets.marker_bar |

## Pakiet src/gui — interfejs użytkownika

| Plik | Rola |
|---|---|
| qt/ (podkatalog) | Implementacja UI PySide6 (aplikacja, sygnały, zakładki) |
| indicator_schemas.py | Definicje schematów/konfiguracji wskaźników nakładanych na wideo |
| layout_manager.py | Zarządzanie układem elementów na overlayu (pozycje, rozmiary) |
| telemetry_manager.py | Warstwa pośrednicząca ładująca dane telemetryczne dla GUI |
| def_layout.json | Domyślny układ wskaźników (dane konfiguracyjne, nie kod) |

## Pakiet src/indicators — silnik renderowania overlayu

- compositor.py — główna funkcja `compose_overlay`/`render_preview`, składa wszystkie wskaźniki w jedną klatkę
- dispatcher.py — `render_value_indicator`, routing do odpowiedniego renderera na podstawie typu wskaźnika
- chart_builder.py / chart_utils.py / chart.py — budowanie danych wykresu i renderowanie wskaźnika typu wykres
- bar.py, gauge.py, segment_bar.py — renderery pasków, zegarów wskazówkowych i pasków segmentowych
- text.py, custom_text.py — renderowanie wskaźników tekstowych i tekstu niestandardowego
- time_display.py — nowoczesny, wielolinijkowy blok czasu/daty (zastąpił legacy time_block)
- static_map.py, moving_map.py — wskaźniki mapy statycznej i mapy podążającej za pozycją (korzystają z map_renderer.py)
- rotated_paste.py — pomocnicza funkcja wklejania obrazu z rotacją
- helpers.py — cache fontów, parsowanie kolorów hex, wspólne narzędzia
- registry.py — rejestr dostępnych typów wskaźników
- frame_data.py — przygotowanie danych klatki (`prepare_overlay_frame_data`)

Zależności: wszystkie moduły w `indicators/` opierają się na PIL (Pillow) do rysowania i na danych z telemetry_extract.py/telemetry_fit.py/telemetry_gpx.py.

## Moduły pomocnicze na poziomie src/

| Plik | Rola | Zależności |
|---|---|---|
| overlay_renderer.py | Warstwa kompatybilności wstecznej — re-eksportuje wszystko z src.indicators.* | src.indicators.* |
| map_renderer.py | Pobieranie kafelków map (CartoCDN), cache dyskowy/pamięciowy, rysowanie trasy GPS i markera pozycji na mapie | PIL, urllib.request |
| telemetry_extract.py | Parsowanie JSON z ExifTool, ekstrakcja próbek (prędkość, wysokość, ISO, ekspozycja, temperatura, trasa), interpolacja i wygładzanie (moving average, EMA), obsługa rotacji wideo | exiftool (subprocess), orjson (opcjonalnie), ffprobe |
| telemetry_gpmf.py / telemetry_gpmf_new.py | Parsowanie natywnej telemetrii GoPro GPMF (starsza i nowsza wersja) | |
| ffmpeg_pipeline.py | Pipeline renderowania finalnego wideo przez FFmpeg | |
| video_helpers.py | Funkcje pomocnicze do obsługi plików wideo | |

## Zależności zewnętrzne (pyproject.toml)

Python ≥3.10, Pillow jako zależność podstawowa; opcjonalnie: fitparse (pliki FIT), opencv-python (przetwarzanie wideo), orjson (przyspieszenie JSON). Testy: pytest (katalog tests/). Lintowanie: Ruff.

## Uproszczony graf zależności

TeleMGP0.py → src.telemetry_extract, src.gui.qt.application
src.gui.qt.application → src.gui.* (layout_manager, telemetry_manager, indicator_schemas)
src.gui.* → src.indicators.* (compositor, dispatcher, registry)
src.indicators.* → telemetry_extract.py, telemetry_fit.py, telemetry_gpx.py, telemetry_gpmf*.py, map_renderer.py
ffmpeg_pipeline.py → video_helpers.py, src.indicators.compositor
