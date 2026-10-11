# Raport Etap 2 — domyślny katalog eksportu

## Zadanie i stan początkowy

Przywrócono globalne ustawienie domyślnego katalogu eksportu dla SportCamHUD.

- Repozytorium: `C:\_DEV\BikeRideHUD-main-new`
- Gałąź: `fix/gui-freeze-hud-composite`
- HEAD przed zmianami: `150dff536add20d5db6478dd3300185f8c5f2c6b`
- Przed zmianami katalog roboczy zawierał zmodyfikowany `def_layout.json` oraz nieśledzony raport audytu. Oba pliki zachowano i nie dodano ich do commita.
- Backup `C:\_DEV\_SportCamHUD_BACKUP_20261011_175842` nie był modyfikowany.

## Przyczyna braku funkcji

W `SettingsTab` nie było pola domyślnego katalogu ani trwałego zapisu tej preferencji. Wspólny kod renderowania rozwiązywał względną ścieżkę wyłącznie względem katalogu jednego `video_path`; dodawanie zadania do kolejki przechowywało względną nazwę. Brakowało zatem wspólnej reguły dla wielu klipów, direct exportu i kolejki.

Dotychczasowe oczekiwanie testu, by zapisywać `default_export_dir` w `def_layout.json`, było sprzeczne z wymaganiem ustawienia globalnego. Testy zmieniono tak, by sprawdzały profil użytkownika i dodatkowo hash pliku layoutu przed i po zapisie.

## GUI i trwałość

W **Opcje → Ogólne** dodano edytowalne pole „Domyślny folder eksportu”, przyciski „Wybierz” i „Wyczyść” oraz zapis ustawienia. Dialog wyboru katalogu jest standardowym dialogiem Qt/Windows. Wyczyść natychmiast zapisuje tryb automatyczny; placeholder pokazuje „Domyślnie: katalog filmu źródłowego.”

W repozytorium nie było ogólnego magazynu preferencji użytkownika. Ustawienie jest zapisywane atomowo w istniejącym profilu aplikacji: `%APPDATA%\SportCamHUD\app_preferences.json`. Nie jest zapisywane do layoutu. Jeśli brak wartości w profilu, aplikacja odczytuje starsze `default_export_dir` z layoutu (wartość główna albo `global`) bez jego modyfikacji. Zapisana pusta wartość wyłącza zgodność wsteczną i oznacza tryb automatyczny.

## Reguły lokalizacji i kolejka

1. Jawna, absolutna ścieżka podana dla konkretnego eksportu ma pierwszeństwo i nie zmienia preferencji globalnej.
2. Dla względnej nazwy używany jest globalny katalog eksportu.
3. Gdy preferencja jest pusta albo niedostępna, używany jest katalog pierwszego źródłowego MP4. Bez bezpiecznego katalogu źródłowego eksport jest zatrzymywany; CWD nie jest fallbackiem.

W lokalnych katalogach walidacja sprawdza istniejący folder i możliwość utworzenia oraz usunięcia pliku próbnego. Nie tworzy katalogu eksportu. Niedostępna lokalna konfiguracja wyświetla ostrzeżenie i przechodzi do folderu źródłowego. Zapis preferencji nie wykonuje walidacji sieciowej przy otwieraniu Opcji.

Ścieżki UNC, dyski sieciowe i wymienne są rozpoznawane bez próbnego dostępu w GUI. Walidacja odbywa się w wątku renderowania. Jeśli zapisany cel sieciowy/wymienny przestał być dostępny, kolejka używa zamrożonego fallbacku w katalogu źródłowym i wysyła ostrzeżenie do GUI. Kolejka zamraża ścieżkę absolutną przy dodaniu zadania; późniejsza zmiana preferencji nie przenosi zadania. Kolizje lokalne nadal otrzymują sufiksy `_001`, `_002` itd.; kolizja odkryta dopiero przy renderze jest rozwiązywana przez ten sam mechanizm. Zadanie ze starą, nierozstrzygniętą ścieżką albo nieistniejącym katalogiem jest odrzucane bez tworzenia katalogu.

Przy bezpośrednim eksporcie istniejący plik lokalny wymaga potwierdzenia nadpisania. Dla celu sieciowego/wymiennego, gdzie sprawdzenie pliku mogłoby zablokować GUI, użytkownik potwierdza zapis przed uruchomieniem; jeśli zadanie kolejki napotka istniejący plik, wybierana jest następna bezkolizyjna nazwa.

## Zmienione pliki

- `src/export_paths.py` — profil preferencji, zgodność z layoutem i wspólny resolver.
- `src/gui/qt/tabs/settings_tab.py` — kontrolki Opcji i zapis globalnej preferencji.
- `src/gui/qt/tabs/render_tab.py` — wybór ścieżki, eksport bezpośredni i zamrożenie ścieżki kolejki.
- `src/gui/qt/_mixins/render_mixin.py` — wspólne rozstrzygnięcie w wykonaniu renderu oraz fallback kolejki.
- `src/gui/export_queue.py` — walidacja ścieżek, odroczenie sprawdzania urządzeń sieciowych/wymiennych i aktualizacja kolizyjnej ścieżki.
- `src/gui/qt/signals.py` — ostrzeżenie z wątku renderu przekazywane do GUI.
- `tests/test_default_export_dir_settings.py` — izolacja profilu, testy persystencji, ścieżek, kolejki i ochrony layoutu.

## Testy i ograniczenia

Historyczny wynik z raportu audytu przed naprawą: `7 FAILED, 1 PASSED, 1 DESELECTED`. Testu bazowego nie uruchamiano ponownie przed zmianami, ponieważ jego poprzedni kontrakt zapisywał do produkcyjnego `def_layout.json`.

Po zmianach, w `APPDATA`/`LOCALAPPDATA` odizolowanym przez fixture:

- `tests/test_default_export_dir_settings.py`: **13 passed**.
- `tests/test_export_queue_basic.py` + `tests/test_export_queue_lifecycle.py`: **32 passed** in the isolated profile.
- `compileall` dla zmienionych modułów: **PASS**.
- `ruff check src/export_paths.py`: **PASS**.
- `ruff check` dla całego zestawu zmodyfikowanych modułów: **FAIL** — wykrył 90 uwag w dużych, istniejących plikach (m.in. kolejność importów, długość linii i wcześniejsze duplikaty metod). Nie uruchamiano masowego autofixu poza zakresem zadania.
- `git diff --check`: **PASS** przed commitem.
- Dodatkowy `tests/test_gui_logic_degree_export_settings_cleanup.py` nie zebrał testów: importuje nieistniejący `get_arial_fallback_font` z `src.indicators.helpers`. To niezależny błąd kolekcji; modułu poza zakresem nie zmieniano.

Testy obejmują UI pola, wybór ścieżki z polskimi znakami, czyszczenie, odczyt po ponownym utworzeniu ustawień, ręczną ścieżkę, fallback do pierwszego z wielu klipów, brak CWD, niedostępny i niezapisywalny katalog, odroczenie UNC, zamrożenie ścieżki kolejki oraz brak tworzenia brakującego katalogu. Nie uruchamiano renderu wideo na fizycznym dysku zewnętrznym/UNC ani eksportu kodekiem; parity gotowego pliku i zachowanie rzeczywistego urządzenia sieciowego są **NOT TESTED**. Połączone uruchomienie starego pliku regresji GUI jest **BLOCKED** przez wspomniany brak symbolu podczas kolekcji. Benchmarków nie wykonywano.

`def_layout.json` zachował stan użytkownika: nie zapisywano do niego ani z testów, ani z nowej funkcji. Hash w teście persystencji pozostaje taki sam przed i po teście. Zmiany AMD/Intel/NVIDIA, audio, HUD, AutoFIT, DJI, SmartSync, cieni, kompasu i rendererów nie były celem tej pracy.

## Git i commit

Commit implementacji Etapu 2:

`4b52155c6c4066cc2b663edf8946f47b28090695` — `Restore global default export directory`

Do commita weszło wyłącznie siedem plików wymienionych w sekcji „Zmienione pliki”. `def_layout.json` i wcześniejszy nieśledzony raport audytu pozostały poza stagingiem. Push nie wykonano.

## Podsumowanie

**PASS** — ustawienie globalne, picker/clear, trwały zapis, resolver direct/queue, fallback źródłowy, snapshot kolejki oraz izolacja danych użytkownika mają pokrycie testami jednostkowymi. **NOT TESTED** — rzeczywisty eksport kodekiem i urządzenia sieciowe/wymienne. Etap 3 nie był rozpoczynany.
