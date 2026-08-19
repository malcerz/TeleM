# AGENT.md — TeleM

## 1. Rola agenta

Pracujesz nad projektem **TeleM** — aplikacją do nakładania telemetrii na wideo (GoPro/FIT/GPX), z podglądem i finalnym renderingiem. Projekt ma działać na **NVIDIA / AMD / Intel**, a aktualnie rozwijana i profilowana ścieżka produkcyjna to przede wszystkim:

- **AMD_NATIVE_D3D11**
- D3D11VA hardware decode
- D3D11 VideoProcessor
- AMD AMF HEVC encode
- GPU HUD / map / gauge / chart paths
- Python/Pillow jako część CPU preparation / fallback

Pracuj jak inżynier utrzymujący istniejący system, a nie jak autor nowego projektu.

Najważniejsza zasada:

> **Correctness najpierw, performance potem. Nie upraszczaj kontraktów danych ani z-order tylko po to, aby przyspieszyć rendering.**

---

## 2. Sposób pracy

### Zawsze najpierw audyt

Przed zmianą:

1. znajdź dokładny root cause,
2. wskaż plik/funkcję/kontrakt,
3. sprawdź wszystkie powiązane ścieżki runtime,
4. dopiero potem implementuj najmniejszą poprawkę.

Nie wykonuj dużego refaktoru, jeśli problem można naprawić lokalnie.

### Pracuj etapami

Każdy etap ma mieć jasno ograniczony zakres.

Jeżeli zadanie mówi:

- `READ-ONLY AUDIT` — nie zmieniaj kodu,
- `IMPLEMENTATION` — zmieniaj tylko zakres potrzebny do danego etapu,
- `RUNTIME VALIDATION` — wykonaj rzeczywisty test pipeline'u, a nie tylko test jednostkowy.

Po zakończeniu etapu przygotuj raport:

```text
RAPORT_TELEM_ETAP_<nr>.md
```

i **zatrzymaj się**. Nie przechodź samodzielnie do kolejnego etapu.

### Nie wykonuj scope creep

Bez wyraźnego polecenia nie:

- przebudowuj GUI,
- nie zmieniaj layoutu użytkownika,
- nie dodawaj nowych pól telemetrycznych,
- nie zmieniaj ABI native tylko „dla porządku”,
- nie poprawiaj starych niezwiązanych testów,
- nie zmieniaj algorytmów synchronizacji danych,
- nie zmieniaj encoder settings,
- nie optymalizuj obszaru, który nie został jeszcze zmierzony.

---

## 3. Repozytorium i środowisko

Typowa lokalizacja projektu:

```text
C:\_DEV\TeleM
```

Platforma:

```text
Windows 11
Python
FFmpeg
PyQt
Pillow
D3D11
AMD AMF
```

Aktualny sprzęt referencyjny AMD:

```text
CPU: AMD Ryzen 5 5500U — 6C/12T
GPU: AMD Radeon(TM) Graphics
```

Aktualny materiał referencyjny:

```text
Video/GX030120.MP4
Video/Poranna_jazda_na_rowerze.fit
```

Wideo:

```text
3840×2160
30000/1001 FPS
HEVC
~180 s
5395 real decoded frames
```

Produkcja AMD:

```text
backend        AMD_NATIVE_D3D11
decoder        GPU_HUD_D3D11VA
VP             D3D11 VideoProcessor
encoder        AMD AMF HEVC
telemetry      PRECOMPUTED
map            GPU
gauge          GPU
map order      CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
```

---

## 4. Fundamentalne kontrakty telemetryczne — NIE ŁAMAĆ

### 4.1. Source ownership

Źródło ustawione dla wskaźnika jest autorytatywne:

```text
GPMF -> wyłącznie GPMF
FIT  -> wyłącznie FIT
GPX  -> wyłącznie GPX
```

Zakaz silent fallback:

```text
FIT -> GPMF
GPX -> GPMF
```

Jeżeli wybrane źródło nie ma danych:

```text
current = None
history = empty
```

### 4.2. Missing vs zero

Kontrakt:

```text
missing sensor/data = None
real zero           = 0.0
```

Presentation:

```text
None -> unavailable / hidden
0.0  -> prawdziwa, widoczna wartość
```

Nie używaj konstrukcji typu:

```python
value or 0.0
```

dla telemetrii.

### 4.3. STEP lookup

Dla pól typu sample-and-hold:

```text
value = próbka o największym timestamp <= target_dt
```

Przykład:

```text
target < first sample -> None
target == sample      -> exact sample
between samples       -> previous sample
after last sample     -> last sample
```

Implementacja opiera się na semantyce `bisect_right(...)-1`.

Nie zmieniaj tego na strict `< target_dt`.

### 4.4. Chart history

Historia wykresu:

```text
sample.timestamp <= target_dt
```

Nie może zawierać przyszłych próbek.

Nie tnij historii po:

```text
frame_index / fps
current_position * len(samples)
```

jeżeli dostępne są prawdziwe timestampy.

### 4.5. Linear fields

Nie zmieniaj istniejącej interpolacji dla:

```text
speed
altitude
distance
```

bez osobnego zadania.

---

## 5. GPMF — ustalone kontrakty

### GPS9

GPS9 zawiera pełny rzeczywisty czas UTC:

```text
lat
lon
alt
speed2d
speed3d
days
secs
DOP
fix
```

`days + secs` jest źródłem prawdziwego czasu GPS.

Nie syntetyzuj czasu GPS z:

```text
creation_time + index * 0.1
```

### Cadence sensorów

Nie zakładaj globalnego:

```text
GPMF = 10 Hz
```

Różne strumienie mają różne częstotliwości.

Przykładowo:

```text
GPS9           ~10 Hz
ISO/SHUT       ~FPS kamery
TMPC           ~1 Hz
ACCL/GYRO      ~198.7 Hz
```

### ACCL/GYRO

Aktualnie:

- timestampy pochodzą z GPMF,
- orientacja została ustalona,
- SCAL jest obsłużony,
- magnitude = sqrt(x²+y²+z²),
- wartości pozostają float,
- brak smoothingu,
- source = GPMF only.

Nie zmieniaj tego bez osobnego zadania.

---

## 6. Geometry / size / text — kontrakt zamknięty

Historyczny problem:

```text
size = 10
font_size = 2.5
```

oraz synchronizacja GUI powodowała skok fontu.

Aktualny kontrakt:

- canonical text geometry = `font_size`,
- legacy `size` nie może nadpisywać `font_size`,
- zapis/reload jest stabilny,
- preview/final geometry jest zgodne.

Nie wracaj do starej semantyki `size`.

Nie zmieniaj:

```text
bbox
font_size
anchor
position
rotation
```

bez osobnego zadania.

---

## 7. AMD map z-order — kontrakt zamknięty

Aktualny ordered compositor:

```text
CPU_BELOW_MAP
-> GPU_MAP
-> CPU_ABOVE_MAP
```

Insertion order layoutu jest źródłem prawdy.

Nie rozwiązuj problemów przez:

```text
move track_map to end
sort indicators by type
always draw map last
```

### Native clear lifecycle

Poprawna kolejność:

```text
base VP
-> clear previous CPU_ABOVE_MAP bbox
-> CPU_BELOW_MAP / charts
-> GPU gauge
-> GPU map
-> current CPU_ABOVE_MAP
-> final HUD
```

Nie przenoś destructive clear za GPU map.

### AFTER indicators

Element po `track_map` musi być nad mapą.

Jeżeli element po mapie ma:

```text
value=None
```

nie powinien być rasteryzowany.

Jeżeli ma:

```text
0.0
```

jest widoczny.

### GPU chart / gauge after map

Jeżeli specjalny GPU element po mapie nie może zachować z-order:

```text
correctness > GPU
```

Może zostać skierowany do `CPU_ABOVE_MAP`.

---

## 8. Stan optymalizacji AMD po ETAPIE 8C

### Zamknięte

ETAP 8C usunął pełnoklatkowy alpha scan `CPU_ABOVE_MAP`.

Stary path:

```python
above_full.getchannel("A").getbbox()
above_full.crop(alpha_bbox)
```

skanował:

```text
3840 × 2160 = 8,294,400 px/frame
```

Nowy path:

```text
existing compositor bboxes
-> rendered bbox union
-> conservative pad=64
-> candidate crop
-> local alpha getbbox()
-> final compact crop
```

Typowy realny candidate:

```text
559×190
```

Typowy final bbox:

```text
~431×62
```

Redukcja alpha-scan:

```text
8,294,400 px -> 106,210 px
~98.7%
```

Timing:

```text
above_bbox_crop BEFORE:
median ~10.7–11.1 ms
p95    ~19 ms

AFTER:
median ~0.25 ms
p95    ~0.8–1.1 ms
```

### Wynik end-to-end po 8C

3 × 900 frames:

```text
28.073 FPS
28.349 FPS
27.786 FPS
median = 28.073 FPS
dropped = 0
```

To jest poprawa około +4.9% względem mediany 8B, ale nadal daleko od 60 FPS.

### Ważne

Pełny canvas `compose_overlay()` nadal jest tworzony.

ETAP 8C usunął:

```text
full-frame alpha scan
```

ale NIE usunął:

```text
full-frame CPU ABOVE canvas allocation/clear/composition
```

To jest potencjalny następny temat, ale musi zostać najpierw zmierzony.

---

## 9. Profilowanie — zasady

Nie ufaj nazwie bucketu bez sprawdzenia zakresu timera.

Historyczny przykład:

```text
chart_upload
```

okazał się nie chart uploadem, tylko:

```text
CPU_ABOVE_MAP compose
+
full-frame alpha bbox/crop
```

Realny chart upload dla workloadu GX030120 wynosił:

```text
0 ms
```

Dlatego przed optymalizacją zawsze:

1. znajdź `timer start`,
2. znajdź `timer stop`,
3. wypisz wszystko w jego zakresie,
4. sprawdź overlap z innymi timerami,
5. dopiero wtedy interpretuj wynik.

### Throughput vs latency

Nie sumuj ślepo timingów CPU/GPU.

Rozróżniaj:

```text
serial CPU work
GPU async submit
AMF async queue
blocking wait
wall-clock throughput
```

### Mux

Oddziel:

```text
video/render wall
audio mux wall
total wall
```

Mux po renderze nie jest per-frame bottleneckiem.

---

## 10. Aktualny AMD performance baseline

Referencja po etapach 7D–8C:

- HW decode: YES
- AMF: 0 dropped
- GPU map: active
- GPU gauge: active
- production GPU->CPU frame readback: NO
- telemetry per-frame: bardzo mały koszt
- encoder nie jest jedynym limiterem
- frontend bez AMF osiągał około 29.7 FPS
- pipeline ma znaczną serialną pracę CPU przed native/AMF

ETAP 8A przed 8C pokazał orientacyjnie:

```text
decode availability       ~2.1 ms avg
telemetry                 ~0.19 ms avg
compose_overlay           ~5+ ms avg
native process_frame      ~2.5 ms avg
map preparation/upload    ~2 ms
gauge preparation/upload  ~1.5 ms
```

Po ETAPIE 8C należy wykonać nowy pomiar, zanim uznasz kolejny obszar za dominujący bottleneck.

---

## 11. Testy

Po ETAPIE 8C pełna suite:

```text
336 passed
3 failed
17 skipped
```

Znane, wcześniejsze failure'y:

```text
tests/test_amd_native_etap4.py
tests/test_qp_analyzer.py
tests/test_render_tab.py
```

Nie naprawiaj ich bez osobnego polecenia.

Nie zmieniaj poprawnego ABI/runtime tylko po to, aby zazielenić stary test.

### Ważne zestawy regresji

Przy zmianach AMD uruchamiaj zależnie od zakresu m.in.:

```text
tests/test_gpu_compositor.py
tests/test_map_sync.py
tests/test_amd_native_ordered_map.py
tests/test_amd_native_ordered_map_clear.py
tests/test_amd_native_above_dirty_bbox.py
tests/test_etap6b_contract.py
tests/test_etap6d_chart_history.py
tests/test_etap6e_step_lookup.py
```

Zawsze sprawdzaj brak nowych failure'ów.

---

## 12. Real runtime jest ważniejszy niż sam unit test

Dla GPU/native wymagany jest rzeczywisty test na materiale:

```text
GX030120.MP4
```

Samo:

```text
pytest = green
```

nie wystarcza do zamknięcia problemu runtime.

Dla zmian w D3D11/AMF sprawdzaj:

```text
requested
decoded
processed
VP
AMF submitted
AMF output
dropped
HW decode proof
AMD map path
AMD gauge/chart paths
```

Przy testach dłuższych:

```text
900 frames / 30 s
```

jest dobrym minimum.

Dla istotnych zmian lifecycle/z-order, jeśli 30 s przechodzi, warto wykonać cały materiał ~180 s.

---

## 13. Raport końcowy każdego etapu

Raport powinien zawierać minimum:

```text
A. Root cause
B. Implementation / audit result
C. Files/functions
D. Runtime contract
E. Real-material validation
F. Performance BEFORE/AFTER (jeśli dotyczy)
G. Tests
H. Regressions
I. Remaining issues
J. Final classification
```

Oddziel zawsze:

```text
CONFIRMED
SUSPECTED
OUT OF SCOPE
```

Nie przedstawiaj hipotezy jako faktu.

---

## 14. Git / bezpieczeństwo pracy

Przed zmianami:

```text
git status
git diff
```

Nie nadpisuj niezwiązanych zmian użytkownika.

Nie wykonuj:

```text
git reset --hard
git clean -fd
```

bez wyraźnego polecenia.

Nie commituj, nie pushuj i nie merguj bez polecenia użytkownika.

Jeżeli zmieniasz native DLL:

- zbuduj właściwy produkcyjny target,
- nie kieruj się historycznym/nieużywanym targetem,
- potwierdź używany DLL/ABI w runtime.

---

## 15. Styl pracy z użytkownikiem

Użytkownik pracuje etapami i oczekuje technicznych, jednoznacznych raportów.

Nie pisz ogólników typu:

```text
"prawdopodobnie jest szybciej"
```

Zamiast tego:

```text
BEFORE median = ...
AFTER median  = ...
delta         = ...
```

Jeżeli nie masz pomiaru:

```text
NOT MEASURED
NOT INSTRUMENTED
NOT AVAILABLE
```

Nie zgaduj.

---

## 16. Co robić na początku nowego zadania

1. Przeczytaj to `AGENT.md`.
2. Przeczytaj aktualny prompt etapu.
3. Sprawdź `git status`.
4. Zlokalizuj wskazane funkcje.
5. Odtwórz baseline.
6. Dopiero wtedy działaj.
7. Po wykonaniu testów napisz raport `RAPORT_TELEM_ETAP_<nr>.md`.
8. Zatrzymaj się.

---

## 17. Aktualny punkt projektu

Ostatni zakończony etap:

```text
ETAP 8C — COMPLETE
```

Potwierdzone:

```text
CPU_ABOVE_MAP full-frame alpha scan = eliminated
pixel parity = PASS
ordered map/clear lifecycle = PASS
3×900 frames = PASS
AMF dropped = 0
full suite = 336 passed / 3 failed / 17 skipped
```

Najbliższy sensowny temat, jeśli użytkownik go zleci:

```text
audyt kosztu tworzenia / clear / compose pełnego CPU_ABOVE_MAP canvas
oraz region-aware composition
```

Ale **nie rozpoczynaj go samodzielnie**.
