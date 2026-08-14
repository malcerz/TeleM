# TeleM — AGENT.md

## Cel projektu

TeleM to aplikacja do renderowania telemetrii na materiale wideo, głównie z kamer GoPro. Nakładki HUD wykorzystują dane z FIT, GPMF, GPS/mapy oraz innych źródeł telemetrycznych.

Głównym celem obecnych prac jest maksymalizacja wydajności renderowania 4K przy zachowaniu identycznej poprawności obrazu i telemetrii.

Priorytetowa platforma w tym etapie:
- Windows 11
- AMD Ryzen 5 5500U / zintegrowany Radeon
- materiał referencyjny 3840×2160, 30000/1001 FPS
- HEVC Main10 / P010 / HLG / BT.2020

Backend NVIDIA jest działający i NIE powinien być modyfikowany w ramach prac nad AMD. Obsługa Intel będzie optymalizowana osobno później.

## Zasada nadrzędna

**Correctness przed performance.**

Realny eksport wykonany przez produkcyjne GUI jest źródłem prawdy.

Nie deklaruj PASS wyłącznie na podstawie:
- testu syntetycznego,
- PoC,
- benchmarku pomocniczego,
- checkpointu,
- pojedynczej klatki,
- samego faktu, że kod się kompiluje.

Każda większa zmiana pipeline'u musi być zweryfikowana na realnym eksporcie.

## Aktualny działający backend AMD

Obecna architektura bazowego obrazu:

```text
HEVC Main10
    ↓
Media Foundation / D3D11VA
    ↓
DXGI_FORMAT_P010 decoder surface
    ↓
bezpośrednio do ID3D11VideoProcessor
    ↓
NV12 output surface
    ↓
GPU HUD compositor
    ↓
AMD AMF HEVC
    ↓
audio mux
    ↓
final MP4
```

W produkcyjnym AMD path:
- hardware decode działa,
- decoder surface trafia bezpośrednio do VideoProcessora,
- rawvideo pipe dla bazowego obrazu nie występuje,
- CPU raw base video = 0,
- CPU→GPU upload bazowej klatki = 0,
- GPU→CPU readback bazowej klatki = 0,
- dodatkowa kopia decoder surface = 0,
- frame accounting materiału referencyjnego = 1131/1131,
- AMF drops = 0.

Nie wolno cofać tego pipeline'u do:

```text
FFmpeg software decode
→ CPU NV12
→ staging
→ GPU
```

chyba że jawnie uruchamiany jest istniejący reference/fallback do testów A/B.

## Aktualny HUD pipeline

HUD nadal jest generowany przez Python/Pillow, ale kompozycja z bazowym wideo odbywa się na GPU.

Aktualna ścieżka:

```text
compose_overlay()
    ↓
persistent Pillow RGBA canvas
    ↓
regionalne kopie tylko dirty regions
    ↓
persistent ctypes RGBA buffer
    ↓
regionalny upload do persistent D3D11 RGBA8 texture
    ↓
direct planar NV12 compute compositor
    ↓
ta sama NV12 surface
    ↓
AMF
```

Istotne założenia:
- CPU `BlendRGBAToNV12()` NIE jest używany w `GPU_HUD`,
- CPU reference blend pozostaje dostępny wyłącznie jako fallback/reference,
- D3D11 HUD texture jest persistent,
- HUD używa straight alpha,
- dirty upload wykorzystuje multi-rect path,
- preferowany limit rectów obecnie: 8,
- nie wykonywać pełnego `Image.tobytes()` per frame,
- nie przywracać pełnego native memcpy HUD per frame.

Compute compositor działa plane-aware:
- Y plane: R8,
- UV plane: R8G8,
- output: NV12.

Nie zastępować go niedokończonym historycznym compute shaderem ani niesprawdzonym VP Stream 1.

## Telemetria

Dane FIT/GPMF są poprawne i dynamiczne.

Aktualny telemetry fast path:
- buduje zależności z aktywnego layoutu raz na eksport,
- rozwiązuje tylko aktywne FIT fields,
- deduplikuje wielokrotnych konsumentów tego samego pola,
- nie skanuje wszystkich odkrytych FIT fields co klatkę.

Nie hardcodować list aktywnych pól.

Nie zmieniać semantyki:
- timestamp matching,
- step/linear interpolation,
- first/last boundary,
- None handling,
- FIT/GPMF synchronization.

## Mapa

Preview i finalny eksport mają teraz zgodny geograficzny viewport.

Poprawiona logika jest resolution-independent:
- logiczny viewport mapy odpowiada preview,
- efektywny tile zoom rośnie wraz z rozdzielczością renderowania,
- Preview 960 px szerokości: zoom bazowy,
- 1920 px: +1 poziom zoom,
- 3840 px: +2 poziomy zoom,
- marker i route są skalowane razem z gęstością mapy.

Nie cofać tego do stałego tile zoom dla wszystkich rozdzielczości.

### Następny kierunek dla mapy

Następny właściwy etap optymalizacji mapy powinien:
- zachować obecny viewport i zoom parity Preview ↔ Export,
- usunąć per-frame kopiowanie dużego cached gridu,
- operować możliwie na finalnym viewport region,
- zachować pixel-exact wynik przed/po.

Nie zmieniać wyglądu mapy w imię wydajności.

## Aktualny kierunek optymalizacji

### Etap 5C — mapa
Cel:
- usunąć niepotrzebne duże kopie obrazu mapy,
- cropować cached background przed kopiowaniem,
- pracować na małym viewport working image,
- zachować identyczną geometrię route i markera,
- porównać wszystkie 1131 map widgets przed/po.

### Etap 5D — wykresy
Po poprawnym 5C:
- zoptymalizować cadence i heart-rate charts,
- cache'ować finalne statyczne assembly,
- per frame renderować tylko elementy dynamiczne,
- zachować dokładną kolejność alpha,
- wymagane A/B i pixel comparison.

### Etap 5E — ogólny Pillow compositing
Dopiero później:
- ograniczać koszt `alpha_composite`,
- ograniczać `paste/crop/copy`,
- pracować regionalnie,
- nie wykonywać szerokiego refactoru bez profilowania,
- zachować fallback/reference.

## Profilowanie

Nie optymalizuj na podstawie intuicji. Zawsze mierzyć realny production path.

Preferowane metryki:
- AVG,
- Median,
- P95,
- P99,
- TRUE end-to-end FPS.

TRUE FPS:

```text
faktycznie zakodowane klatki / całkowity wall-clock
```

Pomiar powinien obejmować:
- decode,
- HUD,
- GPU processing,
- AMF drain,
- audio mux,
- zamknięcie finalnego pliku.

Nie przedstawiać CPU enqueue time jako GPU execution time.

Blocking GPU timestamp queries mogą być używane tylko w trybie profilowania/diagnostyki.

## Golden / regresja

Przy każdej zmianie zachować porównanie z poprzednim poprawnym stanem.

Minimum:
- frame 30,
- frame 300,
- frame 900,
- frame count,
- FIT,
- GPMF,
- map,
- date/time,
- HUD alpha/color,
- base video color,
- audio,
- AMF drops.

Jeżeli zmiana dotyczy konkretnego widgetu, preferowane jest porównanie wszystkich 1131 klatek tego widgetu.

Jeżeli można osiągnąć pixel-identical wynik, traktować to jako preferowane kryterium.

## Zasady zmian

1. Nie modyfikuj NVIDIA podczas prac AMD.
2. Nie implementuj Intel w ramach etapów AMD.
3. Nie wykonuj szerokich refactorów bez potrzeby.
4. Jedna duża zmiana architektoniczna na etap.
5. Zachowuj reference/fallback przed usunięciem starej ścieżki.
6. Nie usuwaj działającej diagnostyki — wyłączaj jej koszt w produkcji.
7. Nie wprowadzaj CPU round-trip dla bazowego obrazu.
8. Nie przywracaj pełnego CPU blend HUD.
9. Nie zmieniaj jakości AMF tylko po to, aby pokazać lepszy FPS.
10. Nie zmieniaj rozdzielczości HUD bez osobnego etapu i A/B.
11. Nie deklaruj PASS bez realnego eksportu GUI.
12. Nie ufaj starym raportom, jeśli aktualny kod mówi coś innego.

## Build natywnej DLL

Natywna DLL AMD musi być zawsze budowalna deterministycznie z repo.

Target:

```text
telem_amd_native
```

Przy zmianach ABI:
- zwiększ ABI świadomie,
- aktualizuj Python ctypes binding,
- loguj absolute DLL path,
- loguj build ID,
- nie pozwalaj GUI załadować przypadkowej DLL z PATH/CWD.

## Co jest obecnie największym obszarem do poprawy

GPU pipeline bazowego obrazu jest już w dużej mierze docelowy.

Największy potencjał wydajności pozostaje po stronie CPU HUD:
- `compose_overlay()`,
- map renderer,
- cadence / heart-rate charts,
- regionalne przygotowanie HUD buffer,
- część operacji Pillow `alpha_composite`, `paste`, `copy`, `crop`.

Nie wracaj do optymalizacji decode/D3D11VA bez wyraźnego dowodu regresji albo nowego bottlenecku.

## Docelowy kierunek

Docelowy TeleM powinien:
- dekodować sprzętowo na NVIDIA / AMD / Intel,
- utrzymywać bazowe klatki w pamięci GPU,
- minimalizować GPU→CPU→GPU,
- generować możliwie mało danych HUD na CPU,
- uploadować tylko zmienione regiony HUD,
- używać sprzętowego kodowania,
- zachowywać identyczną synchronizację FIT/GPMF/video,
- mieć osobne zoptymalizowane backendy sprzętowe bez regresji funkcjonalnej.

Dla AMD obecna ścieżka D3D11VA → VP → GPU HUD → AMF jest bazą, której nie należy już burzyć.

## Styl pracy agenta

Przed zmianą:
1. przeczytaj aktualny kod,
2. potwierdź aktywną produkcyjną ścieżkę,
3. zmierz obecny koszt,
4. określ dokładne kryterium PASS.

Po zmianie:
1. wykonaj test krótki,
2. wykonaj realny pełny eksport,
3. porównaj golden,
4. zmierz TRUE FPS,
5. podaj frame accounting,
6. zatrzymaj się po zakresie zadanego etapu.

Nie rozpoczynaj kolejnego etapu bez wyraźnego polecenia.
