# TeleM — ETAP 7D — RESULT

## A. Zakres i przyczyna

Etap 7C ujawnił, że native `CPU_ABOVE_MAP` czyścił poprzedni bounding box dopiero w końcowej fazie klatki. Mogło to wymazać fragmenty mapy, gauge’a lub warstwy poniżej mapy.

## B. Poprawiona kolejność klatki

```text
base VP
→ clear previous CPU_ABOVE_MAP bbox
→ CPU_BELOW_MAP / charts
→ GPU gauge
→ GPU map
→ current CPU_ABOVE_MAP
→ final HUD
```

`ClearPreviousAboveMap()` działa przed pozostałymi warstwami, a `BlendAboveMap()` nakłada już wyłącznie bieżący crop. Nie ma ponownego destrukcyjnego clear po mapie.

## C. Implementacja

Zmieniono:

- `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.h`
- `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp`
- `tests/test_amd_native_ordered_map_clear.py`

ABI pozostało bez zmian (`AMD_NATIVE_ABI_VERSION = 8`). Native DLL przebudowano pomyślnie.

## D. Walidacja dynamicznych przejść

Native runtime przetestowano na 90 klatkach z przejściami: tekst widoczny, brak tekstu, zmiana pozycji i zmiana rozmiaru. CPU_REFERENCE i GPU zakończyły się wynikiem `90/90`, bez dropped frames.

Log GPU potwierdził:

```text
AMD_MAP_ORDER: CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
```

Końcowe klatki zakodowanych plików zostały sprawdzone pixel-oracle: stary obszar tekstu znika po przesunięciu overlayu, a obszar mapy nie jest czyszczony przez poprzedni bbox.

## E. Z-order i alpha

Poprawiony kontrakt jest spełniony: map pozostaje pod bieżącym `CPU_ABOVE_MAP`, a bieżący overlay pozostaje nad mapą. Blend używa alpha overlayu; nie wprowadzono dodatkowego pełnoklatkowego compositingu ani readbacku GPU→CPU.

## F. Chart i gauge

Gauge GPU pozostaje pomiędzy warstwą poniżej mapy a mapą. W realnym układzie testowym nie było aktywnego chart widgetu, dlatego osobny przypadek chart-under-ABOVE jest `NOT APPLICABLE`; istniejący guard `GPU_SPLIT` zachowano.

## G. Reuse zasobów i transfery

Warstwa ABOVE nadal używa istniejącego zasobu i przesyła tylko crop bounding boxu, nie pełną klatkę. Nie dodano per-frame tworzenia tekstur ani buforów. W pełnym przebiegu crop ABOVE przesłał `576,660,760` bajtów dla 5395 klatek, średnio około 106.9 KB/klatkę.

## H. Walidacja 30 s

```text
requested/decoded/processed/VP = 900/900/900/900
AMF submitted/output/dropped   = 900/900/0
HW decode                      = YES
effective FPS                  = 27.285
map GPU frames                 = 900
map ABOVE updates/visible      = 900/900
```

## I. Walidacja pełnego materiału

Materiał `Video/GX030120.MP4`:

```text
requested frames               = 5400
decoded/processed/VP            = 5395/5395/5395
AMF submitted/output/dropped    = 5395/5395/0
EOS events                     = 1
effective FPS                  = 28.673
audio                          = present, mux successful
HW decode                      = YES
AMD map order                  = CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
GPU map frames                 = 5395
CPU_ABOVE_MAP updates/visible  = 5395/5395
```

Profiling nie wykazał produkcyjnego GPU→CPU readbacku. Map i gauge działały przez GPU, a zasoby były reuse’owane.

## J. Wydajność

Pełny przebieg około 180 s: compose średnio `6.156 ms`, p95 `9.825 ms`; map CPU preparation średnio `2.204 ms`; dropped frames `0`.

## K. Testy

Nowy test sprawdza kolejność dispatchów, brak późnego clear, reuse zasobu ABOVE oraz prosty oracle RGBA. Wynik testów powiązanych: `68 passed`.

Pełna suite po zmianie:

```text
330 passed, 3 failed, 17 skipped
```

Trzy failure’y są tymi samymi, znanymi i niezwiązanymi problemami: `test_amd_native_etap4.py`, `test_qp_analyzer.py`, `test_render_tab.py`. Nie dodano nowych failure’ów.

## L. Regresja

Potwierdzono brak zmian w kontraktach GPS9, SmartSync, ISOE, SHUT, TMPC, track_map path oraz pozostałych testach związanych z etapami 7B/7C.

`def_layout.json` nie był modyfikowany; SHA256 przed i po: `E79F34C0237672ED58FE86301A485284C6F97AFC4A5730E3C16CCDC88DE217E7`.

## M. Klasyfikacja

```text
ORDERED MAP CLEAR LIFECYCLE = PASS
AMD TRACK_MAP Z-ORDER CONTRACT = PASS
ETAP 7D = COMPLETE
```

Pozostają poza zakresem: dalsza optymalizacja GPU, zmiany renderera i naprawa wcześniejszych, niezwiązanych test failure’ów.
