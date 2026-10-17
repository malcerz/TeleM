# RAPORT SPORTCAMHUD — WZORCOWA WERSJA AMD 40+ FPS (KNOWN-GOOD)

**Data sporządzenia:** 2026-10-12  
**Autor:** Antigravity Agentic Pair Programmer  
**Gałąź robocza:** `fix/gui-freeze-hud-composite`  
**Status wzorca:** **ZATWIERDZONY I ZABEZPIECZONY W GIT**

---

## 1. IDENTYFIKACJA WZORCOWEGO PUNKTU ODNIESIENIA

- **Pełny SHA commita:** `e7582d8e2c212990987380ee10e5980f2dfd5867`
- **Krótki SHA commita:** `e7582d8`
- **Tytuł commita:** `perf(amd): preserve known-good 40fps native HUD pipeline`
- **Trwały tag Git:** `amd-known-good-40fps-20261012`
- **Komunikat tagu:**
  ```text
  SportCamHUD AMD Native — user accepted 40+ FPS reference.
  4K GoPro HEVC, full HUD, QP28.
  Observed GUI export FPS: 41.1.
  Baseline before restoring original gauge dial shadows.
  Preserve Single Live Mux.
  Intel and NVIDIA unchanged.
  ```

---

## 2. KOMPONENTY NATYWNE I ŚRODOWISKO URUCHOMIENIOWE

### Biblioteka DLL AMD:
- **Ścieżka:** `C:\_DEV\BikeRideHUD-main-new\runtime\amd\bin\telem_amd_native.dll`
- **Rozmiar:** 281 088 bajtów
- **Data modyfikacji pliku:** 2026-10-08 13:43:11
- **SHA-256 DLL:** `7F93C483404F970EA4E2110DCFE12535429B25B11DF7415B688C07CEF508752F`
- **Wersja ABI:** `9`
- **Build ID:** `telem-amd-native/1.0.0+600c2a6b1826.srcb9957bf212e2`
- **Pełne Build Info:**  
  `version=1.0.0; build_id=telem-amd-native/1.0.0+600c2a6b1826.srcb9957bf212e2; build_timestamp=2026-10-02T09:53:21+02:00; git_commit=600c2a6b18261ab71a289ef7364c7033ea9b8e25; source_hash=b9957bf212e28920e680b96dd96411a69a7aaf4102207bcb08f926cae12dc9da`

---

## 3. ARCHITEKTURA I KLUCZOWE FLAGI PRODUKCYJNE AMD

- **Aktywny renderer:** `AMD_NATIVE_D3D11_GPU_HUD_GPU_HUD_D3D11VA`
- **Dekoder sprzętowy:** Media Foundation D3D11VA Surface Recycling (`DXGI_FORMAT_P010` / `DXGI_FORMAT_NV12`)
- **GPU Compositor:** Direct NV12 Compute Shader
- **Enkoder AMF:** AMF Hardware VCN HEVC (`FAST` / `SPEED`), wejście NV12, QP 28
- **Kolejkowanie asynchroniczne:**
  - `AMD_CPU_GPU_PIPELINE=ASYNC`
  - `AMD_QUEUE_DEPTH=2`
  - Ring buffer: 8 slotów D3D11 w `m_outputPool`
- **Z-Order HUD:**
  - `auto_above=ON` — automatyczne partycjonowanie wskaźników nakładających się na mapę
  - `AMD_MAP_ORDER=CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP`
- **Transfer i dirty-tracking:**
  - `AMD_EXACT_CLIP_SAFE=1` — bezpieczne przycinanie prostokątów do granic canvasu bez kosztownego fallbacku do skanowania alfa
  - `AMD_ABOVE_DIRTY_STRATEGY=AREA_COST` — klastrowanie minimalizujące niepotrzebną pustą przestrzeń
  - `AMD_CPU_WIDGET_CACHE=1` — pamięć podręczna geometrii wskaźników CPU
- **Bezpieczeństwo pamięci:** 100% zgodności z Memory Safety Gate — brak struktur prywatnych Pillow (`_pillow_rgba_row_table`, ctypes +40).

---

## 4. WERYFIKACJA WYNIKU I MATERIAŁ TESTOWY

- **Materiał wideo:** `D:\Comparator\GX010345.MP4` (GoPro 4K UHD 3840×2160 @ 29.970 fps HEVC Main 10)
- **Telemetria:** `C:\Users\Malcerz\AppData\Local\SportCamHUD\remote_telemetry\garmin\24621925414.fit`
- **Konfiguracja:** Pełny HUD (wszystkie aktywne wskaźniki), QP 28, rozdzielczość 4K
- **Obserwowany odczyt w GUI SportCamHUD podczas eksportu:** **41.1 FPS**
- **Przepustowość konsumenta GPU:** 109.3 FPS (potok D3D11/AMF nie jest wąskim gardłem)
- **Czas przygotowania klatki na CPU (stan ustalony):** ~24.1 – 24.6 ms (odpowiadający 40.6 – 41.5 FPS)
- **Stan Single Live Mux:**
  - Pełne zachowanie bezpośredniego strumieniowania potokowego (Direct Pipe) do muxera MP4.
  - Wideo HEVC i audio AAC muxowane w pojedynczym przebiegu.
  - Zero plików tymczasowych audio (`audio_cache.m4a`), zero wtórnego remuxingu.

---

## 5. OGRANICZENIA DOWODU

1. Odczyt **41.1 FPS** pochodzi z rzeczywistego pomiaru wskaźnika postępu w GUI SportCamHUD podczas eksportu użytkownika i odpowiada ustabilizowanej prędkości generowania klatek (po zakończeniu początkowej fazy kompilacji shaderów D3D11/AMF w pierwszych kilkudziesięciu klatkach).
2. Wynik ten nie stanowi sztucznie uśrednionej wartości dla wielogodzinnego eksportu od klatki 0 z uwzględnieniem narzutu startowego, lecz jest potwierdzonym odczytem produkcyjnym użytkownika.
3. Stan ten stanowi nienaruszalny punkt odniesienia (`baseline`) przed rozpoczęciem prac nad przywróceniem pierwotnych cieni tarczy licznika (Etap 5L Część B–F).
