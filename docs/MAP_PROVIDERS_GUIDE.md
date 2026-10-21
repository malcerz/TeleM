# SportCamHUD — Przewodnik po dostawcach map i zasadach licencjonowania

Ten dokument wyjaśnia, skąd pochodzą mapy w SportCamHUD, jakie warunki prawne obowiązują podczas generowania i publikacji filmów z nałożonymi mapami (np. na YouTube) oraz jak bezpiecznie konfigurować własne klucze API i serwery kafelków.

---

## 1. Skąd pochodzą dane mapowe?

SportCamHUD nie jest właścicielem danych kartograficznych. Aplikacja pobiera kafelki rastrowe w formacie Web Mercator (standard kafelków 256x256 px) od zewnętrznych dostawców:

1. **OpenStreetMap (OSM / OSMF)**
   - Dane: Społecznościowa, otwarta baza danych geograficznych na licencji ODbL 1.0 (Open Database License).
   - Serwer kafelków: Publiczny serwer fundacji OpenStreetMap (`tile.openstreetmap.org`), utrzymywany z darowizn.
2. **CARTO (Basemaps)**
   - Style: Positron (`light_all`, `light_nolabels`), Dark Matter (`dark_all`, `dark_nolabels`), Voyager (`voyager_all`, `voyager_nolabels`).
   - Dane: OpenStreetMap zoptymalizowane pod kątem czytelności nakładek danych, hostowane przez CARTO CDN.
3. **Esri (ArcGIS World Imagery)**
   - Styl: `satellite` (zdjęcia satelitarne i lotnicze).
   - Dane: Mozaika zdjęć wysokiej rozdzielczości od komercyjnych dostawców (Maxar/DigitalGlobe, Earthstar Geographics, CNES/Airbus, USGS, USDA FSA) oraz społeczności GIS.
4. **Własny serwer kafelków (Custom / Self-Hosted)**
   - Dowolny serwer zgodny ze standardem XYZ (`http://host:port/{z}/{x}/{y}.png`), np. lokalny kontener Docker z TileServer GL lub instancja `osm-tile-server`.

---

## 2. Różnica między danymi OpenStreetMap a serwerem kafelków OSMF

Kluczowe rozróżnienie prawne:

- **Baza danych OpenStreetMap (ODbL):** Jest w pełni wolna i otwarta. Pozwala na bezpłatne użytkowanie prywatne i komercyjne, tworzenie dzieł pochodnych i publikację, pod warunkiem wskazania autorstwa: `© OpenStreetMap contributors` oraz udostępnienia ewentualnej zmodyfikowanej bazy danych na tej samej licencji.
- **Publiczny serwer kafelków OSMF (`tile.openstreetmap.org`):** Posiada osobną politykę użytkowania (**Tile Usage Policy**). Ponieważ infrastruktura OSMF jest finansowana ze zbiórek i darowizn:
  - **Zabrania masowego pobierania (bulk download) oraz prefetchu trasy.** Pobieranie kafelków dla obszarów lub poziomów zoom niewyświetlanych bezpośrednio człowiekowi jest surowo wzbronione.
  - **Wymaga unikalnego nagłówka User-Agent** identyfikującego aplikację.
  - **Wymaga respektowania pamięci podręcznej (cache)** przez co najmniej 7 dni.
  - Aplikacje o dużym natężeniu ruchu lub masowym eksporcie wideo nie mogą polegać na darmowych serwerach OSMF — muszą korzystać z własnej infrastruktury kafelków.

---

## 3. Matryca uprawnień: Prywatne, YouTube i Monetyzacja

| Zastosowanie | OpenStreetMap (OSMF) | CARTO Basemaps | Esri World Imagery | Własny serwer (Custom) |
|---|---|---|---|---|
| **Użytek prywatny** (oglądanie w domu, plik na dysku) | **TAK** (dozwolony) | **TAK** (dozwolony z kluczem API) | **TAK** (dozwolony) | **TAK** (pełna swoboda) |
| **Publikacja na YouTube** (wideo bez monetyzacji) | **WARUNKOWY** (wymagana atrybucja w opisie/wideo; zakaz prefetchu) | **WARUNKOWY** (do 5M zapytań/mies., wymagana atrybucja na mapie) | **WARUNKOWY** (wymagana pełna atrybucja Esri i partnerów) | **TAK** (zależnie od licencji bazy danych) |
| **Monetyzacja filmu** (AdSense, sponsorzy, sprzedaż) | **WARUNKOWY** (dane ODbL tak; ale zakaz masowego scrapingu serwera OSMF) | **WARUNKOWY** (darmowy limit komercyjny do 1M zapytań/mies.; trwałe utrwalenie w MP4 wymaga potwierdzenia) | **ZABRONIONY** na publicznym endpoincie (wymaga komercyjnej licencji ArcGIS) | **TAK** (pełne prawa komercyjne) |
| **Masowy Route Prefetch** (pobranie całej trasy przed renderem) | **ZABRONIONY** | **ZABRONIONY** | **ZABRONIONY** | **TAK** (w pełni dozwolony) |
| **Lokalny Cache** | Obowiązkowy (min. 7 dni) | Obowiązkowy (max. 30 dni) | Ograniczony (zakaz trwałego archiwizowania) | Zależny od użytkownika |

---

## 4. Kiedy wymagany jest klucz API?

### CARTO
Od aktualizacji polityki CARTO Basemaps, dostęp do kafelków `cartocdn.com` wymaga klucza API użytkownika.
- **Jak uzyskać:** Załóż darmowe konto na [carto.com](https://carto.com).
- **Limity:** Darmowy pakiet komercyjny oferuje do 1 000 000 wyświetleń kafelków na miesiąc.
- **Konfiguracja w SportCamHUD:** Klucz API można bezpiecznie zapisać w systemowym menedżerze poświadczeń (Windows Credential Manager) lub ustawić zmienną środowiskową `CARTO_API_KEY`.

### Esri ArcGIS
Publiczny endpoint satelitarny (`server.arcgisonline.com`) nie wymaga logowania do doraźnego wyświetlania, jednak **nie daje prawa do komercyjnego eksportu wideo ani monetyzacji**.
- Do legalnego wykorzystania komercyjnego wymagany jest płatny plan ArcGIS Location Services lub subskrypcja komercyjna Esri.
- Klucz tokena można ustawić w zmiennej środowiskowej `ARCGIS_API_KEY` lub zapisać w menedżerze poświadczeń.

---

## 5. Bezpieczne przechowywanie kluczy API

SportCamHUD stosuje rygorystyczne zasady bezpieczeństwa poświadczeń:
1. **Brak haseł w plikach i Git:** Klucze API **nigdy** nie są zapisywane w plikach layoutów (`def_layout.json`), plikach projektu ani repozytorium kodu.
2. **Windows Credential Manager:** Klucze są szyfrowane przez system operacyjny Windows i chronione uprawnieniami konta użytkownika.
3. **Maskowanie w logach:** Aplikacja automatycznie maskuje wszelkie klucze w logach (`api_key=***`, `token=***`).

---

## 6. Wymagana atrybucja wizualna i opisy

Dostawcy map wymagają wskazania źródła danych:

1. **OpenStreetMap:**
   - Na mapie lub w napisach końcowych: `© OpenStreetMap contributors`
   - W przypadku filmów publikowanych w internecie (YouTube): obowiązkowy link `https://www.openstreetmap.org/copyright` w opisie filmu.
2. **CARTO:**
   - Na mapie: `© OpenStreetMap contributors, © CARTO`
   - Link: `https://carto.com/attribution/`
3. **Esri World Imagery:**
   - Na mapie: `Sources: Esri, Maxar, Earthstar Geographics, and the GIS User Community`

> **Uwaga:** Zgodnie z decyzją projektową, SportCamHUD domyślnie nie zmienia ustalonego wyglądu Twojego HUD bez Twojej zgody. Dopóki nie włączysz opcji wyświetlania atrybucji na mapie lub nie zamieścisz wymaganego podpisu w opisie filmu, eksport komercyjny jest oznaczony statusem *warunkowym*.

---

## 7. Rekomendacja dla legalnej dystrybucji i twórców na YouTube

### Najbardziej bezpieczny wariant bezpłatny: Własny serwer kafelków (Self-Hosted)
Dla użytkowników i twórców publikujących zmonetyzowane filmy na YouTube, **rekomendowanym i w 100% bezpiecznym prawnie rozwiązaniem** jest uruchomienie lokalnego serwera kafelków na bazie wolnych danych OpenStreetMap.

- **Rozwiązanie:** Kontener Docker `overv/openstreetmap-tile-server` lub `maptiler/tileserver-gl`.
- **Zalety:**
  - 100% darmowe i legalne dla każdego celu (w tym monetyzacja YouTube).
  - Brak limitów pobierania i zapytań na sekundę.
  - Dozwolony pełny prefetch trasy z wyprzedzeniem (błyskawiczny render offline).
  - Brak ryzyka zablokowania IP lub wygaśnięcia kafelków po 30 dniach.
- **Wymagania:** Jednorazowe pobranie pliku `.osm.pbf` (np. dla Polski ~1.8 GB z serwisu Geofabrik) i uruchomienie lokalnej usługi.
- **Konfiguracja w SportCamHUD:** Wystarczy wskazać URL wskaźnika mapy:
  `http://localhost:8080/tile/{z}/{x}/{y}.png`.
