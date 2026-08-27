# RAPORT INTEL ETAP 4F — 10-bit REGION HUD compositor feasibility PoC (OX)

Data: 2026-08-25 | Branch: `intel-render` | HEAD: `e019a6b45278f09f718f528642767f505ea87934`
Tryb: **RESEARCH / PoC ONLY** | Commits: **brak** | Produkcja: **nietknięta**
Artefakty: `scratch/intel_etap4f/` (region_compositor.py, test_synthetic.py,
real_hud_poc.py, state_T0.json)

## Executive summary

**INTEL ETAP 4F: PoC SUCCESS — PRODUCTION NOT IMPLEMENTED.**

Zbudowano i zweryfikowano działający 10-bit REGION compositor (Candidate A:
blend w przestrzeni YUV BT.2020/pc w precyzji ≥10-bit, modyfikujący wyłącznie
obszar HUD):

```text
OUTSIDE_HUD_BASE_MODIFICATION = 0   (Y i UV, max diff = 0, real GX020079 frame)
```

— dokładnie cel etapu. Realny TeleM REGION HUD (produkcyjny
`frame_renderer` + `get_layout_hud_bbox`) po blendzie daje wewnątrz HUD
zgodność z obecną ścieżką na poziomie szumu HEVC (Y MAD 2.47 lvl10,
korelacja 0.9998, średnie U/V identyczne — zero hue shift).

Implementacja produkcyjna NIE została wdrożona: PoC numpy wykonuje blend w
187 ms/frame (cel produkcyjny <8 ms) przez pełno-ramkowe kopie robocze —
wydajność wymagałaby przepisania na in-place/uint16/region-only buffers, a
integracja wymaga przeprojektowania przepływu „region base ↔ compositor"
(patrz Integration feasibility). To zgodne z §29 (custom compositor = osobny
etap).

## State pinning

T0: `scratch/intel_etap4f/state_T0.json` — branch `intel-render`,
HEAD `e019a6b…`, SHA-256 streaming/command_builder/frame_renderer/test_video_helpers.
Working tree stabilny; produkcja T_final == T0 (weryfikacja na końcu).
FFmpeg: `2026-08-17-git-426841da9d-full_build-www.gyan.dev`.

## Current problem

Software `overlay` (ETAP 4E): `p010le → yuva420p(8-bit) → blend → p010le`
na CAŁEJ ramce ⇒ `OUTSIDE_HUD_BASE_MODIFICATION != 0`
(Y 75% px ≠0; V do 282 lvl10). `overlay_qsv` P010 zdyskwalifikowany (4D).

## Fidelity target

Poza logicznym HUD (+ co najwyżej 1 chroma-cell ring):
`Y diff = 0, U diff = 0, V diff = 0` pre-encode vs REF.

## Candidate architectures

| Kand. | Opis | Decyzja |
|---|---|---|
| A — 10-bit YUV region blend | HUD RGBA→YUV(BT.2020/pc) per-region, blend w int/float ≥10-bit, write-back regionu | **WYBRANY** (najbliżej semantyki overlay; zero RGB roundtrip całości) |
| B — high-precision RGB region blend | region p010→RGB16→composite→p010 | odłożony: wymaga jawnego transfer/primaries decision dla HLG (ryzyko rozjazdu z obecną semantyką); A osiągnęło cel |
| C — existing library primitive | PIL/numpy wystarczą (numpy wybrany — używany przez projekt) | spełnione przez A |

## Selected PoC design

`scratch/intel_etap4f/region_compositor.py`:

- wejście: raw p010le frame (bytes) + HUD RGBA (np. H×W×4) + bbox origin,
- plany 10-bit: Y (H,W) oraz UV (H//2, W) interleaved pary (U,V),
- luma: `out = round(hud_y*a + base_y*(1-a))` per piksel,
- chroma: box-average 2×2 RGBA (RGB i alpha osobno) → konwersja BT.2020 →
  `out_uv = round(hud_uv*a_cell + base_uv*(1-a_cell))` per komórka,
- write-back wyłącznie okna bbox/chroma; reszta planów kopiowana 1:1,
- kill-property: brak jakichkolwiek operacji poza oknem (testowane).

## Pixel math / color-space math

Macierz BT.2020 (KR=0.2627, KG=0.6780, KB=0.0593), **full range (pc)**,
skala 10-bit (×1023) — odwzorowanie semantyki stwierdzonej w negocjacji
obecnego overlay (`csp:bt2020nc range:pc`, ETAP 4D/4E logi). Bez tone-mappingu,
bez konwersji primaries/transferu (§11).

## Chroma coordinate handling

`cx0=floor(bx/2)`, `cy0=floor(by/2)`; liczba komórek:
`cw=ceil((bx+bw)/2)-cx0`, `ch=analogicznie`; okno planu (interleaved):
kolumny `[2*cx0, 2*(cx0+cw))`. Przypadki testowane: parzyste/nieparzyste
origin, edge-of-frame (clamp do granicy). Uwaga: wcześniejszy błąd
jednostek (jak w overlay_qsv) został tu wychwycony własnym testem
(niezgodność expected/got wskazała pary U/V vs sample).

## Alpha handling

Alpha 0/0.25/0.5/0.75/1.0 + kolory white/black/red/green/blue/gray:
formuła `out=round(hud*a+base*(1-a))` zweryfikowana ±1 lvl10 na Y/U/V;
alpha=0 ⇒ ramka bit-to-bit identyczna; alpha=1 ⇒ czysta konwersja HUD;
AA-krawędzie tekstu = naturalne uśrednienie alfa w komórce 2×2.
Normalizacja alfy (/255) była źródłem jednego buga PoC — wykryty testem.

## Synthetic test results

`test_synthetic.py` — ALL PASS (exit 0):

| test | outside Y | outside U | outside V | inside HUD |
|---|---|---|---|---|
| even bbox @ (100,100) | 0 | 0 | 0 | formuła ±1 lvl10 ✓ |
| half-size @ (50,50) | 0 | 0 | 0 | ✓ |
| odd origin (101,103) | 0 | 0 | 0 | ✓ |
| edge-of-frame | 0 | 0 | 0 | ✓ |
| alpha=0 | ramka bit-identyczna | — | — | n/a |
| alpha=1 kolory ×6 | — | — | — | Y/U/V = konwersja BT.2020 ±1 ✓ |
| alpha sweep 0.25/0.5/0.75 | — | — | — | formuła ±1 ✓ |
| pack/unpack p010 | low-6-bits=0, range 0..1023 | | | |

## Real HUD results

Prawdziwy REGION TeleM: `frame_renderer.render_overlay_frame` z
`init_worker(hud_bbox=get_layout_hud_bbox(...))` na syntetycznej telemetrii:

```text
bbox=(3032,240,808,1700) canvas RGBA 808x1700
OUTSIDE: Y max diff = 0 | UV max diff = 0   (pre-encode, real GX frame)
```

Porównanie inside vs obecna produkcja (cur_gx.mp4 f0 post-encode,
identyczny layout/telemetria):

```text
Y: MAD=2.47 lvl10, p99=10, corr=0.9998      (= szum HEVC + AA downsampling)
U/V MAD=1.1/1.0 lvl10; średnie U/V identyczne (519/519, 495/495)
```

Wniosek: **HUD visually correct**, zero hue shift, zero alpha artifacts.

## Pre-encode parity

Outside parity liczona pre-encode (raw p010). Inside porównanie zawiera
szum enkodu referencyjnego (poza-HUD noise tej samej pary = 2.43 lvl10,
czyli wewnątrz różnice są na tym samym poziomie co szum).

## Performance

| wariant | wall/FPS | compositor ms/f | region conv ms/f | copy-back ms/f |
|---|---|---|---|---|
| current FFmpeg overlay | 24.2 FPS (overlay ≈1.7% wall) | ~0 (w C) | — | — |
| PoC numpy compositor | nie mierzono end-to-end | **187** | zawarte | zawarte |

187 ms/f (region 808×1700) = forma badawcza (float32, pełno-ramkowe kopie
robocze int32, pack/unpack całości). Produkcyjnie osiągalne <8 ms/f po
przepisaniu: in-place uint16 na buforach pipe, operacje tylko na oknie
regionu (~1.4 Mpx), ewentualnie numba/C — ale to już implementacja.

## Memory traffic

PoC (badawczo): 2 pełno-ramkowe kopie robocze int32 (~39 MB @4K) +
pack/unpack (~50 MB) ⇒ ~90 MB/frame narzutu — NIE akceptowalne produkcyjnie.
Docelowy kształt produkcyjny: bufor ramki już istnieje w workerze/pipe;
compositor dotyka wyłącznie bboxa (luma ~1.4 MB + chroma ~1.4 MB uint16 na
klatkę dla mierzonego bboxa) ⇒ brak drugiej pełnej kopii 4K.

## Integration feasibility

Kluczowa przeszkoda architektury: worker renderujący HUD **nie ma dostępu do
pikseli bazy** (baza przepływa wewnątrz procesu FFmpeg). Region-blend wymaga
albo (i) zwrócenia cropped-base z filtergraph do compositora i paste-back
(nowy dwukierunkowy przepływ), albo (ii) przeniesienia całego composite do
FFmpeg — a ten nie umie 10-bit alfy. Ocena:

```text
implementation complexity : MEDIUM-HIGH
regression risk           : MEDIUM (dotyka ścieżki writer/pipe CPU_REFERENCE)
maintenance cost          : MEDIUM (własny kod kolorów 10-bit)
```

## Production implementation

**NOT IMPLEMENTED** (research/PoC only zgodnie z nagłówkiem zadania;
dodatkowo warunek wydajności §17 niespełniony przez PoC-as-is).

## Risks

1. Wydajność Python/numpy — bez optymalizacji dyskwalifikuje wdrożenie.
2. Wymagany przepływ „base region → compositor → back" to zmiana architektury
   pipe (§14: docelowo HUD worker, po decyzji architektury).
3. Różnica downsamplingu chromy HUD (box 2×2 vs swscale) — wewnątrz HUD na
   poziomie szumu; do percepcyjnej akceptacji przy wdrożeniu.

## Quality value

**REALNY I UNIKALNY**: jedyna znana metoda uzyskania
`OUTSIDE_HUD_BASE_MODIFICATION = 0` dla HDR (usuwa globalną degradację
chromy/lumy poza HUD obecnego overlay). Wartość czysto jakościowa.

## Performance value

**BLISKI ZERU**: overlay kosztuje 1.7% wall (ETAP 4E); PoC-as-is byłby
wolniejszy. Motywacja tego etapu jest jakościowa — i tak trzeba to czytać.

## Recommendation

Jeden następny krok: osobny etap projektowy „region round-trip" — prototyp
przepływu `crop(base,bbox) → worker blend(10-bit) → paste` z buforem
in-place uint16 i celem <8 ms/f, z decision gate na koszty integracji
(MEDIUM-HIGH). Bez pozytywnej decyzji — pozostać przy obecnym fallbacku.

## Final verdict

**INTEL ETAP 4F: PoC SUCCESS — PRODUCTION NOT IMPLEMENTED**

