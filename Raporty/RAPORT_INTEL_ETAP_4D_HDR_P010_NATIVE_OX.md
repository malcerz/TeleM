# RAPORT INTEL ETAP 4D — HDR/P010 NATIVE: audyt + warunkowa implementacja (OX)

Data: 2026-08-25 | Branch: `intel-render` | HEAD: `e019a6b45278f09f718f528642767f505ea87934`
Tryb: audit + conditional implementation | Commits: **brak**
Artefakty: `scratch/intel_etap4d/` (PoC logi, md5, diffmap, state_T0)

## Executive summary

**INTEL ETAP 4D = INVESTIGATED — NOT IMPLEMENTED.**

QSV P010 decode i P010 GPU-residency zostały **zweryfikowane pozytywnie** (TEST 1/2),
a metadata HDR przechodzą automatycznie. Jednak **TEST 4 wykrył twardy defekt
geometryczny `overlay_qsv` z głównym wejściem P010 na tym buildzie FFmpeg +
Intel driverze**: prostokąt blendingu chromy jest interpretowany w jednostkach
luma na planie chromy, więc skażona chroma obejmuje **4× większy obszar niż HUD**
(2× w każdym wymiarze), z fałszywym zabarwieniem w pierścieniu wokół overlay
(potwierdzone kontrolnym testem 4× mniejszego rect — bbox błędu skala się 1:1).

Kryterium §34 „HUD geometry correct / correct color" → **FAIL**.
Production path **nie został wdrożony**; poprawny fallback CPU_REFERENCE
pozostaje nietknięty i przetestowany na realnym materiale.

## State pinning

- T0: `scratch/intel_etap4d/state_T0.json` (branch/head + SHA-256 8 plików; stan
  zawiera niezacommitowane zmiany ETAPÓW 3B/3C/4A/4B — zgodne z poprzednimi etapami).
- Working tree był stabilny w trakcie audytu; brak obcych modyfikacji.
- FFmpeg: `ffmpeg version 2026-08-17-git-426841da9d-full_build-www.gyan.dev`
  (potwierdzone `-version`; nie aktualizowano — §5).

## Hardware

- Intel(R) UHD Graphics 730, DXGI adapter index **1**, vendor 0x8086 (4692)
- NVIDIA Quadro P400 obecna jako DXGI 0 — **NIE używana** (patrz NVIDIA isolation)

## Current baseline (zmierzony ponownie, §23)

Realny materiał `Video/GX020079.MP4` (3840×2160, HEVC Main10, HLG,
BT.2020/BT.2020NC, **full/pc range**, Display Matrix **rotation=-180**),
eksport jak użytkownik: encoder=intel, resolution=source, REGION aktywny:

```text
[INTEL] CPU_REFERENCE download format: p010le
[INTEL] Render path: CPU_REFERENCE | residency: CPU_REFERENCE
[INTEL] Fallback reason: unsupported native vertical-slice configuration
[INTEL] Decode path: SOFTWARE | HWDownload used: NO
[INTEL] HUD upload path: REGION | ratio 0.103 | bytes/frame: 3 400 992
300 frames: wall 12.41 s -> 24.18 FPS
```

Historyczne ~15 FPS dotyczyło pełno-klatkowego HUD (31.6 MiB/f); po ETAPACH
HOTFIX+4A aktualny CPU_REFERENCE osiąga **24.2 FPS** (HUD −89%). Baseline do A/B:
`baseline_gx_audit.json`.

## P010 capability audit

| Element | Wynik |
|---|---|
| QSV HEVC 10-bit decode → P010 surfaces | **VERIFIED** (TEST 1) |
| Luma zgodność decode vs SW | **bit-exact** po kompensacji rotacji kontenera |
| `vpp_qsv=transpose=reversal` vs SW vflip+hflip | **bit-exact pre-encode** (Y i UV, MAD UV=0.0) |
| `overlay_qsv` main=P010 + BGRA upload | runtime **działa**, ale: **defekt geometrii chromy** (niżej) |
| Output format po overlay_qsv | p010le ✓ |
| hevc_qsv P010 encode | ✓ (`-pix_fmt p010le`) |

### Odkrycie dodatkowe (ważne dla przyszłych etapów)

Realny plik ma **Display Matrix rotation=-180**. Ścieżka SW (CPU_REFERENCE)
autorotuje; ścieżka `-hwaccel qsv -hwaccel_output_format qsv` **nie stosuje
autorotacji** — pierwszy test porównawczy wykazał rot180 dopóki nie dodano
jawnej rotacji (`vpp_qsv=transpose=reversal`). Ewentualny future native slice
dla tego materiału MUSI obsługiwać container rotation jawnie.

## PoC command (rzeczywisty, TEST 2)

```text
ffmpeg -init_hw_device qsv=intel_qsv,child_device=1,child_device_type=d3d11va
  -hwaccel qsv -hwaccel_device intel_qsv -hwaccel_output_format qsv
  -qsv_device 1 -filter_hw_device intel_qsv -noautorotate
  -i Video/GX020079.MP4
  -f lavfi -i "color=c=red@0.5:s=800x600:r=30000/1001:d=2,format=bgra"
  -filter_complex "[0:v]vpp_qsv=transpose=reversal[base];
                   [1:v]format=bgra,hwupload=derive_device=qsv[ov];
                   [base][ov]overlay_qsv=x=100:y=100[v]"
  -map "[v]" -frames:v 10 -c:v hevc_qsv -preset veryfast -global_quality 24
  -pix_fmt p010le out.mp4   -> exit 0
```

Uwaga konfiguracyjna: `hwupload=derive_device=qsv` bez nazwanego urządzenia +
`-hwaccel qsv` bez `-hwaccel_device` daje
`Inputs with different underlying QSV devices are forbidden` — pinowanie
dekodera i uploadu do tego samego nazwanego device (jak w produkcji TeleM)
jest wymagane.

## Pixel/color parity results

| Porównanie | Wynik |
|---|---|
| QSV decode Y vs SW decode Y (po rot180 kompensacji) | **max diff = 0 (bit-exact)** |
| QSV decode UV vs SW (ta sama metoda flipa) | MAD 20.4/65536 ≈ **0.3 lvl10** — rounding/co-siting, harmless |
| base-only pre-encode: vpp_qsv reversal vs vflip+hflip | **Y i UV bit-exact (MAD=0.0)** |
| base-only post-encode (A0 vs B0, hevc_qsv) | **bit-exact 10/10 klatek (diff=0)** |

Wniosek: sam tor wideo (decode→rotacja→encode P010) jest **idealny**.

## HUD parity — DEFEKT GEOMETRII CHROMY W overlay_qsv

Pre-encode, klatka 0, pattern czerwony alpha=0.5, 800×600 @ (100,100):

- **Luma poza overlay: QSV path bit-exact vs REF (MAD=0.00, max=0)** ✓
  (ciekawostka: obecna ścieżka CPU_REFERENCE modyfikuje bazę poza HUD —
  MAD=80, max=192, 75% pikseli ≠0 — efekt konwersji formatów w filterze
  `overlay`; native jest wierniejsze źródłu niż obecny fallback)
- **Chroma poza logicznym overlay: USZKODZONA.**
  Duże odchyłki (>16 lvl10) dokładnie w prostokącie **(100..699)×(100..899)**
  na planie chromy = rect overlay podany w jednostkach LUMA. Środki:
  U 31881→30165, V 31823→39067 — przesunięcie ku czerwieni (fałszywe
  zabarwienie pierścienia wokół HUD).
- 95.13% próbek chromy poza overlay: |d|<=2 lvl10 (rounding); ~5% to rect 2×.

### Kontrolny test hipotezy (§8 pkt 8)

Overlay 400×300 @ (50,50) → bbox uszkodzonej chromy:
**rows 50–348, cols 50–449** — zgodność 1:1 z „rect w jednostkach luma na
planie chromy". Defekt deterministyczny, skaluje się z rozmiarem HUD.
Dowód wizualny: `scratch/intel_etap4d/B1_uv_diffmap.png`.

Interpretacja: composite w VPP dla main=P010 + overlay=nv12(from BGRA)
aplikuje współrzędne bez konwersji /2 dla planu chromy. To defekt
buildu/drivera, nie TeleM — ale dyskwalifikuje ścieżkę wg §34.

## Alpha analysis

- BGRA upload do QSV surface działa; global `alpha` option OK.
- Blend wewnątrz overlay: hue czerwieni zachowany (U↓/V↑ zgodnie z patternem),
  luminancja spójna.
- Ryzyko §16 (8-bit SDR HUD na 10-bit HLG) nie doczekało się oceny końcowej —
  geometryczny defekt chromy dyskwalifikuje wcześniej.
- Odnotowano: obecny CPU_REFERENCE blending też modyfikuje chromę poza HUD
  (MAD 551); przyszła decyzja jakościowa wymaga własnego testu percepcyjnego.

## Native eligibility (projekt pierwszego slice'a — NIE wdrożony)

Kontrakt §13 rozszerzony o warunki wykryte w audycie:

```text
Intel + single-file + HDR/10-bit + source resolution + rotation_degrees=0
+ no cuts + HUD active + QSV P010 decode VERIFIED
+ container_rotation == 0   (autorotacja nie działa na QSV surfaces!)
+ overlay_qsv P010 chroma geometry VERIFIED   (obecnie FAIL na tym buildzie)
```

## Production implementation

**NOT IMPLEMENTED.** Kryterium §34 niespełnione (chroma geometry corruption).
Fallback SOFTWARE decode → CPU_REFERENCE → hevc_qsv(p010le) nietknięty.

## FFmpeg graph before (= after; production unchanged)

```text
SW decode (-noautorotate jeśli container rot)
→ [0:v]format=p010le[,vflip,hflip]
→ [base][1:v]overlay=<hx>:<hy>     (HUD REGION RGBA przez pipe)
→ hevc_qsv -pix_fmt p010le
```

## Full-frame readback

**FULL_VIDEO_FRAME_GPU_TO_CPU_READBACK: YES** (w PoC native — hwdownload
całości wyłącznie do weryfikacji). Produkcja bez zmian; CPU_REFERENCE nadal
robi pełny round-trip (jego P0).

## NVIDIA isolation

**NVIDIA_USED_BY_INTEL_PIPELINE: NO** — wszystkie komendy pinują Intel
(child_device=1, qsv_device 1); zero cuda/nvdec/nvenc/*_cuda. Quadro P400
(DXGI 0) tylko enumerowana.

## Runtime test

Real `GX020079.MP4`: baseline render 300 klatek CPU_REFERENCE — PASS, exit 0,
output metadata HDR zachowane (p010le/bt2020/HLG/pc), REGION aktywny, brak
crashy. Failure/fallback (§27): eligibility odrzuca HDR → poprawny fallback,
correct output — **VERIFIED**.

## Performance

| metric | CPU_REFERENCE (aktualny) | HDR_NATIVE | delta | speedup |
|---|---|---|---|---|
| effective FPS (300f @4K source) | **24.18** | n/a — brak implementacji | — | — |
| wall (300f) | 12.41 s | n/a | — | — |
| HUD bytes/frame | 3 400 992 (REGION) | (byłby REGION upload) | — | — |
| slot_lifetime avg | 668 ms | n/a | — | — |
| ffmpeg_stdin_write avg | 31.0 ms | n/a | — | — |

Architektura native usuwałaby round-trip (potencjał dużego zysku), ale zysku
**nie mierzono** — brak poprawnego composite (defekt chromy). Nie zawyżam.

## Tests

Focused suite po etapie: **60 passed** (bez zmian — zero diffów produkcyjnych
w 4D; §28 nie ma zastosowania przy braku implementacji).

## Changed files

Brak zmian produkcyjnych. Nowe: raport + `scratch/intel_etap4d/*`
(state_T0.json, md5 dowody ×4, B1_uv_diffmap.png, baseline_gx_audit.*).

## Preserved

AMD preserved | NVIDIA preserved | SDR native preserved |
CPU_REFERENCE preserved (runtime-verified na realnym HDR) |
telemetry preserved | multi-file preserved

## Risks

1. Defekt overlay_qsv może być naprawiony w nowszym FFmpeg/driverze — audyt
   powtórzyć po aktualizacji (w tym etapie zakaz aktualizacji — §5).
2. Autorotacja nie działa na QSV surfaces — przyszły native slice musi jawnie
   obsłużyć container rotation (`vpp_qsv=transpose=reversal` jest bit-exact).
3. Obecny CPU_REFERENCE lekko narusza chromę/bazę poza HUD (konwersje w
   `overlay`); bez wpływu na decyzje 4D, warte osobnego spojrzenia.
4. Współdzielona maszyna: baseline FPS ma tolerancję ±10%.

## Next bottleneck

P0 bez zmian: round-trip CPU_REFERENCE HDR (slot_lifetime ~668 ms @4K).
Ścieżki: naprawa/obejście defektu overlay_qsv P010 (np. composite region-only
po stronie VPP z poprawnymi współrzędnymi chromy, jeśli driver pozwoli), albo
redukcja kosztów obecnej ścieżki.

## Recommendation

Jeden następny krok: **audyt konwersji w filterze `overlay` dla P010**
(stwierdziliśmy modyfikację bazy poza HUD: MAD=80) — sprawdzenie wejścia
`format=yuv420p10le` dla HUD RGBA→YUV i pominięcia zbędnych konwersji może
poprawić wierność i czas FFmpeg-side obecnej, bezpiecznej ścieżki, bez
dotykania ryzykownego VPP composite.


