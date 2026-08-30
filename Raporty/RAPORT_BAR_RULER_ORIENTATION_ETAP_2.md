# TeleM — BAR/RULER: prawdziwa orientacja pionowa ETAP 2

## 1. Dlaczego ETAP 1 nie naprawił `alt_text`

ETAP 1 obejmował wyłącznie klucz `alt_visual`. Fizyczny przypadek użytkownika używał `alt_text` w formie `bar`, stylu `Ruler`, z `rotation=90` i bez pola `orientation`, więc poprzedni warunek nie był wykonywany.

## 2. Aktualny kontrakt `orientation`

`bar.py::_render_ruler_vertical()` już implementuje właściwy kontrakt:

- `orientation=vertical` określa pionową oś, ticki i marker,
- tekst etykiety, wartości i jednostki jest rysowany poziomo,
- `rotation` obraca dopiero gotowy widget.

Nie dodano nowego renderera.

## 3. Properties GUI

Pole `Orientacja` było już obecne w aktualnym `_bar_ruler_fields()` w `src/gui/qt/models.py`, z mapowaniem:

```text
Pozioma -> horizontal
Pionowa -> vertical
```

Jest dostępne dla stylu Ruler w sekcji Gauge. Nie dodano duplikatu pola.

## 4. Legacy migration

Compositor rozpoznaje teraz semantycznie każdą konfigurację:

```text
form=bar/segment_bar
bar_style=ruler
brak orientation
rotation=90 lub 270
```

i używa runtime config:

```text
orientation=vertical
rotation=0
```

Nie jest sprawdzany konkretny ID wskaźnika, więc działa dla `alt_text`, `alt_visual` i innych starych Rulerów o tym samym kształcie. Jawne `orientation` pozostaje nienaruszone.

## 5. Zachowanie `rotation`

Konfiguracja `orientation=vertical, rotation=90` pozostaje świadomym obrotem całego widgetu i nie jest nadpisywana. `rotation` nadal służy do końcowego obrotu widgetu, a `orientation` do geometrii osi.

## 6. Save/load layout

Dodano `normalize_layout_for_save()`. Zapis presetów oraz `def_layout.json` podczas rozpoczęcia renderu zapisuje legacy Ruler jako jawne `orientation=vertical, rotation=0`. Runtime layout nie jest przy tym mutowany.

## 7. `alt_text` real case

Test obejmuje dokładnie:

```text
alt_text
form=bar
bar_style=ruler
rotation=90
orientation missing
```

Effective config ma `orientation=vertical`, `rotation=0`, a bbox ma wysokość większą od szerokości. Tekst nie dostaje legacy transformacji 90°.

## 8. Preview/final parity

Main Preview, Export Preview i Final Render korzystają ze wspólnego `compose_overlay()`. Migracja jest wykonywana w compositorze, więc nie ma osobnej poprawki tylko dla final render.

## 9. Testy

Uruchomiono focused suite obejmujący legacy `alt_visual`, legacy `alt_text`, orientację poziomą/pionową, jawny rotation, bbox, Properties oraz istniejące testy bar/ruler:

```text
63 passed
```

## 10. Zmienione pliki

- `src/indicators/compositor.py` — semantyczna migracja i normalizacja layoutu do zapisu.
- `src/gui/qt/_mixins/preset_mixin.py` — zapis z jawną orientacją.
- `src/gui/qt/_mixins/render_mixin.py` — zapis `def_layout` z jawną orientacją.
- `tests/test_altitude_bar_rotation.py` — przypadki `alt_text`, save normalization i orientacje.
- `Raporty/RAPORT_BAR_RULER_ORIENTATION_ETAP_2.md`.

Nie zmieniano cancel/partial MP4, HUD Resolution/Frequency, map, telemetry, GPU backendów, Lean ani innych wskaźników poza wspólnym kontraktem legacy Ruler.
