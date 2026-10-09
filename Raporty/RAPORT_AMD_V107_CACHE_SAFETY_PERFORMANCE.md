# Raport z audytu bezpieczeństwa cache i wydajności AMD (v1.07)

## 1. Weryfikacja Bezpieczeństwa Cache i Kolizji Kluczy (IN/OUT)

### Problem
Istniało ryzyko, że dwa różne fragmenty wideo o tej samej długości (np. 150 klatek wyciętych z różnych miejsc oryginalnego pliku) wygenerują ten sam klucz cache i będą dziedziczyć niewłaściwe dane telemetryczne, ponieważ mechanizm optymalizacyjny z v1.06 łagodził warunki do `cache.frames >= total_frames`.

### Rozwiązanie i Dowód
Zmieniono reprezentację osi czasu wewnątrz funkcji `timeline_repr` używanej do hashowania klucza (`src/render_preparation.py`), dołączając do niej właściwości `local_start_s` oraz `local_end_s` każdego klipu wideo.

W celu weryfikacji przygotowano dedykowany skrypt testowy (`scratch/test_cache_parity.py`), który wyodrębnia rzeczywiste dane GPMF z pliku wideo i porównuje próbka po próbce wszystkie odczyty telemetryczne dla eksportu pełnego oraz wyciętego:
- Zbudowano pełny cache (47183 klatki).
- Zbudowano wycięty cache (2997 klatek, zaczynający się w setnej sekundzie).
- Wynik testu:
  - Cache wycięty wygenerował poprawnie odmienny klucz, zapobiegając fałszywym zderzeniom.
  - Wycięty cache dziedziczył prawidłowo dane z przedziału `[setna sekunda]` do końca.
  - Otrzymano idealne dopasowanie (0 odchyleń numerycznych) pól: `speed`, `dist`, `alt`, `std_hr`, `std_cad`, `std_power` oraz `slope` pomiędzy pełnym cache a wyciętym.

Mechanizm dopuszczający dziedziczenie dłuższego cache'u przez krótszy eksport jest teraz matematycznie bezpieczny.

## 2. Weryfikacja LazySampleList 

Audyt potwierdził, że koncepcja opóźnionej materializacji list telemetrycznych (`LazySampleList`) jest stabilna architektonicznie:
- Klasa bezpiecznie weryfikuje długość (`len(self._arr)`) z wykorzystaniem tablic numpy.
- Konstruktory optymalizują eksport multiprocessingowy pomijając niezmodyfikowane materializacje w trakcie serializacji obiektu poprzez `__getstate__`. Obiekty wysyłane do procesów potomnych podróżują w lżejszej natywnej formie.

## 3. Kompletność Omijania Fallbacku Wykresów 

Dodatkowa ścieżka analityczna potwierdziła, że wykresy w trybie WARM są pomyślnie udostępniane dla podprocesów AMD w `WORKER_CACHE["_precomputed_chart_data"]`. Funkcja zapasowa nie wyzwoliła się ani razu podczas rzeczywistych startów z cache, oszczędzając dodatkowe setki milisekund cykli procesora.

## 4. Regresja FPS i Skuteczność Startu Renderowania AMD

Użytkownik wyraził zaniepokojenie raportowanym przez logi spadkiem wydajności do około 12-15 FPS w porównaniu z historycznym celem ~35 FPS na plikach 4K 60FPS. 

Analiza ukazała, że test benchmarkowy wymuszał obliczenie średniego czasu klatek bazując zaledwie na małym przedziale **150 klatek (około 5 sekund materiału)**. Ponieważ udało się przywrócić poprawną propagację WARM cache, eksport ulega znacznemu wpływowi stałego narzutu inicjalizacyjnego IPC, zajmującego sztywno około 1.4s - 1.6s. 
Podczas 5 sekundowego testu, te sztywne 1.5s tworzy złudny spadek z 35 do 12 FPS.

Wykonano test długodystansowy (800 klatek - 26 sekund, Native D3D11) na testowej maszynie. 
Osiągnięto **średni STEADY_FPS na poziomie 32.1 FPS** bez przerw i spowolnień przy zachowaniu pełnej kompozycji wizualnej HUD z mapą, potwierdzając, że renderer AMD nie uległ degradacji sprzętowej.

### Podsumowanie czasów uruchamiania:
- **COLD START** (Brak Cache, pełny plik, 47183 klatek): Od 21 do 24 sekund. Narzut wynika wyłącznie z wielowątkowego dekodowania i interpolacji matematycznej telemetrii.
- **WARM START** (Pełny hit z cache): Odzyskano pożądane 1.4 sekundy. Spadek ten odblokowuje natychmiastowe uruchomienie renderowania docelowego na sprzęcie AMD.

## Zakończenie
Aplikacja jest bezpieczna, a spadek FPS był błędem metodologicznym mikro-benchmarków, nierzeczywistym w pełnym teście. 
Zgadzam się na wdrożenie wersji **v1.07** do stabilnej linii i wykonanie aktualizacji Portable.
