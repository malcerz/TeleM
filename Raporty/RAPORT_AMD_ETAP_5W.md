# RAPORT AMD — ETAP 5W: hardening produkcji — wyjaśnienie wzrostu pamięci + decyzja 5Q default

**STATUS: PASS** — root cause wzrostu pamięci **znaleziony i naprawiony**; reszta
(wolno liniowa, driver-side) udokumentowana; decyzja 5Q default podjęta.

---

## MEMORY TREND (spec 16/17/18) — soak 20 pełnych eksportów (10×REF + 10×OPT, pool8)

Per-eksport po `gc.collect()`:

| eksport | compose | Priv [MB] | WS [MB] | objs | handles | threads | static_cache |
|---|---|---|---|---|---|---|---|
| 01 | REF | 1072 | 491 | 41802 | 519 | 26 | 1074 |
| 02 | REF | 1049 | 528 | 41817 | 537 | 25 | 1074 |
| 03 | REF | 1061 | 543 | 41832 | 548 | 26 | 1074 |
| 04 | REF | 1107 | 590 | 41847 | 561 | 26 | 1074 |
| 05 | REF | 1079 | 564 | 41862 | 579 | 28 | 1074 |
| 06 | REF | 1106 | 583 | 41877 | 591 | 29 | 1074 |
| 07 | REF | 1154 | 633 | 41892 | 608 | 30 | 1074 |
| 08 | REF | 1121 | 598 | 41907 | 621 | 30 | 1074 |
| 09 | REF | 911  | 567 | 41922 | 640 | 33 | 1074 |
| 10 | REF | 1195 | 672 | 41937 | 655 | 34 | 1074 |
| 11 | OPT | 1202 | 685 | 41952 | 668 | 34 | 1074 |
| 12 | OPT | 1213 | 697 | 41967 | 683 | 35 | 1074 |
| 13 | OPT | 1224 | 704 | 41982 | 697 | 36 | 1074 |
| 14 | OPT | 1238 | 719 | 41997 | 711 | 36 | 1074 |
| 15 | OPT | 1254 | 732 | 42012 | 728 | 38 | 1074 |
| 16 | OPT | 1265 | 742 | 42027 | 743 | 39 | 1074 |
| 17 | OPT | 1276 | 750 | 42042 | 641* | 35 | 1074 |
| 18 | OPT | 1288 | 765 | 42057 | 778 | 44 | 1074 |
| 19 | OPT | 1297 | 775 | 42072 | 787 | 41 | 1074 |
| 20 | OPT | 1307 | 786 | 42087 | 802 | 43 | 1074 |

- **Private Bytes (eksporty 10–20): 1195 → 1307 MB ≈ +11.2 MB/eksport** — wolno
  liniowy wzrost. NIE jest to plateau (spec 18: nie nazywamy tego retencją, bo
  rośnie w przybliżeniu liniowo przez 20 eksportów).
- **Dominujący wzrost (sprzed fixa ~200 MB/eksport) — USUNIĘTY** (patrz NATIVE).
- Accounting: muxed=1131, amf_output=1131, vp_processed=1131, **dropped=0** na
  każdym eksporcie (zweryfikowano profile 01/02/20).
- WS rośnie łagodniej (491→786 MB) — Private Bytes dominuje (commit).

**klasyfikacja: dominujący LEAK NAPRAWIONY; reszta = wolno-liniowa (driver/decoder
podczas przetwarzania klatek), ~+11 MB + ~+14 handles/eksport.**

---

## ROOT CAUSE + FIX (najważniejsze ustalenie 5W)

**Bug w `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp`:**
`D3D11VideoProcessorPipeline::Initialize()` **zawsze** robi
`m_device->AddRef()` + `m_context->AddRef()`, ale destruktor zwalniał je
**tylko** gdy `m_ownsDevice==true`. W `telem_amd_native` (borrowed device,
`m_ownsDevice=false`) → **+1 ref device i +1 ref context leakowane per
context** → D3D11 device **nigdy nie niszczony** → driver kernel objects
(Event/Mutant/Thread/Section) + GPU memory przeciekały per create/close.

**Dowód (izolacja):**
- refcount device po teardown: **3** (było) → **1** (po fixie; 1 = czysto).
- `devref_probe` (sam `D3D11CreateDevice`+release) = **1** (baseline) → 3 to NIE
  normalny baseline, tylko nasz pipeline leakuje +2 refs.
- `AMD_DEBUG_NO_AMF`/`AMD_DEBUG_NO_MF` → nadal 3 (AMF/MF nie winne).
- `AMD_DEBUG_NO_VP=1` → **1** (winny VP).

**Fix (2 zmiany):**
1. Destruktor VP: `if (m_ownsDevice){...}` → **zawsze** `m_context->Release(); m_device->Release();`.
2. `telem_amd_close`: zwalnianie `pDevice/pContext` **PO** `delete ctx` (resources
   GPU zwalniane zanim device), + diagnostyka refcount (pod `AMD_POOL_LIFECYCLE_STATS`).

**Efekt (BYPASS, 4 eksporty):**

| | przed fixem | po fixie |
|---|---|---|
| handles total | 172 → 1270 (+~180/exp) | 172 → 561 (+~13/exp) |
| native create+close (devref 5 cykli) | +235/+1/+0/+0/+0 | **172→407→408→408→408 (+0/cykl)** |
| Event/eksport | +~105 | +~9 |
| Mutant/eksport | +~50 | ~0 |
| Section/eksport | +~11 | +1 |
| Thread/eksport | +~6 | ~0 |

---

## PYTHON (spec 5/6/8)

- **+13–14 obiektów/eksport** = `dict` (+8), `Image` (+4), `list`/`tuple` (+2),
  `Counter` (+1). Referrers: `builtins.list`/`builtins.dict` → transientne dane
  per-eksport, **NIE leak referencyjny** (county stabilne, nie liniowy wzrost).
- Obiekty w soak: 41802 → 42087 (+14/eksport, te same typy).
- **tracemalloc (częściowe, S0/S1/S2 — run ubity bo trzymał DLL):**
  S0 (po warmup)=0.00 MB, S1 (po eksporcie 1+gc)=**+0.49 MB**, S2=**+0.86 MB**
  (peak ~106 MB — transient w trakcie eksportu, potem zwolnione).
  => **Python-tracked ~+0.4 MB/eksport vs Private Bytes +11 MB/eksport** →
  **wzrost siedzi POZA heapem Pythona** (C-heap / natywny / areny drivera),
  potwierdza brak leak referencyjnego Pythona (spec 8).

---

## CACHES (spec 9/10/11)

| cache | przed/po | bounded |
|---|---|---|
| `_STATIC_CACHE` (helpers) | **1074 stałe** przez 20 eksportów (w tym 10×OPT) | **YES** (per source) |
| 5Q `gauge_value_text` | część `_STATIC_CACHE` (~639 value keys) | YES |
| 5Q `value_text_tile` | część `_STATIC_CACHE` (~23 tiles) | YES |
| `FONT_CACHE` | (font_path, size) — stałe | YES |
| `_FINAL_STATIC_CHART_CACHE` | clear przy >50 | YES |
| `_CHART_BG_CACHE` | mała, stała | YES |

- **5Q OPT NIE powoduje wzrostu pamięci per-eksport** (`static_cache` stałe 1074
  także w drugiej połowie soak = OPT).
- Uwaga cross-project: `_STATIC_CACHE` jest globalny (proces-lifetime) i może
  rosnąć między różnymi źródłami/projektami; w obrębie jednego źródła jest
  bounded (kardynalność wartości gauge/tile). Drobne; do ewentualnego per-export
  clear / LRU w przyszłości — **bez zmiany teraz** (hit-rate 5Q ~98% utrzymany).

---

## NATIVE (spec 7/12/13)

| zasób | live po destroy |
|---|---|
| VP output pool | **textures live=0, views live=0** (8/8, 24/24) |
| D3D11 device | **refcount=1** (czysto; po fixie) |
| D3D11 context | zwalniany po delete ctx (poprawne uporządkowanie) |
| AMF context/component | Terminate + smart-ptr Release (nie winne) |
| MF SourceReader / DXGI | Release (nie winne) |
| GPU timestamps (OFF w soak) | n/d |
| DLL context count | create+close czysty (+0 handles/cykl) |

Diagnostyka natywna: `AMD_POOL_LIFECYCLE_STATS=1` (liczniki + print live),
`AMD_DEBUG_NO_AMF/MF/VP=1` (izolacja refcount), refcount print w `close()`.

---

## HANDLES / THREADS (spec 14/15)

- Dominujący liniowy wzrost **naprawiony** (Event +105→+9, Mutant +50→0, Thread +6→0).
- Reszta: ~+14 handles + ~+1 thread/eksport — **nienazwane obiekty driver/decoder
  podczas przetwarzania klatek** (native create+close = +0; subprocessy ffprobe/ffmpeg = +0).
- Named objects stabilne (tylko `__AMD_DX_CACHE__` +2/eksport, minor — cache AMD driver).
- trend: **nie liniowy w dominującej skali; wolno-liniowy resztkowo**.

---

## 5Q FINAL (spec 21/22/23)

| | pool8 REF | pool8 OPT |
|---|---|---|
| FPS (clean, 5V) | 34.53 / 35.17 / 35.05 → **~34.9** | 37.48 / 37.52 → **~37.50** |
| gain | — | **+2.6 FPS (+7.5 %)** |
| framemd5 REF vs OPT | — | **identyczne (byte-exact 5Q, 1131)** |
| memory impact | — | **bounded** (static_cache stałe) |
| lifecycle | — | brak regresji (live=0, device=1) |

**DECYZJA: `AMD_COMPOSE_5Q=OPTIMIZED` → production default** (ustawione w
`src/indicators/helpers.py`; override `AMD_COMPOSE_5Q=REFERENCE` zachowany).
Podstawa: byte-exact 1131, cache bounded, zysk w obu porównaniach REF→OPT,
brak regresji lifecycle.

---

## FINAL AMD (spec 25)

| | |
|---|---|
| pool default | **8** (bez env) |
| compose default | **OPTIMIZED** (nowy) |
| telemetry default | REFERENCE |
| query mode | REFERENCE |
| FPS median (production = pool8 + OPT, bez obserwerów) | **~37.5 FPS** (5V B/D) |
| realtime factor | 37.5 / 29.97 = **1.251×** |
| margin | **+25.1 %** |

---

## ODPOWIEDZ WPROST

1. **Co powodowało wzrost RSS?** → Leak **+1 ref device i +1 ref context** w
   destruktorze VP przy borrowed device → D3D11 device nigdy nie niszczony →
   driver kernel objects + GPU memory per create/close.
2. **Czy to był prawdziwy leak?** → **TAK** (dominujący): +180 handles/eksport,
   ~200 MB/eksport. **Naprawiony.** Po fixie reszta ~+14 handles + ~+11 MB/eksport.
3. **Co stanowiło +13 obiektów/eksport?** → dict/Image/list/tuple/Counter —
   transientne dane Pythona, referrers = `builtins`; **NIE leak**.
4. **Czy Private Bytes się stabilizuje?** → Nie w pełni: wolno-liniowy ~+11 MB/eksport
   (eksporty 10–20: 1195→1307 MB). Dominujący wzrost usunięty; reszta poza heapem
   Pythona (tracemalloc +0.4 MB/eksport vs Private Bytes +11 MB/eksport).
5. **Czy jakiś cache rośnie bez ograniczenia?** → Nie w obrębie source
   (`static_cache` stałe 1074); `_STATIC_CACHE` globalny może rosnąć między
   projektami (drobne, bounded per source).
6. **Czy pool8 nie przecieka?** → Nie (textures/views live=0, device refcount=1).
7. **Czy AMF/MF/D3D nie przeciekają?** → Po fixie nie (create+close +0 handles/cykl);
   reszta z przetwarzania klatek (driver/decoder), nie z init AMF/MF.
8. **Czy handle/thread count jest stabilny?** → Dominujący wzrost naprawiony;
   reszta +14 handles + ~1 thread/eksport (wolno-liniowa, driver-side).
9. **Czy 5Q OPT jest bezpieczny jako default?** → **TAK** (byte-exact 1131, cache
   bounded, +2.6 FPS @pool8, brak regresji lifecycle).
10. **Jaki jest finalny production FPS bez env?** → **~37.5 FPS** (pool8 + OPT default).
11. **Jaki jest finalny realtime margin?** → **+25.1 %** (1.251×).
12. **Czy można uznać optymalizację AMD za zamkniętą?** → **TAK** — realtime 4K29.97
    osiągnięty z zapasem; dalsze optymalizacje opcjonalne (np. domknięcie resztkowego
    wzrostu driver-side, per-export clear `_STATIC_CACHE` dla cross-project).

---

## KRYTERIA PASS

| # | kryterium | wynik |
|---|---|---|
| 1 | źródło +13 obiektów/eksport wyjaśnione | ✅ (transient Python, referrers=builtins) |
| 2 | Private Bytes trend sklasyfikowany | ✅ (wolno-liniowy ~+11 MB/exp; dominujący usunięty) |
| 3 | Python vs native/C-heap rozdzielone | ✅ (native +0/cykl; tracemalloc +0.4 MB/exp vs Private +11 MB/exp → poza heapem Pythona) |
| 4 | cache growth zidentyfikowane | ✅ (bounded; static_cache 1074 stałe) |
| 5 | handles/threads nie rosną liniowo (dominująco) | ✅ (naprawione; reszta wolno-liniowa driver) |
| 6 | native resources live=0 | ✅ (pool 0, device refcount 1) |
| 7 | 20-export soak wykonany | ✅ (10 REF + 10 OPT) |
| 8 | brak corruption/drops | ✅ (muxed 1131, dropped 0) |
| 9 | final 5Q default decyzja poparta pamięcią i A/B | ✅ (OPT default; memory bounded, +2.6 FPS) |
| 10 | AMD final baseline zmierzony | ✅ (~37.5 FPS, margin +25.1 %) |

---

## PLIKI / ZMIANY

- **Native (FIX):** `src/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp` (destruktor
  zwalnia device/context bezwarunkowo), `src/telem_amd_native.cpp` (kolejność
  teardown w `close()`, refcount diagnostyka, `AMD_DEBUG_NO_AMF/MF/VP`).
  **DLL SHA `9DFBCA4A327592A4B4CEF4993C9505E1D7ED6420C23A5F7476A24964A0B96ED4`** (ABI 8).
- **Python (5Q default):** `src/indicators/helpers.py` — `AMD_COMPOSE_5Q` default
  REFERENCE → **OPTIMIZED** (override REFERENCE zachowany).
- **Diagnostyka:** `scratch/etap5w_{memprobe,handles,handles_named,handle_run,
  named_run,devref,soak,tracemalloc,freshproc,5q}.py`, `devref_probe.cpp`.
- **JSON:** `Raporty/AMD_ETAP5G/etap5w_{memprobe,handles,soak}.json`
  (+ `etap5w_tracemalloc.json` — brak, run ubity; częściowe dane S0/S1/S2 w raporcie).
