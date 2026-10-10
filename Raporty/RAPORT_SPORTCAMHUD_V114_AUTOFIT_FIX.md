# Raport: Naprawa automatycznego dopasowania FIT/GPX (v1.14)

## 1. Faktyczna przyczyna awarii
Brak automatycznego dopasowania wynikał z trzech czynników:
1. **Ograniczony zakres skanowania lokalnego:** Algorytm w uto_telemetry_preflight.py w sposób nieelastyczny skanował wyłącznie bezpośredni katalog zawierający MP4 (pomijając skonfigurowane w UI foldery oraz dyski zewnętrzne urządzeń Garmin).
2. **Krótkie i sztywne okno czasowe pobierania online:** Pobieranie aktywności przez dostawcę Garmin Connect odbywało się wyłącznie z ograniczeniem ±2h względem zapisanego w MP4 czasu początkowego. Przy resecie zegara kamery GoPro (np. na datę domyślną pokroju 2016-01-01) odszukanie rzeczywistej aktywności przez API Garmina w tym oknie czasowym z założenia musiało kończyć się fiaskiem (puste odpowiedzi).
3. **Błędna ewaluacja w NO_MATCH:** Pobierano topowego (a obiektywnie nietrafionego) kandydata niezależnie od faktu odrzucenia go przez mechanizm scoringu odległości.

## 2. Przeszukiwane lokalizacje
Wprowadzono rozszerzone skanowanie lokalne przed wykonaniem jakichkolwiek zapytań online:
- Folder bezpośrednio zawierający nagrania MP4 (parent_dir).
- Katalog zdefiniowany na stałe w ustawieniach aplikacji w zakładce Ustawienia (parametr 	elemetry_dir).
- Katalogi wykrytych dynamicznie nośników (np. podłączone przez USB zegarki lub urządzenia Edge), skanujące ścieżki /Garmin/Activities lub /Garmin/Activity.
Użyto dedykowanej weryfikacji przez system plików bez długotrwałego i niekontrolowanego przeszukiwania rekurencyjnego innych partycji, tak jak było to wymagane.

## 3. Komunikacja z Garmin Connect
Jeżeli nie znaleziono dopasowania lokalnie, zapytanie do serwerów następuje natychmiast, lecz z lepszą logiką i weryfikacją:
- Rzeczywista weryfikacja uwierzytelnienia.
- Najpierw badane jest wąskie okno czasowe nagrania (±2h). 
- W przypadku awarii i wykazania braku wyników, przy jednoczesnej dostępności sygnału GPS (GPMF) na początku nagrania, uruchamiane jest kontrolowane zapytanie *awaryjne*. Sprawdza ono listę aktywności z **ostatnich 45 dni**, rozwiązując problem kamer ze zresetowanym, starym zegarem, minimalizując przy tym narzut sieciowy paginacji na API Garmina. 

## 4. Wyszukiwanie i ewaluacja aktywności
* Zmodyfikowano plik ctivity_matcher.py, w którym algorytm score_candidate akceptuje teraz flagę ignore_time_match. W sytuacji wyszukiwania awaryjnego (czas uległ desynchronizacji), ranking polega **wyłącznie** na dopasowaniu długości trwania oraz pierwszej próbce współrzędnych GPS (odległość geograficzna), wykluczając czas od zapisu w karze.
* Dokładnie obsługiwany jest status decision: 
  - Jeśli jest to AUTO_ACCEPT, FIT jest automatycznie pobierany z Garmin Connect.
  - Jeśli NEEDS_SELECTION, proces informuje, że "Znaleziono kilka aktywności (dopasowanie niejednoznaczne). Wybierz ręcznie." (przerywa przypisywanie ślepego trafu).
  - Jeśli NO_MATCH, w logu UI pojawia się informacja "Znaleziono aktywności, ale żadna nie pasuje do nagrania".

## 5. Konfiguracja Dynamiczna
W pliku load_tab.py usunięto usterkę blokującą zastosowanie nowej wartości źródła w ustawieniach (z Garmin na Strava lub None) przed zamknięciem aplikacji. Menedżer przechowuje self._dynamic_integrations_config powiązany z Event Bus'em. 

## 6. Zmiany w kodzie
- Zmodyfikowano logikę dopasowania plików dyskowych (urządzenia Garmin, katalog z UI).
- Usprawniono okna wyszukiwania Garmin Connect (±2h vs -45 dni).
- Poszerzono parametry funkcji oceniających w ctivity_matcher.py.
- Wprowadzono precyzyjne odzwierciedlanie operacji backendu w logach aplikacji frontendowej Qt. 
- Zmiany objęły pliki: src/integrations/auto_telemetry_preflight.py, src/integrations/activity_matcher.py oraz src/gui/qt/tabs/load_tab.py. 

## 7. Wyniki testów i stan gałęzi
* Przeprowadzono nowe testy jednostkowe asercji menedżera 	est_telemetry_status_transitions.py, udowadniające logiczną poprawność okna wyszukiwania i odnajdowania telemetrii w chmurze przy fałszywym czasie wideo bez uszkodzenia interfejsu.
* Dodatkowo symulowano błędy po utracie pakietów bez zamrożenia (Freeze) okna programu (zastosowano wątki poboczne). 
* Zmiany zacommitowano na branchu ix/gui-freeze-hud-composite (Zoptymalizowany pod kątem braku ingerencji w mechanizmy ekstrakcji Audio / demuxingu AMD/Intel). Niewielka ilość testów w starszych gałęziach środowiska wykazuje ImportError starych metod, co jest podyktowane historycznymi migracjami niezwiązanymi z powyższą naprawą.

## 8. Naprawa wyświetlania metadanych GPMF w UI (Kamera i Data nagrania)
W odpowiedzi na brak widocznych metadanych kamery w siatce parametrów technicznych wczytanego pliku:
1. **Edycja natywnego parsera C++ (.pyd):** Zmodyfikowano kod w pliku gpmf_extractor.cpp (pętla ładunków GPMF) oraz gpmf_bindings.cpp, dodając parametr metadata_only. Skompilowano pomyślnie natywny moduł C++ za pomocą MSVC, co rozwiązuje problem wydajności (natychmiastowe wyjście z pętli po pierwszych klatkach telemetrii zamiast skanowania całego pliku 8 GB).
2. **Ulepszenie konwersji daty:** W pliku mp4_inspector.py używamy parametru metadata_only=True podczas wywoływania natywnej biblioteki. Wyodrębniony znacznik czasu (start_dt_utc) reprezentujący autentyczny czas z satelit (GPS Lock) jest następnie konwertowany z UTC do natywnej strefy czasowej systemu Windows i formatowany jako YYYY-MM-DD HH:MM:SS. 
3. **Modyfikacja interfejsu (LoadTab):** Do widgetu VideoFileCardWidget dodano trzeci wiersz (Row 2) na siatce (QGridLayout). Zawiera on teraz lbl_record_date (Data nagrania) oraz lbl_camera (Kamera). Uzupełniono funkcję update_info, by bezpiecznie wiązała info["gpmf_meta"] z interfejsem graficznym.
* Zmiany pomyślnie przeszły testy layoutu (brak zniszczenia stylów / zakładek) oraz zapobiegły długim blokadom aplikacji przy wczytywaniu dużych nagrań wideo.

## 9. Rozwiązanie problemów GPMF i AutoFIT (Rzeczywiste Nagranie F:\GoPro\2026-10-09\GX010361.MP4)

### 9.1 GPMF - Data nagrania i Kamera
- **Diagnoza braku daty:** Zoptymalizowany pod kątem 8 GB plików tryb metadata_only przerywał pracę C++ zaraz po 20 ładunkach GPMF. Jednak punkt GPS9 pojawiał się dopiero po kilkuset pakietach w niektórych filmach (częsty przypadek dłuższego łapania fix'a przez kamerę lub buforowania MP4). Warunek reak w kodzie natywnym (gpmf_extractor.cpp) zatrzymywał skanowanie, zanim parser dotarł do jakiejkolwiek poprawnej próbki GPS. Zmodyfikowano warunek ucieczki, aby wymagał on obecności absolutnego czasu nagrania (irst_gps9_abs_ts > 0.0) lub w przypadku braku fix'a przerywał dopiero po przeskanowaniu znaczącej liczby pakietów awaryjnych. Skutkuje to prawidłowym ustaleniem wartości 2026-10-09 04:27:55 UTC.
- **Diagnoza braku modelu kamery:** Natywny parser odczytywał wartość GoPro wprost ze struktury MINF ładunku GPMF. Nowsze modele (od HERO9 w górę) niekiedy nadają taką ogólnikową nazwę do strumienia GPMF. 
- **Wdrożona naprawa:** Zmodyfikowano plik src/gui/qt/mp4_inspector.py. Jeżeli natywny camera_model wskazuje po prostu na "GoPro", wykonywany jest lekki odczyt flagi kontenera firmware (ormat_tags: firmware) za pomocą ffprobe. Skrypt mapuje wewnętrzne prefiksy (np. H26.xx...) na czytelną nazwę i zwraca GoPro HERO13 Black. Test na rzeczywistym MP4 potwierdza poprawne mapowanie.

### 9.2 AutoFIT - Niejednoznaczność i ręczny wybór
- **Diagnoza NEEDS_SELECTION:** Algorytm auto-dopasowania odrzucał decyzję NEEDS_SELECTION, interpretując ją w UI błędnie jako "Nie znaleziono pasującego pliku". Wynikało to z braku bramki pytającej interfejs Qt.
- **Wdrożona naprawa:** Uruchomiono mechanizm obsługi zwrotnej dla niejednoznacznych statusów. Wprowadzono callback on_needs_selection, który poprzez klasę QMetaObject asynchronicznie przerywa pobieranie z Garmin Connect na czas akcji i otwiera na wątku GUI blokujące, czytelne okno QInputDialog z wyświetlonymi dokładnymi logami w formacie Data | Sport | Czas Trwania | ID. Po wskazaniu prawidłowego profilu przez użytkownika auto-wczytywanie powraca do pracy, pobierając ten i tylko ten konkretny ślad telemetrii.
- W celach diagnostycznych, Auto-Telemetry-Preflight wypisuje teraz do standardowego strumienia tekstowego pełną punktację matching'u znalezionych kandydatów wraz z ich wynikami score.

### 9.3 Wersja aplikacji
- Wersja w pliku src/version.py została oficjalnie zaktualizowana do 1.14.
