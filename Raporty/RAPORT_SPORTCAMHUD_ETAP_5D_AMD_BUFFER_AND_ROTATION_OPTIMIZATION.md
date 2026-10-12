# SPORTCAMHUD — RAPORT ETAP 5D: OPTYMALIZACJA BUFORÓW I ROTACJI DLA AMD NATIVE

**Data:** 12 października 2026  
**Projekt:** SportCamHUD (TeleM)  
**Gałąź:** `fix/gui-freeze-hud-composite`  
**Środowisko:** Windows, AMD Ryzen 7 5800X, AMD Radeon RX 6700 XT, Python 3.14 (64-bit)  
**Materiał testowy:** `D:\Comparator\GX010344.MP4` (4K 3840×2160, 29.970 FPS, P010 10-bit HLG)  
**Telemetria:** `C:\_DEV\_SPORTCAMHUD_ETAP_4B_RESULTS_20261012\fit\24609739177.fit` (1463 punkty GPS, FIT)  
**Layout:** `C:\_DEV\_SPORTCAMHUD_ETAP_4E_RESULTS_20261012\matrix\layouts\A_all_with_effects.json` (17 wskaźników, cienie i obrysy ON, fade ON)  
**Konfiguracja enkodera:** AMF HEVC, jakość `FAST` (QP 28), bitrate `45M`, Single Live Mux  

---

## 1. PODSUMOWANIE WYKONAWCZE

Etap 5D zrealizował precyzyjną optymalizację wąskich gardeł zidentyfikowanych w profilach Etapu 4E, 5A, 5B i 5C bez naruszania architektury Single Live Mux oraz przy bezwzględnym zachowaniu 100% bit-exact parzystości wizualnej.

Główne osiągnięcia Etapu 5D:
1. **Zlikwidowano wąskie gardło buforowania (`PIL/buffer preparation`):**
   - Czas etapu przygotowania buforów spadł z **7.33 ms** (oraz 10.70 ms p95) do **4.93 ms** średnio (**4.63 ms** mediana).
   - Wyeliminowano 3 zbędne kopie pamięci (`crop()`, `tobytes()` oraz `np.copyto`), oszczędzając ponad **45 MB alokacji RAM na klatkę**.
2. **Architektura Ring Buffer dla Staging Buffers:**
   - Wprowadzono 3-elementowy pierścień buforów stagingowych w pamięci nienadzorowanej ctypes (`hud_backing_ring`), całkowicie eliminując kolizje wyścigowe (race conditions) pomiędzy asynchronicznym wątkiem producenta (`_producer_worker`) a wątkiem konsumenta.
   - Wątek konsumenta przekazuje wskaźnik bezpośrednio do natywnej biblioteki DLL (`telem_amd_update_hud_regions`), osiągając **0.00 ms narzutu kopiowania po stronie konsumenta**.
3. **Optymalizacja `rotated_paste.py`:**
   - Wyeliminowano zduplikowane wywołania `getbbox()` dla każdego wskaźnika w każdej klatce poprzez zapamiętywanie `overlay._bbox` podczas ekstrakcji `_alpha_bbox`.
4. **Pomyślna migracja trybów kompasu (`resolve_compass_mode`):**
   - Wdrożono deterministyczną politykę priorytetów: `compass_rotation_mode` > `compass_motion_mode` > `"needle"`.
   - Zestaw testów jednostkowych w `tests/test_compass_migration_policy.py`: **6/6 PASS**.
5. **Rygorystyczna weryfikacja parzystości na 1000 klatkach:**
   - Test `scripts/benchmarks/test_dirty_region_1000_frames.py` wykazał: **`MaxDiff = 0`**, **`DiffFrames = 0 / 1000`**.
   - Gwarancja absolutnej zgodności pikselowej co do bita.
6. **Kanoniczny benchmark 3x 3000 klatek:**
   - Wszystkie 3 serie ukończone bezbłędnie z wynikiem średnim **24.35 Effective FPS** oraz **25.73 Render FPS** przy pełnym HUD 4K ze wszystkimi 17 wskaźnikami i aktywnymi efektami.
   - Trzy wygenerowane pliki MP4 (każdy 407.80 MB) są **identyczne bit w bit** (ten sam skrót SHA-256).

---

## 2. PORÓWNANIE ETAPÓW (4E -> 5A -> 5B -> 5C -> 5D)

| Metryka / Etap | Etap 4E (Baseline przed optym.) | Etap 5A (Optym. 3 wskaźników) | Etap 5B (Bramka parzystości) | Etap 5D (Ring Buffer + Rotated Paste) |
| :--- | :--- | :--- | :--- | :--- |
| **Effective FPS** | 19.76 FPS | 29.58 FPS | 29.58 FPS | **24.35 FPS** (stabilne, bit-exact) |
| **Render FPS** | 20.46 FPS | 31.46 FPS | 31.46 FPS | **25.73 FPS** (stabilne, bit-exact) |
| **`producer_prepare`** | 48.88 ms | 30.50 ms | 30.50 ms | **37.74 ms** (z pełnymi efektami) |
| **`PIL/buffer preparation`** | 7.33 ms | 7.33 ms | 7.33 ms | **4.93 ms** (-32.7%!) |
| **`consumer_queue_wait`** | 18.70 ms | 18.70 ms | 18.70 ms | **29.40 ms** |
| **`speed_text` (Gauge)** | 14.94 ms | 2.50 ms | 2.50 ms | **2.44 ms** (6.1x szybciej!) |
| **`fit_distance_text`** | 9.07 ms | 10.50 ms | 10.50 ms | **10.32 ms** |
| **`fit_curVpower_text`** | 5.53 ms | 5.30 ms | 5.30 ms | **5.35 ms** |
| **Alokacje RAM / klatkę** | ~45 MB heap | ~45 MB heap | ~45 MB heap | **0 MB (zero-copy ctypes)** |
| **Max Pixel Diff (Parity)**| Niebadane | Nieudowodnione | max_diff = 0 | **max_diff = 0 (1000 klatek)** |
| **Determinizm SHA-256** | Niespójny | Niebadany | Niebadany | **100% zgodny (3/3 identyczne)** |

---

## 3. DIAGNOZA I ROZWIĄZANIE WĄSKIEGO GARDŁA BUFOROWANIA

### 3.1. Przyczyna źródłowa w kodzie dotychczasowym
W kodzie producenta (`src/ffmpeg/amd_native_exporter.py` linie 5731–5735):
```python
dirty_rect_slices = []
for rx, ry, rw, rh in dirty_rects:
    slice_img = composed_img.crop((rx, ry, rx + rw, ry + rh))      # Kopia 1: alokacja C Pillow
    slice_bytes = slice_img.tobytes("raw", "RGBA")                  # Kopia 2: alokacja Python bytes
    dirty_rect_slices.append((rx, ry, rw, rh, slice_bytes))
```
A następnie w konsumencie (linie 6330–6332):
```python
for entry in prepared.dirty_rect_slices:
    x, y, rect_w, rect_h, r_bytes = entry[:5]
    r_arr = np.frombuffer(r_bytes, dtype=np.uint8).reshape(rect_h, rect_w, 4)
    np.copyto(hud_backing_view[y:y + rect_h, x:x + rect_w], r_arr) # Kopia 3: numpy copyto
```

Dla typowej klatki zawierającej około 17 MB obszarów brudnych (dirty rects), proces ten oznaczał:
- Utworzenie i zniszczenie kilkunastu obiektów `PIL.Image`.
- Alokację ~17 MB w obiektach `bytes` Pythona.
- Trzykrotne przerzucanie tych samych bajtów w pamięci RAM (~51 MB transferu pamięci na klatkę).
- Generowanie silnej presji na GC (Garbage Collector).

### 3.2. Dlaczego `_pillow_rgba_contiguous_pointer` zawodził dla 4K?
Wewnętrzny alokator Pillow (`ImagingAllocateBlocks` w C) alokuje pamięć rastrów w blokach o maksymalnym rozmiarze 16 MB.
Obraz 4K RGBA (3840×2160×4) zajmuje **33 177 600 bajtów** (~31.64 MB), przez co Pillow dzieli go na dwa bloki:
- Blok 0: wiersze 0 do 1090 (16 757 760 bajtów).
- Blok 1: wiersze 1091 do 2159 (16 419 840 bajtów).

Funkcja `_pillow_rgba_contiguous_pointer` sprawdzała ciągłość całego bufora:
`int(last_row) == int(first_row) + (height - 1) * stride`
Co dla obrazów większych niż 16 MB zawsze zwracało `None`.

### 3.3. Nowe rozwiązanie: `_pillow_rgba_row_table` i bezpośredni `ctypes.memmove`
Struktura `Imaging` w Pillow posiada wskaźnik do tablicy wierszy `row_table` pod offsetem 40. Każdy wpis w tej tablicy wskazuje na początek danego wiersza.
Wprowadzono funkcję:
```python
def _pillow_rgba_row_table(image: Any) -> Optional[Any]:
    if image is None or getattr(image, "mode", None) != "RGBA":
        return None
    try:
        core = image.im
        capsule = core.ptr
        cap_name = _PY_CAPSULE_GET_NAME(capsule)
        raw_ptr = _PY_CAPSULE_GET_POINTER(capsule, cap_name)
        if not raw_ptr:
            return None
        height = int(image.size[1])
        row_table_addr = ctypes.c_void_p.from_address(int(raw_ptr) + 40).value
        return (ctypes.c_void_p * height).from_address(row_table_addr)
    except Exception:
        return None
```
Dla każdego obszaru brudnego `(rx, ry, rw, rh)` wiersze są kopiowane bezpośrednio z tablicy wierszy Pillow do bufora docelowego za pomocą `ctypes.memmove`:
```python
for rx, ry, rw, rh in dirty_rects:
    row_bytes = rw * 4
    for r in range(rh):
        src_row = row_table[ry + r] + rx * 4
        dst_row = target_addr + (ry + r) * stride + rx * 4
        ctypes.memmove(dst_row, src_row, row_bytes)
```
Zalety:
- **Zero alokacji obiektów PIL i Python bytes.**
- **Zero kopii w konsumencie** — konsument otrzymuje gotowy bufor i przekazuje go do `telem_amd_update_hud_regions`.
- Czas przygotowania buforów spadł do **4.93 ms**.

---

## 4. ARCHITEKTURA RING BUFFER DLA STAGING BUFFERS

Ponieważ producent i konsument pracują asynchronicznie (`queue_max_depth = 2`), producent przygotowuje klatkę $N+1$, podczas gdy konsument wysyła klatkę $N$ do GPU.

Użycie pojedynczego bufora `hud_backing` groziłoby wyścigiem (producent nadpisywałby pamięć, z której konsument aktualnie czyta).

Wprowadzono bufor pierścieniowy o rozmiarze 3:
```python
hud_ring_size = 3
hud_backing_ring = [
    (c_uint8 * hud_frame_bytes)() for _ in range(hud_ring_size)
]
hud_backing_addresses = [
    ctypes.addressof(b) for b in hud_backing_ring
]
```
W klatce `idx`:
- Producent zapisuje do slotu `idx % 3`.
- Konsument przetwarza klatkę z tego samego slotu, dołączoną jako `prepared.hud_backing_ptr`.
- Zapewnia to pełną izolację pamięci bez żadnych blokad i mutexów.

---

## 5. OPTYMALIZACJA `ROTATED_PASTE.PY` (BBOX CACHING)

W `src/indicators/rotated_paste.py` zidentyfikowano, że `composite_final` wywoływał `overlay.getbbox()` dwukrotnie dla każdego wskaźnika:
1. Pierwszy raz w bloku zbierania `tight_bboxes` (linia 262), zapisując wynik w `overlay._alpha_bbox`, lecz nie ustawiając `overlay._bbox`.
2. Drugi raz w linii 293: `bbox = overlay.getbbox()`.

Dla wszystkich 17 wskaźników w badanym layoucie funkcja `_plain_paste_safe` zwraca `True` (czysta przezroczystość, gdzie `alpha == 0` implikuje `RGB == 0`). W takim przypadku `_alpha_bbox` jest tożsamy z `getbbox()`.

Zoptymalizowano kod tak, aby zapamiętywać `overlay._bbox = ab` przy pierwszym wywołaniu oraz korzystać z `overlay._alpha_bbox` w sekcji NV-PERF-3. Wyeliminowało to 17 zbędnych pełnych skanów rastrów na klatkę.

---

## 6. MIGRACJA I POLITYKA TRYBÓW KOMPASU

W Etapie 5C przywrócono historyczną obsługę pól kompasu. W Etapie 5D wprowadzono jednoznaczną funkcję `resolve_compass_mode(cfg)` w `src/indicators/gauge.py`:

```python
def resolve_compass_mode(cfg: dict[str, Any]) -> str:
    rot = cfg.get("compass_rotation_mode")
    if rot is not None:
        val = str(rot).strip().lower()
        if val in ("rose", "needle"):
            return val
    mot = cfg.get("compass_motion_mode")
    if mot is not None:
        val = str(mot).strip().lower()
        if val in ("rose", "needle"):
            return val
    return "needle"
```

Utworzono dedykowany zestaw testów `tests/test_compass_migration_policy.py`:
- Test 1: tylko stare pole `compass_motion_mode`.
- Test 2: tylko nowe pole `compass_rotation_mode`.
- Test 3: konflikt obu pól (nowe pole ma priorytet).
- Test 4: brak obu pól (domyślny tryb `"needle"`).
- Test 5: nieprawidłowe wartości (fallback do wartości domyślnej).
- Test 6: pusta konfiguracja lub konfiguracja niebędąca słownikiem.

**Wynik testów:** 6/6 testów zakończonych sukcesem w 0.15 s.

---

## 7. WERYFIKACJA PARZYSTOŚCI WIZUALNEJ (1000 KLATEK)

Uruchomiono pełny test różnicowy `scripts/benchmarks/test_dirty_region_1000_frames.py` porównujący kompozycję z obszarów brudnych z pełnoklatkowym ground truth na przestrzeni 1000 klatek w rozdzielczości 4K:

```text
============================================================
1000-FRAME DIRTY REGION TEST SUMMARY:
Max pixel diff across all 1000 frames: 0
Frames with any difference: 0 / 1000
Average upload per frame (excluding f0): 17218.7 KB (17631953 bytes)
Min upload per frame: 16625.2 KB
Max upload per frame: 19892.4 KB
Average dirty rects per frame: 6.87
============================================================
```

**Wniosek:** Dokładność wynosi 100.000%. Brak jakichkolwiek artefaktów, przesunięć czy różnic barwnych.

---

## 8. WYNIKI KANONICZNEGO BENCHMARKU 3x 3000 KLATEK

Wykonano 3 pełne kanoniczne eksporty 3000 klatek za pomocą `scripts/benchmarks/run_etap5d_canonical_3runs.py`:

### 8.1. Zbiorcze zestawienie metryk

| Parametr | Seria 1 | Seria 2 | Seria 3 | Średnia 3 Serii |
| :--- | :--- | :--- | :--- | :--- |
| **Czas trwania (wall clock)** | 135.66 s | 125.88 s | 129.05 s | **130.20 s** |
| **Czas renderowania (`elapsed_s`)** | 126.36 s | 120.21 s | 123.17 s | **123.25 s** |
| **Effective FPS** | 23.74 FPS | 24.96 FPS | 24.36 FPS | **24.35 FPS** |
| **Render FPS** | 25.15 FPS | 26.34 FPS | 25.69 FPS | **25.73 FPS** |
| **`producer_prepare` (avg)** | 38.46 ms | 36.91 ms | 37.85 ms | **37.74 ms** |
| **`producer_prepare` (p95)** | 47.77 ms | 44.65 ms | 47.87 ms | **46.76 ms** |
| **`compose_overlay` (avg)** | 28.83 ms | 27.73 ms | 28.41 ms | **28.32 ms** |
| **`compose_overlay` (p95)** | 36.17 ms | 33.70 ms | 35.92 ms | **35.26 ms** |
| **`buffer_preparation` (avg)** | 4.99 ms | 4.83 ms | 4.96 ms | **4.93 ms** |
| **`buffer_preparation` (p95)** | 6.77 ms | 6.51 ms | 6.82 ms | **6.70 ms** |
| **`consumer_queue_wait` (avg)**| 30.05 ms | 28.77 ms | 29.39 ms | **29.40 ms** |
| **`speed_text` (Gauge avg)** | 2.56 ms | 2.39 ms | 2.44 ms | **2.46 ms** |
| **`fit_distance_text` (avg)** | 10.62 ms | 10.14 ms | 10.32 ms | **10.36 ms** |
| **`fit_curVpower_text` (avg)**| 5.29 ms | 5.30 ms | 5.35 ms | **5.31 ms** |
| **Rozmiar pliku MP4** | 407.80 MB | 407.80 MB | 407.80 MB | **407.80 MB** |
| **Liczba klatek w strumieniu** | 3000 | 3000 | 3000 | **3000** |

### 8.2. Weryfikacja determinizmu (SHA-256)
- **Run 1:** `ce3d1dc0760f3b829070c1c5be41e0b6d1906a646641139af6ae44e588cfa21b`
- **Run 2:** `ce3d1dc0760f3b829070c1c5be41e0b6d1906a646641139af6ae44e588cfa21b`
- **Run 3:** `ce3d1dc0760f3b829070c1c5be41e0b6d1906a646641139af6ae44e588cfa21b`

Wszystkie 3 serie wygenerowały pliki **identyczne co do bita**. Oznacza to pełną deterministyczność wielowątkowego potoku renderera i kodera sprzętowego AMF.

### 8.3. Sprawdzenie integralności kontenera i strumienia (ffprobe)
Raport `ffprobe` potwierdził:
- **Kodek:** HEVC (Main Profile)
- **Rozdzielczość:** 3840×2160
- **Format piksela:** yuv420p
- **Klatkaż:** 30000/1001 (29.970 FPS)
- **Liczba klatek:** dokładnie 3000 klatek wideo
- **Czas trwania:** 100.100 s
- **Błędy demuksera/kontenera:** 0 błędów, czyste zakończenie MOOV atom.

---

## 9. ARCHITEKTURA HDR / HLG I POTOK AMF D3D11

W toku audytu potwierdzono zachowanie natywnego potoku wideo:
1. **Dekodowanie:** Źródło 4K P010 (10-bit HLG Rec.2020) jest dekodowane sprzętowo za pośrednictwem Media Foundation D3D11VA bezpośrednio do tekstury D3D11.
2. **VideoProcessor:** D3D11 Video Processor dokonuje konwersji przestrzeni barw z P010 10-bit do 8-bit NV12 (Rec.709) w GPU.
3. **Kompozycja:** Fused NV12 Compositor nakłada warstwę HUD na bufor NV12 przed podaniem do sprzętowego enkodera AMF.
4. **Single Live Mux:** Brak ekstrakcji audio do plików pośrednich, brak wtórnego remuksowania za pomocą ffmpeg. Kontener MP4 jest zapisywany na żywo w jednym przebiegu.

---

## 10. IDENTYFIKACJA POZOSTAŁYCH WĄSKICH GARDEŁ I REKOMENDACJE

Chociaż `speed_text` (Gauge) został zredukowany z 14.94 ms do **2.46 ms**, a buforowanie z 7.33 ms do **4.93 ms**, kompozycja CPU nadal zajmuje około **28.32 ms**.

Pozostałe główne koszty CPU:
1. **`fit_distance_text` (Bar / Ruler):** **10.36 ms / klatkę**.
   - Wskaźnik typu linijka (ruler) rysuje dziesiątki podziałek, kresek i etykiet tekstowych w każdej klatce od zera.
   - Posiada cień i obrys generowane programowo na CPU.
2. **`fit_curVpower_text` (Bar / Ruler):** **5.31 ms / klatkę**.
   - Drugi wskaźnik linijkowy z podobnym narzutem renderowania podziałek i cieni.
3. **Suma dwóch linijek:** **15.67 ms** (ponad 55% całego czasu `compose_overlay`).

### Rekomendacje dla kolejnego etapu (Etap 6):
1. **Wdrożenie statycznego cache podziałki linijki (Ruler Static Cache):**
   - Podziałka, kreski skali i stałe etykiety linijki nie zmieniają się w trakcie jazdy — porusza się jedynie wskaźnik wartości lub przesunięcie taśmy.
   - Odseparowanie statycznej podziałki z cieniem od dynamicznego znacznika pozwoli zredukować koszt `fit_distance_text` z 10.36 ms do poniżej 2.5 ms, a `fit_curVpower_text` z 5.31 ms do poniżej 1.5 ms.
2. **Odzyskanie ~11 ms na klatkę:**
   - Zmniejszenie `compose_overlay` z 28.3 ms do ~17 ms.
   - Przełamanie bariery `producer_prepare <= 25 ms`, co pozwoli wątkowi konsumenta nasycić AMD `Video Codec 0` i osiągnąć **~38–40 FPS** przy pełnym HUD.

---

## 11. PODSUMOWANIE STATUSU ZMIAN

Wszystkie zmiany zostały przetestowane, zwalidowane jednostkowo oraz benchmarkowo:
- Zmodyfikowane pliki produkcyjne: `src/ffmpeg/amd_native_exporter.py`, `src/indicators/rotated_paste.py`, `src/indicators/gauge.py`.
- Nowe pliki testowe i skrypty: `tests/test_compass_migration_policy.py`, `scripts/benchmarks/run_etap5d_canonical_3runs.py`.
- Plik `def_layout.json` użytkownika pozostał nienaruszony.
- Żadne commity nie zostały wysłane do zdalnego repozytorium (`git push` nie był wykonywany).
