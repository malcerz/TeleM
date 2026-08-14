# TeleM — AMD ETAP 5B — telemetry fast path

Data: 2026-08-14  
Wynik: **PASS**

Zmieniono wyłącznie dobór per-frame pól telemetrycznych w produkcyjnym eksporcie AMD. Renderer HUD, mapy, wykresy, Pillow, dirty upload oraz cały natywny pipeline GPU pozostały bez zmian.

## Audyt zależności

Lista odkrytych pól pochodzi z `TelemetryDataManager.fit_data`, tworzonego po parsowaniu i synchronizacji materiału FIT. GUI rejestruje pola jako niezależne strumienie/klucze `fit_{field_name}_text`. Wybranie strumienia dodaje taki klucz do `layout["indicators"]`; jego forma może być text, chart, gauge itd., ale pole źródłowe nadal wynika z klucza.

- pole może być dynamicznie dodane/usunięte albo enabled/disabled w GUI przed eksportem;
- zmiana text ↔ chart nie zmienia zależności;
- dwa konsumujące to samo pole wpisy są deduplikowane przez dokładną nazwę pola;
- custom texts są statycznymi napisami i nie mają telemetry field binding;
- standardowe `power_text`, `atemp_text`, `hr_text`, `cad_text`, `battery_text` mają jawne, strukturalne mapowanie do istniejących resolverów; nie są aktywowane, jeśli widget jest nieobecny/disabled.

GUI uruchamia eksport w osobnym wątku, natomiast pierwotny `dict(self.layout, ...)` był kopią płytką. Eksporter AMD tworzy teraz jeden `deepcopy(layout)` na starcie. Plan zależności jest budowany z tego snapshotu raz na eksport, więc nie ma skanowania layoutu per-frame i nie jest potrzebny globalny system invalidacji. Kolejny eksport automatycznie buduje plan z aktualnego layoutu.

## FIT fields

Odkryte — 14:

`K1`, `K2`, `alt`, `cadence`, `curVpower`, `distance`, `enhanced_altitude`, `enhanced_speed`, `fractional_cadence`, `gopro_battery`, `heart_rate`, `speed`, `temperature`, `track`.

Aktywne — 4:

`cadence`, `enhanced_speed`, `gopro_battery`, `heart_rate`.

Nieaktywne odkryte — 10:

`K1`, `K2`, `alt`, `curVpower`, `distance`, `enhanced_altitude`, `fractional_cadence`, `speed`, `temperature`, `track`.

ETAP 5A wykonywał 18 wywołań/frame: pięć standardowych aliasów oraz 13 zarejestrowanych w layoucie kluczy FIT, także disabled i dwa stare klucze bez aktualnych samples (`battery_pct_x100`, `solar`). ETAP 5B wykonuje cztery unikalne wywołania odpowiadające czterem aktywnym konsumentom.

## Lookups

| Pole | Przed | Po |
|---|---:|---:|
| `resolve_cache_value` calls/frame | 18.0 | **4.0** |
| Calls — pełne 1131 klatek | 20 358 | **4 524** |
| `cadence` | 1131 | 1131 |
| `enhanced_speed` | 1131 | 1131 |
| `gopro_battery` | 1131 | 1131 |
| `heart_rate` | 1131 | 1131 |
| Duplicate field lookups | niekontrolowane przez wspólny cache | **0** |

Wartości są zapisywane w lokalnym per-frame cache i udostępniane wszystkim konsumentom. Resolver, wybór samples, interpolacja step/linear, obsługa `None`, timestampy oraz first/last boundary nie zostały zmienione.

## Profiling

Pełny profilowany real GUI run, 1131 klatek:

| Stage | Przed AVG | Po AVG | Przed Median | Po Median | Przed P95 | Po P95 | Przed P99 | Po P99 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Telemetry total | 9.281 | **5.554** | 5.810 | **3.889** | 17.176 | **12.950** | 18.930 | **14.864** |
| Dynamic FIT | 5.167 | **2.147** | 3.710 | **1.620** | 11.500 | **5.944** | 13.490 | **7.438** |
| `resolve_cache_value` | 5.054 | **2.065** | 3.633 | **1.566** | 11.261 | **5.707** | 13.163 | **7.149** |

Zmiana telemetry total: **−3.727 ms/frame (−40.2%)**. Sam resolver: −2.989 ms/frame. P95 telemetry spadło o 4.226 ms.

Profilowany wall-clock wyniósł 67.708 s, TRUE FPS 16.704. Zgodnie z wymaganiem nie jest to baseline performance.

## Frame-by-frame correctness

Walidator odtworzył obciążenie ETAPU 5A (18 resolver calls) i porównał je z planem ETAPU 5B na rzeczywistych 1131 timestampach źródła.

| Kontrola | Wynik |
|---|---:|
| Frames compared | 1131 |
| Active fields/frame | 4 |
| Values compared | 4524 |
| Mismatched values | **0** |

Test alternatywnego layoutu aktywował niewykorzystywane obecnie pole `fractional_cadence`. Pole automatycznie weszło do `active_fit_fields`, wykonało dokładnie jeden lookup i zwróciło wartość resolvera bez hardcodowania w kodzie produkcyjnym: **PASS**.

Osobny test dwóch konsumentów `power` (standard text + dynamic FIT chart) potwierdził dokładnie jeden lookup pola na klatkę: **PASS**.

## Golden video

| Kontrola | Wynik |
|---|---|
| Frame 30 | PASS, pixel-identical |
| Frame 300 | PASS, pixel-identical |
| Frame 900 | PASS, pixel-identical |
| Final MP4 SHA-256 | `6E0884960B5530BA305F5391BF45FF0BE801DE7391D0DA14A009E6B1DB25E693` |
| ETAP 4 / 5A SHA-256 | identyczny |
| FIT | PASS |
| GPMF | PASS |
| Map | PASS |
| Date/time | PASS |
| HUD | PASS |
| Color | PASS |
| Audio | PASS |

Cały finalny MP4 jest byte-identical, więc kontrola obejmuje więcej niż trzy wskazane klatki.

## Frame accounting i GPU

| Licznik | Wynik |
|---|---:|
| Source/requested/decoded | 1131 / 1131 / 1131 |
| MF samples / D3D11 surfaces | 1131 / 1131 |
| VP | 1131 |
| GPU HUD | 1131 |
| AMF submitted/output | 1131 / 1131 |
| Muxed | 1131 |
| AMF INPUT_FULL/retries/drops | 0 / 0 / 0 |

DLL nadal ma ABI 4 i SHA-256 `CE640BB8047B3354ADE3518B90FB4B89DAD932A4E22A4CEEFE890A4B6C0348BD`. Native D3D11VA, P010, VP, NV12 range correction, compute compositor, dirty upload i AMF nie zostały zmienione.

## Normal production performance

`AMD_OVERLAY_PROFILE=OFF`, natywne profiling/diagnostics OFF, identyczna definicja TRUE FPS:

| Run | Wall-clock | TRUE FPS |
|---|---:|---:|
| ETAP 4 baseline | 67.745 s | 16.695 |
| **ETAP 5B** | **64.078 s** | **17.650** |

Zysk: **+0.955 FPS, +5.7%**. Normalny telemetry/frame_data w tym przebiegu: AVG 5.251, Median 3.759, P95 12.368, P99 14.235 ms.

Największym bottleneckiem pozostaje `compose_overlay`: około 34.636 ms/frame w normalnym przebiegu. ETAP 5B nie zmieniał compositora.

## Odpowiedzi wprost

1. Odkryto **14** pól FIT.
2. Aktualny layout naprawdę używa **4**: cadence, enhanced_speed, gopro_battery i heart_rate.
3. Pozostały **4 `resolve_cache_value` calls/frame**.
4. Telemetry zaoszczędziło **3.727 ms/frame AVG**; resolver 2.989 ms/frame.
5. Tak. Porównano 4524 wartości; mismatches = **0**.
6. Normalny TRUE FPS = **17.650**.
7. Największy bottleneck to nadal `compose_overlay`, około **34.6 ms/frame**.
8. ETAP 5B spełnia kryteria PASS. Technicznie można przejść do 5C, ale ten etap go nie rozpoczyna.

## Artefakty

- `Raporty/AMD_ETAP5B/full_gui_profile_1131.mp4`
- `Raporty/AMD_ETAP5B/full_gui_profile_1131.mp4.amd_profile.json`
- `Raporty/AMD_ETAP5B/full_gui_production_1131.mp4`
- `Raporty/AMD_ETAP5B/full_gui_production_1131.mp4.amd_profile.json`
- `Raporty/AMD_ETAP5B/all_frame_value_comparison.json`

Testy repozytorium: **170 passed, 17 skipped**. Zatrzymano się po AMD ETAPIE 5B.
