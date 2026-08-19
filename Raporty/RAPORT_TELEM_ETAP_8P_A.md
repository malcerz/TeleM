# TeleM — RAPORT ETAP 8P-A: Rzeczywisty Czas PRECOMPUTED w GUI Export

## Cel Etapu
Ustalić, czy faza `PRECOMPUTED build` rzeczywiście powoduje zauważalny czas oczekiwania przed rozpoczęciem renderowania w realnym GUI export oraz zmierzyć precyzyjnie czas całego potoku eksportu od momentu kliknięcia przycisku Export (`export_start`) aż do ukończenia remuksu (`export_end`).

---

## 1. Architektura Pomiarowa Milestone Timers

W [src/ffmpeg/amd_native_exporter.py](file:///c:/_DEV/TeleM/src/ffmpeg/amd_native_exporter.py) dodano precyzyjne znaczniki czasowe `time.perf_counter()` rejestrujące 9 kluczowych punktów milowych eksportu:

```text
[EXPORT_CLICK / export_start] (t = 0.000 ms)
       │
       ▼ (inicjalizacja struktur, DLL, parser layoutu)
[PRECOMPUTE_BEGIN]
       │
       ▼ (budowa cache'u TelemetryFrameCache w RAM)
[PRECOMPUTE_END]
       │
       ▼ (inicjalizacja Media Foundation D3D11VA, otwarcie strumienia)
[FIRST_FRAME_BEGIN]
       │
       ▼ (renderowanie HUD klatki 0 + submit do AMF)
[FIRST_FRAME_ENCODED]
       │
       ▼ (pętla renderowania wideo: klatki 1 .. N-1)
[VIDEO_RENDER_END]
       │
       ▼ (flush AMF, zwolnienie D3D11)
[MUX_BEGIN]
       │
       ▼ (remux kontenera MP4 z audio FFmpeg)
[MUX_END]
       │
       ▼
[EXPORT_END]
```

Zdefiniowano metryki podsumowujące:
- `precompute_build_ms`: czas budowy cache'u telemetrii (`PRECOMPUTE_END - PRECOMPUTE_BEGIN`).
- `delay_export_to_first_frame_ms`: opóźnienie od startu do zakodowania 1. klatki (`FIRST_FRAME_ENCODED - export_start`).
- `video_render_wall_ms`: czas renderowania samego wideo (`VIDEO_RENDER_END - FIRST_FRAME_BEGIN`).
- `mux_wall_ms`: czas remuksu audio/wideo (`MUX_END - MUX_BEGIN`).
- `TOTAL_FROM_EXPORT_START_ms`: całkowity czas od kliknięcia Export (`EXPORT_END - export_start`).
- `RENDER FPS`: $\frac{\text{frames}}{\text{video\_render\_wall\_s}}$.
- `USER EFFECTIVE FPS`: $\frac{\text{frames}}{\text{TOTAL\_FROM\_EXPORT\_START\_s}}$.

---

## 2. Pomiary Porównawcze A/B (1131 Klatek, 4K, `GX020079.mp4`)

Pomiary wykonano w identycznych warunkach sprzętowych (AMD Radeon RX 7900 XTX, D3D11VA + GPU HUD + AMF HEVC) na materiale referencyjnym 1131 klatek:

### Tabela Punktów Milowych (Wall-Clock Milestones od `export_start = 0.000 ms`)

| Punkt Milowy | PRECOMPUTED | REFERENCE | Różnica ($\Delta$) |
|---|---:|---:|---:|
| `export_start` | $0,000\text{ ms}$ | $0,000\text{ ms}$ | $0,000\text{ ms}$ |
| `PRECOMPUTE_BEGIN` | $509,075\text{ ms}$ | $410,021\text{ ms}$ | $+99,054\text{ ms}$ |
| `PRECOMPUTE_END` | **$2277,914\text{ ms}$** | $410,022\text{ ms}$ | $+1867,892\text{ ms}$ |
| `FIRST_FRAME_BEGIN` | $2277,915\text{ ms}$ | $410,023\text{ ms}$ | $+1867,892\text{ ms}$ |
| `FIRST_FRAME_ENCODED` | **$2843,242\text{ ms}$** | **$910,443\text{ ms}$** | **$+1932,799\text{ ms}$** |
| `VIDEO_RENDER_END` | $43205,850\text{ ms}$ | $42588,876\text{ ms}$ | $+616,974\text{ ms}$ |
| `MUX_BEGIN` | $43205,991\text{ ms}$ | $42589,056\text{ ms}$ | $+616,935\text{ ms}$ |
| `MUX_END` | $43850,067\text{ ms}$ | $43239,687\text{ ms}$ | $+610,380\text{ ms}$ |
| `EXPORT_END` | **$43904,060\text{ ms}$** | **$43295,998\text{ ms}$** | **$+608,062\text{ ms}$** |

---

## 3. Zestawienie Metryk Wydajnościowych

| Metryka | PRECOMPUTED | REFERENCE | Wnioski |
|---|---:|---:|---|
| **`precompute_build_ms`** | **$1768,839\text{ ms}$ ($1,77\text{ s}$)** | $0,000\text{ ms}$ | Budowa cache'u zajmuje $\sim 1,56\text{ ms}$ na klatkę w Pythonie |
| **`delay_export_to_first_frame_ms`** | **$2843,242\text{ ms}$ ($2,84\text{ s}$)** | **$910,443\text{ ms}$ ($0,91\text{ s}$)** | Oczekiwanie na pierwszą klatkę jest o $\sim 1,93\text{ s}$ dłuższe |
| **`video_render_wall_ms`** | **$40927,934\text{ ms}$ ($40,93\text{ s}$)** | **$42178,853\text{ ms}$ ($42,18\text{ s}$)** | **PRECOMPUTED renderuje wideo o $1,25\text{ s}$ szybciej** |
| **`mux_wall_ms`** | $644,076\text{ ms}$ ($0,64\text{ s}$) | $650,631\text{ ms}$ ($0,65\text{ s}$) | Identyczny czas remuksu audio |
| **`TOTAL_FROM_EXPORT_START_ms`** | **$43904,060\text{ ms}$ ($43,90\text{ s}$)** | **$43295,998\text{ ms}$ ($43,30\text{ s}$)** | Całkowity czas użytkownika: $+0,60\text{ s}$ ($+1,4\%$) dla 37 s klipu |
| **`RENDER FPS`** | **$27,634\text{ FPS}$** | **$26,814\text{ FPS}$** | Przepustowość renderowania wideo wyższa o **$+3,06\%$** |
| **`USER EFFECTIVE FPS`** | **$25,761\text{ FPS}$** | **$26,123\text{ FPS}$** | Uwzględniając build, efektywny FPS dla 37 s klipu jest porównywalny |
| **`Telemetry/frame_data` (mediana)** | **$0,040\text{ ms}$** | **$2,741\text{ ms}$** | **$68,5\times$ szybciej per-frame** |

---

## 4. Wnioski Diagnostyczne

1. **Potwierdzenie hipotezy:**
   - W trybie `PRECOMPUTED` czas od kliknięcia Export do pierwszej zakodowanej klatki wynosi **$2,84\text{ s}$** (wobec **$0,91\text{ s}$** w trybie `REFERENCE`).
   - Czas budowy cache'u (`precompute_build_ms`) dla 1131 klatek wynosi **$1,77\text{ s}$** ($> 1\text{ s}$).
2. **Bilans zysków i strat dla krótkich vs długich materiałów:**
   - Dla krótkiego materiału 37 s (1131 klatek): oszczędność na czystym renderowaniu wideo wynosi **$1,25\text{ s}$**, podczas gdy koszt wstępnej budowy cache'u to **$1,77\text{ s}$**. Bilans netto: $+0,52\text{ s}$ na korzyść `REFERENCE`.
   - Dla dłuższego materiału 180 s (5395 klatek z raportu 8O): budowa cache'u trwała **$42,88\text{ s}$**, co przy czystym zysku renderowania $\sim 6\dots 8\text{ ms/frame}$ daje zbliżony łączny czas, ale zauważalny przestój (43 sekundy) przed pojawieniem się paska postępu klatek.
3. **Źródło kosztu buildera:**
   - Builder w obecnej implementacji wykonuje pętlę w czystym Pythonie po wszystkich $N$ klatkach, wywołując pojedyncze bisekcje i interpolacje dla każdego kanału osobno.

---

## 5. Rekomendacja Architektoniczna dla Kolejnych Etapów

Zgodnie z wytycznymi promptu:
> *"Jeśli build faktycznie trwa wiele sekund i pogarsza total user wall, wtedy dopiero rekomenduj fast builder."*

Ponieważ `precompute_build_ms` wynosi **$1,77\text{ s}$** (dla 37 s) i **$42,88\text{ s}$** (dla 180 s), rekomendowana ścieżka rozwoju obejmuje:

### Rekomendowany ETAP 8P-B: Fast Vectorized Telemetry Builder (NumPy / Pre-Interpolation)
- Zamiast wywoływać 5395 razy bisekcyjne funkcje w Pythonie dla każdego kanału, wykonać wektorowe `numpy.interp` na całej osi czasu klatek naraz.
- Przewidywany czas budowy cache'u dla całego 3-minutowego wideo 5395 klatek: **$< 0,05\text{ s}$ (50 ms)** zamiast $42,88\text{ s}$.
- Wyeliminuje to całkowicie opóźnienie przed pierwszą klatką i sprawi, że `PRECOMPUTED` będzie bezwzględnie szybszy od `REFERENCE` zarówno w `RENDER FPS`, jak i w `TOTAL_FROM_EXPORT_START`.
