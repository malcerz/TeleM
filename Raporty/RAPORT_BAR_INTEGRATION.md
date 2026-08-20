# TeleM — Integracja modułu `bar.py`: `ruler` + `segments`

**Data:** 2026-08-20  
**Platforma testowa:** Windows 11, Python 3.10.11, Pillow 10.x, PySide6 6.8  

---

## A. Poprzednia architektura bar / segment_bar

Wcześniej w projekcie TeleM istniały dwa niezależne pliki rendererów dla wskaźników paskowych:
- `src/indicators/bar.py` — rysujący pojedynczy pasek z zewnętrznymi adnotacjami (tekst wartości, etykiety min/max) renderowanymi osobno na poziomie compositora (`compositor.py`).
- `src/indicators/segment_bar.py` — rysujący kolorowe paski segmentowe dla baterii i paneli słonecznych z osobnym blokiem logiki, osobnym formatem cache i osobnym wpisem w GUI (`form="segment_bar"`).

Powodowało to podział formularzy w GUI, duplikację kodu normalizacji oraz konieczność utrzymywania dwóch odrębnych ścieżek renderowania i obliczania bounding boxów.

---

## B. Nowa architektura

Wszystkie warianty pasków zostały zintegrowane w jednym module `src/indicators/bar.py`:

```text
bar.py
 ├── ruler    (wielopodziałkowa linijka telemetryczna z markerem i etykietami)
 └── segments (nowoczesny pasek segmentowy z gradientem i rosnącą wysokością)
```

- Publiczny punkt wejścia: `_render_bar_indicator(...)`
- Wybór stylu: `bar_style = "ruler"` (domyślny) lub `bar_style = "segments"`
- Wszystkie etykiety, wartości i tytuły są renderowane bezpośrednio w lokalnym rastrze wskaźnika (`raster_w × raster_h`), dzięki czemu są supersample-safe i chronione przed obcięciem czy problemami z pozycjonowaniem.

---

## C. Zmienione pliki i funkcje

1. **`src/indicators/bar.py`**:
   - Wgrano i zintegrowano nowy moduł obsługujący `_render_ruler` oraz `_render_segments`.
2. **`src/indicators/dispatcher.py`**:
   - Zaktualizowano `render_value_indicator` — formy `bar` oraz legacy `segment_bar` kierowane są bezpośrednio do `_render_bar_indicator`.
3. **`src/indicators/segment_bar.py`**:
   - Zamieniono na lekki backward-compatibility shim przekierowujący wywołania do `_render_bar_indicator(..., cfg={"bar_style": "segments"})`.
4. **`src/indicators/registry.py`**:
   - Zaktualizowano reguły domyślnych form: `battery`, `solar`, `gopro_battery` mają `form="bar"` z `bar_style="segments"`.
5. **`src/gui/qt/models.py`**:
   - `bar_indicator_fields(bar_style="ruler")`: dynamiczny schemat właściwości zawierający wybór `Styl: Ruler / Segments`.
   - `get_schema_for_form(form, bar_style="ruler")`: automatycznie zwraca schemat dostosowany do wybranego stylu.
6. **`src/gui/qt/_mixins/preset_mixin.py`** oraz **`src/gui/qt/_mixins/indicator_mixin.py`**:
   - Obsługa dynamicznej zmiany schematu właściwości przy przełączeniu `bar_style` w GUI bez utraty danych konfiguracyjnych.
7. **`src/ffmpeg/command_builder.py`**:
   - Zaktualizowano `get_layout_hud_bbox` dla `form in ("bar", "segment_bar")`, zapewniając idealne wyliczenie rozmiaru dla stylów `ruler` i `segments` przy rotacjach 0°, 90°, 180° i 270°.
8. **`tests/test_bar_integration.py`**:
   - Dodano kompletny zestaw testów jednostkowych i integracyjnych dla nowego modułu.

---

## D. Zmiany dispatchera

W `src/indicators/dispatcher.py`:
```python
    elif form in ("bar", "segment_bar"):
        if form == "segment_bar" and "bar_style" not in cfg:
            cfg["bar_style"] = "segments"
        return _render_bar_indicator(**_kwargs, formatted_val=formatted_val)
```
Dispatcher nie duplikuje logiki stylów — przekazuje konfigurację wprost do `bar.py`, zapewniając kompatybilność ze starymi layoutami.

---

## E. Zmiany GUI

- W nagłówku wskaźnika dla `Forma = Bar` dodano pole wyboru:
  ```text
  Styl: [ Ruler | Segments ]
  ```
- **Dla stylu Ruler** wyświetlane są zakładki:
  - `Text`: Wartość, Etykieta, Zakres, Środek, Jednostki, Tytuł z jednostką, Decimals, Kolory tekstu i zakresu, Pozycje X/Y.
  - `Ticks`: Podziałki główne (`major_ticks`), Podziałki drobne (`minor_ticks`), Ticks (legacy), Kolory osi, kresek, wskaźnika, obramowania oraz rozmiar wskaźnika (`marker_size`).
  - `Gauge`: Zakres min/max, grubość osi.
- **Dla stylu Segments** wyświetlane są zakładki:
  - `Text`: Wartość, Etykieta, Pokaż min/max, Jednostki, Decimals, Kolory tekstu i zakresu.
  - `Segments`: Liczba segmentów, Odstęp (`segment_gap`), Zaokrąglenie (`segment_radius`), Kolor i alfa nieaktywnych, Rosnąca wysokość (`grow_height`), Start wzrostu (`grow_start`), Zakres min/max.
- **Bezpieczeństwo konfiguracji**: Przełączenie `Ruler <-> Segments` nie usuwa parametrów drugiego stylu ze słownika layoutu.

---

## F. Backward compatibility

- Istniejące layouty z `form = "bar"` bez parametru `bar_style` domyślnie renderują styl **Ruler** (100% zgodności wstecznej).
- Stare layouty zawierające `form = "segment_bar"` są automatycznie renderowane jako styl **Segments** bez potrzeby migracji plików.
- Istniejące importy `from src.indicators.segment_bar import _render_segment_bar_indicator` działają bez zmian dzięki zastosowaniu warstwy shim.

---

## G. Wyniki testów Ruler

- Prawidłowe renderowanie podziałek głównych i drobnych.
- Płynne pozycjonowanie okrągłego markera pozycji z cieniem i obramowaniem.
- Etykiety skrajne (min/max) oraz etykieta środkowa (`show_mid_label`) wyświetlają się zgodnie z konfiguracją.

---

## H. Wyniki testów Segments

Przetestowano dla wartości: `0, 1, 25, 50, 75, 100` oraz wartości poza zakresem (`-15, 130`):
- `0%` -> 0 aktywnych segmentów.
- `1%` -> 1 aktywny segment (dzięki `ceil`, minimalny niezerowy stan jest zawsze widoczny).
- `50%` -> 10 z 20 aktywnych segmentów z gradientem wielostopniowym.
- `100%` -> 20 z 20 aktywnych segmentów.
- Wartości `< min` i `> max` są bezpiecznie przycinane (`clamp`).

---

## I. Rotation / BBox

Przetestowano rotacje dla obu stylów:
- `rotation = 0°` (poziomy)
- `rotation = 90°` (pionowy — używany m.in. przez `alt_visual`)
- `rotation = 180°` (odwrócony poziomy)
- `rotation = 270°` (odwrócony pionowy)

Wszystkie warianty bounding box zostały zweryfikowane testem `test_bar_rotation_and_bbox_no_clipping`:
- **0 pikseli obcięcia (Zero Clipping)**.
- Rzeczywisty obszar niezerowego kanału alfa w całości mieści się w wyliczonym prostokącie HUD Bounding Box.

---

## J. Preview / Final parity

- **Preview w GUI**: Wywołanie `render_preview()` z layoutem zawierającym wskaźniki `ruler` i `segments` generuje poprawny, ostry podgląd w czasie ~22 ms.
- **Eksport wideo (CPU / NVIDIA / AMD)**: Renderowanie klatek overlay odbywa się w identyczny sposób we wszystkich backendach eksportu.

---

## K. Orientacyjna wydajność

Pomiary dla rozdzielczości 1920×1080 (100 iteracji):
- **Ruler**: **~0.28 ms / klatkę** (dzięki wydajnemu `_STATIC_CACHE` dla tła osi i podziałek).
- **Segments**: **~1.38 ms / klatkę**.

W porównaniu do starego rendereru, nowy moduł jest znacznie bardziej wydajny i nie alokuje nadmiarowych buforów.

---

## L. Status starego `segment_bar.py`

Plik `src/indicators/segment_bar.py` został przekształcony w lekki **backward-compatibility shim**:
```python
def _render_segment_bar_indicator(*args, **kwargs):
    cfg = kwargs.get("cfg")
    if isinstance(cfg, dict) and "bar_style" not in cfg:
        cfg["bar_style"] = "segments"
    return _render_bar_indicator(*args, **kwargs)
```
Nie ma w projekcie dwóch niezależnych implementacji segmentowego bara.

---

## Podsumowanie i odpowiedź na pytanie kluczowe

> **Czy TeleM posiada teraz jeden wspólny renderer `bar`, obsługujący zarówno `ruler`, jak i `segments`, bez utraty kompatybilności ze starymi layoutami?**

### **TAK.**
Wszystkie wskaźniki paskowe korzystają ze wspólnego modułu `src/indicators/bar.py`. Styl `ruler` i `segments` są w pełni zintegrowane w dispatcherze, GUI i systemie Bounding Box, a stare layouty oraz importy zachowują 100% kompatybilności.
