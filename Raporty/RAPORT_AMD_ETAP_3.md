# TeleM — AMD ETAP 3 — raport końcowy

## Wynik

**ETAP 3: PASS.** Produkcyjny `GPU_HUD` nie wywołuje pełnego `PIL.Image.tobytes()` ani nie wykonuje natywnego pełnego memcpy HUD. Persistent tekstura D3D11 i compositor ETAP 2 pozostały bez zmian. Wybrany wariant `DIRTY`, target 8, osiągnął **10.493 TRUE FPS** przy pełnym eksporcie 1131 klatek, wobec 9.061 FPS w ETAP 2.

Nie zmieniono renderera HUD, semantyki telemetrii, rozdzielczości 3840×2160, compute-shadera/NV12 math, bazowego uploadu NV12, software decode FFmpeg, AMF ani backendów NVIDIA/Intel.

## Audyt rzeczywistej pamięci Pillow

`compose_overlay()` domyślnie nie tworzy nowego obrazu co klatkę. `_THREAD_CANVAS.cache[(width, height)]` przechowuje persistent `Image.new("RGBA")`; kolejne wywołania czyszczą poprzednie bboxy i ponownie rysują do tego samego obiektu Pillow.

Pillow 12.3.0 nie udostępnia jednak tego obrazu przez writable buffer protocol:

- `memoryview(Image)` — `TypeError`,
- `memoryview(ImagingCore)` — `TypeError`,
- `Image.frombuffer("RGBA", ..., bytearray, ...)` mapuje bufor jako `readonly=1`,
- pierwsze `ImageDraw`/`paste` uruchamia copy-on-write i odłącza obraz od bufora,
- `np.asarray(Image)` tworzy read-only ndarray oparty na nowym obiekcie `bytes`.

Ręczne przestawienie wewnętrznego `Image.readonly` pozwalało pisać do bufora w eksperymencie, ale jest nieudokumentowanym hackiem i nie zostało użyte.

Wcześniejsze martwe skrypty `run_etap3a_*` tworzyły `Image.frombuffer()`, po czym ignorowały obraz zwrócony przez `compose_overlay()`. Persistent buffer pozostawał więc pusty. Ich raporty „zero-copy” nie opisują rzeczywistego production path i nie zostały wykorzystane.

### Zastosowany bezpieczny fallback

GPU path utrzymuje jeden persistent, writable bufor ctypes RGBA o stałym stride `15360`:

```text
compose_overlay -> persistent Pillow Image
                -> kontrolowana ekstrakcja FULL lub per-region
                -> persistent ctypes RGBA buffer
                -> ten sam pointer + stride + rect list przez ABI 3
                -> bezpośredni UpdateSubresource persistent D3D11 texture
```

- Image buffer pointer: **niedostępny przez obsługiwany writable buffer protocol**,
- pointer persistent bufferu w pełnym Test B: `0x1e44160a040`,
- pointer wysłany w pierwszej i ostatniej klatce: `0x1e44160a040`,
- pointer stable: **YES**,
- Image i persistent buffer współdzielą backing memory: **NO**,
- diagnostyczne porównanie finalnego obrazu Pillow i bufora faktycznie wysłanego do DLL: **MAE 0, MAX 0**.

Jest to jawnie dozwolony wariant z kontrolowaną kopią, nie fałszywe zero-copy.

## ABI i native upload

ABI podniesiono do 3. Dodano `telem_amd_update_hud_regions()` przyjmujące:

- pointer RGBA,
- width/height,
- stride,
- tablicę rectów,
- liczbę rectów,
- flagę full upload.

W `GPU_HUD` funkcja nie używa `currentHUDRGBA`, `std::vector.assign()` ani `memcpy()`. Wskaźnik jest używany synchronicznie bezpośrednio przez `UpdateSubresource`; Python utrzymuje backing buffer przez cały eksport. Stara funkcja i `currentHUDRGBA` pozostały dla jawnego `CPU_REFERENCE`.

Persistent tekstura D3D11:

- format: `DXGI_FORMAT_R8G8B8A8_UNORM`,
- rozmiar: 3840×2160,
- tworzenie w każdym pełnym eksporcie: 1,
- per-frame texture creation: 0,
- compositor: niezmieniony direct planar NV12 compute shader.

## Memory path before — ETAP 2

| Etap | Wielkość / czas |
|---|---:|
| compose_overlay output | persistent Pillow RGBA 3840×2160 |
| `Image.tobytes("RGBA")` | 17.237 ms; 31.640625 MiB/frame |
| bytes → native `currentHUDRGBA` memcpy | pełne 31.640625 MiB/frame |
| HUD CPU → GPU | pełne 31.640625 MiB/frame |
| całe `update_hud`/upload | 6.418 ms |

Przed zmianą występowała pełna materializacja `bytes`, pełna natywna kopia oraz pełny transfer GPU.

## Memory path after

### Test A — persistent pointer + FULL upload

Pillow nie może bezpiecznie rysować bezpośrednio do backing bufferu, dlatego FULL wykonuje materializację do NumPy i jedną kontrolowaną kopię do persistent ctypes buffer. Nie ma `Image.tobytes()` ani native memcpy.

| Metryka | Wynik |
|---|---:|
| Frames | 1131/1131 |
| Pillow/buffer preparation AVG | 23.243 ms |
| Python→native bridge AVG | 0.034 ms |
| Native HUD CPU copy AVG | 0.000 ms |
| HUD texture upload AVG | 3.020 ms |
| Python persistent copy | 31.640625 MiB/frame |
| HUD CPU→GPU | 31.640625 MiB/frame |
| TRUE FPS | **8.778** |
| Wall-clock | 128.840 s |

FULL jest poprawny, ale wolniejszy od ETAP 2: koszt bezpiecznej materializacji i kopii do persistent bufferu przewyższa zysk z usunięcia native memcpy.

Golden Test A, klatki 30/300/900: MAE 0, MAX 0.

### Test B — MULTI DIRTY, target 8

Pierwsza klatka inicjalizuje pełny backing buffer i pełną teksturę. Następne klatki wykorzystują listę bboxów bieżących wskaźników oraz dokładnie te same, rozszerzone o 40 px bboxy poprzedniej klatki, które `compose_overlay()` czyści. Nie ma full-image pixel diff ani jednego globalnego bboxa.

Każdy końcowy rect jest wycinany z finalnego obrazu Pillow i kopiowany do odpowiadającego regionu persistent bufferu. DLL przesyła te regiony bez dodatkowej kopii CPU.

| Metryka | AVG | Median | P95 | P99 |
|---|---:|---:|---:|---:|
| Pillow/buffer preparation, ms | 11.619 | 11.230 | 13.491 | 19.635 |
| Python→native bridge, ms | 0.031 | 0.029 | 0.041 | 0.063 |
| Native HUD CPU copy, ms | 0.000 | 0.000 | 0.000 | 0.000 |
| HUD texture upload, ms | 1.740 | 1.667 | 2.032 | 2.874 |
| Rects/frame | 5.996 | 6 | 6 | 6 |
| MiB/frame | 10.291 | 10.272 | 10.272 | 10.272 |

AVG jest nieco większe od P95, ponieważ pierwsza klatka wykonuje obowiązkową pełną inicjalizację 31.64 MiB.

Transfer CPU→GPU zmniejszył się średnio o **67.47%**, z 31.64 do 10.29 MiB/frame.

W stanie ustalonym pozostają dwie **regionalne**, nie pełnoklatkowe operacje CPU: Pillow→regional intermediate oraz regional intermediate→persistent buffer. Po klatce inicjalizacyjnej liczba pełnych kopii HUD per frame wynosi **0**. Native full memcpy wynosi **0**.

## Wybór limitu rectów

Wykonano 32-klatkowe realne testy tej samej ścieżki produkcyjnej:

| Target | AVG rects | P95 rects | AVG MiB | P95 MiB | Upload AVG | TRUE FPS próbki |
|---:|---:|---:|---:|---:|---:|---:|
| 4 | 3.906 | 4 | 11.971 | 11.336 | 2.589 ms | 5.843 |
| 8 | 5.844 | 6 | 10.940 | 10.272 | 2.245 ms | 6.178 |
| 16 | 5.844 | 6 | 10.940 | 10.272 | 2.302 ms | 6.171 |

Target 4 wymuszał większe prostokąty i przesyłał więcej danych. Targety 8 i 16 dawały te same sześć regionów; 8 miał minimalnie niższy upload i FPS minimalnie wyższy. Wybrano **8**. Algorytm nie scala pary, jeżeli union zwiększyłby przesyłaną powierzchnię o więcej niż 25%.

## Performance

| Wariant | TRUE FPS | Wall-clock | Zmiana vs ETAP 2 |
|---|---:|---:|---:|
| ETAP 2 | 9.061 | 124.825 s | baseline |
| ETAP 3 FULL | 8.778 | 128.840 s | −3.1% |
| ETAP 3 DIRTY | **10.493** | **107.784 s** | **+15.8%** |

Timingi pełnego Testu B:

| Stage | AVG ms | Median ms | P95 ms | P99 ms |
|---|---:|---:|---:|---:|
| Decode/pipe | 22.192 | 17.759 | 29.604 | 32.582 |
| Telemetry | 19.629 | 19.741 | 22.571 | 24.116 |
| compose_overlay | 35.333 | 32.613 | 46.118 | 63.192 |
| PIL/buffer preparation | 11.619 | 11.230 | 13.491 | 19.635 |
| Python→native bridge | 0.031 | 0.029 | 0.041 | 0.063 |
| Native HUD CPU copy | 0.000 | 0.000 | 0.000 | 0.000 |
| HUD texture upload | 1.740 | 1.667 | 2.032 | 2.874 |
| GPU compositor CPU submit | 0.395 | 0.382 | 0.542 | 0.728 |

Normalny eksport nie włącza blocking GPU completion timing. Największym pojedynczym bottleneckiem jest teraz pozostawiony bez zmian `compose_overlay` — 35.33 ms; dalej decode/pipe 22.19 ms, telemetry 19.63 ms i regionalne przygotowanie bufora 11.62 ms.

## Golden regression

Porównanie pełnego Testu B z finalnym ETAP 2 po dekodowaniu obu plików:

| Frame | MAE | MAX | P95 | P99 | Wynik |
|---:|---:|---:|---:|---:|---:|
| 30 | 0.0 | 0 | 0.0 | 0.0 | PASS |
| 300 | 0.0 | 0 | 0.0 | 0.0 | PASS |
| 900 | 0.0 | 0 | 0.0 | 0.0 | PASS |

Output jest dla tych klatek dokładnie identyczny, nie tylko wizualnie zbliżony.

Co więcej, kompletne pliki MP4 z ETAP 2, ETAP 3 FULL i ETAP 3 DIRTY mają ten sam SHA-256: `27DD5B35037CC3E0151A38C8566A592EE9562CD816C54FE05BDEF603AEC0A35A`. Finalny video, audio i mux są więc bitowo identyczne.

| Element | Wynik |
|---|---:|
| Base video | PASS |
| FIT dynamic | PASS |
| GPMF dynamic | PASS |
| Map | PASS |
| Date/time | PASS |
| Color/alpha | PASS |
| Audio | PASS |

Audio AAC po ekstrakcji ma identyczny jak golden SHA-256: `E7D3FA3DF057F0705BF2F8410B6FDE44FAC298002A55BDB1B6EC403E642D1FF3`.

## Frame accounting i AMF

| Licznik | Wynik |
|---|---:|
| Source | 1131 |
| Decoded | 1131 |
| HUD | 1131 |
| Native HUD updates | 1131 |
| GPU HUD | 1131 |
| VP processed | 1131 |
| AMF submitted | 1131 |
| AMF output | 1131 |
| Muxed | 1131 |
| AMF dropped | 0 |
| AMF INPUT_FULL / retries | 0 / 0 |

`requested_frames=1132` nadal wynika z nominalnego `ceil(duration × fps)`; źródło zawiera 1131 klatek i wszystkie zostały przetworzone.

## Build i testy

- ABI: 3,
- build ID użyty w eksportach: `telem-amd-native/1.0.0+42dc5799a538.src60574fb5e1bb`,
- finalna DLL SHA-256: `91A6F9BE8851DA2CB28314FF32303224EDFE814BB31AEF26BA2C4C6BBED43E09`,
- dwa kolejne clean buildy: identyczny hash — PASS,
- `git diff --check`: PASS,
- testy: **158 passed, 17 skipped**.

## Odpowiedzi wprost

1. **Co powodowało koszt PIL tobytes?** Pillow przechowuje RGBA we własnym `ImagingCore`, który nie udostępnia writable buffer protocol. `tobytes()` uruchamiał raw encoder, materializował nowy pełny obiekt `bytes` 31.64 MiB i kopiował wszystkie wiersze co klatkę.
2. **Czy udało się udostępnić Pillow persistent backing buffer?** Nie bezpiecznie. `frombuffer` jest readonly i odłącza się przy pierwszym rysowaniu. Zastosowano persistent ctypes buffer z kontrolowanymi kopiami regionów; jego pointer jest stały i udowodniony.
3. **Ile pełnych kopii HUD pozostaje?** W finalnym dirty path: jedna pełna inicjalizacja pierwszej klatki; następnie 0 pełnych kopii per frame. Pozostają dwie kopie regionalne. Native full memcpy: 0.
4. **Ile MB/frame trafia CPU→GPU?** AVG **10.291 MiB**, P95 **10.272 MiB**, zamiast 31.641 MiB.
5. **Czy dirty rects pomagają?** Tak: upload 3.020→1.740 ms względem ETAP 3 FULL, przygotowanie 23.243→11.619 ms, TRUE FPS 8.778→10.493.
6. **Jaki jest TRUE FPS?** **10.493 FPS** dla finalnego DIRTY, 1131 klatek, z pełnym drain, mux i zamknięciem pliku.
7. **Co jest teraz największym bottleneckiem?** `compose_overlay` około 35.33 ms; dalej decode/pipe i telemetry.
8. **Czy można przejść dalej?** Tak. ETAP 3 spełnia kryteria; należy zachować FULL oraz CPU_REFERENCE jako jawne ścieżki kontrolne.

## Artefakty

- `AMD_ETAP3/test_a_full_1131.mp4`,
- `AMD_ETAP3/test_a_full_1131.mp4.amd_profile.json`,
- `AMD_ETAP3/test_b_dirty8_1131.mp4`,
- `AMD_ETAP3/test_b_dirty8_1131.mp4.amd_profile.json`,
- `AMD_ETAP3/test_b_frames/frame_30.png`, `frame_300.png`, `frame_900.png`,
- `AMD_ETAP3/diagnostic_full_timeline_python_hud_frame30.png`,
- `AMD_ETAP3/diagnostic_full_timeline_backing_frame30.png`,
- `AMD_ETAP3/regression_results.json`.
