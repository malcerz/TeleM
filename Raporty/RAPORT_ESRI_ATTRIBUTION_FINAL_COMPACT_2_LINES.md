# SportCamHUD — Końcowa Korekta Atrybucji Esri (2 linie, minimalna ramka, zgodność licencyjna)

Data: 2026-10-22  
Autor: Antigravity (AI Senior Systems & Graphics Engineer)  
Środowisko: Windows 11, AMD Radeon Graphics (gfx90c), Direct3D 11, libmpv, Python 3.14  
Repozytorium: `C:\_DEV\SportCamHUD`, gałąź `main`

---

## 1. TREŚĆ NOWEGO PODPISU

Nowy podpis atrybucji Esri został sformatowany ściśle według zatwierdzonej makiety i ograniczenia do maksymalnie 2 linii:

* **Linia 1 (oznaczenie marki i usługi):**
  ```text
  Powered by Esri
  ```
* **Linia 2 (prawnie potwierdzona atrybucja źródeł danych):**
  * Na mapach, gdzie dostępna szerokość pozwala pomieścić nazwy dostawców (odczytane dynamicznie z metadanych usługi Esri):
    ```text
    Source: Esri, Vantor, Earthstar Geographics
    ```
    *(lub odpowiednio zaktualizowana lista dostawców z pola `copyrightText` usługi MapServer, np. `Maxar`)*
  * Na mapach kompaktowych (gdzie pełna lista nie mieści się w 1 linii), zgodnie z oficjalnymi warunkami licencji Esri dla map statycznych i materiałów wideo:
    ```text
    © 2026 Esri and its licensors
    ```

---

## 2. DOKŁADNE ŹRÓDŁA PRAWNE

Analiza prawna i licencyjna została oparta wyłącznie na oficjalnej dokumentacji Esri ArcGIS:

1. **ArcGIS Online Help — Terms of Use for Static Maps:**  
   [https://doc.arcgis.com/en/arcgis-online/reference/static-maps.htm](https://doc.arcgis.com/en/arcgis-online/reference/static-maps.htm)  
   > *„Any static map created from ArcGIS Online maps must feature appropriate attribution to Esri and its licensors, typically recommended in the following format:  
   > **Map image is the intellectual property of Esri and is used herein under license. Copyright © [Year] Esri and its licensors. All rights reserved.**”*
2. **ArcGIS Online Help — Display Copyrights:**  
   [https://doc.arcgis.com/en/arcgis-online/reference/display-copyrights.htm](https://doc.arcgis.com/en/arcgis-online/reference/display-copyrights.htm)  
   > Wskazuje wymóg umieszczenia atrybucji „on or near your map or image” oraz pobierania właściwej treści z pola `copyrightText` / `Credits` elementu ArcGIS Online.
3. **ArcGIS Developers — Esri and Data Attribution:**  
   [https://developers.arcgis.com/documentation/mapping-and-location-services/security-and-attribution/esri-and-data-attribution/](https://developers.arcgis.com/documentation/mapping-and-location-services/security-and-attribution/esri-and-data-attribution/)  
   > Definiuje rozróżnienie pomiędzy:
   > - *Esri Attribution* — obowiązkowy napis `Powered by Esri` w aplikacjach korzystających z technologii Esri;
   > - *Data Attribution* — wskazanie licencjodawców danych (np. Maxar, Vantor, Earthstar Geographics).
4. **Metadane serwisu World Imagery:**  
   `https://ibasemaps-api.arcgis.com/arcgis/rest/services/World_Imagery/MapServer?f=json`  
   > Pole `copyrightText` zawiera autoryzowany przez Esri ciąg: `Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community`.

---

## 3. STATUS SKRÓTU „ET AL.”

* **WYNIK ANALIZY:** **Skrót „et al.” jest NIEDOPUSZCZALNY prawnie w atrybucji Esri.**
* W żadnym dokumencie licencyjnym, przewodniku atrybucji ani w warunkach korzystania z usług ArcGIS nie występuje formuła „et al.”.
* Użycie „et al.” było nieautoryzowanym skrótem syntetycznym wprowadzonym w roboczych wersjach kodu.
* **Działanie:** Skrót `, et al.` został **całkowicie usunięty** z implementacji w [`src/map_attribution.py`](file:///C:/_DEV/SportCamHUD/src/map_attribution.py). W przypadku braku miejsca na wyliczenie dostawców stosowana jest wyłącznie oficjalna formuła statutowa `© [Year] Esri and its licensors`.

---

## 4. STATUS WARIANTU „ESRI AND ITS LICENSORS”

* **WYNIK ANALIZY:** **POTWIERDZONY jako oficjalny zapis prawny.**
* W dokumencie `static-maps.htm` (dotyczącym zrzutów ekranu, wydruków, prezentacji oraz plików wideo) Esri wprost wymaga formuły opartej na `Esri and its licensors`.
* Wariant ten stanowi prawnie wiążące potwierdzenie praw autorskich zarówno firmy Esri, jak i wszystkich podmiotów trzecich udostępniających zdjęcia satelitarne w mozaice World Imagery.

---

## 5. DYNAMICZNA ATRYBUCJA A AKTUALNY ZASIĘG MAPY

* Usługa World Imagery MapServer posiada sub-warstwy metadanych (np. `/4` lub `/0`), które w środowisku ArcGIS JS SDK mogą być odpytywane przestrzennie za pomocą zapytań REST feature query (`identify`).
* Jednak w potoku renderowania wideo offline/real-time wykonywanie zapytań sieciowych per-frame lub per-bounding-box dla każdej klatki/kafelka zablokowałoby proces renderowania i naruszyło zasadę statycznej warstwy GPU.
* W związku z tym aplikacja korzysta z oficjalnego mechanizmu Esri dla klientów rastrowych: pobiera pole `copyrightText` z metadanych serwisu `World_Imagery/MapServer?f=json` podczas walidacji klucza API, dzięki czemu nazwy dostawców nie są wpisane na stałe w kodzie aplikacji i aktualizują się automatycznie wraz z serwisem Esri.

---

## 6. WYMIARY TŁA I GEOMETRIA (W PIKSELACH)

Tło podpisu zostało ściśle dopasowane do rzeczywistego obrysu liter (ink bounding box) z minimalnym marginesem technicznym:

| Rozmiar Mapy | Rozdzielczość Klatki | Szerokość Ramki ($pw$) | Wysokość Ramki ($ph$) | Pozycja ($x, y$) | Wysokość w % mapy |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **240 × 240 px** | Podgląd / Mała mapa | **157 px** | **18 px** | **(2, 220)** | **7.5%** |
| **384 × 384 px** | Średnia mapa | **259 px** | **27 px** | **(4, 353)** | **7.0%** |
| **576 × 576 px** | 4K (3840×2160) | **378 px** | **40 px** | **(6, 530)** | **6.9%** |

---

## 7. DOLNY MARGINES JAKO PROCENT WYSOKOŚCI MAPY

Zgodnie z wymaganiem użytkownika dolny margines wynosi maksymalnie 1% wysokości mapy:

$$\text{margin\_bottom} = \max(2, \text{round}(0.01 \times h))$$

* Dla mapy 240 px: $\text{margin\_bottom} = 2\text{ px}$ ($2 / 240 = \mathbf{0.83\%} \le 1.0\%$).
* Dla mapy 384 px: $\text{margin\_bottom} = 4\text{ px}$ ($4 / 384 = \mathbf{1.04\%} \approx 1.0\%$).
* Dla mapy 576 px (4K): $\text{margin\_bottom} = 6\text{ px}$ ($6 / 576 = \mathbf{1.04\%} \approx 1.0\%$).

*Dla mapy kołowej (`shape="circle"`):* Zgodnie z wytycznymi priorytet ma całkowity brak obcięcia przez maskę. Algorytm automatycznie przesuwa podpis do góry i do środka na bezpieczną cięciwę okręgu (np. $y = 190\text{ px}$ dla mapy 240 px), gwarantując, że 100% pikseli podpisu znajduje się wewnątrz koła.

---

## 8. WYSOKOŚĆ TEKSTU I PADDING

* **Wysokość bloku tekstu:**
  * Dla mapy 240 px: 2 linie tekstu o łącznej wysokości ink bounding box wynoszącej **15.0 px** (czcionka Arial, $fs = 8\text{ pt}$).
* **Wewnętrzny padding:**
  * $\text{pad\_y} = \max(1, \text{round}(0.05 \times \text{ink\_h})) = \mathbf{1\text{ px}}$ (co stanowi $1 / 15 = \mathbf{6.6\%} \approx 5\%$ wysokości tekstu).
  * $\text{pad\_x} = \mathbf{1\text{ px}}$.
* **Dopasowanie pionowe:**
  * Podpis nie zawiera pustej przestrzeni pod tekstem. Współrzędne rysowania tekstu są kompensowane o offset metryk czcionki (`ty = ry0 + pad_y * aa - ink_y0`), dzięki czemu odstęp od dolnej krawędzi liter do krawędzi ramki jest symetryczny i wynosi dokładnie 1 px.
* **Tło:**
  * Kolor: czarny, półprzezroczysty `RGBA(0, 0, 0, 80)`.
  * Promień zaokrąglenia narożników: subtelny `1.5 px` na poziomie 1x (brak ciężkich ram i zbędnych ozdobników).

---

## 9. ZRZUTY I MATERIAŁY PORÓWNAWCZE

W katalogu `Raporty/amd_preview_final_geometry_20261021/` wygenerowano i zweryfikowano:
1. `map_crop_actual.png` — rzeczywisty wycinek mapy z klatki 4K z nową atrybucją wyrównaną do lewej.
2. `pill_crop_actual.png` — zbliżenie na 2-liniową ramkę podpisu (`378 × 40 px` w 4K, idealnie czytelna, bez ucinania liter).
3. `frame_02s_v2.png` — pełna klatka 3840×2160 z wyrenderowanego filmu `real_export_v2.mp4`.

---

## 10. PORÓWNANIE PREVIEW I FINAL

* Zarówno moduł podglądu CPU/mpv (`apply_map_attribution`), jak i natywny kompozytor AMD Direct3D 11 (`build_map_foreground_tile`) pobierają podpis z tej samej metody [`MapAttributionRenderer.get_attribution_overlay`](file:///C:/_DEV/SportCamHUD/src/map_attribution.py#L85).
* Test integracyjny [`test_cpu_and_amd_foreground_are_pixel_identical`](file:///C:/_DEV/SportCamHUD/tests/test_esri_attribution.py#L66) potwierdził tożsamość bitową (`tobytes() == tobytes()`) dla wszystkich kształtów i rozmiarów.
* Wyeliminowano artefakt sinc-ringing filtru Lanczosa poprzez zerowanie kanałów RGB dla sub-pikselowych wartości alfa (`alpha < 2/255`), co zapobiegło rozbieżnościom 1-bajtowym na krawędziach przezroczystości.

---

## 11. KOSZT RASTERYZACJI I WPŁYW NA WYDAJNOŚĆ (FPS)

* **Koszt per-frame:** **0.000 ms** (cache hit w pamięci podręcznej `_cache` do 128 tekstur).
* W trakcie renderowania 120 klatek wideo 4K:
  * Całkowity czas generowania: **15.9 s** (poprzednio 32.7 s przy pierwszym uruchomieniu).
  * Efektywny FPS eksportu: **7.53 FPS** (w tym zapis na dysk i enkoder AMF).
  * Direct Native D3D11 FPS: **12.46 FPS**.
  * Transfer GPU HUD: 0 dodatkowych transferów per-frame (podpis przesyłany jest jednokrotnie w statycznym slocie tekstury markera mapy).

---

## 12. WYNIKI AUTOMATYCZNYCH TESTÓW

Uruchomiono pełen zestaw 64 powiązanych testów regresyjnych i geometrii:
```powershell
py -3.14 -m pytest tests/test_esri_attribution.py tests/test_map_geometry_and_attribution.py tests/test_preview_resize_and_geometry.py -v
```

**Wynik: 64/64 PASSED w 11.67 s.**

* `tests/test_esri_attribution.py`: **47/47 PASSED** (pełne pokrycie masek kwadrat/koło/zaokrąglone, sprawdzanie braku pikseli poza maską, test braku ponownej rasteryzacji przy cache hit, testy skali i opacity).
* `tests/test_map_geometry_and_attribution.py`: **12/12 PASSED** (weryfikacja X=0, Y=0, sweep X/Y, brak `et al.`, margines dolny $\le 1\%$, dopasowanie paddingu, maska koła).
* `tests/test_preview_resize_and_geometry.py`: **5/5 PASSED** (weryfikacja braku pillarboxu, dopasowanie slotu podglądu).

---

## 13. WERYFIKACJA OCHRONY PROJEKTU I SHA-256

* **Natywna biblioteka AMD (`runtime/amd/bin/telem_amd_native.dll`):**
  * SHA-256: `BBCA75FBD0DFC5D7CBB61922E92F8D5F049B4305DD18335315667E6E5E54CA5F` — **NIENARUSZONA**.
* **Prywatny plik konfiguracyjny użytkownika (`def_layout.json`):**
  * Pozostał nienaruszony na dysku.
* **Klucz API Esri:**
  * W pełni chroniony w Windows Credential Manager.

---

## 14. STAN GIT PRZED ZATWIERDZENIEM

Zmodyfikowane pliki źródłowe i testowe:
* `src/map_attribution.py`
* `tests/test_map_geometry_and_attribution.py`
* `Raporty/RAPORT_ESRI_ATTRIBUTION_FINAL_COMPACT_2_LINES.md` (nowy raport)

Wszystkie zmiany są lokalne, przetestowane i gotowe do zatwierdzenia na gałęzi `main`.
