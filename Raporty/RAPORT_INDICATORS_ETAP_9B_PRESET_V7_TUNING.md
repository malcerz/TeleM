# TeleM — ETAP 9B: finalny tuning wizualny `cycling_dashboard_v7`

Data: 2026-08-22  
Zakres: **PRESET ONLY**. Nie zmieniano rendererów, telemetryki ani `src/*`.

## 1. Zakres

Nowy preset powstał na bazie `presets/cycling_dashboard_v6.json`. Zachowano v6 i wcześniejsze presety. Zmieniano wyłącznie istniejące właściwości pozycji, rozmiaru, font scale i fill alpha.

## 2. v6 → v7

| Widget | Property | v6 | v7 |
|---|---|---:|---:|
| `track_map` | `x` | 86.0 | 82.0 |
| `track_map` | `y` | 38.0 | 34.0 |
| `track_map` | `size` | 20.0 | 16.5 |
| `slope_text` | `x` | 68.0 | 70.0 |
| `slope_text` | `y` | 53.0 | 58.0 |
| `slope_text` | `size` | 20.0 | 15.0 |
| `fit_cadence_text` | `y` | 85.0 | 82.0 |
| `fit_heart_rate_text` | `y` | 85.0 | 82.0 |
| `fit_heart_rate_text` | `fill_alpha` | 65 | 45 |
| `dist_visual` | `y` | 96.5 | **74.0** |
| `dist_visual` | `size` | 30.0 | 28.0 |
| `dist_visual` | `value_font_scale` | .90 | 1.05 |
| `alt_visual` | `font_size` | 1.20 | 1.38 |
| `fit_enhanced_speed_text` | `size` | 17.3 | 18.5 |
| `fit_enhanced_speed_text` | `font_size` | 2.0 | 2.2 |
| `iso_text` | `font_size` | 1.4 | 1.54 |
| `exposure_text` | `font_size` | 1.4 | 1.54 |
| `temp_text` | `font_size` | 1.4 | 1.54 |
| `fit_curVpower_text` | `value_font_scale` | .90 | 1.04 |
| `compass` | `size` | 7.8 | 7.2 |

`track_map.map_orientation` pozostało `track_up`. Nie dodano `opacity`, ponieważ mapa nie miała tej właściwości w istniejącym presetowym kontrakcie.

## 3. Iteracje

### Pierwsza iteracja

Zastosowano wartości z audytu 9A: zmniejszenie mapy i Slope, podniesienie chartów, wzmocnienie Distance/top telemetry/speed gauge, zmniejszenie Compass oraz osłabienie fill HR.

### Druga iteracja

Po pierwszej klatce v7 jedyna jednoznaczna korekta dotyczyła Distance: `dist_visual.y 78.0 → 74.0`, aby ruler nie wchodził w górną krawędź chartu HR. Wykonano dokładnie dwie iteracje renderu.

## 4. Finalny layout v7

| Element | Finalna pozycja / rozmiar |
|---|---|
| Map | `x=82.0`, `y=34.0`, `size=16.5` |
| Slope | `x=70.0`, `y=58.0`, `size=15.0` |
| Speed Gauge | `x=50.0`, `y=53.0`, `size=18.5`, `font_size=2.2` |
| Cadence chart | `x=24.0`, `y=82.0`, `size=27.0`, window `60 s` |
| HR chart | `x=59.0`, `y=82.0`, `size=27.0`, window `60 s` |
| Distance | `x=50.0`, `y=74.0`, `size=28.0`, value scale `1.05` |
| Compass | `x=70.65`, `y=20.0`, `size=7.2` |

## 5. Speed Gauge

Średnica wzrosła z około `664 px` do około `710 px`. Wartość stała się wyraźniejsza, a gauge zachował centralną pozycję, tick semantics i źródło FIT. Jest teraz silniejszym punktem kompozycji bez zmiany renderera.

## 6. Map

Mapa jest mniejsza o około 17.5% względem v6 i przesunięta lekko w lewo/górę. Track-Up pozostał aktywny. Dominacja prawej strony jest wyraźnie mniejsza; mapa nadal jest czytelna i nie jest obcinana przez canvas.

## 7. Compass

Średnica zmniejszona z `7.8` do `7.2`. Compass nadal korzysta z `heading`, zachowuje cardinals, ticki i semantykę gauge’a. Pozostaje pomocniczy i nie konkuruje już tak silnie z mapą.

## 8. Slope

Rozmiar zmniejszony do `15.0`, pozycja przesunięta do `x=70.0, y=58.0`. Pionowy marker i zakres pozostają bez zmian. W klatce v7 Slope nie dominuje już prawej części i zachowuje czytelność.

## 9. Charts

Cadence i HR są nadal symetryczną parą o szerokości `27.0` i oknie `60 s`. Oba zostały podniesione do `y=82.0`; HR fill alpha zmniejszono do `45`, dzięki czemu czerwony wykres nie konkuruje tak mocno z centralnym speed gauge’em.

## 10. Distance

Distance ma większą wartość tekstową (`1.05`) i został przeniesiony z dolnej krawędzi do `y=74.0`. Po drugiej iteracji ruler znajduje się nad strefą chartów; nie stwierdzono clippingu ani kolizji z gauge’em.

## 11. Top telemetry

ISO, Shutter i Temp mają font `1.54` zamiast `1.4`. Virtual Power ma `value_font_scale=1.04`. Top strip jest czytelniejszy bez zmiany źródeł i semantyki. Battery/Solar pozostawiono na dotychczasowych pozycjach, ponieważ grupowanie nie wymagało dodatkowego ryzyka.

## 12. Altitude

Zmieniono tylko `font_size 1.2 → 1.38`. Geometria i pozycja pozostały bez zmian. Marker jest lepiej widoczny, bez zwiększania zajmowanego obszaru.

## 13. Margins/collisions

Kontrola klatki 3840×2160:

- Compass ↔ Map: zachowany odstęp, brak nakładania;
- Slope ↔ Map: po zmniejszeniu Slope brak nakładania;
- Slope ↔ HR: pozostawiony dodatni odstęp, brak clippingu;
- Slope ↔ Speed Gauge: brak nakładania;
- Distance ↔ charts: po korekcie `y=74.0` ruler jest nad chartami;
- Distance ↔ Speed Gauge: brak nakładania;
- charts ↔ dolna krawędź: zwiększony margines względem v6;
- z-order: niezmieniony.

## 14. Porównanie z `wzor/00000.png`

Podobieństwo wizualne: **wyraźnie poprawione, umiarkowanie dobre**, nadal nie jest to pixel-parity ze wzorcem.

Największe poprawy dotyczą hierarchii: mniejsza mapa, słabszy Slope, mocniejszy centralny gauge, podniesione i zrównoważone wykresy oraz czytelniejsze małe odczyty. Pozostają różnice wynikające z samego wzorca: inna typografia, inny styl ikon/outline oraz brak wiarygodnego Solar.

## 15. Solar

**DATA SOURCE UNRESOLVED**. Nie zmieniono źródła, nie mapowano `solar_pct`, Battery ani innego pola FIT.

## 16. Lean

**DEFERRED**. Nie dodano `lean_angle`, widgetu Bike Lean ani fuzji ACCL/GYRO. `wzor/rower_ico.png` pozostał nietknięty.

## 17. Validation

Wykonano:

- JSON parse `cycling_dashboard_v7.json`;
- layout load dla 3840×2160;
- dwie klatki CPU 3840×2160 przy około 60 s, zgodnie z limitem dwóch renderów;
- kontrolę Track-Up;
- bbox/collision sanity;
- `git diff --check`.

Nie uruchamiano pełnego suite 600+ testów, długiego eksportu AMD ani runtime NVIDIA.

## 18. Lista zmienionych plików

- `presets/cycling_dashboard_v7.json`;
- `Raporty/INDICATORS_ETAP_9B_V7_FRAME.png`;
- ten raport.

Tymczasowy skrypt renderujący został usunięty po pracy. Nie zmieniono `src/*`, presetów v1–v6 ani `wzor/rower_ico.png`.

## 19. Remaining differences

- pełna zgodność ze wzorcem wymagałaby dalszej pracy nad typografią/ikonografią, ale nie jest potrzebna do tego etapu;
- Solar pozostaje nierozwiązany na poziomie danych;
- Lean pozostaje odroczony do kontrolowanej kalibracji IMU;
- nie stwierdzono potrzeby przyszłej zmiany renderera dla zmian wykonanych w 9B.
