# TeleM — FINAL NVIDIA PASS: zamrożony baseline produkcyjny

Data: 2026-08-20. Audyt wykonano na aktualnym repozytorium. Ten etap zamyka
bieżącą serię optymalizacji NVIDIA; po raporcie nie kontynuuję kolejnego etapu.

## A. Zakres i zamrożona konfiguracja

Zweryfikowany baseline:

```text
GX030120.MP4 + Popoludniowa_jazda_na_rowerze_solar_battery.fit
5400 klatek, 29.970 FPS, 3840x2160 output
workers=4
MAX_IN_FLIGHT=8
preview=ON
DIRECT_REGION + MULTI_REGION_ATLAS
MAX5 / GRID16
atlas=1900x762, 5 regionów
zero-copy SHM=ON
writer=BufferedWriter.write(memoryview(SHM))
NVDEC + CUDA + overlay_cuda + HEVC NVENC
```

Nie zmieniano NVENC/NVDEC, 8-bit pipeline, SmartSync, telemetry precompute,
źródeł FIT, chart semantics, gauge, atlas planner ani Direct-Region.

W normalnej ścieżce usunięto wybór eksperymentalnych writerów `raw`/`os.write`/
unbuffered. Audyt pozostaje opt-in przez `TELEM_PIPELINE_AUDIT=1`; poza audytem
writer nie tworzy timestampów, histogramów, pomiarów kolejki ani diagnostycznych
struktur per frame. `TELEM_AUDIT_MAX_IN_FLIGHT` działa wyłącznie z audytem.
Ścieżka GUI NVIDIA wymusza zweryfikowane cztery workery, więc ustawienie presetów
nie wybiera przypadkowo niezmierzonej liczby workerów.

## B. Zmiany w tym etapie

Zmiany finalnego passu:

- `src/ffmpeg/streaming.py`: produkcyjny writer ma jeden prosty fast path
  `BufferedWriter.write(memoryview)`, zwalnia pamięć po zapisie; rozbudowane
  pomiary są odseparowane do trybu audytu;
- `src/gui/qt/_mixins/render_mixin.py`: NVIDIA używa stale `workers=4`;
- `tests/test_etap5h_writer_queue.py`: test dotyczy produkcyjnego writera i
  zwalniania slotu, bez usuniętych eksperymentalnych trybów;
- `AGENTS.md`: dodano sekcję zamrożonego baseline’u NVIDIA;
- `Raporty/RAPORT_NVIDIA_FINAL_BASELINE.md`: niniejszy raport.

Nie zmieniano żadnego modułu `src/indicators` w tym etapie.

## C. Kontrola zero-copy i lifecycle

Końcowy audyt 5400 klatek (`scratch/etap5f_final_audit.json`) wykazał:

```text
zero_copy frames       = 5400 / 5400
fallback_copy_frames   = 0
writer                 = BufferedWriter, _io.BufferedWriter
frames_written         = 5400
write_calls            = 5400
requested bytes        = 31,272,480,000
returned bytes         = 31,272,480,000
partial writes         = 0
preview updates        = 108
preview frequency      = 5.09 Hz
```

Każdy audytowany frame ma kolejność:

```text
worker render -> ordered output -> memoryview SHM
-> BufferedWriter.write -> memoryview.release -> shm_pool.release
```

Nie wykryto `BufferError`, wiszących memoryview, przedwczesnego zwolnienia slotu,
zajętych slotów po zamknięciu ani pozostawionego writera. FFmpeg zakończył się
poprawnie; `ffprobe` końcowego pliku podał `nb_frames=5400` i duration
`180.180000` s.

## D. Poprawność obrazu i semantyka wykresów

### D1. Pixel parity

Istniejący POC zero-copy został uruchomiony ponownie na checkpointach
`0, 10%, 25%, 50%, 75%, 90%, 5000, 5200, 5399`:

```text
max_diff=0
different_bytes=0
```

ROT180 został uruchomiony ponownie dla `0, 25%, 50%, 75%, 100%`:

```text
max_diff=0
different_pixels=0
```

FIT zawierał i poprawnie wykrył `battery_pct` oraz `solar_pct`; katalog wykrył
18 pól z całej aktywności, nie z pierwszego rekordu. W aktualnym referencyjnym
layoucie `fit_battery_text` jest phantom/bez widocznego contentu i został
konserwatywnie wyłączony z transportu. To nie jest brak pola FIT: próbki pola są
dostępne w dataset/registry. Nie zmieniano dynamicznego discovery ani renderera
indicatorów.

### D2. Charts

Semantyka zatwierdzona w ETAPIE 5E.6 i ponownie objęta testami ETAP5 pozostaje:

- zakres historii: początek aktywności → aktualny czas, bez przyszłych próbek;
- `cadence=0` jest realnym zerem i pozostaje widoczne;
- `None` pozostaje missing i nie jest zamieniane na `0`;
- `None` i długa luka FIT rozcinają segment;
- historia sprzed luki pozostaje widoczna;
- HR average zachowuje dotychczasową semantykę;
- cadence i HR nie wymagają identycznych timestampów.

Ostatni zaakceptowany mikrobenchmark chartów z ETAPU 5E.6, `avg / median / p95`
w ms, bez zmian w tym finalnym passu:

| Chart | render avg / median / p95 | pełny chart avg / median / p95 |
|---|---:|---:|
| cadence | 0.540 / 0.525 / 0.691 | 1.315 / 1.280 / 1.781 |
| HR | 0.543 / 0.519 / 0.704 | 1.366 / 1.319 / 1.986 |

Największym hotspotem CPU pozostaje render chartów, w szczególności pełny
`fit_heart_rate_text`; finalny pass nie optymalizował go dalej.

## E. Benchmark produkcyjny — 3 eksporty, audyt OFF

Każdy run miał identyczny materiał, layout, FFmpeg, NVENC, workers=4, MIF=8,
preview ON, Direct-Region, Multi-Region Atlas, MAX5/GRID16 i zero-copy ON.

| Run | FRAME_PIPELINE FPS | REAL_EXPORT FPS | wall time | preview |
|---:|---:|---:|---:|---:|
| 1 | 282.4 | 259.2 | 20.832 s | 5.18 Hz / 108 |
| 2 | 280.3 | 258.1 | 20.920 s | 5.16 Hz / 108 |
| 3 | 283.6 | 260.7 | 20.712 s | 5.21 Hz / 108 |
| **mediana** | **282.4** | **259.2** | **20.832 s** | **5.18 Hz** |

Każdy log potwierdzał:

```text
HUD producer: DIRECT_REGION
HUD mode: MULTI_REGION_ATLAS
HUD atlas: 1900x762
workers: 4
MAX_IN_FLIGHT: 8
```

Nie porównuję mechanicznie tych wartości z wcześniejszymi runami audytowymi:
audyt ma dodatkowy koszt instrumentacji. Największym ograniczeniem pozostaje
CPU raw RGBA pipe / FFmpeg backpressure, nie workerowy transfer SHM.

## F. Końcowy audyt ON

Po trzech eksportach produkcyjnych wykonano jeden eksport kontrolny z
`TELEM_PIPELINE_AUDIT=1`. Wyniki główne:

```text
FRAME_PIPELINE metadata = 281.6 FPS
REAL_EXPORT metadata    = 259.1 FPS
frames                  = 5400
zero-copy               = 5400 / 5400
fallback                = 0
writer                  = BufferedWriter
writes                  = 5400
preview                 = 108 updates, 5.09 Hz
```

Nie zaobserwowano błędów lifecycle ani różnicy liczby klatek. Audyt potwierdził
również, że `worker_shm_copy=0` dla wszystkich klatek.

## G. Testy

Zestaw NVIDIA/ETAP5:

```text
170 passed
```

Ponowna kontrola POC zero-copy i ROT180: zaliczona, wyniki parity `0/0`.

Ogólny zestaw bez znanych testów AMD DLL oraz `test_mp4_inspector.py`:

```text
501 passed, 23 skipped, 3 failed
```

Trzy błędy są środowiskowe i niezwiązane z finalnym passu: dwa AMD native
smoke/restart wymagają `native/d3d11_amf_pipeline/bin/telem_amd_native.dll`, a
`test_encoder_fallback_on_unsupported_gpu` zakłada środowisko AMD, podczas gdy
test wykonano na NVIDIA. Zgodnie z kontraktem nie naprawiano starego AMD/Qt.

## H. Wnioski końcowe i przyszły marker

1. Baseline NVIDIA jest zamrożony i produkcyjnie zweryfikowany.
2. Direct-Region pozostał aktywny; nie przywrócono FULL_FRAME transportu.
3. Zero-copy SHM działa dla 100% klatek, fallback wyniósł 0.
4. Preview działa podczas finalnego eksportu, aktualizuje się około 5 FPS i nie
   wykonuje pełnego kosztownego compositingu dla każdej klatki.
5. `cadence=0`, `None`, gap splitting, activity-start prefix i HR semantics nie
   zostały naruszone.
6. Nowy produkcyjny medianowy wynik to **282.4 FRAME_PIPELINE FPS** oraz
   **259.2 REAL_EXPORT FPS**.
7. Największy aktualny hotspot to **raw RGBA pipe / FFmpeg backpressure**;
   drugim istotnym kosztem CPU jest chart HR.
8. Jeśli kiedyś rozpocznie się następna duża seria NVIDIA, jej markerem będzie
   eliminacja CPU raw RGBA pipe przez transport GPU-native. Nie jest to część
   tego etapu i nie zostało zaimplementowane.

Odpowiedzi jednoznaczne:

- Czy baseline jest zamrożony? **Tak.**
- Czy Direct-Region jest aktywny? **Tak, z Multi-Region Atlas.**
- Czy zero-copy obejmuje wszystkie klatki? **Tak, 5400/5400; fallback 0.**
- Czy preview działa bez istotnej ścieżki CPU per frame? **Tak, około 5.18 Hz.**
- Czy zapisano 5400 klatek? **Tak, ffprobe potwierdził 5400.**
- Czy zmieniono chart/gauge/telemetrię? **Nie.**
- Czy największym kolejnym ograniczeniem jest pipe? **Tak.**
- Co jest następnym markerem, jeśli kiedyś wrócimy do NVIDIA? **GPU-native
  transport zamiast CPU raw RGBA pipe; bez implementacji teraz.**

## Zmienione pliki w FINAL NVIDIA PASS

- [AGENTS.md](../AGENTS.md)
- [src/ffmpeg/streaming.py](../src/ffmpeg/streaming.py)
- [src/gui/qt/_mixins/render_mixin.py](../src/gui/qt/_mixins/render_mixin.py)
- [tests/test_etap5h_writer_queue.py](../tests/test_etap5h_writer_queue.py)
- niniejszy raport.

