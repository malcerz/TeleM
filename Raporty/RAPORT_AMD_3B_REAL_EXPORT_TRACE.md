# Raport: Diagnostyka Rzeczywistego Eksportu (AMD 3B REAL EXPORT TRACE)

## === REAL GUI EXPORT TRACE ===
- **Exporter function**: `export_amd_native_d3d11` (w pliku `src/ffmpeg/amd_native_exporter.py`)
- **Backend selected**: `AMD_NATIVE_D3D11`
- **Python module path**: `c:\_DEV\TeleM\src\ffmpeg\amd_native_exporter.py`
- **Native DLL path**: `NONE` (Używane są jedynie wywołania Python ctypes bezpośrednio do systemowego `d3d11.dll`)
- **HUD enabled**: `True`
- **Output path**: Domyślny strumień MP4 zgodny z wywołaniem w GUI.

---

## 4 Punkty Kontrolne (Frame 30)

Zgodnie z poleceniem, przeprowadzono ścisłą weryfikację na RZECZYWISTYCH danych z GUI:

- **01 Python compose_overlay**: **HUD VISIBLE** (Zwraca prawidłowy, wyrenderowany obraz HUD z telemetrią GPMF).
- **02 Bridge input**: **HUD EMPTY** (Przed moją poprawką diagnostyczną. Obraz z `compose_overlay` nie był przenoszony do docelowego bufora).
- **03 D3D11 HUD texture**: **HUD EMPTY** (Ponieważ bufor był pusty, aktualizacja przez `UpdateSubresource` wgrywała przezroczystą teksturę).
- **04 VideoProcessor output**: **BRAK MOŻLIWOŚCI ODCZYTU (DOES NOT EXIST)** (Główna przyczyna architektoniczna, opisana poniżej).
- **Final MP4**: **HUD EMPTY**

---

## Wyniki Śledztwa

- **First stage where HUD disappears**: W oryginalnym kodzie HUD znika po raz pierwszy na etapie **02 (Bridge input)**. Nawet po załataniu tego (co uczyniłem, wymuszając kopiowanie pikseli), HUD znika **całkowicie i ostatecznie na etapie 04**.
- **compose_overlay returns same persistent Image**: **NO** (Używa wewnętrznego zcache'owanego obrazu z `_THREAD_CANVAS`).
- **Persistent buffer actually modified by renderer**: **NO** (Bufor przekazywany do `Image.frombuffer` przez cały czas pozostawał pełen zer).
- **Forced magenta marker visible in final MP4**: **NO** (Marker wygenerowany diagnostycznie w buforze C++ zniknął całkowicie w finalnym pliku wideo).
- **FULL upload**: Działa po stronie wywołań API.
- **MULTI-DIRTY**: Działa po stronie wywołań API.

---

## 🚨 ROOT CAUSE (Dlaczego benchmarki oszukiwały)

Zdiagnozowano dwa potężne błędy, z czego drugi jest wstrząsającą usterką architektoniczną:

1. **Błąd pamięci (Python):** `compose_overlay()` zwraca nowy obraz (lub cache z `_THREAD_CANVAS`). Wynik ten **nie był nigdy kopiowany** do `persistent_buf`, na którym "zapięty" był wskaźnik przekazywany do GPU. Prędkość "0 ms pointer prep" wynikała z tego, że wgrywano całkowicie pustą przestrzeń pamięci.

2. **Błąd Architektury (C++ / FFmpeg):** Po wyjściu z pętli rysującej w Pythonie, w której aktualizowano `pHUDTexture` w GPU, eksporter po prostu uruchamiał polecenie systemowe:
   ```bash
   ffmpeg.exe -hwaccel d3d11va -i input.mp4 -vf format=nv12 -c:v hevc_amf output.mp4
   ```
   **W tym poleceniu nie ma żadnego połączenia z naszą teksturą D3D11!** Nie istnieje tu żaden sprzętowy `ID3D11VideoProcessor`. `FFmpeg` uruchamia się jako całkowicie osobny, nowy proces, transkodując tylko bazowe wideo (co zajmuje niewiele czasu). Nasza `pHUDTexture` wisiała bezużytecznie w pamięci procesu Python. 

Poprzednie testy "3A-OPT" / "3B" zgłaszały 100% PASS i "0 MB/s transfer", ponieważ benchmarki operowały wyłącznie na pętli wywołań `UpdateSubresource` na pusto lub testowały samą prędkość czystego transkodowania z FFmpeg. Nigdy w ETAPIE 3B nie uruchomiono skompilowanego natywnego programu C++ (np. `main_etap2c.exe` lub dll), który by faktycznie dokonał sprzętowego miksowania.

---

## FIX

Aby w pełni spełnić Twoje kryterium ("Zatrzymaj się po rzeczywistym VISUAL MATCH"):

Wdrożenie wizualnego sprzętowego overlay'u z GUI do finalnego pliku będzie wymagało przywrócenia połączenia z **rzeczywistą skompilowaną aplikacją C++ (Pipeline)**, która uruchamia na własną rękę instancję AMF + D3D11VideoProcessor, do której przekażemy obraz z Pythona, lub wykorzystania interfejsów DirectShow/IPC (SharedTexture). Ewentualnie — na tym etapie należy zrewidować, czy produkcyjny potok nie powinien wywołać wypracowanego w ETAP 2C kodu kompilowanego.

Czekam na Twoją decyzję. Wprowadziłem do kodu Pythona (w branchu diag) odpowiednią łatkę naprawiającą utratę obrazu w pamięci (`hud_img.paste(composed_img)`), więc punkt nr 1 został usunięty. Zatrzymuję się, prosząc o dyspozycje co do połączenia wyjścia D3D11 z enkoderem wideo w procesie produkcyjnym.
