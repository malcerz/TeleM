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

---

## Akceleracja sprzętowa dla wszystkich GPU (NVIDIA / AMD / Intel)

### Wymagania

Oprócz `libmpv-2.dll` w katalogu głównym projektu **konieczny jest też
binding `python-mpv`** — bez niego aplikacja nie używa mpv i spada na
wolny fallback (OpenCV/QMediaPlayer), co daje rozpikselowany podgląd
kilka FPS.

```
python -m pip install python-mpv
```

### Problem

W poprzedniej wersji mpv było inicjalizowane z `hwdec='auto'` i domyślnym
kontekstem GPU.  Na maszynach z AMD działało to poprawnie (d3d11va aktywne),
ale na niektórych systemach NVIDIA mpv cicho spadało do **dekodowania
programowego** (software fallback), co objawiało się szarpaniem klatek
i wysokim użyciem CPU.

### Rozwiązanie

1. **Moduł `mpv_hwdec.py`** (`src/gui/qt/mpv_hwdec.py`)
   - Detekcja GPU przez PowerShell (`Win32_VideoController`) → mapowanie vendorów (`nv`, `amd`, `intel`).
   - `build_mpv_options(vendor)` — buduje kwargs dla `mpv.MPV(...)` z jawnie wymuszonym `gpu-api=d3d11` / `gpu-context=d3d11` (z fallbackiem `opengl`/`win`), co gwarantuje, że `d3d11va` (lub `nvdec`/`cuda` na NVIDIA) może się zainicjalizować.
   - Per-vendor łańcuch hwdec: `d3d11va,nvdec,cuda,auto` (NV), `d3d11va,dxva2,auto` (AMD/Intel).

2. **Kontroler** (`controller.py`)
   - `set_video_widget()` używa `build_mpv_options(self.mpv_preview_vendor)`.
   - `reinit_mpv(vendor)` — restart playera po zmianie wyboru GPU z UI.
   - `_check_mpv_hwdec()` — weryfikacja ~1.5s po załadowaniu pliku:
     odczytuje `hwdec-current`, `current-gpu-context`, `video-params/pixelformat`,
     loguje ostrzeżenie jeśli aktywne jest dekodowanie programowe.

3. **UI — wybór akceleratora** (`load_tab.py`)
   - Pod przyciskami `[Wczytaj] [Wyczyść]` w zakładce **Wczytywanie**
     znajduje się combo `Podgląd GPU: [Auto ▼]` z listą wykrytych GPU
     oraz opcją `CPU (software)`.
   - Zmiana emituje `sig_preview_accel_changed` → kontroler re-inicjalizuje mpv.

### Weryfikacja działania

Uruchom aplikację, załaduj wideo i sprawdź konsolę:

```
[Controller] MPV zinicjalizowany pomyślnie (GPU: NVIDIA, hwdec=d3d11va,nvdec,cuda,auto)
[MPV HW] Dekodowanie sprzętowe aktywne: d3d11va
          interop=auto-auto, vo=gpu, gpu_ctx=d3d11, fmt=d3d11_nv12
```

Jeżeli widzisz `[MPV HW] OSTRZEŻENIE: Dekodowanie PROGRAMOWE` — zmień GPU
w combo podglądu lub sprawdź sterowniki karty graficznej.
