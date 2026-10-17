# SPORTCAMHUD — poprawka GUI: ogromny kafelek „Mapa” po wczytaniu layoutu

Data: 2026-10-16. **STATUS: PASS**

## Przyczyna
- Panel dostępnych wskaźników (`src/gui/qt/widgets/data_stream_bar.py`, `DataStreamBar`) układa kafelki własnym `FlowLayout`. Jego `_do_layout` pomijał każdy widget z `not widget.isVisible()`.
- „Wczytaj preset” (`PresetMixin._on_load_preset`) ponownie emituje `sig_data_streams_ready`, a `on_streams_ready` usuwa i tworzy kafelki na nowo, gdy panel jest już widoczny. Qt pokazuje dzieci dodane do layoutu z opóźnieniem (wywołanie kolejkowane), więc w chwili układania nowe przyciski nie są jeszcze „widoczne”. Przebieg layoutu je pomija i nie dostają geometrii.
- Ostatni kafelek — „Mapa” — nie otrzymywał już kolejnego przeliczenia. Zostawał z **domyślną geometrią Qt 640×480 px** w lewym górnym rogu panelu i zasłaniał pozostałe kafelki (Twój zrzut).
- Rozmiar mapy HUD nie miał z tym związku: geometria z layoutu nie była przenoszona na widget.

Odtworzenie (offscreen, prawdziwe `AppController` i `MainWindow` z portable `dist/portable-hdr-stage`, szablonowy `def_layout`, film GX020079, potem „Wczytaj preset” z **kopią** Twojego `def_layout.json`):

| moment | kafelek Mapa | pozostałe (maks.) |
|---|---|---|
| po wczytaniu filmu | 44×26 | 260×26 |
| po „Wczytaj preset” (1. i 2. raz) | **640×480** | 260×26 |

Przycisk był w FlowLayout i był widoczny, ale nie dostał geometrii z layoutu. Start aplikacji bezpośrednio z Twoim layoutem (bez „Wczytaj preset”) nie wywołuje błędu — 44×26.

## Naprawa
`FlowLayout._do_layout` pomija tylko widgety **jawnie ukryte** przez kod (`isHidden()` + `WA_WState_ExplicitShowHide`). Kafelki czekające na pokazanie dostają geometrię od razu. Kafelek „Mapa” podlega tym samym regułom co pozostałe. Bez sztywnych rozmiarów, bez zmiany wyglądu innych kafelków, bez zmian HUD.

Zmieniony plik: `src/gui/qt/widgets/data_stream_bar.py` (`FlowLayout._do_layout`) oraz nowy test `tests/test_data_stream_bar_map_tile.py`.

## Testy
| scenariusz | wynik |
|---|---|
| A. start z szablonowym layoutem | Mapa 44×26 |
| B. wczytanie Twojej konfiguracji (kopia, „Wczytaj preset”) | 44×26 |
| C. ponowne wczytanie tej samej konfiguracji | 44×26 |
| D. zakładki | nie dotyczy zmiany (panel nie przebudowuje się przy zmianie zakładki); niezautomatyzowane |
| E. zmiana rozmiaru okna (1920×1040 → 1280×900) | 44×26, pozostałe 260×26 |
| F. zapis i ponowne wczytanie | zapis nie był wykonywany, żeby nie dotykać Twojego `def_layout.json`; wczytanie pokryte w B/C |
| G. mapa na filmie | renderer i HUD nie zmienione; konfiguracja `track_map` w kopii = oryginał (x 7,02, y 26,45, size 13,0) |
| H. pozostałe kafelki | bez zmian (maks. 260×26), `test_preview_map_panel_parity.py` 7/7 |

- Test regresyjny Qt: `tests/test_data_stream_bar_map_tile.py` przebudowuje kafelki dwukrotnie przy widocznym panelu i zmienia rozmiar. Sprawdza, czy wysokość Mapy równa się wysokości nadanej przez layout, czy się nie zmienia i czy nie przekracza innych kafelków. Na nowym kodzie: 1/1 PASS. Na starym kodzie (`git archive` poprzedniego HEAD): **FAIL `(44, 26) != (640, 480)`**, czyli test wykrywa błąd.
- Skalowanie Windows 125% i 150%: nie testowane osobno. Poprawka nie używa wartości pikselowych (geometria pochodzi z `sizeHint`).
- Zrzut po poprawce: `Raporty/map_tile_fix_artifacts/portable_fixed.png` (offscreen, fonty jako prostokąty). Dane geometrii: `*.json` w tym katalogu.

## Ochrona
- `def_layout.json` (Twój): `65fa8390d1cda70ed8d115631a75e35559b24b9990e1ca15f944f0fb371606f4` przed i po. Testy używały kopii `Raporty/map_tile_fix_artifacts/user_layout_copy.json`.
- DLL AMD: `e359d7784d2ff3d2b1aefb6cf56dc1ba3c38a67260fd8d87e27851ef0d55ee89` (bez zmian, także w nowym pakiecie).
- Renderer, HDR, eksport, audio, QP/VBR, Intel/NVIDIA: nie zmieniane.

## Portable
- Nowy pakiet: `C:\_DEV\BikeRideHUD-main-new\dist\portable-hdr-gui-fixed`, z commita `1404441`, przez `tools/build_portable_release.py`; 6320 plików, 1,71 GB.
- Poprzedni `dist/portable-hdr-stage` nienadpisany.
- Test GUI z nowego pakietu jego własnym Pythonem: szablon → film → dwa razy „Wczytaj preset” z kopii Twojego layoutu → zmiana rozmiaru okna: Mapa **44×26** we wszystkich krokach — **PASS**.
- Szablon `def_layout.json` w pakiecie niezmieniony (`9985a035…`).

## Commit
`1404441c291bb678235235ced8bf4896de2498b8` — fix(gui): keep the Mapa indicator tile compact after preset load.

## Uwaga poboczna (niezmieniane)
Panel ma dwa przyciski mapy: „Mapa” oraz „Mapa / FIT” (strumień `track_map` ze źródła FIT trafia też do wiersza FIT). Oba działają; nie zmieniałem tego bez Twojej decyzji.

ntfy: wysłane po zapisaniu raportu, "id":"HQYL6exloFH6", HTTP 200.
