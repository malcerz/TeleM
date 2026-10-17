# RAPORT — Przegląd kodu i ustawień wskaźników (2026-10-15)

## Zadanie
Przejrzeć przesłany `src.zip` i ustawienia wskaźników; wskazać, co jeszcze trzeba poprawić. Przegląd bez zmian w kodzie.

## Stan
- `src.zip` = bieżący `src/` z repo (155/155 plików `.py` identycznych, SHA256). HEAD `cbe0dd4`, gałąź `fix/gui-freeze-hud-composite`.
- Layout: `def_layout.json` (working tree), 32 wskaźniki, 18 włączonych.
- Metoda: statyczne porównanie pól GUI (`gui/qt/models.py`) z kluczami czytanymi przez renderery, analiza `def_layout.json`, test pokrycia znaków fontu Digital-7 (PIL). Bez renderowania klatek.

## A. Błędy: ustawienie w GUI nic nie robi
| # | Wskaźnik | Ustawienie | Stan | Dowód |
|---|---|---|---|---|
| A1 | Mapa | `map_shape` = „Zaokrąglony” i „Prostokąt” | renderowane jako kwadrat | `helpers.apply_map_shape` obsługuje tylko `round`/`circle` (`src/indicators/helpers.py:424`) |
| A2 | Mapa | `map_corner_radius`, `map_border_width`, `map_border_color` | nieużywane przez żaden renderer | pola tylko w `models.py:774-778`; w Twoim layoucie `map_corner_radius=33` nie ma efektu |
| A3 | Mapa | `map_marker_style` | jedyny wybór „Kropka” | `models.py:736` |
| A4 | Tekst | `text_distance`, `unit_offset_x`, `unit_offset_y` | nieczytane przez renderery | `models.py:247, 262-269` |
| A5 | Bar (Segments) | `value_font`, `label_font`, `range_font` | nieczytane przez renderery (pokazywane w panelu) | `models.py:527, 544, 552` |

Rekomendacja: albo zaimplementować (A1–A2: maska z zaokrąglonymi rogami + ramka, analogicznie do istniejącej maski koła; uwaga na ścieżkę GPU Track-Up AMD), albo ukryć pola w GUI. Najpierw A1–A2, bo dotyczą Twojego aktualnego layoutu.

## B. Font i polskie znaki
- Font globalny `Digital-7` nie ma polskich liter: dla `ąćęłńóśźż` i wielkich PIL zwraca ten sam prostokąt 34×42 (glif zastępczy), cyfry mają 30×42. Znak `°` jest obsłużony osobno (`helpers.py:699`), litery nie mają fallbacku.
- W layoucie: etykieta przechyłu `PRZECHYŁ` (Ł) jest **prawdopodobnie** rysowana z pustym prostokątem (nie sprawdzono na klatce). Etykiety czasu zapisano bez polskich znaków („Srednia predkosc”), co wygląda na obejście tego problemu.
- Font nie jest w paczce portable, jest w profilu Windows użytkownika.
- Rekomendacja: fallback per‑znak (jak dla `°`) do fontu z polskimi znakami, oraz dołączenie fontu do `src/assets`.

## C. Ustawienia w `def_layout.json` do przejrzenia
| # | Wskaźnik | Obserwacja | Sugestia |
|---|---|---|---|
| C1 | Garmin Battery (segment bar) | `decimals=2` dla procentów → np. `87.00%` | `decimals=0` |
| C2 | Heart Rate (chart) | linia `#930002` (ciemna czerwień) na wypełnieniu `#ff0000`, zakres 70–120 przy `auto_scale=true` | jaśniejsza linia; zakres i tak z danych |
| C3 | Cadence (chart) | linia `#383838` (prawie czarna) | słabo widoczna na ciemnym tle wideo |
| C4 | Speed (gauge) | `label="speed_text"` (klucz zamiast nazwy), `max_val=30` przy `auto_scale=true` | nadać etykietę; sprawdzić zakres przy zjazdach >30 km/h |
| C5 | Power (bar) | `auto_scale=false`, `max_val=350` | wartości >350 W prawdopodobnie trafią na koniec skali (nie sprawdzono na klatce) |
| C6 | Wysokość (bar) | `rotation="0"` jako tekst, pozostałe wskaźniki mają liczbę | ujednolicić typ (zapis przez GUI) |
| C7 | Temperatura FIT | `unit="C"`, kompas/przechył używają `°` | `°C` |
| C8 | GoPro temp (`temp_text`) | `min_val=0.1` | prawdopodobnie przypadkowa wartość |
| C9 | Solar (bar ruler) | jednocześnie `segments=5` i `segment_count=5` | martwy duplikat klucza |
| C10 | 14 wyłączonych `fit_*` | pozostają w pliku z pełnymi konfiguracjami | można usunąć lub zostawić; bez wpływu na render |
| C11 | Wszystkie | każdy wskaźnik niesie klucze wszystkich form (np. `needle_*` przy tekście i mapie, do 84 kluczy) | czyszczenie przy zapisie do schematu formy zmniejszy szum; bez wpływu na render |

## D. Spójność kodu
- Precyzja wykresów: `chart.py:41-46` (fallback przy nieudanym imporcie) preferuje `decimals`, a kanoniczne `helpers.resolve_decimal_places` → `telemetry_resolver` preferuje `decimal_places` dla wykresów. Fallback działa tylko przy błędzie importu, ale reguły są sprzeczne.
- `registry.py`: dopasowanie formy po podciągu (`"hr"` pasuje do np. `fit_hrv…`, `"alt"` do `…_alt…`), kolejność reguł decyduje; nowe pola FIT mogą dostać niezamierzoną formę.
- Duże moduły: `render_tab.py` 4162, `bar.py` 2275, `render_mixin.py` 1922, `gauge.py` 1451 linii. Plan podziału jest już opisany w `RAPORT_SPORTCAMHUD_ETAP_5M_SOURCE_DEBT_AUDIT.md` (A1–A7, B1–B6, C1–C6). Nie powtarzam go; nadal otwarty.

## E. Inne zauważone przy okazji
- Portable `C:\_DEV\SportCamHUD-portable` ma DLL sprzed poprawki QP (`d66bc70`).
- `tools/build_portable_release.py` ma nieaktualny oczekiwany SHA DLL AMD i wyklucza `src/native` (potrzebny `telem_gpmf_native.pyd`); nie da się go użyć bez zmian.
- Niezacommitowane zmiany NVIDIA/Intel live mux + `live_av_mux.py` nadal wiszą w working tree.

## Proponowana kolejność (po jednym etapie)
1. Mapa: zaokrąglone rogi + ramka (A1–A2), z walidacją Z‑order/pikseli na ścieżce AMD GPU.
2. Fallback polskich znaków dla fontu (B).
3. Ukrycie lub implementacja pozostałych martwych pól (A3–A5).
4. Korekty layoutu C1–C9 (można zrobić od razu w GUI, bez zmian kodu).
5. Aktualizacja portable + naprawa `build_portable_release.py`.

## Testy
NOT TESTED: brak renderu klatek dla punktów B i C2–C4 (obserwacje z konfiguracji i fontu). Punkty A1–A5 potwierdzone przez brak odczytu klucza w kodzie rendererów.

## Izolacja backendów
Brak zmian w kodzie.

## Podsumowanie
Przegląd wykonany. Najważniejsze: martwe ustawienia mapy (A1–A2) i brak polskich znaków w foncie Digital-7 (B).
