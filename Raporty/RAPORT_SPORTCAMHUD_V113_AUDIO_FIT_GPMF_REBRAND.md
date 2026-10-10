# Raport: SportCamHUD v1.13 - AUDIO, FIT, GPMF, REBRANDING

## 1. Usunięcie pre-ekstrakcji audio
Zgodnie z HARD INVARIANT: usunięto całkowicie funkcje tworzące i odwołujące się do udio_cache.m4a z 	elemetry_cache_manager.py oraz md_native_exporter.py. Audio jest teraz przekazywane do enkodera GPU bezpośrednio z oryginalnego pliku MP4 z wykorzystaniem stream_copy AAC w locie (Live Mux). Usunięto przestarzałe testy z tym związane oraz dopisano sztywną regułę do AGENTS.md.

## 2. Przywrócenie Auto FIT i deduplikacja (Single Coordinator)
Naprawiono problem blokujących zapytań sieciowych w tle. Usunięto bliźniaczy ciąg wywołań w ProjectMixin i pozostawiono jednego, prawnego koordynatora wyszukiwania (asynchronicznego) zarządzanego przez LoadTab. Dodatkowo, aby walczyć ze zjawiskiem rozkalibrowanego zegara GoPro, preflight wypakowuje natywnym parserem C++ początkową współrzędną GPS z nagrania wideo. Jeżeli dopasowanie czasowe lokalnych FIT zawodzi, program fall-backuje na dopasowanie wg. odległości geograficznej (<3km = boost punktacji). Zaimplementowano late-attach: w przypadku ukończenia poszukiwań w tle, FIT dołącza do telemetrii w sposób bezinwazyjny bez konieczności restartu dekodera H.265.

## 3. Informacje o pliku (GPMF)
Do widoku "Informacje o filmie" wprowadzono szybkie, wstępne odpytywanie kontenera MP4 parserem C++ (w osobnym wątku roboczym). Okno informacyjne teraz obok klasycznych danych z FFprobe prezentuje precyzyjną Datę nagrania oraz Model kamery w oparciu o strumienie GoPro GPMF.

## 4. Kompletny rebranding do SportCamHUD
Rozpoczęto cykl ewolucyjny v1.13 pod nową marką SportCamHUD. Wszystkie pliki, klasy i szablony odwołujące się do dawnej nazwy BikeRideHUD zostały globalnie przemianowane. Podmieniono launcher główny (SportCamHUD.py). Co krytyczne, zaprogramowano blok migracyjny wstrzykiwany na starcie (tuż po importach w pliku uruchomieniowym). Przenosi on bezpiecznie i niewidzialnie dawny profil %LOCALAPPDATA%\BikeRideHUD pod nową nazwę chroniąc layout, układy okien, konfigurację licencji, bufor logowania i cache telemetrii. Zaktualizowano też klucze deponentów poświadczeń Windows Credential Manager z płynną migracją i nowym prefiksem sesji (szczególnie dla pociętej sesji DI Garmina). Synchronizacja z portable została zachowana.
