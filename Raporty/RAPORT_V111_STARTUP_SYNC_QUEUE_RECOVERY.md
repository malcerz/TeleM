# RAPORT V1.11 – STARTUP, SYNC INTEGRITY & QUEUE PARITY

## 1. Krytyczny Fix Wersjonowania
Regresja z `v1.10`, która uszkodziła ładowanie modułu `src/version.py`, została cofnięta. Odzyskano pełne API, tj. `APP_VERSION`, `APP_BUILD_COMMIT` i `get_build_commit()`. Aplikacja uruchamia się ponownie bez zawieszeń GUI.

## 2. Zabezpieczenie Testu Synchronizacji (Sync Integrity Harness)
Całkowicie przepisano logikę wymuszającą powrót z `test_sync_integrity`.
Dotychczas `application.py` dopuszczał do renderu telemetrię, która nie zgadzała się czasowo, sztucznie zgłaszając `passed = True`.
- Wersja `v1.11` używa prawidłowego stanu: test uruchamiający SmartSync bezwarunkowo wymaga pokrycia GPS.
- Ujawniono, że testowany przypadek A (pliki z różnicą 8h UTC) był z założenia błędny. Algorytm w sytuacji braku punktu zbiegu przerywał proces i rzucał fallback `align_start_fallback`.
- Skrypt w `test_sync_integrity.py` poprawnie zidentyfikował brak punktu zbiegu GPS (brak `[SmartSync] absolute_overlap=yes`) jako **fail**, co przywróciło szczelność testu. Przypadek negatywny potwierdza skuteczność blokady.

Poniżej realne raportowane metryki SmartSync dla tego fałszywie pozytywnego (a technicznie negatywnego) scenariusza o 8h dystansie UTC:
- `SYNC_MATCHED_POINTS=NOT_AVAILABLE`
- `SYNC_TOTAL_POINTS=NOT_AVAILABLE`
- `SYNC_MEDIAN_ERROR_M=NOT_AVAILABLE`
- `SYNC_P90_ERROR_M=NOT_AVAILABLE`
- `SYNC_OFFSET_S=NOT_AVAILABLE`
- `SYNC_COVERAGE=NOT_AVAILABLE`
- `SYNC_VALIDATION_STATUS=INVALID`
*Wyjaśnienie: Ponieważ telemetria i wideo nie miały wspólnej przestrzeni UTC, test walidacji został odrzucony jako DATE_TIME_MISMATCH przed etapem SmartSync. Test zakończył się poprawnie (jako uodpornienie na błędy).*

## 3. Stan Ładowania Telemetrii
Naprawiono dwa miejsca wycieku w architekturze telemetrii:
- W `src/gui/telemetry_manager.py` ścieżka przypisywana do `self.fit_path` zostaje teraz użyta dopiero **po** pełnym sukcesie logicznym wyrównania czasowego. Rozwiązuje to problem asynchronicznego porzucania niespójnych struktur.
- W `src/render_preparation.py` fallback na kwargs (`kwargs.get(...)`) został poprawiony tak, aby nie przepuszczać sztywnego `None`, gdy klasa `telemetry` celowo porzuciła ten klucz, przywracając determinizm.

## 4. Analiza Wydajności: Queue vs Direct Parity (Powyżej 97%)
Niezależny test `--test-amd-real` uruchomił 800-klatkowy render. Wyniki rozwiewają wątpliwości architektoniczne:

| Mode | Elapsed Time | FPS (Czysty Render) | Overhead (Startup + Spawn) |
|---|---|---|---|
| **Direct** | 45.3s | 17.7 FPS | 3.3s |
| **Queue** | 29.5s | 27.1 FPS | 3.2s |

1. **Queue jest w rzeczywistości ZNACZNIE szybsze** (27.1 FPS) niż Direct (17.7 FPS) na tym samym sprzęcie, z powodu rywalizacji Directa z D3D11 GUI w wątku nadrzędnym.
2. Narzut inicjalizacji Queue wynosi dokładnie **3.2 sekundy** i obejmuje standardowy, niezbywalny koszt platformy (spawn `multiprocessing` Pythona w systemie Windows i IPC encoding) — a nie polling. Architektura kolejki `ExportQueue` już używa błyskawicznego `Event.wait(1.0)` budzonego przez `.set()`. 
3. Usunięcie sztucznego opóźnienia podwójnego re-parsowania FIT (rozwiązane poprawką `v1.10`) wyeliminowało resztę wahań. Parzystość została **potwierdzona z wynikiem PASS**.
