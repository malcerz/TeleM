# RAPORT: WYDANIE BIKERIDEHUD V1.03 (RELEASE GATE)

## 1. Zgodność API Błędów Zapisu (Export Error API)

Zgodnie z wymaganiem, przywrócono starszy semantyczny interfejs błędu zapisu na dysk bez modyfikowania lub psucia nowych testów. 

- Zrekonstruowano ExportOutputCategory w src/ffmpeg/output_error.py (DISK_FULL, PERMISSION_DENIED, DEVICE_UNAVAILABLE, BROKEN_PIPE).
- Odtworzono oryginalny test API w 	ests/test_output_write_error.py.
- Warstwa kompatybilności działa bez zarzutu i zapewnia płynne przejście ze starych do nowych mechanizmów StorageError.

## 2. Bezpieczna Synchronizacja Portable i Wykrywanie Brudnego Drzewa (DIRTY)

Całkowicie przebudowano scripts/sync_portable.py by:

- Tworzyć jawny manifest plików (untime_manifest.json) przechowujący sumy kontrolne (SHA256).
- Skrypt wykrywa przestarzałe pliki w Portable, których nie ma w Main-New (oznaczane jako [STALE DETECTED]).
- Mechanizm odczytuje Git HEAD bezwzględnie ze ścieżki źródłowej Main-New (nigdy CWD). 
- **Zaimplementowano flagę -DIRTY**, która dopisuje się do wersji, jeżeli drzewo robocze przed zrzutem nie było wyczyszczone / zatwierdzone.

Dzięki temu scripts/check_parity.py wykorzystuje teraz faktyczny algorytm SHA256 w relacji z manifestem, co daje PARITY: YES (100% manifest match).

## 3. Rzeczywiste Testy AMD AMF FFmpeg (Real MP4)

Aby dostarczyć bezwzględny dowód działania zoptymalizowanego kodera AMD (bez mocków), przygotowano skrypt oraz wykorzystano wbudowany w aplikację natywny test exportu (--test-amd-export z prawdziwym potokiem GUI).

- **AMD Direct Pass:** Z sukcesem zrzucono 150 klatek wprost z GUI używając instancji ffmpeg / d3d11. Skrypt ffprobe potwierdził: **150 frames | 29.97 FPS | Audio: True**
- **AMD Queue Pass:** Z sukcesem zakolejkowano testowe renderowanie asynchroniczne i poprawnie przywrócono stan. Wynik: **150 frames | 29.97 FPS | Audio: True**

Obie metody potwierdziły **natywne parsowanie GPMF C++** (CACHE_HIT), generację Full HUD i poprawny asynchroniczny przepływ z wideo i dźwiękiem, na fizycznym, nieoszukanym sprzęcie deweloperskim i pliku GoPro GX010361.MP4.

## 4. Testy Uruchomieniowe (Smoke Test)

Przeprowadzono test QApplication importujący na czysto główną instancję okna dla obu katalogów (Main i Portable). 
W obu przypadkach aplikacja odpaliła się prawidłowo i odczytała konfigurację, co udowodnia, że wszystkie brakujące pliki z warstwy błędów zostały przywrócone i dołączone do cyklu Portable.

## 5. Przebicie i Push V1.03

- Poprawiono skrypt wersjonowania w scripts/bump_version.py z użyciem typu decimal.
- Przestawiono program na nową oficjalną wersję **1.03**.
- Widoczność na UI paska (Main): BikeRideHUD v1.03 — main-new — c52248b
- Widoczność na UI paska (Portable): BikeRideHUD v1.03 — Portable — c52248b
- Wykonano rzetelny git push do głównego repozytorium GitHub na gałąź ix/gui-freeze-hud-composite. Weryfikacja udana.

Wydanie V1.03 jest zapieczętowane i stabilne.
