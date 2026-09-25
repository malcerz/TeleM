# RAPORT_AMD_GAUGE_SELECTION_FINDING_DEFERRED

## Status: ODŁOŻONE — nie produkcyjne

Data odkrycia: 2026-09-16  
Kontekst: przypadkowe powtórzenie zadania `alt_visual` profiling

---

## Odkrycie

### Problem w `_resolve_gauge_layout_key`

W layoucie `cycling_dashboard_v10.json` wskaźnik `compass` pojawia się **przed**
`fit_enhanced_speed_text` na liście wskaźników i posiada `form: "gauge"`.

Funkcja `_resolve_gauge_layout_key` iteruje po wskaźnikach w kolejności słownika
i zwraca **pierwszy** pasujący `form == "gauge"` — czyli `compass`, a nie speed gauge.

Skutek: GPU gauge pipeline przez całe ETAP 2A–2D działał z kluczem `compass`,
nie `fit_enhanced_speed_text`. Proba layout_safe na ramce 0 zwracała `bbox=None`
(compass nie jest w map_above_layout), gauge GPU fallback → CPU_REFERENCE.

### Eksperymentalna naprawa

Dodano `continue` dla `gauge_style == "compass"`, co sprawia że resolver
poprawnie wybiera `fit_enhanced_speed_text`.

### Wynik eksperymentu (300 klatek, GX020079/v10/4K)

| Metryka | CPU gauge (OFF) | GPU gauge + fix (ON) | Delta |
|---|---|---|---|
| FPS | 33.495 | 38.040 | **+13.6%** |
| above_total avg | 18.632 ms | 9.237 ms | **-50.4%** |
| producer_prepare avg | 28.147 ms | 17.145 ms | **-39.1%** |
| consumer_native_call | 5.396 ms | 16.823 ms | +11.4 ms (blend przeniesiony do GPU) |

### Regresja wizualna

Speed gauge **zniknął z obrazu** w konfiguracji GPU ON.

Analiza: `GPU gauge blend submit: count=0` — DLL nigdy nie wywołuje `BlendGauge`.
Warunek blokujący: `!m_gaugeActive` w `BlendGauge()` (d3d11_vp_pipeline.cpp:2978).
`m_gaugeActive` jest ustawiane przez `telem_amd_update_gauge` / `telem_amd_update_gauge_region`.
Nie jest jasne dlaczego `m_gaugeActive=false` skoro upload działa (300 klatek, ~147k bajtów).

Diagnozy nie dokończono — zadanie przerwane per polecenie użytkownika.

---

## Stan

- Eksperymentalna zmiana wycofana z kodu produkcyjnego
- Temat **NIE jest zaakceptowany produkcyjnie**
- Dane benchmarkowe zachowane w `scratch/amd_gauge_fix/`
- Dalsze dochodzenie wymaga osobnego etapu

---

## Następne kroki (przyszły etap)

1. Zbadać dlaczego `m_gaugeActive=false` pomimo poprawnego uploadu
2. Sprawdzić `telem_amd_update_gauge_region` — czy ustawia `m_gaugeActive=true`
3. Alternatywnie: zbadać czy `telem_amd_update_gauge` (nie region) ustawia flagę
4. Po naprawie DLL ponowny test wizualny i pixel diff
5. Dopiero po zero-regresji wizualnej — re-benchmark i decyzja o merge

---

## Uwaga o compass

Niezależnie od gauge GPU — `_resolve_gauge_layout_key` z aktualną logiką
może zwracać `compass` w layoutach gdzie compass poprzedza speed gauge.
Może to być przyczyną wcześniejszych „gauge fallback" wpisów w logach.
Do zbadania w osobnym etapie.
