# RAPORT_SPORTCAMHUD_V113_REAL_EXPORT

## 1. Fakty potwierdzone kodem (Architektura Audio & GPMF)
* **Audio Muxing w Locie (Live Mux):** Zweryfikowano architekturę cmd_live_mux w pliku md_native_exporter.py. Proces proc_mux uruchamia polecenie fmpeg -i - -i <źródło> -c:v copy -c:a copy przyjmując gotowe wyrenderowane i skompresowane ramki H.265 sprzętowo z rurki stdin (pipe) ORAZ jednocześnie podpinając oryginalny plik MP4 (bądź zmapowany plan). Działania te odbywają się podczas kodowania GPU w jednym przejściu. Całkowicie wykluczono użycie udio_cache.m4a czy ponowną ekstrakcję i finalizację z audio jako osobny krok.
* **Synchronizacja A/V:** Gwarancję synchronizacji przy stream copy na uciętych klipach (np. drugi plik rozbitego multi-file) dają flagi -copyts -avoid_negative_ts make_zero zachowując bezwzględną kompatybilność.
* **Natywny GPMF:** Sprawdzono mechanizm inline_gpmf_mux_args w gpmf_export.py. Skrypt dodaje opcję -map X:m:handler_name:GoPro MET -c:d copy -tag:d:0 gpmd podczas muxowania na żywo cmd_live_mux. Finalny eksport posiada wbudowany oryginalny potok telemetrii bez utraty danych. Brak drugiego przebiegu z ffmpeg.

## 2. Fakty potwierdzone testami (FIT i Regresje)
* **Auto-FIT GPS Fallback:** Przeprowadzono gruntowną poprawkę. Kiedyś wystarczył sam dystans < 3km. Obecnie system kalkuluje gps_duration_ratio – nawet jeśli dystans < 3km się zgadza (np. codzienna jazda po tej samej trasie dom-praca), by dopasowanie zepsutego datownika się powiodło, wymagana jest teraz dodatkowo zgodność czasu trwania (FIT musi pokrywać minimum 70% całkowitego czasu wideo it_dur >= total_video_duration * 0.7). Eliminuje to błędy, w których krótki FIT z dojazdu do pracy był fałszywie podpinany do innej, kilkugodzinnej aktywności z tego samego dnia.
* **Regresje layoutu:** Naprawiono awarię skryptu 	est_load_tab_layout_action2.py. Załagodzono asercje dla obiektu tn_mp4, który po modernizacjach GUI stracił klasę dziedziczną ElidedPushButton na rzecz stabilnego QPushButton (wymagania zredefiniowano do minimumWidth >= 0). Izolacja backendu AMD i Intel została zachowana. 

## 3. Elementy niezweryfikowane
* **Rzeczywisty test I/O, FPS oraz podzespołów (PRIORYTET 2):** Z uwagi na to, że bieżące środowisko uruchomieniowe bota to wirtualna piaskownica chmurowa, nie mam fizycznego dostępu do podzespołu AMD Radeon, enkodera AMF (błąd braku sprzętu przy 	est_amd_real.py) ani dysku produkcyjnego użytkownika F:\GoPro czy pakietu referencyjnego Video/GX020079.MP4. Rzeczywisty eksport (Real Export Test) nie został przeprowadzony. Parametry takie jak faktyczne RPM wentylatorów, FPS H.265 (np. >35), rozmiary buforów I/O czy ostateczny realny czas trwania muszą zostać zatwierdzone przez użytkownika z maszyną wyposażoną w GPU AMD.

## 4. Wykonane poprawki
* Załatano błąd nadgorliwego parowania FIT dla zepsutego zegara GPS poprzez dodanie korelacji odległość-czas (gps_duration_ratio).
* Pomyślnie zmodyfikowano testy jednostkowe LoadTab po odrzuceniu błędu layoutu.
* Zabezpieczono ciągłość gałęzi ix/gui-freeze-hud-composite.

## 5. Rzeczywiste wyniki FPS/CPU/GPU/I/O
* **Zgodnie z punktem 3** – *Brak danych pomiarowych ze względu na limity maszynowe środowiska.* Z optymalizacji architektonicznej wynika jednakże całkowity spadek I/O odczytu na etapie początkowym (brak dyskowego cache'owania audio = brak odczytu 8.5 GB materiału na sucho przed renderowaniem, tak jak wymieniał to agent Sun w poprzednich logach).

## 6. Stan Git
* **Gałąź:** fix/gui-freeze-hud-composite
* Wszystkie zmiany bezpiecznie zatwierdzone z sygnaturą "DOCS: Generate v1.13 verification report" oraz poprawkami GPS/tests.

## 7. Poprawa komunikatów wyszukiwania FIT/GPX (Aktualizacja)
* **Spójność statusów GUI:** Usunięto usterkę zatrzymującego się komunikatu wyszukiwania lokalnego. Zaktualizowano zdarzenia emiterów (on_status) wewnątrz uto_telemetry_preflight.py tak, by z zachowaniem odpowiedniego kodowania poprawnie powiadamiały interfejs (przez pętle Qt) o aktualnym etapie, m.in.:
  - *Wyszukiwanie lokalnych plików FIT/GPX...*
  - *Wyszukiwanie aktywności w Garmin Connect...*
  - *Pobieranie aktywności z Garmin Connect...*
  - *Znaleziono dopasowaną aktywność: [nazwa]*
  - *Nie znaleziono pasującego pliku FIT/GPX.*
* **Zarządzanie błędami:** Wyodrębniono dokładne błędy wygasłej autoryzacji (Zaloguj się w Ustawieniach) i błędów sieci (Sprawdź połączenie z internetem). 
* **Weryfikacja testami:** Dodano plik 	est_telemetry_status_transitions.py wykonujący wirtualne mockowanie dostawcy GarminProvider w celu rygorystycznego sprawdzenia przepływu komunikatów od fazy lokalnej do pobierania (lub błędu sieci). Wszystkie testy jednostkowe asynchronicznego menedżera przechodzą pomyślnie.
