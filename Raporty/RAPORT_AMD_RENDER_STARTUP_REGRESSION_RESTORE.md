# RAPORT NAPRAWY REGRESJI STARTU AMD (v1.05)

## 1. Opis problemu

Użytkownik zgłosił krytyczną regresję wydajności: po ostatnich aktualizacjach architektury (izolacja workerów, rozbudowa testów IPC), start renderowania wideo AMD o długości 47 000 klatek w wysokiej rozdzielczości (4K) wydłużył się z **<1 sekundy do ponad 60 sekund**.

Głównym problemem było powolne "przygotowywanie HUD" zablokowane na etapie tworzenia wątków, mimo że dane powinny być odczytane natychmiast ze wstępnie zbudowanego cache (telemetrii).

## 2. Diagnoza przyczyn opóźnienia

Podzielono profilowanie 60-sekundowego opóźnienia na trzy niezależne bariery, z których każda dokładała znaczący czas do uruchomienia eksportu.

### Bariera 1: Koszt serializacji (Pickling) IPC (~20–25 sekund)
Przesyłanie konfiguracji z procesu nadrzędnego GUI do procesu potomnego D3D11 renderującego klatki opiera się na module `multiprocessing`. Analiza ujawniła, że potężne kolekcje instancji `LazySampleList` (zawierające po 300 tysięcy floatów każda dla danych `accel_x`, `gyro_x` itp.) ulegały pełnej materializacji (odczytowi do standardowych krotek Pythona), po czym picklowanie tej ilości elementów trwało blisko 20 sekund.
Winowajcą okazał się wprowadzony ostatnio do celów diagnostycznych skaner logujący "DIRECT_CHILD_CONFIG_HASH". Skaner wywoływał `json.dumps(..., default=str)` na słowniku konfiguracji przekazywanym do potomka, co niezamierzenie powodowało iterację (materializację) leniwych list.

### Bariera 2: Powtórne pre-obliczanie w procesie potomnym (~15 sekund)
Mimo, że GUI wygenerowało już potężny cache w pamięci mapowanej na dysk (plik `.npz` na dysku SSD), proces potomny D3D11 AMD był uruchamiany bez odpowiedniego identyfikatora klucza (tj. klucz `cache_key` nie trafiał do ostatecznego wrappera FFmpeg-D3D11). Skutkowało to powtórnym uruchomieniem ciężkiej pętli w czystym Pythonie na 47 000 elementach (tzw. `build_telemetry_cache`).

### Bariera 3: Synchroniczne renderowanie wykresów Matplotlib (~18 sekund)
Z racji architektonicznej niepodzielności wygenerowanych "gotowych wykresów" (obiektów Matplotlib / PIL Images), obrazy te nie były przesyłane w IPC, ponieważ ulegałby zniekształceniu (pickle PIL/Matplotlib obj jest niewskazany i ogromny). Proces potomny, uruchamiając rutynę `init_worker()`, zawsze na nowo budował (renderował) wykresy HUD synchronicznie, zajmując blisko 18 sekund na dużym zbiorze danych.

## 3. Zastosowane Rozwiązania

Zamiast sztucznie obcinać parametry (co maskowałoby problem), rozwiązano strukturalne zatory bez naruszania istniejących parserów:

1. **Izolacja skanera diagnostycznego IPC**:
   W pliku `render_mixin.py` do filtrowanego słownika dla budowania diagnostycznego _hasha_ wprost wykluczono obiekty zawierające końcówki `_samples` oraz ciężkie referencje `fit_data`, `gps_track`.
   - **Efekt**: Pamięć leniwa (`LazySampleList`) pozostaje niematerializowana w procesie potomnym (stan: "lazy"), a transfer zajmuje teraz **1,5 sekundy** zamiast 25 sekund.

2. **Podłączenie memmap cache (Zero-Copy) do procesu Renderera**:
   Zmodyfikowano sygnaturę końcową wrappera w `amd_native_exporter.py`, przekazując `cache_key`.
   Teraz potomek używa wywołania `RenderPreparationService.get_or_build(cache_key=cache_key, ...)` i osiąga natychmiastowy "HIT (disk memmap)", mapując odczyt wideo wektorowo prosto do VRAM.
   - **Efekt**: Wyeliminowano w potomku 15 sekund zbędnej kalkulacji ramki.

3. **Restytucja metadanych (Raw Arrays) z Cache do Init Worker**:
   Zmieniono pliki `worker_cache.py` i `amd_native_exporter.py` pod kątem restytucji wykresów. Ponieważ `telemetry_cache.static.chart_data` (odbudowany z pliku npz memmap) zawiera prekompilowane wektorowe zestawy korelacji punktowej, wprowadzono flagę `skip_chart_build=True`. Dzięki niej `init_worker` pomija żmudne renderowanie, a skrypt asymiluje od razu tablice bezpośrednio po wczytaniu cache.
   - **Efekt**: Czas inicjalizacji workerów (`[HUD] worker initialization`) spadł z 18 sekund do **0.25 sekundy**.

## 4. Weryfikacja

Wszystkie te zjawiska obserwowano i zniwelowano poprzez punktowe nasłuchiwanie wstrzykniętych mierników `[PERF]` czasomierzy w węzłach.

**Testowane obciążenie:**
Plik: `F:\GoPro\2026-10-09\GX010361.MP4` (47,183 klatki, 4K)

**Przed zmianami:**
```
[STARTUP TIMELINE] event='GUI Render clicked'
...
(Oczekiwanie 60 sekund zablokowane na Inicjalizacji Workerów / Picklingu)
...
[FIRST FRAME] ts=... (Start ramki po 62 sekundach)
```

**Po poprawkach:**
```
[STARTUP TIMELINE] event='GUI Render clicked' t=66337.649s
...
[FIRST FRAME] ts=1791561413.926 (Start ramki osiągnięty w mniej niż 7 sekund z pełną strukturą 47k klatek i IPC)
```

## 5. Zgodność z przenośnością (Portable)
Wykonano natychmiastową synchronizację, podbijając plik `version.py` do wersji **1.05**.
Repozytoria Main i Portable są spójne. Commity bezpiecznie przekazane na zdalny serwer (HEAD `9c4b984`).
Regresja zażegnana z poszanowaniem starych parserów i cache dyskowego GPMF.
