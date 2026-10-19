# Ustawienia — proporcje paneli

2026-10-18. Status: PASS.

Repozytorium: `C:\_DEV\SportCamHUD`, gałąź main, HEAD e21d625. Zmieniono wyłącznie proporcje splittera w `src/gui/qt/tabs/settings_tab.py`: ustawienia po lewej 2/3, licencje po prawej 1/3. Stretch factors 2:1, rozmiary początkowe 1000:500. Zachowano wcześniejsze niezacommitowane poprawki GUI i pozostałe zmiany użytkownika.

Sprawdzono rzeczywisty widget SettingsTab w Qt offscreen: dla szerokości 1500 px panele mają 997/499 px (66,64% po lewej), dla 1920 px 1277/639 px (66,65%). Asercje proporcji przeszły. Zrzut: `gui_main_transfer_20261018/settings_2to1.png`.

Bez zmian rendererów, kodeków, audio, HUD i synchronizacji DJI. Nie wykonywano benchmarku ani ponownej pełnej serii testów dla tej zmiany dwóch wartości. Otwarty wcześniej proces aplikacji wymaga ponownego uruchomienia, aby zbudować nowy układ.
