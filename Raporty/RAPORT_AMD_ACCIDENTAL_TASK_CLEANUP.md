# RAPORT_AMD_ACCIDENTAL_TASK_CLEANUP

## Status: COMPLETE

Data: 2026-09-16  
Operator: Antigravity  
Gałąź: `amd-bikeridehud`

---

## Przyczyna

Zadanie `alt_visual GPU profiling` zostało przypadkowo uruchomione ponownie.
W trakcie jego wykonywania agent wyszedł poza zakres `alt_visual` i wprowadził:

1. Eksperymentalną zmianę w `_resolve_gauge_layout_key` (compass exclusion)
2. Tymczasowe logi diagnostyczne w frame-0 deferred probe

Zmiany te NIE były zlecone, NIE są zwalidowane produkcyjnie, i wprowadzały
regresję wizualną (speed gauge znikał z obrazu).

---

## Zidentyfikowane przypadkowe zmiany

### `src/ffmpeg/amd_native_exporter.py`

**Zmiana 1 — `_resolve_gauge_layout_key` (linie ~401–419):**
- Dodano `compass` exclusion: `if gauge_style == "compass": continue`
- Zmieniono docstring opisując exclusion
- **WYCOFANO** — przywrócono oryginalne iterowanie bez exclusion

**Zmiana 2 — frame-0 deferred probe (linie ~4805–4814):**
- Dodano blok `print("[AMD GAUGE DIAG] frame 0 deferred probe: ...")`
- **WYCOFANO** — usunięto diagnostic logging

---

## Pliki inne — NIE tknięte

Wszystkie pozostałe pliki w diffie (`d3d11_vp_pipeline.cpp`, `d3d11_vp_pipeline.h`,
`telem_amd_native.cpp`, `amd_config.py`, `compositor.py`, `gauge.py`,
`test_amd_benchmark_governance.py`) zawierają wyłącznie prawidłowe wcześniejsze
zmiany AMD (alt_visual GPU, production defaults Q2/R1, queue depth, ring size).
Nie zostały zmodyfikowane przez cleanup.

---

## Metryki

```
BEFORE cleanup:
  amd_native_exporter.py: 255 insertions

AFTER cleanup:
  amd_native_exporter.py: 238 insertions
  (17 linii przypadkowych usunięto)
```

---

## Zachowane poprzednie zmiany

```
AMD_QUEUE_DEPTH=2            YES - niezmienione
AMD_VP_PROCESSOR_RING_SIZE=1 YES - niezmienione
AMD_CPU_GPU_PIPELINE=ASYNC   YES - niezmienione
AMD_ABOVE_BATCHED=0          YES - niezmienione
AMD_AFTER_MAP_ALT_VISUAL_GPU YES - niezmienione
alt_visual C ABI + upload    YES - niezmienione
alt_visual profiling         YES - niezmienione
Q2/R1 production defaults    YES - niezmienione
BikeRideHUD.py launcher      YES - niezmieniony
```

---

## Artefakty scratch

Nie usunięto — dane benchmarkowe w `scratch/amd_gauge_fix/` pozostają.
Zawierają wyniki A/B (FPS +13.6%, above_total -50.4%) i runDIAG profil.
Te dane są potrzebne dla przyszłego etapu gauge GPU.

Manifest: `scratch/amd_accidental_task_cleanup/artifacts_manifest.txt`

---

## Wynik podsumowania

```
ACCIDENTAL_CHANGES_FOUND=2 (compass exclusion + diagnostic logging)
ACCIDENTAL_CHANGES_REMOVED=2
VALID_PREVIOUS_CHANGES_PRESERVED=YES (wszystkie 8 plików bez regresji)
GAUGE_FINDING_SAVED=YES -> Raporty/RAPORT_AMD_GAUGE_SELECTION_FINDING_DEFERRED.md
```

---

## PASS / FAIL

**PASS** — stan kodu przywrócony do prawidłowego stanu sprzed przypadkowego rerunu.
