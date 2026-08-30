# TeleM — RENDER ETAP: audyt rozdzielczości HUD + skala 100/75/50%

## Wynik

Dodano ustawienie `Rozdzielczość HUD` bezpośrednio pod `Częstotliwość HUD`:

- `100%` -> `1.0` (domyślne i zgodne ze starymi konfiguracjami),
- `75%` -> `0.75`,
- `50%` -> `0.5`.

Ustawienie jest niezależne od częstotliwości HUD i rozdzielczości eksportu.

## Aktualny tor standardowego eksportu

```text
źródło / dekoder
    -> FFmpeg skaluje bazowy obraz do render_w x render_h
    -> Python compositor rasteruje HUD do overlay_w x overlay_h
    -> pipe RGBA / SHM / atlas regionów
    -> FFmpeg skaluje overlay do render_w x render_h
    -> compose overlay z obrazem bazowym
    -> encoder CPU / Intel / AMD-AMF / NVIDIA
```

Wcześniej `RenderMixin` ograniczał canvas HUD do maksymalnie 1920 px szerokości. Oznaczało to np. dla eksportu 4K raster HUD 1920×1080, niezależnie od wybranej rozdzielczości. Dla eksportu 480p był to już canvas 854×480.

Po zmianie canvas jest liczony od rozdzielczości eksportu:

```text
overlay_w = render_w * hud_resolution_scale
overlay_h = render_h * hud_resolution_scale
```

Wymiary są zaokrąglane do wartości parzystych dla bezpiecznej pracy z filtrami YUV/GPU. Przykład dla `480p = 854×480`:

| Skala | Raster HUD | Canvas wyjściowy |
|---:|---:|---:|
| 100% | 854×480 | 854×480 |
| 75% | 640×360 | 854×480 |
| 50% | 428×240 | 854×480 |

Geometria procentowa layoutu, map, wykresów, gauge’y i tekstów jest liczona względem mniejszego canvasu, a następnie cały overlay jest powiększany przez istniejący tor FFmpeg. Main Preview pozostaje bez zmiany; Export Preview stosuje ten sam model: render niskiej rozdzielczości i powiększenie do rozmiaru podglądu.

## Diagnostyka

Standardowy eksport wypisuje raz na uruchomienie:

```text
[HUD Resolution] scale=0.50 canvas=428x240 output=854x480
```

Pozwala to rozstrzygnąć rzeczywisty rozmiar rastra bez wnioskowania ze źródła wideo.

## Backend coverage

- CPU, Intel/QSV, standardowy AMD/AMF i NVIDIA korzystają ze wspólnego parametru canvasu overlayu; ich backendowe filtry/enkodery nie zostały zmienione.
- AMD_NATIVE_D3D11 ma osobny, natywny compositor i osobny kontrakt bufora HUD. Został objęty audytem statycznym, ale nie był przebudowywany w tym etapie, ponieważ wymagałoby to zmiany chronionego natywnego toru D3D11 oraz jego dirty-region/upload semantics.
- Brak runtime-testów na AMD/NVIDIA/Intel w tej sesji; ścieżki vendorowe zachowano statycznie.

## Walidacja

- `51 passed, 1 deselected` dla testów RenderTab, filtrów FFmpeg i nowego kontraktu skali HUD.
- `py_compile` dla zmienionych modułów: OK.
- Wyłączony z tego wyniku test `test_encoder_fallback_on_unsupported_gpu` jest niezwiązany ze zmianą i nie przechodził, ponieważ testowa detekcja zwróciła `nv` zamiast oczekiwanego `amd`.
- Nie wykonano długiego eksportu 4K ani fizycznego testu GUI.

## Benchmarki

Nie wykonano benchmarku na wskazanym materiale 4K w tej sesji. W repozytorium nie ma materiału użytego do zlecenia, więc nie podaję pomiarów jako nowych wyników.

Oczekiwany kompromis: 75% rasteru to około 56% pikseli HUD względem 100%, a 50% to około 25%; powiększenie końcowe może zmniejszyć ostrość drobnego tekstu i cienkich linii.
