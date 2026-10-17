# SPORTCAMHUD — ETAP 5X: polskie znaki, precyzja, rozpoznawanie wskaźników

2026-10-15, Europe/Warsaw. **STATUS: PASS** (Polskie znaki PASS, Precyzja PASS, Registry PASS, Podgląd/eksport PASS z zastrzeżeniem w p. 10).

## 1. HEAD i Git
- Start: `8af7934`, gałąź `fix/gui-freeze-hud-composite`, working tree bez obcych zmian w plikach etapu. Koniec: `f520f1d`.
- Commity:
  - `aa1ee2f` fix(hud): fallback missing Polish glyphs without changing primary font
  - `dc38959` fix(hud): unify decimal precision resolution
  - `f520f1d` fix(hud): prevent indicator type alias collisions
- Niezacommitowane pozostają tylko wcześniejsze/cudze zmiany: `def_layout.json`, eksportery Intel/NVIDIA, `live_av_mux.py`, raport 5R‑F, `tools/validate_5w_map_gpu.py`, artefakty w `Raporty/`. `helpers.py` rozdzielono między dwa commity (staging tylko fragmentu fallbacku).
- `def_layout.json`: SHA256 `65fa8390…606f4` przed i po (sprawdzane po każdym eksporcie testowym), tylko odczyt. Bez reset/clean/stash/rebase/merge/push, bez portable, bez zmian DLL.

## 2. Przyczyny
1. **Polskie znaki:** wszystkie fonty HUD ładuje `helpers.load_font` (jedno `ImageFont.truetype`). Digital-7 ma w `cmap` 104 kody, bez `ąćęłńóśźż/ĄĆĘŁŃÓŚŹŻ` i bez `°`; Pillow rysował glif `.notdef` (w Digital-7 wygląda jak „0”: „PRZECHY0”, „0REDNIA PR0DKO00”). Mechanizmu zastępczego nie było, poza graficznym `°`.
2. **Precyzja:** kanoniczny `telemetry_resolver.resolve_presentation_precision` (wykres: `decimal_places` pierwszy; inne formy: `decimals` pierwszy; clamp 0..2; pola całkowite → 0) był używany przez tekst/kompozytor/wykres, ale `bar.py` (4 miejsca), `widget_cache.py` i `lean.py` (2) czytały wprost `cfg.get("decimals", …)`: ignorowały `decimal_places`, nie ograniczały zakresu, a wartość nieliczbowa/`None` powodowała wyjątek. Fallback w `chart.py` miał odwrotne pierwszeństwo niż resolver.
3. **Registry:** `get_form_for_key` i `get_chart_color` dopasowywały dowolny podciąg: `hr` w `fit_hrv`/`fit_shr` → wykres z kolorem tętna, `alt` w `fit_salt` → bar wysokości. Reguły działają tylko przy tworzeniu nowego wskaźnika (domyślna forma) i dla koloru linii wykresu bez własnego `chart_color`; zapisany `form` zawsze wygrywa przy renderze.

## 3. Zmienione pliki
`src/indicators/font_fallback.py` (nowy), `src/indicators/helpers.py`, `src/telemetry_resolver.py`, `src/indicators/bar.py`, `src/indicators/lean.py`, `src/indicators/widget_cache.py`, `src/indicators/chart.py`, `src/indicators/registry.py`; testy `tests/test_font_fallback_5x.py`, `tests/test_decimal_precision_5x.py`, `tests/test_registry_alias_5x.py`.

## 4. Wykrywanie brakujących glifów
- Własny odczyt tablicy `cmap` TTF/OTF (formaty 4 i 12, platformy Unicode/Windows; obsługa TTC), bez nowych zależności (fontTools nie jest zainstalowany). Wynik buforowany per ścieżka fontu.
- Gdy `cmap` jest nieczytelny: sonda rastrowa — porównanie maski znaku z maską pewnie nieistniejącego kodu `U+10FFFD`.
- Uszkodzony plik: brak wyjątku, font zwracany bez zmian (test `test_broken_font_does_not_crash`).
- Owijanie fontu następuje raz przy `load_font` (cache `FONT_CACHE`), tylko gdy font nie ma którejś polskiej litery. Podział tekstu na przebiegi (font główny / zastępczy) buforowany per tekst (LRU 256). Teksty ASCII i teksty w pełni pokryte idą prosto do Pillow — brak kosztu w hot path.

## 5. Font zastępczy
`C:\Windows\Fonts\segoeui.ttf`, potem `arial.ttf` (używane z systemu, nie kopiowane). Zmienna `TELEM_HUD_FALLBACK_FONT` pozwala wskazać inny. Rozmiar fontu zastępczego jest dobierany tak, by wysokość wersalika „H” była równa fontowi głównemu; glify stoją na linii bazowej fontu głównego, kotwice (`la/ls/mm/rb/lt/md`) liczone z metryk fontu głównego jak w Pillow (test zgodności kotwic ±1 px). Kolor, przezroczystość, obrys, cień i rotacja przechodzą przez te same wywołania Pillow. Diagnostyczny wyłącznik: `TELEM_HUD_GLYPH_FALLBACK=0`.

## 6. Wygląd fontu głównego
- Teksty bez polskich liter: raster bajtowo identyczny z czystym `truetype` (Digital-7, rozmiary 24/48/96, z obrysem i bez; `textbbox` i `textlength` identyczne).
- W tekście mieszanym piksele liter fontu głównego przed pierwszą polską literą są identyczne.
- Pełny eksport AMD z layoutem użytkownika (bez polskich liter w widocznych napisach): MP4 **bajtowo identyczny** z fallbackiem i bez (SHA `80f21814…`, 4 przebiegi).
- Uwaga wizualna: Digital-7 rysuje małe litery jako wersaliki, a fallback zachowuje wielkość litery z tekstu (np. „Dzień” → „DZIEń”). Etykiety wpisane wersalikami dają spójny wynik.

## 7. Symbol stopni
`°` nigdy nie jest podmieniany (`_NEVER_SUBSTITUTE`); dalej rysuje go `draw_text_with_graphic_degree` jako pierścień. Test: `25.5°C`, `-12.8°`, `180°` z obrysem — raster identyczny z fallbackiem i bez. Na rastrze przechyłu widoczne „+12.5°” z pierścieniem (`etap5x_artifacts/run/lean_label_cpu_off_vs_on.png`). **PASS.**

## 8. Reguły decimals / decimal_places
Jedna funkcja `telemetry_resolver.configured_precision(cfg, default)` (używana przez `resolve_presentation_precision` i nowe `helpers.config_decimals`):
- `form == "chart"`: `decimal_places`, gdy brak → `decimals`, gdy brak → domyślna rendera;
- pozostałe formy (Text/Gauge/Bar/Segments/Lean): `decimals`, gdy brak → `decimal_places`, gdy brak → domyślna;
- clamp 0..2; wartość nieliczbowa/`None` → domyślna (wcześniej wyjątek w `bar.py`);
- reguła semantyczna (pola całkowite: tętno, kadencja, ISO, ekspozycja, moc → 0) nadal stosowana tylko w `resolve_presentation_precision`, czyli dla wartości formatowanej przez resolver; renderery bar/lean formatujące własne liczby (zakres, fallback wartości) zachowują dotychczasowe domyślne precyzje.
- Domyślne precyzje i wartości 0..2 obecnego layoutu bez zmian. Testy: 0/1/2, oba klucze, clamp, ujemne, zero, brak danych, zaokrąglanie (`25.43`, `-12.8`, `0.00`). Pozostałe bezpośrednie odczyty poza HUD: `src/ffmpeg/command_builder.py:377` (stara ścieżka FFmpeg CPU) i `intel_multirect_planner.py` (Intel) — nie zmieniane (zakres/izolacja backendów).

## 9. Registry
- Wzorce pasują tylko od początku tokenu rozdzielonego `_`; skróty z `WHOLE_TOKEN_PATTERNS` (`hr`) muszą być całym tokenem. Kolejność reguł bez zmian, aliasy zachowane.
- Dodano regułę koloru `curvpower` (wcześniej dawał ją podciąg `power`).
- Zmiany zachowania (tylko prawdziwe kolizje): `fit_hrv_text` chart→text i kolor domyślny; `fit_shr_text` chart→text; `fit_salt_text` bar→text. Bez zmian m.in.: `hr_text`, `fit_hr_text`, `fit_heart_rate_text`, `fit_cadence_text`, `fit_fractional_cadence_text`, `alt_text`, `fit_enhanced_altitude_text`, speed/passing_speed, power/curVpower, battery/solar, slope, lean, temperatura, kompas, nieznane pola → text.
- Wszystkie 32 klucze obecnego layoutu: forma i kolor identyczne jak w `8af7934` (test porównuje z wersją z git). Deserializacja istniejących layoutów nie korzysta z registry — nie przebudowywano jej.

## 10. Podgląd / eksport
- Podgląd i eksport AMD korzystają z tego samego `load_font` i tych samych rendererów CPU warstwy HUD; nie ma osobnego algorytmu. Zgodność rastrów podgląd↔HUD AMD dla tekstu została wykazana w 5W (max_diff 0); 5X nie zmienia tej ścieżki poza fontem.
- Eksport AMD (kanoniczny harness `--test-amd-export`, `GX020079.mp4 + .fit`, 300 klatek, 4K, HEVC FAST 40M; layout = kopia `def_layout.json` z polskimi etykietami): w klatce MP4 widać „ŚREDNIA PRĘDKOŚĆ”, „DZIEń” w miejsce „0REDNIA PR0DKO00”, „DZIE0” (`run/polish_time_off_vs_on.png`).
- Etykieta przechyłu: na rastrze CPU (ścieżka podglądu) „PRZECHYŁ” zamiast „PRZECHY0” (`run/lean_label_cpu_off_vs_on.png`). **W eksporcie AMD tytuł przechyłu, linia odniesienia i podziałka nie są rysowane w ogóle** — także z wyłączonym fallbackiem; ścieżka GPU przechyłu wysyła tylko obracaną grafikę roweru. Błąd istniał wcześniej, poza zakresem 5X — do osobnego zadania. Dodatkowo w layoucie użytkownika `title_text=""`, więc etykieta i tak jest ukryta.
- Porównanie MP4 jest po kodowaniu (wizualne); równość bajtowa dotyczy przypadku bez polskich liter.

## 11. Render FPS (300 klatek, ta sama para i ustawienia)
| przebieg | fallback | layout | Render FPS |
|---|---|---|---|
| A / A2 | wył. | użytkownika | 41.128 / 40.122 |
| B / B2 | wł. | użytkownika | 41.329 / 39.777 |
| D | wył. | polskie etykiety | 40.156 / 40.102 |
| C | wł. | polskie etykiety | 40.075 / 41.232 |

Średnio ~40.6 w obu wariantach; różnice w granicach rozrzutu powtórzeń (~1.5 FPS). Pełny benchmark 1131 klatek: NOT TESTED.

## 12. Testy
- Nowe testy 5X: 70 (fonty, precyzja, registry); łącznie z testami 5W i fontów: **138 passed**.
- Regresja (73 pliki testów wskaźników/fontów/wykresów/bar/lean): 34 niepowodzenia — **identyczny zbiór** jak na `8af7934` (uruchomionym z eksportu git w izolowanym katalogu); brak nowych błędów. `tests/test_widgets.py` nie importuje się (brak `src.gui.widgets`) — wcześniejszy problem.
- Intel/NVIDIA: brak zmian w ich plikach; wspólne zmiany zwracają te same typy (font = podklasa `FreeTypeFont`, precyzja = int 0..2). Testy sprzętowe Intel/NVIDIA nie uruchamiane.

## 13. Otwarte problemy
- AMD: przechył bez tytułu, linii odniesienia i podziałki (p. 10).
- Fallback zachowuje wielkość liter; Digital-7 ma tylko wersaliki.
- `command_builder.py` / Intel planner nadal czytają `decimals` wprost.
- 34 wcześniejsze niepowodzenia testów i `test_widgets.py`.
- Portable bez aktualizacji (DLL i kod sprzed QP/5W/5X).

## 14. Artefakty
`Raporty/etap5x_artifacts/`: `run_5x_export.py`, `lean_label_raster.py`, `run/*.log|json`, `run/layout_*.json`, `run/*_f150.png`, `run/polish_time_off_vs_on.png`, `run/polish_lean_off_vs_on.png`, `run/lean_label_cpu_off_vs_on.png`. MP4 usunięto po pomiarach.

## 15. ntfy
Wysyłane po zapisaniu raportu; wynik poniżej.

Wynik: wysłano, id=FwVSBpVmjIlc.
