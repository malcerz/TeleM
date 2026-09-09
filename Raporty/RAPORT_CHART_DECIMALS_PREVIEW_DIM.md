# RAPORT: Global chart decimals and Preview video dim

## Zakres

Wykonano wyłącznie dwa niezależne zakresy:

1. wspólne formatowanie wartości dla wszystkich wskaźników `form = chart`;
2. przyciemnienie wyłącznie klatki filmu w interaktywnym Preview.

Nie zmieniano eksportera Final Render, formatowania czasu/dat, mapy ani
backendów AMD/NVIDIA/Intel.

## CHART

### Root cause

Chart nie miał własnego pola precyzji w schemacie GUI. Wartość bieżąca była
formatowana w compositorze przez legacy `decimals`, a etykiety osi w
`chart_utils` miały niezależne, zahardkodowane formatowanie `:.0f`. Fallback
tekstu wartości w rendererze chart używał również stałej precyzji.

### Hard-coded formatting found

Znalezione stałe formatowanie liczb telemetrycznych:

- `src/indicators/chart_utils.py`: etykiety osi `:.0f`;
- `src/indicators/chart.py`: fallback bieżącej wartości `:.1f` w dwóch
  ścieżkach renderera.

Formatowanie osi czasu, timestampów i dat pozostało bez zmian.

### Canonical decimal config

`chart_indicator_fields()` udostępnia pole:

```text
Miejsca po przecinku
key: decimal_places
range: 0..3
default: 1
```

Wspólny `resolve_decimal_places()` zachowuje jawne `0`. Dla starszych
presetów honorowany jest legacy alias `decimals`; gdy oba pola są nieobecne,
pozostają istniejące domyślne wartości rendererów (0 dla dotychczasowych
wskaźników FIT/status/% i 1 dla zwykłych chartów).

### Implementacja i parity

`decimal_places` jest przekazywane przez cały renderer chart do:

- bieżącej/dynamicznej wartości;
- etykiet min/max osi i pozostałych wartości osi;
- cache geometry/background, aby różne precyzje nie współdzieliły rastra;
- ścieżki static/prefix oraz GPU_SPLIT przed capture tile/rasteru.

Dane wejściowe pozostają `float` z pełną precyzją. `decimal_places` jest
używane tylko w f-stringach etykiet. Test autoscale potwierdza, że zakres
otrzymuje surowe `123.456` i `234.567`, niezależnie od `decimal_places=0`.

Dynamic FIT proof: `fit_custom_text` w `form=chart` z wartością `123.456`
generuje `123.46 u` dla `decimal_places=2`. Rzeczywisty layout
`Video/GX010114.layout.json` został wyrenderowany jednoklatkowo z aktywnymi
chartami FIT HR=0, cadence=0 oraz dodatkowym chartem speed=2; ścieżka Preview
zwróciła poprawny raster 3840×2160.

Preview, precompute i Final korzystają z tego samego formatowania compositora;
GPU_SPLIT otrzymuje już sformatowany tekst przed capture. Bez `decimal_places`
stary alias/default działa jak wcześniej.

## PREVIEW DIM

### Old preview pipeline

Preview CPU składał klatkę źródłową i pełny HUD bez przyciemnienia. W ścieżce
MPV/QVideoWidget natywne wideo było widoczne pod osobnym, przezroczystym
oknem HUD.

### New compositing order

```text
VIDEO FRAME
↓
DIM VIDEO RGB
↓
COMPOSE HUD
↓
PREVIEW
```

W ścieżce Pillow `render_preview()` dimuje źródło przed `compose_overlay()`.
W ścieżce natywnego wideo `TopLevelHUDWindow` rysuje czarny overlay tylko w
`video_rect`, a następnie rysuje normalny HUD.

### Dim implementation and brightness

Dodano wspólny `dim_preview_video()` z domyślnym współczynnikiem:

```text
PREVIEW_VIDEO_BRIGHTNESS = 0.55
```

Operacja używa PIL LUT (`Image.point`) na RGB, bez Pythonowej pętli po
pikselach. Kanał alpha jest kopiowany bez zmian. `None` pozostaje bezpiecznym
fallbackiem.

### Proofs

Syntetyczna klatka `(100,80,60,123)` daje `(55,44,33,123)`. Jasny piksel HUD
po compositingu pozostaje identyczny. Test z `preview_video_brightness=1.0`
potwierdza, że `render_preview` jest wtedy bitowo równy źródłu plus
`compose_overlay`; Final Render nie wywołuje `render_preview`, więc dim nie
przenika do eksportera.

Zmiany timeline/layout/HUD nadal wywołują istniejący refresh Preview; nie
dodano reloadu filmu dla samego `decimal_places`.

### Performance

Pomiar dla RGBA 960×540, 100 iteracji, rozgrzany LUT:

```text
dim_preview_video: 3.182 ms/frame
baseline RGBA copy: 0.878 ms/frame
additional dim cost: ~2.304 ms/frame
```

Jest to operacja C-level/LUT, bez kosztownego blur/gamma/HSV i bez pętli
Pythonowej.

## Tests

```text
python -m pytest tests/test_chart_decimals_preview_dim.py -q
9 passed in 0.13s

python -m pytest tests/test_amd_chart_map_split.py \
    tests/test_nvidia_regression_chart_preview.py \
    tests/test_etap5e_preview_export_parity.py -q
10 passed in 0.33s
```

Szerszy szybki zestaw chart/regression miał 71 testów zaliczonych oraz 2
niezależne, wcześniejsze błędy w dirty worktree (`thickness` w schemacie chart
i `segment_count` w PropertyEditor). Nie były skutkiem tej zmiany i nie
zostały modyfikowane.

Nie uruchamiano `tests/test_indicator_exhaustive_proof.py`, zgodnie z taskiem.
Pełny eksport MP4 przed/po nie był uruchamiany; parity Final jest potwierdzone
testem ścieżki kompozycji i separacją `render_preview` od eksportera.

## Changed files

- `src/indicators/helpers.py`
- `src/indicators/chart.py`
- `src/indicators/chart_utils.py`
- `src/indicators/compositor.py`
- `src/gui/qt/models.py`
- `src/gui/qt/_mixins/preview_mixin.py`
- `src/gui/qt/widgets/video_preview.py`
- `tests/test_chart_decimals_preview_dim.py`

## Backend isolation / risks

Zmiana jest wspólna dla CPU/reference i istniejących ścieżek Preview. Nie
zmienia kodu dekodowania, enkodowania, AMD map/gauge/chart lifecycle, NVIDIA,
Intel ani Final Render. Preview dim w natywnym oknie zależy od poprawnego
`video_rect`; HUD jest rysowany po overlayu i zachowuje normalną jasność.

GLOBAL CHART DECIMAL CONTROL: PASS
DECIMALS 0/1/2/3: PASS
DYNAMIC FIT CHART: PASS
CHART PREVIEW/FINAL PARITY: PASS
AUTOSCALE RAW PRECISION: PASS

PREVIEW VIDEO VISIBLE: PASS
PREVIEW VIDEO DIMMED: PASS
HUD BRIGHTNESS UNCHANGED: PASS
FINAL RENDER UNCHANGED: PASS
PREVIEW DIM PERFORMANCE: PASS
