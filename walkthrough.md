# Walkthrough: Wdrożenie Odtwarzacza MPV z Akceleracją Sprzętową w TeleM

Zintegrowano wysokowydajny silnik odtwarzania wideo `libmpv` (z pełną akceleracją sprzętową kart graficznych NVIDIA/Intel/AMD) z istniejącym interfejsem PySide6 projektu TeleM.

## Główne Zmiany

### 1. Kontroler Aplikacji (`controller.py`)
- Zaimplementowano dynamiczną inicjalizację `mpv_player` (`mpv.MPV`) podczepianą pod uchwyt okna (window handle `wid`) z parametrem `hwdec='auto'` do dekodowania sprzętowego.
- Zaimplementowano mechanizm sprawdzania dostępności biblioteki `mpv` (`is_using_mpv`). W przypadku jej braku w systemie, aplikacja bezproblemowo powraca do domyślnego mechanizmu `QMediaPlayer` (fallback).
- Zintegrowano sterowanie MPV z mechanizmem osi czasu, wczytywaniem wideo, pauzą oraz omijaniem wyciętych regionów (`_skip_cut_regions`).
- Zoptymalizowano `_render_preview` w trybie MPV – ponieważ wideo jest rysowane bezpośrednio przez GPU, CPU generuje wyłącznie przezroczyste klatki nakładki HUD w formacie RGBA ( Format_RGBA8888), co drastycznie obniża zużycie energii i obciążenie procesora.

### 2. Podgląd Wideo (`video_preview.py`)
- Dodano klasę `TopLevelHUDWindow` – jest to niezależne, w pełni przezroczyste okno systemowe lewitujące nad widokiem wideo. Dzięki temu natywny bufor DirectX wideo nie zasłania rysowanych wskaźników telemetrycznych (pulsu, kadencji, map i prędkościomierza).
- Dodano mechanizm autopozycjonowania nakładki `hud_overlay` – okno nakładkowe automatycznie synchronizuje swoją geometrię przy zmianie rozmiaru oraz przemieszczaniu okna głównego aplikacji (poprzez `showEvent`, `resizeEvent` oraz filtr zdarzeń okna rodzica).
- Zoptymalizowano hit-testing myszy – zdarzenia kliknięcia i przeciągania wskaźników telemetrycznych są przechwytywane przez filtr zdarzeń bezpośrednio na oknie pod wideo (dzięki transparentności wejściowej okna HUD), co pozwala na precyzyjną interakcję.

## Weryfikacja Działania
1. **Odtwarzanie:** Filmy 4K/8K ładują się i odtwarzają płynnie na karcie graficznej.
2. **Nakładka HUD:** Wskaźniki są stale widoczne, nie mrugają i nie są zasłaniane przez wideo.
3. **Stabilność:** Wycofywanie się do trybu CPU-fallback (QMediaPlayer) działa poprawnie, gdy moduł `mpv` jest nieobecny.
