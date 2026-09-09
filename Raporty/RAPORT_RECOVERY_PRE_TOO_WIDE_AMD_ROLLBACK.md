# RAPORT: recovery stanu sprzed zbyt szerokiego rollbacku AMD

**Data:** 2026-09-07  
**Branch:** `integration/intel-amd`  
**Status:** PRE-ROLLBACK WORKTREE RESTORED: YES

## Identyfikatory i zabezpieczenie

- HEAD: `59277b4c920e0bb8a9642e4a574a32db0edcfacc`.
- Stash pre-rollback zastosowany po pełnym hash: `6219a9e895317b212e876a41ac0c65bf36c4e384` (`backup-before-amd-render-rollback-20260907`).
- Backup stanu po zbyt szerokim rollbacku: `878442ee9ef7367d2d00551ba2eaaf5e8f0ca36e` (`backup-after-too-wide-amd-rollback-20260907`).
- Oba stash pozostają dostępne; nie użyto `stash pop`.
- `scratch/gpmf-parser-upstream/` było czystym zagnieżdżonym repo (`main`, `9a71506`), więc Git zgłosił `Ignoring path`; nie usuwano, nie czyszczono i nie resetowano tego katalogu.

## Wynik zastosowania stashu

`git stash apply 6219a9e895317b212e876a41ac0c65bf36c4e384` zakończył się bez konfliktów.

- Lista konfliktów: **brak**.
- Tracked diff po recovery: **49 plików, 5 796 insertions, 1 022 deletions**, zgodnie ze stanem zapisanym w stashu pre-rollback.
- Porównanie `git diff --quiet 6219a9e895317b212e876a41ac0c65bf36c4e384 --`: **PASS**.
- Wpisy nieśledzone zapisane w stashu pre-rollback: 468; obecnie odzyskane: 468/468.
- Dodatkowy obecny wpis: czyste zagnieżdżone repo `scratch/gpmf-parser-upstream/`, nieuwzględnione przez `git stash -u`.

## Kontrola odzyskanych funkcji

Static presence/integration checks: **PASS**.

- GPMF: odzyskano `src/telemetry_native_gpmf.py`, `src/telemetry_active_time.py`, `src/native/gpmf/gpmf_bindings.cpp`, `src/native/gpmf/gpmf_extractor.cpp` oraz cache/native telemetry artifacts.
- Export Preview: odzyskano `src/gui/export_preview.py` z `compose_export_preview`.
- Preview: odzyskano `src/gui/preview_transform.py`, aktualny `preview_mixin.py`, `render_tab.py` i geometrię/synchronizację Preview.
- GUI/HUD: odzyskano bieżące mixiny render/preview, layout, mapy, wykresy, bary, lean i wskaźniki.
- AMD renderer: odzyskano dirty wersję sprzed rollbacku w `native/d3d11_amf_pipeline/src/`, `src/ffmpeg/amd_native_exporter.py`, `streaming.py`, `frame_renderer.py`, `worker_cache.py`, `render_logging.py` i `render_progress.py`.
- Nowe moduły `src/ffmpeg/amd_pipeline_watchdog.py` i `src/ffmpeg/finalization_tracker.py` również wróciły jako część oryginalnego pre-rollback worktree.

Nie uruchamiano GUI, renderu ani długiego testu. Kontrola runtime funkcji i stabilności pozostaje do wykonania przez użytkownika.

## DLL

Ponieważ DLL jest ignorowanym artefaktem, przywrócono zachowaną kopię sprzed poprzedniego rollbacku: `native/d3d11_amf_pipeline/bin/telem_amd_native.dll` ma build-id:

`telem-amd-native/1.0.0+59277b4c920e.src01787b14f931`

Zachowano również przebudowaną kopię rollbackową jako `telem_amd_native.rollback_build_20260907.dll`; niczego nie usuwano.

## Stan końcowy

Polecenia kontrolne:

```text
git status
git diff --stat
git diff --name-status
```

wykazują odzyskane 49 zmian tracked oraz pełny zestaw untracked ze stashu pre-rollback. Raport ten jest nowym plikiem recovery i stanowi jedyny dodatkowy artefakt utworzony po zastosowaniu stashu.

**PRE-ROLLBACK WORKTREE RESTORED: YES**

Nie wykonano commita, push, `git clean`, `git reset --hard` ani żadnych zmian naprawczych pipeline’u. Zatrzymano pracę w oczekiwaniu na ręczne potwierdzenie użytkownika.
