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
