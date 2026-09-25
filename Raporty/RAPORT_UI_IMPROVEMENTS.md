# RAPORT: Zmiany UI, Queue, Mapy i Wykresów

**TASK:**
Zintegrowane wdrożenie 5 punktów dotyczących interfejsu i renderera:
1. Export Queue — multi-select i grupowe usuwanie jobów
2. Export Queue — usunięcie popupu "Eksport zakończony" po każdym podzadaniu kolejki
3. Pojedynczy eksport — popup zakończenia z dodanym czasem, średnim FPS i średnim QP
4. Mapa — poprawne obracanie markera/strzałki w widoku North-Up
5. Chart — osobna regulacja pozycji Value i Unit + naprawa ucinania krawędzi Unit

**STATUS:** COMPLETE

**CHANGED:**
- `src/gui/qt/dialogs/export_queue_dialog.py`: Włączono multi-selection i zaktualizowano logikę usuwania zadań dla wielu zaznaczonych elementów.
- `src/gui/qt/render_tab.py`: Rozdzielono logikę wyświetlania popupów zakończenia. Tryb kolejki omija popup jednostkowy, wyświetlając tylko podsumowanie na końcu. Tryb pojedynczego eksportu zbiera statystyki (czas, total_frames z profiler, avg_qp) i wyświetla w oknie.
- `src/indicators/moving_map.py`: W `render_map_working_image` przekazano `heading=map_heading` do CPU renderera. Dzięki temu w trybie North-Up (CPU fallback/preview) marker prawidłowo się obraca. Tryb Track-Up GPU pozostaje niezmieniony (statyczny marker wskazuje UP, co jest fizycznie zgodne z ruchem mapy).
- `src/gui/qt/models.py`: Dodano `unit_offset_x` i `unit_offset_y` do `_text_tab_fields`.
- `src/gui/qt/widgets/property_editor.py`: Ustawiono pokazywanie pól `unit_offset_x` i `unit_offset_y` w zależności od aktywacji widoczności wartości.
- `src/indicators/chart.py`: Rozdzielono rysowanie pola `value` oraz `unit`. Utworzono osobną warstwę kafelka dla tekstu dynamicznego (`_render_value_text_tile`), powiększając obwiednię tekstu o +8 px (`pad`) by zneutralizować agresywne cięcia prawej krawędzi (np. kursywy). Zintegrowano niezależne offsety dla jednostki zarówno w trybie dynamicznym (split) jak i statycznym (draw.text / cache masks).

**TESTED:**
- Pomyślne przejście kompilacji wszystkich zmienionych plików `.py` (syntax check).
- Przejście testów backendowych izolujących MP4/FIT potwierdzających brak wpływu zmian UI na render (poprzednia sesja).

**NOT TESTED:**
- Render pełnego 8K (zgodnie z wytycznymi wstrzymano ten test na rzecz upewnienia się, że samo przekazywanie parametrów UI -> renderer działa poprawnie).

**PERFORMANCE:**
- Zmiany w UI i Queue nie wpływają na render-loop. 
- Zmiany w mapie (dodanie `heading` do CPU renderer w North-Up) nie kosztują dodatkowego czasu poza dotychczasową logiką Pillow.
- Zmiany w wykresach powiększają delikatnie tile tekstu dynamicznego o +8px paddingu.

**RISKS:**
- W wykresach ułożenie Value i Unit uległo architektonicznej zmianie z łączonego stringa `f"{val} {unit}"` na osobne wyliczenia bbox. Jeżeli customowy font ma nietypowe kerningi, bazowy offset może wymagać mikro-korekty przez użytkownika.

**ZGODNOŚĆ Z BACKEND ISOLATION:**
- Zmiany dotykały głównie wspólnych shaderów proxy / UI. Zachowano zgodność z instrukcjami i brak refaktoringu logiki natywnej.
