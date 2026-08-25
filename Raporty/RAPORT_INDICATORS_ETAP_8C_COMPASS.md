# TeleM — ETAP 8C: Compass oparty o kanoniczne `heading`

Data: 2026-08-21.

## 1. Zakres zmian

Dodano konfigurowalny wskaźnik `compass`, korzystający wyłącznie z kanonicznego pola `heading` z ETAPU 8B. Nie dodano nowej telemetrii, algorytmu COG, Track-Up, Slope ani Lean.

## 2. Architektura

Compass jest lokalnym rozszerzeniem `src/indicators/gauge.py`, aktywowanym wyłącznie przez jawne `gauge_style: "compass"` (alternatywnie `gauge_mode`). Zwykły gauge, w tym `fit_enhanced_speed_text`, zachowuje dotychczasową ścieżkę.

Renderer otrzymuje gotową wartość `heading`; nie zna GPS, FIT, GPMF, GPX, priorytetów źródeł ani matematyki bearingu. Binding `compass -> heading` dodano do istniejącego planu zależności, `frame_data`, precompute/cache i finalnego renderera.

## 3. Compass semantics

Konwencja geograficzna: `0° = North`, `90° = East`, `180° = South`, `270° = West`. Wartość jest normalizowana lokalnie do `[0, 360)`. Renderer nie wykonuje smoothingu ani interpolacji.

## 4. Wybrany model

Wybrano wariant A: nieruchoma tarcza z `N/E/S/W`, tickami i stałą geometrią oraz wskazówką obracaną przez absolutny `heading`. To najmniejsza zmiana zgodna z istniejącym gauge i bez semantyki Track-Up.

## 5. Cardinal labels

Obsługiwane są `N`, `E`, `S`, `W`. Subticki są co 15°, a główne ticki co 45°. Etykiety kardynalne mają osobny, mocniejszy kolor.

## 6. Heading text

Domyślny format to trzy cyfry: `005°`, `027°`, `180°`. Property `compass_heading_format` wybiera `03d` albo `d`; formatter jest lokalny dla Compass.

## 7. Missing heading behavior

Przy `heading=None` tarcza pozostaje widoczna, wskazówka nie jest rysowana, a wartość to `--°`. `None` nie jest traktowane jako 0°/North.

## 8. GUI properties

Wykorzystano istniejące pola wspólne gauge: enabled/toggle, x, y, size, rotation, font, label, source, form i unit. Dodano tylko pola Compass: `field=heading`, `gauge_style=compass`, opacity, widoczność kardynałów i headingu, format, odstęp ticków oraz kolory tarczy, ticków, kardynałów, wskazówki i wartości. Źródło GPMF/FIT/GPX korzysta z istniejącego dropdownu.

## 9. Preset v4

Utworzono `presets/cycling_dashboard_v4.json` na bazie v3. v1/v2/v3 nie zostały zmienione. Jedyną zmianą funkcjonalną v4 jest Compass:

| Property | Wartość |
|---|---|
| key | `compass` |
| form/style | `gauge` / `compass` |
| field/source | `heading` / `gpmf` |
| x/y | `70.65` / `20.0` |
| size | `7.8` |
| rotation/opacity | `0` / `1.0` |
| ticks | subtick 15°, major 45° |
| cardinals/text | N/E/S/W enabled, `03d`, `°` |
| z-order | po `track_map` w kolejności layoutu; AMD: `CPU_ABOVE_MAP` |

Średnica wynosi około 403 px przy 3840×2160 i pozostawia odstęp od virtual power, mapy i speed gauge.

## 10. CPU rendering

Zapisano `Raporty/INDICATORS_ETAP_8C_COMPASS_CPU_FRAME.png`, `Raporty/INDICATORS_ETAP_8C_COMPASS_OVERLAY.png` oraz `Raporty/INDICATORS_ETAP_8C_COMPASS_STANDALONE.png`. CPU frame jest deterministycznym fixture 3840×2160 z headingiem GPMF dla 20 s (`324.17°`, display `324°`) i reprezentatywnymi pozostałymi wartościami. Overlay jest transparentny.

## 11. Bbox / clipping

W renderze 3840×2160 bbox Compass wyniósł `(2512, 231, 403, 403)`. Tarcza, ticki, kardynały, wskazówka i heading text mieszczą się w obrazie. Virtual power kończy się na x=2507, Compass zaczyna na x=2512, a przewidywany region mapy zaczyna się na x=2918; Compass kończy na x=2915. Nie zmieniano globalnego dirty-bbox marginu.

## 12. Heading validation 20/60/120

Źródło: `Video/GX030120.MP4` / `GX030120.json`; parametry ETAPU 8B: 5 m, lookback 5 s, próg 1 km/h, circular smoothing 2 s.

| Czas | GPMF | Compass CPU | Compass AMD probe |
|---:|---:|---:|---:|
| 20 s | 324.17° | `324°` | CPU_REFERENCE, `324°` |
| 60 s | 27.04° | `027°` | ta sama semantyka |
| 120 s | 0.54° | `001°` | ta sama semantyka |

Renderer sprawdzono także dla `0, 45, 90, 135, 180, 225, 270, 315, 359°`.

## 13. FIT source validation

Dla dopasowanego `Video/Poranna_jazda_na_rowerze.fit` użyto własnego zsynchronizowanego GPS tracku:

| Czas | FIT heading | Display |
|---:|---:|---:|
| 20 s | 324.34° | `324°` |
| 60 s | 24.68° | `025°` |
| 120 s | 2.02° | `002°` |

Nie użyto niedopasowanego pliku popołudniowego.

## 14. AMD behavior

Krótki runtime probe `AMD_NATIVE_D3D11` z v4 i startem telemetrycznym +20 s zakończył się sukcesem (`telem_amd_native.dll`, AMF/MediaFoundation/D3D11VA): `AMD_MAP_PATH=GPU`, `AMD_CHART_PATH=GPU_SPLIT`, `AMD_GAUGE_PATH=GPU`, `AMD_TELEMETRY_MODE=PRECOMPUTED`. `AMD_MAP_ORDER` zawierał `CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP`, z Compass po mapie.

Compass nie ma specjalnego renderera AMD. Jest CPU_REFERENCE w `CPU_ABOVE_MAP` i zachowuje semantykę CPU. `INDICATORS_ETAP_8C_COMPASS_AMD_FRAME.png` jest CPU_REFERENCE parity fixture, nie deklaracją GPU rasteru. Tymczasowy MP4 probe usunięto po walidacji.

## 15. GPU gauge/fallback

Nie zmieniano guarda AMD GPU gauge. Aktualna optymalizacja GPU nadal identyfikuje `fit_enhanced_speed_text`; Compass nie jest dopisywany do GPU capture key. Probe z minimalnym FIT speed streamem zalogował `GPU gauge fallback -> CPU_REFERENCE (gauge not rendered)`, bo nie miał aktywnego renderowanego FIT speed gauge. Nie był to fallback wywołany obecnością Compass. Testy gauge i AMD potwierdzają zachowanie zwykłego gauge.

## 16. NVIDIA static analysis

Nie zmieniono `streaming.py`, `command_builder.py`, CUDA, NVENC ani kodu NVIDIA. Wspólna CPU overlay path zachowuje bbox, rotację i clipping bez specjalnego kodu NVIDIA.

**NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.**

## 17. Performance

Bezpośredni pomiar lokalnego rasteru Compass przy 3840×2160 dał medianę około `0.62 ms`. Nie dodano transferu GPU→CPU→GPU ani własnego smoothingu. AMD probe raportował pełny `compose_overlay` około `1.0 ms` dla 1280×720; nie jest to izolowany benchmark wszystkich wskaźników.

## 18. Testy

- Compass + gauge: **32 passed**;
- heading/map/chart regression: **25 passed**;
- `python -m pytest -q --ignore=tests/test_fit_registration.py`: **604 passed, 17 skipped**;
- `py_compile` zmienionych modułów: OK;
- runtime AMD Native v4 probe: sukces, AMF encode i remux OK.

`tests/test_fit_registration.py` pominięto z powodu istniejącego błędu kolekcji `ModuleNotFoundError: src.gui.hud_tuner_app`; nie został wprowadzony przez ETAP 8C.

## 19. Lista zmienionych plików

ETAP 8C dotyczy: `src/indicators/gauge.py`, `src/indicators/compositor.py`, `src/indicators/frame_data.py`, `src/telemetry_precompute.py`, `src/ffmpeg/frame_renderer.py`, `src/indicators/registry.py`, `src/gui/indicator_schemas.py`, `src/gui/qt/models.py`, `src/gui/qt/_mixins/indicator_mixin.py`, `presets/cycling_dashboard_v4.json` oraz `tests/test_compass_rendering.py`. Raport i artefakty zapisano w `Raporty/`.

## 20. Remaining risks

- runtime NVIDIA nie był dostępny;
- Compass pozostaje CPU_REFERENCE na AMD, co jest zamierzonym fallbackiem parity;
- probe AMD był krótkim renderem 1280×720 i nie zastępuje długiego eksportu;
- brak realnego GPX oznacza brak runtime walidacji GPX;
- przy wielu konsumentach `heading` z różnymi źródłami warto w przyszłości rozdzielić per-consumer source cache.

Track-Up, Slope i Lean nie zostały zaimplementowane. AMD/NVIDIA pipeline, decoder/encoder selection, map renderer i heading algorithm nie zostały przebudowane.
