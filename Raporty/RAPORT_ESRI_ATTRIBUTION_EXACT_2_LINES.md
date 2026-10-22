# SportCamHUD — Ostateczny Dwuliniowy Podpis Esri (Weryfikacja i Raport)

Data: 2026-10-22  
Autor: Antigravity (AI Senior Systems & Graphics Engineer)  
Środowisko: Windows 11, AMD Radeon Graphics (gfx90c), Direct3D 11, libmpv, Python 3.14  
Repozytorium: `C:\_DEV\SportCamHUD`, gałąź `main`

---

## 1. CEL I ZATWIERDZONA TREŚĆ PODPISU

Zgodnie z ostateczną dyspozycją użytkownika, dotychczasowa atrybucja została zastąpiona zatwierdzonym, dokładnym dwuliniowym podpisem:

* **Linia 1:**
  ```text
  Powered by Esri. Source: Esri, Vantor,
  ```
* **Linia 2:**
  ```text
  Earthstar Geographics, and the GIS User Community
  ```

### Główne reguły implementacji:
1. **Dwie linie i ścisły podział:** Podział następuje dokładnie po przecinku po `Vantor,`. Żadna linia nie jest ucinana.
2. **Zakaz skrótów i uogólnień:** Całkowicie wykluczono skrót „et al.” oraz zastępczy zapis „Esri and its licensors” na rzecz wskazania pełnych nazw dostawców danych.
3. **Typografia:** Wielkość czcionki jest dynamicznie dopasowywana do szerokości mapy w oparciu o rzeczywisty pomiar szerokości tekstu (`textlength`). Dla mapy 240 px zastosowano czytelny font bazowy 8.5 pt (w przedziale 8–9 px).
4. **Tło:** Półprzezroczyste czarne tło o zatwierdzonej wartości kanału alfa $80 / 255$ z zaokrągleniem narożników ($r \approx 1.5\text{ px}$).
5. **Marginesy i padding:** Wewnętrzny padding ramki wynosi około 1 px ($0.05 \times \text{wysokość tekstu}$, min. 1 px). Dolny margines tła wynosi maksymalnie 1% wysokości mapy (dla mapy 240 px: 2 px, czyli 0.83%).
6. **Granice mapy:** Podpis mieści się w 100% wewnątrz granic mapy (dla kształtów kwadratowych, zaokrąglonych i kołowych).
7. **Parytet Preview i Final:** Dokładnie ten sam algorytm i bufor tekstury w Preview (CPU/mpv) oraz Final (AMD D3D11).
8. **Cache tekstury:** Brak re-rasteryzacji na klatkę — overlay buforowany w pamięci.

---

## 2. ZGODNOŚĆ Z METADANYMI USŁUGI ESRI WORLD IMAGERY

Zweryfikowano rzeczywistą odpowiedź serwisu Esri World Imagery MapServer (`https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer?f=json`):

```json
{
  "copyrightText": "Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community"
}
```

Zatwierdzony podpis odpowiada w 100% aktualnym źródłom danych wskazywanym przez Esri (gdzie dawny Maxar występuje obecnie pod marką Vantor).

> [!IMPORTANT]
> **Uwaga licencyjna dotycząca eksportu MP4:**
> Poprawny i kompletny podpis atrybucyjny na mapie jest warunkiem koniecznym, lecz sam w sobie nie rozstrzyga o prawie do komercyjnego wykorzystania lub monetyzacji wyeksportowanego materiału wideo MP4 na platformach publicznych (np. YouTube). Zgodnie z warunkami ArcGIS Online / Developer Terms, eksport wideo z kafelkami Esri do celów komercyjnych wymaga stosownej płatnej subskrypcji komercyjnej Esri.
> W przypadku gdyby Esri w przyszłości zmieniło listę dostawców w metadanych usługi, mechanizm wykrywa nowe tokeny i loguje ostrzeżenie o konieczności aktualizacji treści dwuliniowej.

---

## 3. POMIARY GEOMETRII I WYMIARY PIKSELOWE

Pomiary wykonane na silniku Pillow przy supersamplingu $3\times$ z filtrem Lanczos:

| Rozmiar Mapy | Kształt | Font ($fs$) | Rozmiar Bounding Box | Pozycja ($x, y$) | Dolny Margines | Margines w % $h$ |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **240 × 240 px** | Kwadrat | **8.5 pt** | **206 × 21 px** | **(1, 218)** | **1 px** | **0.42%** ($\le 1\%$) |
| **240 × 240 px** | Koło | **8.5 pt** | **206 × 21 px** | **(17, 160)** | Bezpieczna cięciwa | $100\%$ wewnątrz maski |
| **480 × 480 px** | Kwadrat | **17.0 pt** | **405 × 38 px** | **(3, 439)** | **3 px** | **0.62%** ($\le 1\%$) |
| **576 × 576 px** (4K) | Kwadrat | **20.4 pt** | **488 × 45 px** | **(4, 527)** | **4 px** | **0.69%** ($\le 1\%$) |
| **576 × 576 px** (4K) | Koło | **20.4 pt** | **488 × 45 px** | **(44, 395)** | Bezpieczna cięciwa | $100\%$ wewnątrz maski |

---

## 4. WYGENEROWANE ZRZUTY EKRANU / KROPY

Wygenerowane rzeczywiste próbki obrazu zostały zapisane w katalogu roboczym:
1. `Raporty/esri_attribution_2lines_20261022/map_240_square.png` — mapa 240x240 px, kształt kwadratowy (pozycja przy samej dolnej krawędzi, margines < 1%).
2. `Raporty/esri_attribution_2lines_20261022/map_240_circle.png` — mapa 240x240 px, kształt okrągły (podpis dopasowany wewnątrz okręgu).
3. `Raporty/esri_attribution_2lines_20261022/map_576_4k.png` — mapa 576x576 px (skala 4K 15%), idealna ostrość i skalowanie.

---

## 5. WYNIKI TESTÓW AUTOMATYCZNYCH

Uruchomiono pełny zestaw testów geometrii, podglądu i atrybucji:

```text
py -3.14 -m pytest tests/test_esri_attribution.py tests/test_map_geometry_and_attribution.py tests/test_preview_resize_and_geometry.py -v
============================= 64 passed in 12.24s =============================
```

* `tests/test_esri_attribution.py`: 47/47 testów zaliczonych (w tym testy kształtów, buforowania, maski oraz bit-exact parity CPU i AMD).
* `tests/test_map_geometry_and_attribution.py`: 12/12 testów zaliczonych (X=0, Y=0, sweep współrzędnych, brak regresji layoutu, 2 linie bez "et al." i bez "licensors").
* `tests/test_preview_resize_and_geometry.py`: 5/5 testów zaliczonych (letterbox, pillarbox, clamping okna, paintEvent).

## 6. INTEGRALNOŚĆ BIBLIOTEK I KONFIGURACJI

* Plik `def_layout.json` **nie został zmodyfikowany ani przestawiony**.
* Plik `runtime/amd/bin/telem_amd_native.dll` **pozostał nienaruszony**:
  * SHA-256: `BBCA75FBD0DFC5D7CBB61922E92F8D5F049B4305DD18335315667E6E5E54CA5F`.
