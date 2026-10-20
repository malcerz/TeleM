# Storage i poprawność temperatury — 2026-10-20

## Stan wejściowy i ograniczenia
main, HEAD 189ec8113aebd8924313519f15a9492f39afb7bf. Prywatny def_layout.json oraz wszystkie wcześniejsze pliki nieśledzone zachowane. Bez push, gałęzi, worktree, przebudowy DLL i zmian manifestów.
AMD SHA256 przed zmianami: BBCA75FBD0DFC5D7CBB61922E92F8D5F049B4305DD18335315667E6E5E54CA5F.

## Etap A — Storage
Reprodukcja aktualnego bloku preflight, z dwoma klipami po 2047.4454 s: kontrola otrzymała tylko 2047.4454 zamiast 4094.8908 s. Probe był ograniczony do pierwszego strumienia wideo; brak informacji o kopiowanym audio. Wyjątki probe/parsing były ignorowane. Monitor nie otrzymywał obliczonej rezerwy; awaria zapytania nie uruchamiała callbacku zatrzymującego klatki.

Zmiany: render_errors.preflight_export_storage i probe_export_storage_media sprawdzają wszystkie klipy i ich audio, używają VideoTimeline.output_frame_count / target_fps oraz subset_excluding. Bezpośredni eksport i kolejka wywołują to samo miejsce w RenderMixin._render_pipeline przed przygotowaniem HUD, GPMF i cache. Niepowodzenia oszacowania i odczytu dysku blokują eksport przez StorageError. Kontrola dotyczy katalogu rzeczywistego wyniku, w tym UNC.

Budżet: konserwatywnie peak 1.5 × target (dla incydentu 60/90 Mb/s), rzeczywisty bitrate audio (384 kb/s fallback dla nieznanego strumienia), 30% margines, rezerwa max(512 MiB, 5% pliku). Monitor co 1.5 s otrzymuje tę rezerwę. W komunikacie są rozmiar, wymagane, dostępne i brakujące GB.

Aktualny kod nie ma funkcji przyspieszania eksportowanego wideo. update_rate_step zmienia częstość HUD, a charts_skip_pauses dotyczy wykresów; nie zmniejszają długości filmu. Nie wprowadzano nowej funkcji zmiany prędkości. Zakresy źródłowe i cuts korzystają z istniejącego planu CFR, nie z sumy rozmiarów źródłowych MP4.

Runtime: osobne powody STORAGE_LOW_SPACE / STORAGE_UNAVAILABLE, zachowane także w stanie failed. W AMD sygnał storage zatrzymuje pętlę nowych klatek i prowadzi do istniejącego flush/drain/live mux, zamiast ścieżki user cancel usuwającej plik. Nie dodano remuksowania ani nowego sposobu finalizacji. Walidacja błędu obejmuje też docelowy MP4, nie tylko .part. Plik częściowy nie jest kasowany ani uznawany za pełny sukces; queue blocker wstrzymuje kolejkę.

Testy: 14 nowych testów storage PASS (1/2/3 klipy, cuts, fail closed, query failure, rzeczywista ścieżka GUI direct/queue). Incydent 4094.8908 s na siatce 30 FPS daje 4094.866667 s; 24 GiB wystarczy na pojedynczy klip, lecz nie na cały wynik i eksport zostaje zablokowany przed inicjalizacją renderera. Dodatkowy zestaw storage/error/AMD live mux/Intel live mux/queue/ranges: 49 PASS przed dodaniem dwóch testów integracyjnych GUI. Sprzętowe przerwanie AMD i zachowanie pliku przy realnym ENOSPC: NOT TESTED na komputerze Intel; nie zapełniano dysku użytkownika.

## Etap B — Temperature
W toku. Reprodukcja przed poprawką: główny resolver na plateau w t=30 zwraca 19.0; pomocniczy interpolator dla surowych 19.6/19.7 zwraca 19.5. Raport poprzedniego etapu testował pomocniczy interpolator, co nie dowodziło kontraktu głównego resolvera.
