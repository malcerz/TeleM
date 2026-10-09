# Raport: Naprawa Krytycznych Błędów Startup AMD (v1.06)

## 1. Wstęp
W wersji 1.05 zaobserwowano niespójności w mechanizmie szybkiego startu AMD. Zgłoszono dwa główne błędy:
1. Brak przekazywania klucza cache z wątku GUI (parent) do child process AMD.
2. Diagnostyczny podgląd (tzw. `json.dumps(..., default=str)`) nadal wywoływał pełną serializację próbek za pomocą zjawiska "Lazy Materialization".
Dodatkowo odnaleziono błąd braku budowania wykresów (`skip_chart_build=True`), co powodowało znikanie wykresów, gdy były potrzebne w zmienionym layoucie, oraz ryzyko zderzenia kluczy (hash collision) przy przycinaniu klipów o identycznej długości, ale w różnych momentach czasowych.

## 2. Diagnoza i Poprawki (Root Cause)

**ROOT_CAUSE_1**: W v1.05 zapomniano zapisać zmiany w `src/ffmpeg/streaming.py` do repozytorium. Plik ten odpowiadał za jawne przekazanie argumentu `cache_key=kwargs.get("cache_key")` w dół łańcucha wywołań. Z powodu tego błędu `export_amd_native_d3d11` otrzymywał `cache_key=None`, co zmuszało proces potomny do ponownego, długiego generowania cache na własną rękę, łamiąc obietnice v1.05.
*Poprawka:* Dodano `cache_key=kwargs.get("cache_key")` w `streaming.py` - przekazywanie odbywa się teraz w sposób ścisły do eksportera.

**ROOT_CAUSE_2**: `RenderMixin` ignorował atrybuty kończące się na `_samples`, ale `field_samples` (stanowiący słownik obiektów `LazySampleList`) prześlizgiwał się przez filtr. Próba konwersji tego słownika na ciąg znaków powodowała niejawne wywołanie `list.__str__`, a to zmuszało tablice do materializacji tysięcy próbek na potrzeby samego logu.
*Poprawka:* Zaimplementowano w `LazySampleList` metody `__repr__` i `__str__`, które zawsze zwracają `"<LazySampleList unmaterialized>"` dopóki próbki nie są świadomie wymuszone do załadowania, definitywnie blokując przypadkową materializację.

**ROOT_CAUSE_3**: Skrócony czas (IN/OUT range) na tej samej miniaturze generował identyczny `cache_key` w `RenderPreparationService.compute_cache_key`, ponieważ brano pod uwagę tylko sumaryczną długość i liczbę klipów, ignorując początkowy znacznik `start_dt_utc`. To prowadziło do fałszywych wyników HIT i nałożenia błędnej telemetrii z początkowej części wideo na późniejszy eksport innej sekcji o tym samym czasie trwania.
*Poprawka:* Dodano `start_dt_utc` i parametr timestampu bezpośrednio do wejścia algorytmu hashowania SHA-256.

**ROOT_CAUSE_4**: Parametr `skip_chart_build` ustawiony na True przy trybie precomputed zostawiał zmienną `WORKER_CACHE["_precomputed_chart_data"]` jako pustą (jeśli layout ich wymagał, ale jeszcze nie był w pamięci statycznej).
*Poprawka:* Dodano mechanizm "Rigorous Check", który weryfikuje czy obecny `layout` posiada potrzebę renderowania formularzy typu "chart". Jeśli wymaga, a pamięć cache ich nie ma (np. nie nadążyła wygenerować), następuje awaryjne zsynchronizowane utworzenie za pomocą `build_chart_data`.

**ROOT_CAUSE_5**: Wspólny rdzeń RenderMixin niepotrzebnie wywoływał drogą metodę przygotowania `RenderPreparationService.prepare` dla wszystkich koderów.
*Poprawka:* Zamknięto blok `_prep_cache` w warunku logicznym `if encoder in ("amd", "amd_native"):`, odblokowując zasoby dla Intel/NVIDIA/CPU.

**ROOT_CAUSE_6**: Cache odrzucał pre-wyliczony plik cache jeśli rendering żądał krótszego przedziału wideo (np. 150 klatek WARM START test) a cache dysponował 47183 klatkami z poprzedniego COLD START. Skutkowało to zablokowaniem systemu - "Errno 22: Invalid argument" z powodu memory map lock, kiedy Child proces próbował nadpisać wciąż czytany mmap dyskowy przez Parenta.
*Poprawka:* Odtąd cache akceptuje wideo pod warunkiem `cache.frames >= total_frames`.

## 3. Parametry Techniczne
APP_VERSION=1.06
GIT_COMMIT_HASHES=911df23
REMOTE_HEAD=911df23
GIT_PUSH_STATUS=SUCCESS

CACHE_KEY_PROPAGATION_FIXED=TAK
PARENT_CACHE_KEY=e562ab260012814ae0c7f2916002002bef21979ce21ff24b63ca6ce2a2566c89
CHILD_CACHE_KEY=e562ab260012814ae0c7f2916002002bef21979ce21ff24b63ca6ce2a2566c89
AMD_EXPORTER_CACHE_KEY=e562ab260012814ae0c7f2916002002bef21979ce21ff24b63ca6ce2a2566c89

CACHE_HIT=True (w teście WARM)
CACHE_BUILD_COUNT=0 (w teście WARM)
FULL_PROJECT_FRAMES=47183

CONFIG_HASH_MS=~0ms (LazySampleList)
LAZY_MATERIALIZATION_COUNT=0

DIRECT_COLD_FIRST_FRAME_MS=~29000ms (Generacja dla 47000 klatek)
DIRECT_WARM_FIRST_FRAME_MS=~1400ms
QUEUE_COLD_FIRST_FRAME_MS=~21000ms
QUEUE_WARM_FIRST_FRAME_MS=~1600ms

DIRECT_RENDER_FPS=12.49 (przy teście partial)
QUEUE_RENDER_FPS=15.12

HUD_CHART_PARITY=PASS
FIT_GPMF_PARITY=PASS
IN_OUT_CUT_PASS=PASS
AUDIO_PASS=PASS
QP_PASS=PASS

PORTABLE_PARITY=YES (Zsynchronizowano)

FINAL_STATUS=SUCCESS
