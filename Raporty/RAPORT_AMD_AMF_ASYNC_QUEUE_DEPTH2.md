# RAPORT: AMD NATIVE — AMF ASYNC PIPELINE / QUEUE DEPTH 2
## Eliminacja AMF_INPUT_FULL Busy-Retry + Pomiary Wydajności i Decyzja Produkcyjna

**Data:** 2026-09-03  
**Repozytorium:** `C:\_DEV\TeleM-integration`  
**Branch:** `integration/intel-amd`  
**Backend:** `AMD_NATIVE_D3D11`  

---

## 1. Rzeczywiste Środowisko Sprzętowe (Hardware Identity)

> [!IMPORTANT]
> **Korekta błędu nomenklatury z wersji roboczej:**  
> We wstępnym szkicu raportu błędnie wskazano model `AMD Ryzen 7 5825U` przez omyłkowe skopiowanie nazwy starszej rewizji rodziny Barcelo. Oba procesory dzielą tę samą architekturę krzemową (Barcelo-R / Cezanne, blok VCN 2.2, PCI Device ID `0x15E7`).  
> Poniższe dane zostały pobrane bezpośrednio z systemu operacyjnego maszyny testowej za pośrednictwem PowerShell CIM / DXGI. Wszystkie benchmarki w tym zadaniu zostały wykonane **na tej rzeczywistej maszynie**:

```text
ACTUAL TEST MACHINE:
  CPU:            AMD Ryzen 7 7730U with Radeon Graphics (8 rdzeni / 16 wątków, 2000 MHz base, 15W cTDP)
  GPU Adapter:    AMD Radeon (TM) Graphics
  PCI Device ID:  PCI\VEN_1002&DEV_15E7&SUBSYS_16361002&REV_C4 (Vendor: 0x1002 AMD, Device: 0x15E7)
  Driver Version: 31.0.21925.1001 (AMD Software: Adrenalin Edition, data sterownika: 2026-05-20)
  OS:             Windows 11 Pro 64-bit
```

---

## 2. Wsad Testowy (Autorytatywny wg BENCHMARKS.md)

- **Plik wideo:** `Video/GX010115.MP4` (3840x2160, 29.970 CFR, HEVC Main 10, HLG/BT.2020, 17 760 klatek)
- **Plik telemetryczny:** `Video/GX010114_116.fit` (sparowanie kanoniczne wg `BENCHMARKS.md`)
- **Preset layoutu:** `presets/cycling_dashboard_v10.json` (+ `lean_indicator` GPU, Speed Gauge GPU, HR/Cadence GPU_SPLIT)
- **Konfiguracja kodera AMF:** `AMFVideoEncoder_HEVC`, `QUALITY_PRESET_SPEED`, CQP QP 28/28, B-frames=0, Ref=1, Direct MP4 Mux (Named Pipe do `ffmpeg`)

---

## 3. Korekta Matematyczna Poprzedniego Audytu

W poprzednim audycie (`Raporty/RAPORT_AMD_CURRENT_41FPS_BOTTLENECK_AUDIT.md`) pojawiła się niespójność metodologiczna polegająca na próbie arytmetycznego zsumowania wyników dwóch odrębnych syntetycznych testów:
- `decode-only`: 8.70 ms (~114.9 FPS)
- `encode-only`: 20.08 ms (~49.8 FPS)
- Suma arytmetyczna: 8.70 ms + 20.08 ms = 28.78 ms $\rightarrow$ 34.75 FPS.

Z powyższego nie można bez modelu arbitrażu wyprowadzić produkcyjnego wyniku 41–42 FPS. Decode-only i encode-only mierzyły silnik VCN w trybie wyłącznym:
1. Podczas `decode-only`, cały VCN dedykowany był na dekompresję strumienia bitowego.
2. Podczas `encode-only`, VCN dedykowany był wyłącznie na kompresję przygotowanych buforów.
3. W realnym potoku produkcyjnym **oba podsystemy (dekoder i enkoder) współdzielą ten sam monolityczny blok sprzętowy VCN 2.2 oraz szynę pamięci Infinity Fabric / DRAM**.
4. W starym kodzie synchronicznym występowało niejawne nachodzenie ramek (Frame $N$ kodował się w sprzęcie, podczas gdy CPU przygotowywało klatkę $N+1$), jednak odbywało się to kosztem patologicznego busy-spinu `AMF_INPUT_FULL`.

---

## 4. Wartość Architektoniczna: Usunięcie Pętli Busy-Spin i Burzy Alokacji COM

Przed niniejszą optymalizacją funkcja `telem_amd_process_frame` w `native/d3d11_amf_pipeline/src/telem_amd_native.cpp`:
1. Wywoływała `ctx->amfEncoder.SubmitTexture(...)` przed upewnieniem się, czy poprzednia klatka opuściła wejście enkodera.
2. Gdy enkoder sprzętowy przetwarzał jeszcze poprzednią klatkę, AMF zwracało błąd `AMF_INPUT_FULL`.
3. Funkcja wchodziła w pętlę `while (sRes == AMF_INPUT_FULL)` kręcącą się na `std::this_thread::yield()`.
4. Przy każdym obrocie pętli ponownie wywoływano `SubmitTexture(...)`, która wewnątrz wywoływała `m_pContext->CreateSurfaceFromDX11Native(...)`.

### Porównanie Architektoniczne:

| Cecha | Stan Przed (Baseline) | Stan Po (ASYNC Depth 2) | Zmiana / Zysk |
| :--- | :---: | :---: | :---: |
| **Liczba błędów AMF_INPUT_FULL / klatkę** | ~3 907 prób/klatkę | **0** | **-100% (całkowita eliminacja)** |
| **Łączne retries (17 760 klatek)** | ~69.4 miliona | **0** | **-100% (całkowita eliminacja)** |
| **Alokacje COM AMFSurface / klatkę** | ~3 907 alokacji/klatkę | **1** (dokładnie raz) | **-99.974%** |
| **Łączne alokacje COM (17 760 klatek)** | ~69.4 miliona alokacji | **17 760** alokacji | **Redukcja o 69.37 miliona** |
| **Zużycie CPU rdzenia renderującego** | 100% spin w yield loop | Brak zbędnego spinu | **Zwolnienie wątków sterownika** |
| **Zarządzanie czasem życia powierzchni** | Niekontrolowane ponowienia | Deterministyczny bounded queue | **Gwarancja izolacji slotów NV12** |

---

## 5. Zaimplementowana Architektura: Potok Asynchroniczny AMF (Queue Depth 2)

Wprowadzono pełną refaktoryzację warstwy natywnej C++ oraz modułu eksportu w Pythonie:

1. **Rozdzielenie tworzenia powierzchni od zgłaszania (`d3d11_amf_encoder`):**
   - Dodano `D3D11AMFEncoder::CreateSurface(...)`, tworzące wrapper COM `AMFSurface` **dokładnie raz na klatkę**.
   - Dodano `D3D11AMFEncoder::SubmitSurface(...)` przyjmujące gotową powierzchnię — w razie backpressure nie ma ponownej alokacji COM.
2. **Pięcioetapowy cykl klatki (`telem_amd_process_frame`):**
   - **Substage A (Pre-drain):** Nieblokujące odebranie pakietów ukończonych w tle.
   - **Substage B (In-flight bound gating):** Bramkowanie `in_flight < queueDepth`. Oczekiwanie na najstarszą klatkę z mikrosekundowym backoffem (`100 µs`), co eliminuje głodzenie wątków sterownika AMD.
   - **Substage C (Single surface creation):** Utworzenie powierzchni AMF dokładnie 1 raz.
   - **Substage D (Submit):** Wysłanie powierzchni do enkodera AMF.
   - **Substage E (Non-blocking post-drain):** Opróżnienie pakietów gotowych bez czekania.
3. **Izolacja slotów (Ring Buffer):**
   - Pula `m_outputPool` posiada 8 buforów NV12 D3D11. Klatka $N$ i $N+1$ używają różnych tekstur D3D11 (`slot = frame_index % poolSize`), co gwarantuje integralność danych.
4. **Zgodność z Direct MP4 Mux:**
   - Gotowe pakiety trafiają na bieżąco do Named Pipe podłączonego do `ffmpeg`. Dodano funkcję `telem_amd_drain_amf(...)` gwarantującą pełne opróżnienie enkodera przy zamykaniu potoku.

---

## 6. Wyniki Benchmarków: Kontrolowany Test 3 000 Klatek

Testy wykonano na 3000 klatkach `GX010115.MP4` w identycznych warunkach (4K UHD, layout v10, QP 28/28 SPEED).

### Tabela 1: Kontrolowane Porównanie Trybów (3 000 klatek)

| Konfiguracja | Klatki | Czas Video Encode | Render FPS | Effective FPS | input_full | retries | max in-flight |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Kontrolowany SYNC Depth 1** | 3000 | 76.950 s | **38.986** | 37.837 | **0** | **0** | 1 |
| **ASYNC Depth 2** | 3000 | 70.698 s | **42.434** | **41.065** | **0** | **0** | 2 |
| **ASYNC Depth 3** | 3000 | 70.739 s | **42.409** | **41.106** | **0** | **0** | 3 |
| **Minimal HUD ASYNC Depth 2** | 3000 | 70.161 s | **42.759** | **41.785** | **0** | **0** | 2 |

### Wyjaśnienie Wyników:
1. **Zysk w kontrolowanym benchmarku:** ASYNC Depth 2 osiąga **42.434 FPS vs 38.986 FPS** w nowym SYNC Depth 1 (**+8.84%**).
2. **Weryfikacja Depth 2 vs Depth 3:** Depth 3 osiąga **42.409 FPS** (praktycznie identyczny wynik, różnica 0.06%). Potwierdza to decyzję techniczną: **Queue Depth = 2 jest w pełni wystarczający do wysycenia potoku sprzętowego; większe kolejki nie przynoszą żadnej korzyści**.
3. **Ostrożne sformułowanie sufitu VCN:**
   - Minimal HUD (pass-through bez kompozycji HUD) = **42.759 FPS**.
   - Full HUD (kompletna kompozycja v10) = **42.434 FPS**.
   - Różnica wynosi **0.325 FPS (0.76%)**.
   - Oznacza to, że **na tej konkretnej maszynie i konfiguracji (Ryzen 7 7730U, 15W cTDP, 4K HEVC Main 10 decode + HEVC SPEED encode, Direct Mux)** mierzony sufit produkcyjny wynosi **~42–43 FPS**. Narzut kompozycji HUD jest w pełni ukryty za czasem pracy enkodera AMF.

---

## 7. Wyjaśnienie Różnicy Między SYNC1 (38.986 FPS) a Historycznym Baseline (41.311 FPS)

Dlaczego nowo zaimplementowany, kontrolowany `SYNC Depth 1` osiąga **38.986 FPS**, podczas gdy historyczny kod synchroniczny z pętlą busy-spin osiągał **41.311 FPS**?

### Mechanizm Historycznego Kodu (Niejawne Nakładanie Klatek):
W starym kodzie `telem_amd_process_frame`:
1. Klatka $N$ wywoływała `SubmitTexture(...)`, po czym natychmiast wywoływała `QueryPacket(...)`. Koder AMF zwracał `AMF_REPEAT` (pakiet jeszcze niegotowy), więc funkcja natychmiast wracała do Pythona.
2. Klatka $N+1$ była dekodowana i składana przez CPU/D3D11, po czym wywoływała `SubmitTexture(...)`.
3. Jeśli koder sprzętowy kończył w tym czasie klatkę $N$, klatka $N+1$ natychmiast trafiała do bufora enkodera AMF (`AMF_OK`), a dopiero w kolejnym kroku odbierano pakiet klatki $N$.
4. **W efekcie stary kod synchroniczny NIE był ścisłym Depth 1**, lecz pracował z **przypadkowym, niekontrolowanym nachodzeniem ramek (efektywny queue depth ~1.5)**. Odbywało się to jednak kosztem ponad 3 900 prób ponowień `AMF_INPUT_FULL` i ciągłych alokacji COM.

### Mechanizm Nowego Kontrolowanego SYNC Depth 1:
W nowym, celowo ścisłym `SYNC Depth 1`:
1. Substage B wymusza warunek: `while (inFlightFrames >= 1)` — wątek MUSI poczekać na zakończenie i odebranie pakietu klatki $N-1$ **zanim klatka $N$ zostanie w ogóle wysłana do enkodera AMF**.
2. Wprowadza to pełną serializację (brak jakiegokolwiek nakładania w sprzęcie enkodera):
   $$\text{Czas cyklu} = \text{decode} + \text{compose} + \text{AMF encode} + \text{drain packet}$$
   Czas ten wynosi ~25.6 ms/klatkę, co odpowiada dokładnie **38.986 FPS**.
3. **Wniosek:** `SYNC Depth 1` jest matematycznie poprawnym, zserializowanym punktem odniesienia, podczas gdy `ASYNC Depth 2` zapewnia kontrolowane, czyste nakładanie klatek w sprzęcie bez patologii busy-spin.

---

## 8. Pełny Render Referencyjny (17 760 Klatek, Cały Plik GX010115.MP4)

Przeprowadzono pełny render całego 10-minutowego wideo `GX010115.MP4` (17 760 klatek 4K) w trybie **ASYNC Depth 2** i porównano go bezpośrednio z historycznym pełnym renderem produkcyjnym:

### Tabela 2: Pełny Render Produkcyjny (17 760 klatek) — Przed vs Po

| Metryka | Historyczny Baseline (z busy-spin) | ASYNC Depth 2 (niniejsza optymalizacja) | Rzeczywista Zmiana |
| :--- | :---: | :---: | :---: |
| **Klatki poddane renderowi** | 17 760 | 17 760 | 100% zgodności |
| **HUD prepare** | 2.122 s | **1.345 s** | **-36.6%** (-0.78 s) |
| **Video encode** | 429.913 s | **427.824 s** | **-2.09 s** (-0.49%) |
| **Finalize (Direct Mux)** | 4.809 s | 5.215 s | +0.40 s |
| **Total Wall Time** | 437.557 s | **434.887 s** | **-2.67 s** zysku |
| **Render FPS** | 41.311 | **41.512** | **+0.49% (+0.201 FPS)** |
| **Effective FPS** | 40.589 | **40.838** | **+0.61% (+0.249 FPS)** |
| **AMF input_full_count** | ~69.4 mln | **0** | **-100%** |
| **AMF retry_count** | ~69.4 mln | **0** | **-100%** |
| **Utworzenia powierzchni COM** | ~69.4 mln | **17 760** (1 / klatkę) | **-99.974%** |

### Rozróżnienie Zysków:
- **Zysk w kontrolowanym teście 3000f (ASYNC2 vs ścisły SYNC1):** **+8.84%** (42.434 vs 38.986 FPS).
- **Zysk na pełnym renderze produkcyjnym 17 760f (ASYNC2 vs stary baseline z busy-spin):** **+0.49%** Render FPS (**+0.61%** Effective FPS, skrócenie łącznego czasu o **2.67 s**).
- **Uwaga metodologiczna dot. różnicy 42.4 FPS (3000f) vs 41.5 FPS (17760f):** Różnica rzędu ~0.9 FPS wynika z zachowania energetyczno-termicznego zintegrowanego SoC 15W podczas długotrwałego (ponad 7-minutowego) obciążenia bloku VCN na poziomie 99% lub zmienności procesów tła systemu Windows. Parametry te nie były bezpośrednio logowane, dlatego traktujemy to jako zachowanie pakietu energetycznego, a nie udowodniony fakt.

---

## 9. Weryfikacja Poprawności i Bezpieczeństwa (Regression Testing)

Dla trybu ASYNC Depth 2 przeprowadzono pełny zestaw testów poprawnościowych:

1. **Weryfikacja wyjścia pełnego renderu (17 760 klatek):**
   - `nb_frames`: **17 760 requested $\rightarrow$ 17 760 encoded and muxed** (100% kompletności).
   - `start_time`: `0.000000`.
   - `PTS/DTS monotonicity`: Przebadano wszystkie 17 760 pakietów w kontenerze MP4 za pomocą `ffprobe`. Liczba naruszeń monotoniczności PTS = **0**.
   - `A/V parity`: Czas trwania wideo = `592.592593 s`, czas trwania audio = `592.597333 s` (różnica 4.7 ms, idealne wyrównanie kontenera).
2. **Multi-File Boundary Source Switch (`GX010114` $\rightarrow$ `GX010115`):**
   - Test na łączeniu klipów (300 klatek): **PASS**.
   - Komunikat: `[AMD DIRECT MUX] source_switch 1->2 global_frame=150`.
   - Wynik: 300 odebranych klatek, 0 zgubionych ramek, brak zacięć strumienia.
3. **Cancel Safety:**
   - Test przerwania renderu (`cancel_event.set()` po 2.0 s): **PASS**.
   - Czyste przerwanie w 2.121 s, zerwanie potoku bez wiszących procesów, brak blokad na plikach DLL i Named Pipe.

---

## 10. Audyt Zmian w Repozytorium (Git Audit)

Wszystkie zmiany zostały zrealizowane wyłącznie w obrębie backendu AMD i są całkowicie izolowane od innych backendów:

```text
git diff --stat:
 native/d3d11_amf_pipeline/src/d3d11_amf_encoder.cpp |  57 ++--
 native/d3d11_amf_pipeline/src/d3d11_amf_encoder.h   |   3 +
 native/d3d11_amf_pipeline/src/telem_amd_native.cpp  | 291 ++++++++++++++-------
 src/ffmpeg/amd_native_exporter.py                   | 167 +++++++++++-
 4 files changed, 392 insertions(+), 127 deletions(-)
```

- `git diff --check native/`: **PASS (zero błędów i ostrzeżeń)**.
- `cmake --build`: **RC: 0 (czysta kompilacja MinGW64 bez błędów)**.

---

## 11. Final Methodology Correction & Verdict

### 1. ACTUAL TEST MACHINE:
**AMD Ryzen 7 7730U with Radeon Graphics** (8C/16T, 15W cTDP, Device ID `0x15E7`, sterownik `31.0.21925.1001`). Oznaczenie `5825U` było błędem redakcyjnym wstępnego szkicu raportu.

### 2. ASYNC2 FULL-RENDER PERFORMANCE GAIN:
**+0.49% Render FPS** (41.512 vs 41.311 FPS) / **+0.61% Effective FPS** (40.838 vs 40.589 FPS), skrócenie łącznego czasu o **2.67 s**.  
*(W kontrolowanym porównaniu 3000f z nowym ścisłym SYNC1 zysk wynosi +8.84% — 42.434 vs 38.986 FPS).*

### 3. ASYNC2 ARCHITECTURAL VALUE:
**MAJOR WIN.** Całkowita eliminacja patologii busy-spin: zredukowano liczbę ponowień `AMF_INPUT_FULL` z ~69.4 miliona do **0**, a liczbę alokacji COM z ~69.4 miliona do **17 760** (dokładnie 1 na klatkę). Wątek renderujący nie spala już 100% czasu rdzenia CPU w jałowej pętli.

### 4. MEASURED REAL PIPELINE CEILING:
**~42–43 FPS** (~23.4 ms/klatkę) **na tej konkretnej maszynie i konfiguracji testowej**. Dowodzi tego wynik Minimal HUD (42.759 FPS) różniący się od Full Production HUD (42.434 FPS) o zaledwie 0.76%.

### 5. SHOULD AMD_QUEUE_DEPTH=2 BECOME DEFAULT?
**YES.** Spełnione są wszystkie 4 kryteria produkcyjne:
- A. Correctness PASS (17 760/17 760 ramek, PTS monotonic, A/V parity).
- B. Multi-file & Cancel PASS.
- C. Brak regresji pełnego renderu (lekki zysk +0.49% / -2.67 s).
- D. Pełna eliminacja busy-spin / burzy alokacji COM.

### 6. IS FURTHER HUD OPTIMIZATION LIKELY TO IMPROVE FPS?
**MARGINAL.** Ponieważ kompozycja HUD w trybie ASYNC Depth 2 zajmuje ~19 ms (mediana) i odbywa się w całości równolegle w cieniu sprzętowego kodowania VCN zajmującego ~20–22 ms, dalsza optymalizacja HUD CPU przyniesie marginalny lub zerowy zysk na ogólny FPS renderowania, dopóki ograniczeniem pozostaje sprzętowy blok enkodera/dekodera VCN.
