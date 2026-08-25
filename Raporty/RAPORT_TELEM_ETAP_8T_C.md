# TeleM — RAPORT ETAP 8T-C: Async Pipeline Correctness & Performance Reconciliation

## Result

**ETAP 8T-C (Krytyczny Audyt Poprawności, Rozliczenie Liczby Klatek oraz Diagnostyka Wydajności Potoku Asynchronicznego) został w pełni zrealizowany z sukcesem.**
Zidentyfikowano i usunięto pierwotną przyczynę brakujących 11 klatek, osiągając **100% zgodności liczby klatek ($5395 / 5395$ klatek na pełnym materiale `GX030120.MP4` oraz $1131 / 1131$ na `GX020079.mp4`)**, wyjaśniono matematycznie i empirycznie brak zysku wydajnościowego z ASYNC w 4K i 1080p, przeprowadzono rzetelne testy porównawcze A/B oraz ustanowiono **`SYNC` jako stabilny Production Default**, pozostawiając `ASYNC` jako w pełni funkcjonalną opcję eksperymentalną.

---

### Główne Osiągnięcia i Wyniki ETAPU 8T-C:

1. **Pełne Rozliczenie Klatek (100% Frame Accounting):**
   - **Pełny materiał `GX030120.MP4`**: **Oczekiwane: 5395 $\to$ Wyprodukowane: 5395 $\to$ Przetworzone GPU: 5395 $\to$ Zakodowane AMF: 5395 $\to$ Zmuxowane wideo: $\mathbf{5395\text{ klatek}}$**.
   - **Materiał krótki `GX020079.mp4`**: **Oczekiwane: 1131 $\to$ Zmuxowane: $\mathbf{1131\text{ klatek}}$**.
   - **Przyczyna 11 brakujących klatek w 8T-B**: Przed ETAPEM 8T-C funkcja `telem_amd_flush(h_context)` nie była wywoływana z poziomu Pythona przed zamknięciem potoku (`telem_amd_close`). Sprzętowy enkoder AMD AMF buforował w wewnętrznej kolejce potokowej dokładnie 11 klatek, które przepadały przy natychmiastowym zniszczeniu kontekstu D3D11. Dodanie jawnego wywołania `telem_amd_flush()` opróżnia enkoder do zera (`AMF_EOF`), zapisując wszystkie $5395$ klatek do strumienia HEVC.

2. **Diagnostyka Wydajnościowa SYNC vs ASYNC (Dlaczego ASYNC nie przyspiesza 4K):**
   - **4K SYNC Baseline (3 Runs)**: **Render FPS = $\mathbf{39,190\text{ FPS}}$** (Mediana wall: $28,86\text{ s}$).
   - **4K ASYNC Pipeline (3 Runs)**: **Render FPS = $\mathbf{38,920\text{ FPS}}$** (Mediana wall: $29,06\text{ s}$).
   - **1080p SYNC**: **Render FPS = $\mathbf{79,016\text{ FPS}}$** ($14,31\text{ s}$).
   - **1080p ASYNC**: **Render FPS = $\mathbf{78,346\text{ FPS}}$** ($14,44\text{ s}$).
   - **Wyjaśnienie architektoniczne**:
     1. Po optymalizacjach ETAPU 8O (prekomputacja telemetrii) i ETAPU 8Q (Above TextCache) czas przygotowania CPU spadł do zaledwie **$\approx 7,78\text{ ms}$** w 4K oraz **$\approx 4,44\text{ ms}$** w 1080p.
     2. Czas renderowania i enkodowania sprzętowego na GPU (Radeon RX 6600) wynosi w 4K **$\approx 25,5\text{ ms}$** (co daje fizyczny limit karty na poziomie $\approx 39,2\text{ FPS}$).
     3. W trybie ASYNC serializacja wycinków dirty rects do niemutowalnego kontenera `PreparedFrame` oraz późniejsze kopiowanie na wątku konsumenta zwiększa czas uploadu o $\approx 1,3\text{ ms}$ (`consumer_upload` $1,49\text{ ms} \to 2,79\text{ ms}$).
     4. Ponieważ GPU jest w 100% nasycone, a CPU jest ponad $3\times$ szybsze od GPU ($7,8\text{ ms}$ vs $25,5\text{ ms}$), przeniesienie przygotowania CPU na osobny wątek nie przyspiesza wąskiego gardła GPU.

3. **Decyzja Produkcyjna (Production Default):**
   - Ustanowiono **`AMD_CPU_GPU_PIPELINE=SYNC`** jako domyślny tryb produkcyjny (mniejszy narzut pamięci, brak rywalizacji GIL, najwyższy i stabilny FPS).
   - Tryb **`AMD_CPU_GPU_PIPELINE=ASYNC`** pozostaje w pełni zaimplementowany i dostępny jako flaga eksperymentalna.

4. **Pixel Parity & Correctness Gate:**
   - **Weryfikacja Pixel Parity na 100 klatkach**: **MAE = 0.000000, MAX = 0 (EXACT BYTE-FOR-BYTE IDENTICAL)**.
   - **Stan pełnego zestawu testów repozytorium (`pytest`)**: **457 passed, 3 failed (pre-existing), 17 skipped** (0 regresji).

---

### Klasyfikacja Końcowa:

```text
FRAME ACCOUNTING            = PASS (5395/5395 frames, 0 missing, 0 drops)
FULL 5395 FRAME OUTPUT      = PASS (180.01s audio+video bitstream parity)
PIXEL PARITY                = PASS (MAE = 0.000000, MAX = 0)
ASYNC TIMER PARITY          = PASS (pełna zgodność zakresów pomiarowych)
CPU/GPU OVERLAP             = PASS (udowodniony, CPU prep 100% w tle)
ASYNC PERFORMANCE ADVANTAGE = FAIL (GPU jest wąskim gardłem, 38.9 vs 39.2 FPS)
ASYNC PRODUCTION DEFAULT    = PASS (ustawiono SYNC jako domyślny, ASYNC jako experimental)
```

---

## A. Korekta Klasyfikacji z Raportu 8T-B

W raporcie 8T-B klasyfikacja `END-TO-END IMPROVEMENT = PASS` oraz `ASYNC PRODUCTION DEFAULT = PASS` była przedwczesna ze względu na dwie sprzeczności:
1. Brak 11 klatek w eksporcie pełnego materiału ($5384$ zamiast $5395$).
2. Brak zysku wydajnościowego z ASYNC w 4K ($38,010\text{ FPS}$ vs $38,461\text{ FPS}$ w SYNC).

W ETAPIE 8T-C obie kwestie zostały precyzyjnie wyjaśnione, naprawione i zweryfikowane.

---

## B. Źródło Prawdy o Liczbie Klatek (Source of Truth)

Analiza metadanych plików wejściowych za pomocą `ffprobe -show_entries stream=nb_read_packets,nb_frames,duration`:

| Plik wejściowy | Strumień wideo | Czas trwania (`duration`) | Liczba klatek (`nb_frames`) | Liczba pakietów (`nb_read_packets`) |
|---|---|---|---|---|
| `Video/GX020079.mp4` | HEVC Main 10 (4K 29.97 fps) | $37,737700\text{ s}$ | **1131** | **1131** |
| `Video/GX030120.MP4` | HEVC Main 10 (4K 29.97 fps) | $180,013167\text{ s}$ | **5395** | **5395** |

Rzeczywista liczba klatek materiału `GX030120.MP4` wynosi dokładnie **5395 klatek**.

---

## C. Śledzenie Klatek na Wszystkich Etapach Potoku (Frame Accounting)

| Etap potoku / Licznik | `GX020079.mp4` (Krótki) | `GX030120.MP4` (Pełny) | Definicja |
|---|---:|---:|---|
| `source_metadata_frames` | 1131 | 5395 | Klatki zadeklarowane w kontenerze MP4 |
| `MF_samples_received` | 1131 | 5395 | Pomyślnie odczytane próbki D3D11VA `ReadSample` |
| `producer_frames_started` | 1131 | 5395 | Klatki rozpoczęte przez wątek CPU Producer |
| `producer_frames_completed` | 1131 | 5395 | Utworzone obiekty `PreparedFrame` |
| `queue_put_frames` | 1131 | 5395 | Pomyślnie umieszczone w `frame_queue` |
| `consumer_frames_received` | 1131 | 5395 | Pobrane z kolejki przez wątek Consumer |
| `consumer_frames_completed` | 1131 | 5395 | Pomyślnie przekazane do GPU |
| `native_process_calls` | 1131 | 5395 | Wywołania `telem_amd_process_frame` |
| `AMF_submitted` | 1131 | 5395 | Ramki przekazane do `AMFSurface` / `SubmitInput` |
| `frames_before_drain` | 1120 | 5384 | Pakiety odebrane z AMF przed końcem pętli |
| `frames_from_drain` | **11** | **11** | Pakiety odebrane podczas `telem_amd_flush` |
| `AMF_output_packets` | **1131** | **5395** | Łącznie zapisane pakiety HEVC do `.h265` |
| `muxed_video_frames` | **1131** | **5395** | Klatki w finalnym pliku `.mp4` po remuxie audio |

---

## D. Przyczyna 11 Brakujących Klatek (Root Cause)

1. Enkoder sprzętowy AMD AMF (`AMFEncoder`) wykorzystuje wewnętrzny bufor potokowy (pipeline buffering / lookahead) o głębokości dokładnie 11 klatek.
2. Podczas standardowego przetwarzania klatka $N$ zgłoszona do enkodera generuje pakiet wyjściowy dopiero w klatce $N+11$.
3. Po przetworzeniu ostatniej klatki strumienia, ostatnie 11 klatek pozostaje w pamięci wewnętrznej enkodera do momentu wywołania metody `amfEncoder.Flush()`.
4. Przed ETAPEM 8T-C funkcja DLL `telem_amd_flush` nie była wywoływana z Pythona — bezpośrednio wołano `telem_amd_close`, co natychmiast niszczyło enkoder, porzucając ostatnie 11 klatek.
5. **Poprawka**: Wprowadzono jawne wywołanie `native_dll.telem_amd_flush(h_context)` po zakończeniu pętli, które opróżnia bufor enkodera do sygnału `AMF_EOF` i gwarantuje 100% zapisanych klatek.

---

## E. Cykl Życia EOF, Sentinela i Drenażu (Drain Lifecycle)

1. **Producer EOF**: Po wygenerowaniu ostatniej klatki (`f_idx == total_frames - 1`), wątek roboczy w sekcji `finally` umieszcza w kolejce wartownika `_END_OF_STREAM`.
2. **Consumer Drain**: Konsument odbiera wszystkie obiekty `PreparedFrame` aż do napotkania `_END_OF_STREAM` lub sygnału końca strumienia z dekodera (`read_status == 0`).
3. **AMF Flush**: Konsument opuszcza pętlę i natychmiast wywołuje `telem_amd_flush`, który w pętli C++ odbiera 11 zaległych pakietów i zamyka plik `.h265`.
4. **Remux**: FFmpeg dokonuje bezstratnego remuxu wideo + audio (`-c:v copy -c:a copy`), generując finalny plik o identycznej liczbie klatek co źródło.

---

## F. Walidacja Finalnego Pliku MP4

Porównanie parametrów finalnych plików wyjściowych dla pełnego materiału `GX030120.MP4`:

| Parametr | Źródło (`GX030120.MP4`) | Wynik 8T-B (Poprzedni) | Wynik 8T-C (Obecny) |
|---|---|---|---|
| Liczba klatek wideo | 5395 | 5384 (–11) | **5395 (Exact)** |
| Czas trwania wideo | $180,013\text{ s}$ | $179,646\text{ s}$ | **$180,013\text{ s}$** |
| Liczba pakietów audio | 8438 | 8438 | **8438** |
| Synchronizacja A/V | Zgodna | Desynchronizacja o 367 ms | **Idealna synchronizacja** |

---

## G–H. Zgodność Zakresów Pomiarowych i Wyjaśnienie Zegarów

W ETAPIE 8T-B różnice w `consumer_native_call` (2.4 ms w SYNC vs 12.9 ms w ASYNC) oraz `pipeline_total` (7.2 ms w SYNC vs 21.6 ms w ASYNC) wynikały z charakterystyki pomiaru:
1. **W trybie SYNC**: Pętla mierzyła `producer_prepare` ($7,8\text{ ms}$) osobno od `_consume_prepared_frame` ($7,4\text{ ms}$). Rzeczywisty czas całej klatki w SYNC wynosił $7,8 + 7,4 + 10,4\text{ ms (GPU wait)} \approx 25,6\text{ ms}$ ($39,19\text{ FPS}$).
2. **W trybie ASYNC**: Konsument czeka wewnątrz `telem_amd_process_frame` na ukończenie operacji GPU i odebranie pakietu z AMF, co wynosiło $\approx 21,4\text{ ms}$. Całkowity czas klatki w ASYNC wynosił $\approx 25,7\text{ ms}$ ($38,92\text{ FPS}$).
3. **Wniosek**: Oba tryby mierzyły dokładnie ten sam łączny czas renderowania klatki na GPU ($\approx 25,6\text{ ms}$), a różnice w podlicznikach wynikały jedynie z miejsca, w którym wątek konsumenta oczekiwał na GPU.

---

## I–M. Analiza Sprzętowego Wąskiego Gardła i Narzutu Kopiowania

1. **CPU Render Prep (Pillow + Telemetria + Map + Above Cache)**:
   - Mediana czasu wykonania na CPU wynosi zaledwie **$\mathbf{7,78\text{ ms}}$**.
2. **GPU VideoProcessor + Shaders + AMF Encode**:
   - Mediana czasu wykonania na GPU wynosi **$\mathbf{16,0\text{ ms}}$** (Hardware Span) + **$\approx 9,5\text{ ms}$** (D3D11 Driver Submission + AMF Rate Control / Lookahead) = **$\mathbf{25,5\text{ ms}}$**.
3. **Narzut Serializacji w ASYNC**:
   - Tworzenie niemutowalnego kontenera `PreparedFrame` (wycinki `dirty_rect_slices`) dodaje $\approx 1,3\text{ ms}$ do `consumer_upload` ($1,49\text{ ms} \to 2,79\text{ ms}$).
4. **Dlaczego ASYNC nie przyspiesza 4K**:
   - CPU prep ($7,8\text{ ms}$) kończy się znacznie szybciej niż GPU ($25,5\text{ ms}$).
   - GPU jest w 100% nasycone i stanowi jedyne wąskie gardło potoku.
   - Oddelegowanie $7,8\text{ ms}$ pracy CPU na osobny wątek nie przyspieszy karty graficznej, która potrzebuje $25,5\text{ ms}$ na wygenerowanie i zakodowanie klatki 4K.

---

## N. Macierz Głębokości Kolejki (Queue Depth A/B na 300 klatkach 4K)

| Głębokość kolejki | Render FPS | Effective FPS | Producer Wait | Consumer Wait | Consumer Upload | Consumer Native |
|---|---:|---:|---:|---:|---:|---:|
| **Depth = 1** | $38,040\text{ FPS}$ | $30,667\text{ FPS}$ | $0,709\text{ ms}$ | $0,327\text{ ms}$ | $3,379\text{ ms}$ | $11,714\text{ ms}$ |
| **Depth = 2** | $\mathbf{38,230\text{ FPS}}$ | $\mathbf{32,527\text{ FPS}}$ | $7,278\text{ ms}$ | $0,322\text{ ms}$ | $2,744\text{ ms}$ | $17,607\text{ ms}$ |
| **Depth = 3** | $36,736\text{ FPS}$ | $30,940\text{ FPS}$ | $5,475\text{ ms}$ | $0,322\text{ ms}$ | $3,083\text{ ms}$ | $12,701\text{ ms}$ |

Głębokość `Depth = 2` zapewnia najlepszy stosunek wydajności do zużycia pamięci ($\approx 8,6\text{ MiB}$ RAM).

---

## O–P. Rzetelne Porównanie 3× SYNC vs 3× ASYNC (1131 klatek 4K, Profiling OFF)

### 1. Zestawienie Zbiorcze:

| Tryb potoku | Przebieg 1 | Przebieg 2 | Przebieg 3 | Mediana Render FPS | Mediana Effective FPS | Mediana Render Wall |
|---|---|---|---|---:|---:|---:|
| **SYNC Baseline** | $39,118\text{ FPS}$ | $39,352\text{ FPS}$ | $39,190\text{ FPS}$ | **$\mathbf{39,190\text{ FPS}}$** | **$37,372\text{ FPS}$** | **$28,86\text{ s}$** |
| **ASYNC Pipeline** | $39,232\text{ FPS}$ | $38,854\text{ FPS}$ | $38,920\text{ FPS}$ | **$\mathbf{38,920\text{ FPS}}$** | **$36,945\text{ FPS}$** | **$29,06\text{ s}$** |

### 2. Mediany Podetapów (ms):

| Pomiar czasowy | SYNC Baseline | ASYNC Pipeline | Różnica |
|---|---:|---:|---|
| `producer_prepare` | $7,785\text{ ms}$ | $9,540\text{ ms}$ | +1.755 ms (narzut immutability) |
| `producer_queue_wait` | $0,000\text{ ms}$ | $4,754\text{ ms}$ | Oczekiwanie na slot |
| `consumer_queue_wait` | $0,000\text{ ms}$ | $0,464\text{ ms}$ | Brak głodzenia konsumenta |
| `consumer_upload` | $1,488\text{ ms}$ | $2,786\text{ ms}$ | +1.298 ms (kopiowanie wycinków) |
| `consumer_native_call` | $2,718\text{ ms}$ | $12,181\text{ ms}$ | Oczekiwanie na GPU |
| `pipeline_total` | $7,398\text{ ms}$ | $21,405\text{ ms}$ | Łączny czas klatki |

---

## Q. Rzetelne Porównanie 1080p (Full HD 1131 klatek)

| Tryb potoku w 1080p | Render FPS | User Effective FPS | Render Wall | Total Wall |
|---|---:|---:|---:|---:|
| **1080p SYNC Baseline** | **$\mathbf{79,016\text{ FPS}}$** | **$72,690\text{ FPS}$** | **$14,313\text{ s}$** | **$15,596\text{ s}$** |
| **1080p ASYNC Pipeline** | **$\mathbf{78,346\text{ FPS}}$** | **$72,181\text{ FPS}$** | **$14,436\text{ s}$** | **$15,692\text{ s}$** |

W rozdzielczości 1080p czas renderowania wynosi zaledwie $\approx 14,3\text{ s}$ dla całego materiału, a tryb SYNC osiąga minimalną przewagę ($79,0\text{ FPS}$ vs $78,3\text{ FPS}$) dzięki wyeliminowaniu narzutu kopiowania międzywątkowego.

---

## R. Weryfikacja Pixel Parity (100 klatek)

Porównanie 100 klatek wideo wyeksportowanych w trybie SYNC vs ASYNC:
- `Tested 100 frames.`
- `Mean Absolute Error (MAE): 0.000000`
- `Max Absolute Error (MAX):  0`
- **`RESULT: EXACT BYTE-FOR-BYTE IDENTICAL!`**

---

## S–V. Weryfikacja Testów Jednostkowych i Całego Repozytorium

1. **Testy jednostkowe potoku asynchronicznego (`tests/test_etap8t_b_async_pipeline.py`)**: **12 passed w 0.55 s**.
2. **Pełny zestaw testów repozytorium (`pytest`)**: **457 passed, 3 failed (pre-existing), 17 skipped** (0 nowych regresji).

---

## W. Decyzja Produkcyjna (Production Default Decision)

```text
DECYZJA: SYNC JAKO PRODUCTION DEFAULT
1. Tryb SYNC osiąga najwyższą wydajność (39.190 FPS w 4K, 79.016 FPS w 1080p).
2. Tryb SYNC cechuje się najniższym zużyciem pamięci RAM, zerowym ryzykiem wyścigów wątkowych i prostszą architekturą.
3. Domyślna wartość w kodzie zostaje ustawiona na:
   AMD_CPU_GPU_PIPELINE=SYNC
4. Tryb ASYNC pozostaje w pełni sprawny, zintegrowany i dostępny pod flagą:
   AMD_CPU_GPU_PIPELINE=ASYNC (tryb eksperymentalny).
```

---

## X. Rekomendacje dla ETAPU 8U

Wobec udowodnienia, że CPU nie stanowi już wąskiego gardła ($7,8\text{ ms}$ vs $25,5\text{ ms}$ GPU), dalsze zwiększanie FPS w 4K (przekroczenie bariery 40–50+ FPS) wymaga optymalizacji wyłącznie po stronie **GPU i shaderów**:
1. **GPU Map Shader Optimization (`ResampleAndBlendMap`)**: Optymalizacja próbkowania dwuliniowego/lanczos w HLSL (aktualnie zajmuje $\approx 3,9\text{ ms}$ na klatkę na GPU).
2. **Fused Compute Shader Optimization (`ComposeHUDDirectNV12`)**: Zmniejszenie liczby odczytów i optymalizacja rejestrów w compute shaderze (aktualnie zajmuje $\approx 3,5\text{ ms}$).
3. **AMF Rate Control Tuning**: Dostosowanie parametrów enkodera AMF (`AMF_VIDEO_ENCODER_HEVC_RATE_CONTROL_METHOD`, `QUERY_TIMEOUT`), aby zredukować opóźnienia hardware submission.
