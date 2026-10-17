# SPORTCAMHUD — usunięcie zbędnego komunikatu HLG HDR

Data: 2026-10-16. **STATUS: PASS**

## Zmiana
- `src/gui/qt/tabs/render_tab.py` (`RenderTab._on_source_color_ready`): usunięto gałąź, która dla potwierdzonego HLG wyświetlała pomarańczowy akapit „Wykryto materiał HLG HDR (BT.2020, 10-bit, …). Podgląd w trakcie eksportu…”. Informacja o braku tone mappingu była nieaktualna od 5Z.4.
- Dla HLG etykieta `lbl_hdr_source_info` jest teraz pusta i ukryta (jak dla SDR). Ukryty wiersz nie zajmuje miejsca, więc nie ma pustego kontenera ani dodatkowego odstępu.
- Bez zmian:
  - kontrolka „Tryb HDR” z opcjami „Zachowaj HDR (HLG 10-bit)” i „Konwertuj do SDR (tone mapping)” oraz opisem wybranej opcji;
  - automatyczne wykrywanie HLG;
  - domyślnie „Zachowaj HDR”;
  - komunikaty `HDR: …` dla PQ/HDR10, segmentów mieszanych oraz metadanych niejednoznacznych lub nieczytelnych.
- Nowy test: `tests/test_render_tab_hdr_info_label.py`.

## Testy (Qt offscreen, prawdziwy `RenderTab`)
| przypadek | wynik |
|---|---|
| HLG | selektor widoczny, akapit ukryty (pusty tekst), domyślnie `preserve_hlg`, dwie opcje z niezmienionymi nazwami |
| SDR | selektor i etykieta ukryte |
| niejednoznaczne / nieczytelne / PQ / mieszane | komunikat `HDR: Nie można jednoznacznie ustalić…` widoczny, selektor ukryty |
| wybór trybu | zmiana emituje `amd_hdr_mode`, trafia do opcji zadania (`_build_options_from_gui`), ścieżka przywracania z zapisanych ustawień działa |

- `test_render_tab_hdr_info_label.py`, `test_hdr_export_mode.py` i `test_render_tab_controls_cleanup.py`: **49/49 PASS**.
- Zapis i przywrócenie trybu po restarcie potwierdzono w 5Z.5; kod zapisu nie był zmieniany.
- Bez eksportu 4K i bez przebudowy DLL.

## Ochrona
- `def_layout.json`: `65fa8390d1cda70ed8d115631a75e35559b24b9990e1ca15f944f0fb371606f4` — niezmieniony.
- DLL AMD: `e359d7784d2ff3d2b1aefb6cf56dc1ba3c38a67260fd8d87e27851ef0d55ee89` — niezmieniona.

## Commit
`1385e0d59b600ee304488f111a5c9e67a033bcbf` — fix(gui): drop the HLG description paragraph from the export tab. Zawiera poprawkę kształtu mapy `9391376`.

## Portable
`C:\_DEV\BikeRideHUD-main-new\dist\portable-hdr-hlg-text-cleanup`:
- z commita `1385e0d`, 6320 plików, 1,71 GB;
- w pakiecie: brak tekstu „Wykryto materiał HLG”, obecna poprawka mapy (`BORDER_REPLICATE`), ta sama DLL AMD;
- wcześniejsze pakiety nienadpisane.

ntfy: wysłane po zapisaniu raportu, "id":"ub42xVhppD9o", HTTP 200.
