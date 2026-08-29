# RAPORT AMD ETAP 4B — DYNAMIC-ONLY SPARSE ABOVE COMPOSE + TIGHT ROI

## 1. Cel Etapu i Zakres

Celem ETAPU 4B było:
1. Przeprowadzenie dokładnego audytu zagnieżdżenia timerów CPU ABOVE (`CPU_ABOVE_TIMER_TREE`) w celu wyeliminowania błędnego sumowania inclusive/child timerów.
2. Zbadanie i zaimplementowanie ścieżki `AMD_ABOVE_SPARSE_COMPOSE` (renderowanie wyłącznie do lokalnych kafli/ROI zamiast pełnoekranowego płótna 3840x2160).
3. Bezwzględne zachowanie 100% zgodności pikselowej ($MaxDiff = 0$) względem Golden Reference ustalonego w ETAPIE 4A (`tests/test_golden_parity_etap4.py`).
4. Wykonanie naprzemiennego benchmarku A/B (REF/CAND/REF/CAND/REF/CAND) na pełnym obciążeniu 1131 klatek UHD 4K.
5. Analiza zysku wydajnościowego lub określenie nowego wąskiego gardła zgodnie z dyscypliną repozytorium.

---

## 2. Audyt Zagnieżdżenia Timerów (Section 0)

Przeanalizowano kod `src/ffmpeg/amd_native_exporter.py` oraz `src/indicators/compositor.py`.
Ustalono dokładną relację inclusive / exclusive / child timerów dla całego etapu przygotowania klatki na CPU:

```text
producer_prepare (30.45 ms) [INCLUSIVE - całkowity czas przygotowania klatki na CPU]
├── Telemetry/frame_data (0.06 ms) [EXCLUSIVE - pobranie rekordu telemetrii]
├── compose_overlay (below map) (1.58 ms) [INCLUSIVE - dolna warstwa HUD]
├── map_cpu_upload (2.71 ms) [EXCLUSIVE - przygotowanie/upload kafelków mapy]
├── gauge_capture (0.55 ms) [EXCLUSIVE - wycięcie/przygotowanie GPU gauge]
├── gauge_tobytes (0.21 ms) [EXCLUSIVE]
├── gauge_upload (0.31 ms) [EXCLUSIVE]
├── above_total (20.83 ms) [INCLUSIVE - całkowity czas warstwy CPU ABOVE]
│   ├── above_compose (18.69 ms) [INCLUSIVE - renderowanie wskaźników do bufora]
│   │   ├── fit_heart_rate_text (3.81 ms) [CHILD - generowanie wykresu HR na CPU]
│   │   ├── fit_cadence_text (3.79 ms) [CHILD - generowanie wykresu Cadence na CPU]
│   │   ├── speed_text (0.92 ms) [CHILD - gauge capture]
│   │   ├── alt_text (0.89 ms) [CHILD - linijka wysokości]
│   │   ├── fit_gopro_battery_text (0.52 ms) [CHILD]
│   │   ├── pozostałe wskaźniki tekstowe (~1.50 ms) [CHILD]
│   │   ├── above_tight_bbox_collect (1.22 ms) [CHILD - zbieranie alpha-tight bboxów wewnątrz compose_overlay]
│   │   └── alokacja/czyszczenie/alpha_composite w buforze (~6.04 ms)
│   ├── above_region_plan (0.08 ms) [EXCLUSIVE - planowanie klastrów dirty rect]
│   ├── above_exact_crop (1.47 ms) [EXCLUSIVE - wycinanie regionów z bufora 4K]
│   └── above_region_to_bytes (1.94 ms) [EXCLUSIVE - tobytes("raw", "RGBA") dla klastrów]
├── PIL/buffer preparation (0.58 ms) [EXCLUSIVE]
└── Python->native bridge / overhead (~4.00 ms)
```

> **Zasada nie-sumowania child timerów:**
> `above_tight_bbox_collect` (1.22 ms) jest timerem wewnętrznym (CHILD) mierzonym wewnątrz funkcji `compose_overlay` podczas rysowania wskaźników. Nie wolno go dodawać do `above_compose` ani `above_total`, gdyż jest w nich już zawarty.

---

## 3. Implementacja Sparse Above Compose

W ramach ETAPU 4B:
1. Rozszerzono `src/indicators/rotated_paste.py` o parametr `coordinate_offset: tuple[int, int]`, kompensujący bankierskie zaokrąglenia (`round(x - 0.5)`), co zagwarantowało identyczne co do piksela pozycjonowanie w lokalnych kaflach ROI jak na pełnym płótnie 4K.
2. Zaktualizowano `src/indicators/compositor.py`, aby obsługiwał `target_image` o dowolnym rozmiarze i przesunięciu `coordinate_origin`.
3. Zintegrowano ścieżkę w `src/ffmpeg/amd_native_exporter.py` pod flagą `AMD_ABOVE_SPARSE_COMPOSE`:
   - Ewaluacja wskaźników GPU capture (`above_gpu_capture`) bez generowania pełnego rastra.
   - Renderowanie poszczególnych klastrów wskaźników bezpośrednio do prealokowanych buforów kafelkowych ROI.
   - Wyciąganie bajtów i przekazywanie do `above_regions_out` z pominięciem pełnoekranowych alokacji 3840x2160.

---

## 4. Weryfikacja Poprawności Wizualnej (Golden Parity Gate)

Wykonano testy automatyczne z ETAPU 4A:
```bash
python -m pytest tests/test_golden_parity_etap4.py
```
**Wynik**: `4 passed in 3.32s` (100% PASS).

Przetestowano 50 klatek w teście jednostkowym `test_sparse_exact_parity_full.py`:
- Każdy przesłany prostokąt $(x, y, w, h)$: identyczny ($MaxDiff = 0$).
- Wszystkie bajty pikseli RGBA: identyczne ($MaxDiff = 0$).

---

## 5. Naprzemienny Benchmark A/B (1131 Klatek, UHD 4K)

Przeprowadzono pełny, naprzemienny benchmark 6 przebiegów (REF / CAND / REF / CAND / REF / CAND) na referencyjnym materiale:
- Wideo: `Video/GX030120.MP4` (3840x2160 @ 29.97 fps)
- Telemetria: `Video/Jazda_na_rowerze_w_porze_lunchu.fit`
- Layout: `def_layout.json`
- Liczba klatek: 1131 klatek

### Wyniki Przebiegów:

| Przebieg | Tryb | RENDER FPS | USER EFF FPS | TRUE FPS | video_wall (s) | prod_prep (ms) | above_compose (ms) | above_total (ms) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **REF_1** | REF (`SPARSE=0`) | 24.868 | 17.856 | 17.856 | 45.480 | 32.257 | 20.787 | 22.709 |
| **CAND_1**| CAND (`SPARSE=1`)| 21.612 | 16.377 | 16.377 | 52.331 | 38.536 | 29.531 | 31.404 |
| **REF_2** | REF (`SPARSE=0`) | 26.629 | 19.434 | 19.434 | 42.472 | 29.564 | 18.595 | 20.481 |
| **CAND_2**| CAND (`SPARSE=1`)| 22.629 | 17.048 | 17.048 | 49.980 | 36.557 | 27.959 | 29.919 |
| **REF_3** | REF (`SPARSE=0`) | 25.952 | 18.876 | 18.876 | 43.581 | 30.448 | 18.685 | 20.832 |
| **CAND_3**| CAND (`SPARSE=1`)| 21.525 | 16.255 | 16.255 | 52.545 | 38.753 | 29.737 | 31.779 |
| **REF Mediana** | **REF** | **25.952** | **18.876** | **18.876** | **43.581** | **30.448** | **18.685** | **20.832** |
| **CAND Mediana**| **SPARSE** | **21.612** | **16.377** | **16.377** | **52.331** | **38.536** | **29.531** | **31.404** |

### Podsumowanie Różnic:
- **RENDER FPS Delta**: -16.72% (spadek z 25.95 do 21.61 fps)
- **above_compose Delta**: +10.847 ms (wzrost z 18.69 ms do 29.53 ms)
- **producer_prepare Delta**: +8.088 ms (wzrost z 30.45 ms do 38.54 ms)

---

## 6. Głęboka Analiza Przyczyny Braku Zysku (Root Cause)

1. **Efektywność Reusable Canvas w referencyjnej ścieżce:**
   - W referencyjnej ścieżce (`AMD_ABOVE_SPARSE_COMPOSE=0`) z `reuse_canvas="above"`, płótno 4K NIE jest alokowane w pętli klatek.
   - Płótno jest prealokowane jednorazowo, a czyszczenie dirty rectów z poprzedniej klatki za pomocą `paste((0,0,0,0), bbox)` zajmuje zaledwie **~0.08 ms**.
   - `compose_overlay` wykonuje się **dokładnie 1 raz** na klatkę. Inicjalizacja fontów, parsowanie stylów i iteracja po wskaźnikach odbywa się jednokrotnie.
   - Wycinanie 5 klastrów zajmuje tylko **~1.47 ms**.

2. **Narzut Sparse Compose w środowisku Python / Pillow:**
   - W trybie sparse, `compose_overlay` jest wywoływane **7 razy na każdą klatkę** (1 raz na GPU capture + 6 razy na poszczególne klastry ROI).
   - Każde z 7 wywołań powtarza rozpakowywanie argumentów, setup lokalnych słowników, filtrowanie wskaźników i zarządzanie obiektami Pythona.
   - Każdy kafelek musi zostać wyczyszczony, skomponowany i docięty pośrednio, co sumarycznie generuje dodatkowe **+10.8 ms narzutu interpretera na klatkę**.

3. **Wniosek Architektoniczny:**
   - Rozmiar płótna 4K nie stanowił wąskiego gardła CPU ABOVE.
   - Prawdziwym wąskim gardłem CPU ABOVE jest czas rysowania pojedynczych komponentów na CPU — przede wszystkim generowanie wykresów `fit_heart_rate_text` (~3.8 ms) i `fit_cadence_text` (~3.8 ms) na CPU.

---

## 7. Decyzja i Izolacja Backendów

1. Zgodnie z regułą Section 8 i 12 `AGENTS.md` (włączenie domyślne tylko przy wykazanym zysku):
   - Flaga `AMD_ABOVE_SPARSE_COMPOSE` pozostaje domyślnie **OFF (`0`)**.
   - Kod ścieżki sparse compose pozostaje w pełni funkcjonalny, stabilny i przetestowany pod flagą środowiskową `AMD_ABOVE_SPARSE_COMPOSE=1`.
2. **Izolacja Backendów**:
   - Zmiany w `rotated_paste.py` i `compositor.py` są neutralne wstecznie i w 100% przetestowane.
   - Ścieżki NVIDIA oraz Intel pozostały całkowicie nienaruszone.

---

## 8. Rekomendacja dla Kolejnego Etapu (ETAP 4C)

Zgodnie z dyrektywą Section 12:
Głównym wąskim gardłem CPU ABOVE pozostaje programowe generowanie rastrów wykresów na CPU w trybie GPU Split:
- `fit_heart_rate_text`: **3.81 ms / klatkę**
- `fit_cadence_text`: **3.79 ms / klatkę**
- Sumaryczny koszt wykresów na CPU: **~7.60 ms / klatkę** (stanowi ponad 40% całego `above_compose`).

**Rekomendowany następny etap:**
`AMD ETAP 4C — CHART CPU CAPTURE ELIMINATION / NATIVE DYNAMIC CHART PATH` (wyeliminowanie generowania kafelków dynamicznych wykresów na CPU poprzez natywny HLSL renderer kursora/wartości lub optymalizację cache wykresu).
