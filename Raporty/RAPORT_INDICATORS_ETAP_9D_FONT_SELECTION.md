# TeleM — ETAP 9D: infrastruktura wyboru fontów

## 1. Nowy materiał testowy

Smoke użył `Video/GX010115.MP4` oraz `Video/Jazda_na_rowerze_w_porze_lunchu.fit`. Dla MP4 wygenerowano `Video/GX010115.json` przez istniejący workflow GPMF→JSON TeleM; parser nie był zmieniany.

## 2. Wynik lekkiej kontroli synchronizacji

Wynik: dopasowanie zaakceptowane. `method=absolute_time_trajectory_refine`, `offset=+2.000 s`, `confidence=high`, `median_error=7.6 m`, `p90_error=12.9 m`, `coverage=1.00`.

## 3. Dwie aktywne referencje TO

`wzor/00000.png` pozostaje referencją geometrii i stylu HUD. `wzor/Zrzut ekranu 2026-08-22 092614.png` pozostaje referencją czytelności overlayu na filmie. Nie wykonano nowego audytu stylistycznego.

## 4. Existing font architecture

Rozszerzono istniejące `load_font()` i jego cache w `src/indicators/helpers.py`. Globalny font przekazywany przez dotychczasowy render pozostaje fallbackiem.

## 5. Canonical font property

Jedyną właściwością jest `font`; brak lub `null` oznacza obecny default TeleM.

## 6. GUI

Istniejący `PropertyEditor` dostał pole `Font` z pustą wartością prezentowaną jako `Domyślny` oraz picker `Wybierz plik…` dla `*.ttf *.otf`. Nie przebudowano edytora.

## 7. Per-widget override

Compositor rozwiązuje font osobno dla każdego widgetu i przekazuje go do istniejącego renderera. Stare layouty bez pola `font` zachowują dotychczasowe zachowanie.

## 8. Supported formats

Akceptowane są `.ttf` i `.otf`; Pillow/FreeType otwiera plik, a nieobsługiwany lub uszkodzony plik przechodzi do fallbacku.

## 9. Absolute/relative paths

Ścieżki absolutne Windows są obsługiwane. Ścieżki względne są rozwiązywane względem katalogu projektu TeleM.

## 10. Cache

Wykorzystano istniejący jeden `FONT_CACHE`, z kluczem `(resolved_path, size)`. Dodatkowo wynik rozwiązywania ścieżki jest cache’owany, więc brak pliku nie powoduje odczytu przy każdej klatce.

## 11. Invalid/missing fallback

Brak, `null`, nieistniejący plik, zły suffix lub błąd otwarcia oznacza dotychczasowy globalny font, bez crasha i bez per-frame warning spam.

## 12. Bbox/font metrics

Renderery nadal mierzą tekst przez obiekt fontu przekazany do danego renderera (`getlength`, bbox i layout tekstu), więc wymiary wynikają z faktycznie wybranego fontu.

## 13. Widget coverage

Override obejmuje plain text, `time_display`, gauge, Compass, bar/ruler, Slope, chart i `segment_bar`; w `time_display` wspólny font zachowuje osobne rozmiary daty, czasu, activity i średniej.

## 14. Roundtrip

JSON roundtrip pola `font` oraz Qt PropertyEditor roundtrip zostały sprawdzone. Edytor poprawnie odczytał `C:\Windows\Fonts\cour.ttf`.

## 15. Manual smoke na GX010115

Wybrany timestamp: `300 s` (`05:00`), reprezentatywna klatka z dużymi jasnymi i ciemnymi obszarami. Tymczasowy layout v7 był użyty tylko w pamięci; ustawiono lokalny `C:\Windows\Fonts\cour.ttf` dla Time, Speed Gauge, Compass, Slope oraz HR/Cadence. Różnica renderu względem Arial była potwierdzona pikselowo, a tymczasowy layout został usunięty.

## 16. Targetowane testy

Uruchomiono `tests/test_font_selection.py` oraz `test_compass_rendering.py`, `test_slope_rendering.py`, `test_gauge_rendering.py`, `test_chart_rendering.py`: **51 passed**. Pełnego suite 600+ nie uruchamiano.

## 17. Performance/cache sanity

Kontrola renderu sześciu rodzin wykazała różnicę pikselową przy zmianie fontu oraz cache fontów bez odczytu pliku na klatkę. Nie dodano transferów GPU↔CPU.

## 18. AMD/NVIDIA impact

Nie zmieniono backendów, encoderów ani pipeline’ów AMD/NVIDIA. NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.

## 19. Zmienione pliki

- `src/indicators/helpers.py` — rozwiązywanie per-widget fontu i reuse cache.
- `src/indicators/compositor.py` — propagacja efektywnego fontu do istniejących rendererów.
- `src/gui/qt/models.py` — canonical field `font` w schematach.
- `src/gui/qt/widgets/property_editor.py` — picker TTF/OTF.
- `tests/test_font_selection.py` — testy infrastruktury, fallbacku, cache, schematów i roundtrip.
- `Raporty/RAPORT_INDICATORS_ETAP_9D_FONT_SELECTION.md` — niniejszy raport.

Nie zmieniano presetów v1–v7 ani referencji w `wzor/`. Nie wybierano docelowego fontu TO.

## 20. Remaining risks

Nie wykonano runtime testu NVIDIA ani pełnego eksportu sprzętowego. OTF zależy od obsługi konkretnego pliku przez zainstalowany Pillow/FreeType. Pozostałe ryzyko dotyczy wyłącznie różnic metryk fontów w ekstremalnie ciasnych konfiguracjach layoutu; ścieżka fallbacku pozostaje bezpieczna.

### AGENTS.md — raport końcowy

**Changed:** lokalny wybór fontu per widget, GUI picker, propagacja i testy.

**Preserved:** CPU reference, AMD/NVIDIA backend selection, encoder paths, telemetry resolver/sync, geometria wskaźników i presetów v1–v7.

**Tested:** 51 targetowanych testów, compile check, Qt offscreen editor check, font-change render smoke, nowy MP4+FIT SmartSync.

**Not tested:** NVIDIA runtime oraz pełny suite.

**Risks:** brak runtime walidacji NVIDIA; konkretne OTF-y zależą od Pillow/FreeType.
