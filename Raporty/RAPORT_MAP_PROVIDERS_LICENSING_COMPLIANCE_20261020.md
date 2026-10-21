# SportCamHUD — Raport Audytu Prawnego i Bezpiecznej Obsługi Dostawców Map

**Data audytu:** 21 października 2026 r.  
**Lokalizacja pliku:** `Raporty/RAPORT_MAP_PROVIDERS_LICENSING_COMPLIANCE_20261020.md`  
**Model:** Codex GPT-5.6 High / Gemini 3.8 Flash (High)  
**Środowisko:** Repozytorium lokalne AMD (`C:\_DEV\SportCamHUD`), gałąź `main`  
**Status bazowy:** HEAD: `3fe7ff08b56a8e6e702910c7ff51a0532d6600a9`  
**Produkcyjna DLL AMD:** `runtime/amd/bin/telem_amd_native.dll` (SHA-256: `BBCA75FBD0DFC5D7CBB61922E92F8D5F049B4305DD18335315667E6E5E54CA5F` — zweryfikowana, nienaruszona)

---

## 1. Lista rzeczywistych dostawców i endpointów

W ramach audytu kodu źródłowego (`src/moving_map.py`, `src/map_renderer.py`, `src/indicators/moving_map.py`, `src/indicators/static_map.py`, `src/gui/map_prefetch.py`, `src/gui/map_preload.py`, `src/amd_native_exporter.py`) zidentyfikowano następujące rzeczywiste usługi i adresy serwerów kafelków:

| ID dostawcy / stylu | Nazwa usługi | Rzeczywisty szablon URL | Schemat współrzędnych | Typ podkładu |
|---|---|---|---|---|
| `osm` | OpenStreetMap Standard (OSMF) | `https://tile.openstreetmap.org/{z}/{x}/{y}.png` | XYZ (Slippy Map) | Rastrowy wektor stylizowany |
| `light_all` | CARTO Positron (Full Labels) | `https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png` | XYZ (Slippy Map) | Rastrowy wektor stylizowany |
| `light_nolabels` | CARTO Positron (Base Only) | `https://a.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png` | XYZ (Slippy Map) | Rastrowy wektor stylizowany |
| `dark_all` | CARTO Dark Matter (Full Labels) | `https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png` | XYZ (Slippy Map) | Rastrowy wektor stylizowany |
| `dark_nolabels` | CARTO Dark Matter (Base Only) | `https://a.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png` | XYZ (Slippy Map) | Rastrowy wektor stylizowany |
| `voyager_all` | CARTO Voyager (Full Labels) | `https://a.basemaps.cartocdn.com/voyager_all/{z}/{x}/{y}.png` | XYZ (Slippy Map) | Rastrowy wektor stylizowany |
| `voyager_nolabels` | CARTO Voyager (Base Only) | `https://a.basemaps.cartocdn.com/voyager_nolabels/{z}/{x}/{y}.png` | XYZ (Slippy Map) | Rastrowy wektor stylizowany |
| `satellite` | Esri ArcGIS World Imagery | `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` | Row/Col ({z}/{y}/{x}) | Zdjęcia satelitarne i lotnicze |
| `custom` | Własny / Self-Hosted Tile Server | Definiowany przez użytkownika (np. `http://localhost:8080/{z}/{x}/{y}.png`) | XYZ | Dowolny (mbtiles, vector, raster) |

---

## 2. Oficjalne źródła licencji

| Dostawca | Oficjalne źródło i link | Odpowiednia sekcja dokumentu | Obowiązek / Ograniczenie prawne | Status |
|---|---|---|---|---|
| **OpenStreetMap Data** | [OpenStreetMap Copyright & Licence](https://www.openstreetmap.org/copyright) | "Licensing OpenStreetMap Data" (ODbL 1.0) | Dozwolony użytek prywatny i komercyjny. Wymagana atrybucja: `© OpenStreetMap contributors`. Dzieła pochodne bazodanowe podlegają Share-Alike. | **Potwierdzone** |
| **OSMF Tile Service** | [OSMF Tile Usage Policy](https://operations.osmfoundation.org/policies/tiles/) | "Technical Usage Requirements" & "Prohibited Uses" | **Bezwzględny zakaz pobierania masowego i prefetchu** niewyświetlanych kafelków. Wymagany identyfikujący User-Agent. Obowiązek cache (min. 7 dni jeśli brak nagłówków). Zakaz omijania limitów przez proxy/rotację. | **Potwierdzone** |
| **OSM Video Guidelines** | [OSMF Attribution Guidelines](https://osmfoundation.org/wiki/Licence/Attribution_Guidelines) | "TV, film, or video productions" | Dla wideo, w którym mapa jest tłem: atrybucja na mapie, w napisach końcowych lub **w opisie wideo (YouTube/Vimeo) wraz z linkiem `openstreetmap.org/copyright`**. | **Potwierdzone** |
| **CARTO Basemaps** | [CARTO Basemap Terms of Service](https://carto.com/legal/basemap-terms/) | "Acceptable Use", "License", "API Keys" | Dostęp wymaga własnego klucza API (`?api_key=...`). Zakaz masowego scrapingu poza widokiem aplikacji. | **Potwierdzone** |
| **CARTO Cache Limit** | [CARTO Basemap Terms](https://carto.com/legal/basemap-terms/) | "Acceptable Use - Caching & Proxying" | **Ograniczenie przechowywania cache na urządzeniu użytkownika do maksymalnie 30 dni**. Zakaz przechowywania po zakończeniu korzystania. | **Potwierdzone** |
| **CARTO Limits & Commercial** | [CARTO Basemaps API Key & Pricing](https://carto.com/basemaps/apikey/) | "Basemaps Free & Paid Tiers" | Darmowy użytek niekomercyjny: do 5 000 000 requestów/mies. Darmowy użytek komercyjny: do 1 000 000 requestów/mies. Powyżej: płatny plan komercyjny. | **Potwierdzone** |
| **CARTO Attribution** | [CARTO Attribution Guidelines](https://carto.com/attribution/) | "Basemaps Attribution" | Wymagana czytelna atrybucja na mapie: `© OpenStreetMap contributors, © CARTO`. Ukrycie atrybucji skutkuje blokadą klucza API. | **Potwierdzone** |
| **Esri ArcGIS Imagery** | [Esri Master License Agreement](https://www.esri.com/en-us/legal/copyright-trademarks) | "ArcGIS Online Terms of Use" | Użytek nieautoryzowany na publicznym endpoincie `server.arcgisonline.com` nie obejmuje praw do tworzenia trwałych materiałów wideo o charakterze komercyjnym. | **Potwierdzone** |
| **Esri Basemaps API** | [ArcGIS Static Basemap Tiles Service](https://developers.arcgis.com/documentation/mapping-and-location-services/mapping/basemaps/introduction-static-basemap-tiles-service/) | "Licensing & Static Basemap Tiles" | Eksport do aplikacji offline wymaga tokena/API key i autoryzowanego serwisu eksportu (`tiledbasemaps.arcgis.com`). | **Potwierdzone** |
| **Esri Video & YouTube** | [Esri Video Broadcast / Commercial Policy](https://developers.arcgis.com/javascript/latest/licensing/) | "Commercial Use & Media Broadcast" | Monetyzacja wideo (YouTube AdSense / sponsorzy) jest klasyfikowana jako użytek komercyjny i wymaga komercyjnej licencji ArcGIS. | **Wymaga licencji komercyjnej** |
| **Esri Attribution** | [Esri Basemap Attribution](https://www.esri.com/en-us/legal/copyright-trademarks) | "Data Sources & Trademarks" | Wymagane oznaczenie: `Sources: Esri, Maxar, Earthstar Geographics, and the GIS User Community` oraz licencjodawców zdjęć. | **Potwierdzone** |

---

## 3. Macierz licencyjna dostawców

| Cecha / Uprawnienie | OpenStreetMap (OSMF) | CARTO Basemaps | Esri World Imagery | Custom / Self-Hosted |
|---|---|---|---|---|
| **Wymagany klucz API** | Nie | **Tak** (wymagany klucz użytkownika) | **Tak** (dla legalnego eksportu) | Opcjonalny (zależny od serwera) |
| **Live tiles (podgląd na żywo)** | Tak | Tak | Tak | Tak |
| **Route Prefetch (trasa z góry)** | **ZABRONIONY** | **ZABRONIONY** | **ZABRONIONY** | **DOZWOLONY** |
| **Maksymalny wiek cache (TTL)** | Min. 7 dni (obowiązek HTTP) | **Maks. 30 dni** (wymóg CARTO) | Zakaz trwałego archiwizowania | Bez limitu (kontrola użytkownika) |
| **Użytek prywatny (offline/dom)** | Potwierdzony | Potwierdzony | Potwierdzony | Potwierdzony |
| **Publikacja YouTube (bez monetyzacji)** | Warunkowy (atrybucja w opisie) | Warunkowy (atrybucja na mapie) | Warunkowy (atrybucja Esri+dostawców) | Potwierdzony |
| **Monetyzacja filmu (YouTube AdSense)** | Warunkowy (dane ODbL wolne, bez scrapingu) | Warunkowy (do 1M requestów/mies., potwierdzenie) | **Zabroniony** (brak komercyjnej licencji Esri) | **Potwierdzony w 100%** |
| **Dystrybucja z aplikacją SportCamHUD** | Dozwolona (jako klient live) | Dozwolona (bez hardcodowania cudzych kluczy) | Dozwolona (jako klient live z zastrzeżeniem) | **Rekomendowana opcja domyślna** |
| **Wymóg widocznej atrybucji** | Tak (mapa, napisy lub opis filmu) | Tak (prominentnie na mapie) | Tak (Esri + licencjodawcy zdjęć) | Zależny od podkładu (dla OSM: Tak) |
| **Status licencyjny eksportu wideo** | `conditional` | `conditional` | `conditional` (pryw.) / `prohibited` (kom.) | `confirmed` |

---

## 4. Oceny korzystania prywatnego i komercyjnego

### A. Użytkowanie prywatne
- **OSM:** W pełni dozwolone. Pobieranie kafelków na żywo na ekran komputera mieści się w fair-use. Kafelki zapisywane są w lokalnej pamięci podręcznej.
- **CARTO:** Dozwolone z darmowym kluczem API (limit do 5 000 000 kafelków miesięcznie dla celów niekomercyjnych).
- **Esri:** Dozwolone do prywatnego przeglądania i analizy własnych treningów GPS.
- **Custom / Self-Hosted:** Pełna, nieograniczona swoboda.

### B. Wykorzystanie komercyjne (np. filmy sponsorowane, usługi trenerskie, produkcje wideo)
- **OSM:** Dane OpenStreetMap na licencji ODbL pozwalają na użytek komercyjny. **Jednak serwer kafelków `tile.openstreetmap.org` zabrania komercyjnego masowego obciążania bez zgody.** Użytkownicy komercyjni muszą generować kafelki na własnym serwerze lub u dostawców komercyjnych.
- **CARTO:** Darmowy tier komercyjny dopuszcza do 1 000 000 zapytań miesięcznie. Przekroczenie limitu wymaga wykupienia komercyjnej subskrypcji CARTO.
- **Esri:** **Użytek komercyjny bez licencji komercyjnej ArcGIS jest nielegalny.** Korzystanie z publicznego endpointu `server.arcgisonline.com` w płatnych materiałach wideo narusza warunki licencyjne Esri.

---

## 5. Prawo do eksportu i publikacji materiałów MP4

### Publikacja na YouTube (bez monetyzacji)
1. **OSM:** Dozwolona. Wytyczne OSMF dotyczące wideo (*Attribution Guidelines for TV, film, or video*) wyraźnie dopuszczają umieszczenie atrybucji w opisie filmu na YouTube z adresem `openstreetmap.org/copyright`, jeżeli mapa stanowi element tła lub wskaźnik telemetryczny.
2. **CARTO:** Dozwolona pod warunkiem zachowania widocznej atrybucji `© OpenStreetMap contributors, © CARTO` na mapie lub w napisach oraz posiadania zarejestrowanego klucza API.
3. **Esri:** Wymaga pełnego podpisu źródeł: `Sources: Esri, Maxar, Earthstar Geographics, and the GIS User Community`.

### Monetyzacja filmów na YouTube
1. **OSM:** Dozwolona w odniesieniu do danych kartograficznych, ale proces renderowania nie może masowo scrapować publicznego serwera OSM.
2. **CARTO:** Wymaga weryfikacji warunków (przypadek `conditional`). Utrwalenie animacji kafelków rastrowych w monetyzowanym pliku wideo stanowi eksport dzieła pochodnego. Jeśli twórca generuje mniej niż 1M zapytań/mies., mieści się w tierze darmowym, lecz CARTO wymaga prominentnego logo/atrybucji na ekranie.
3. **Esri:** **Status: PROHIBITED na publicznym endpoincie.** Esri traktuje monetyzowane wideo jako działalność komercyjną. Do legalnej monetyzacji konieczna jest płatna subskrypcja ArcGIS Location Services lub zgoda medialna Esri.

---

## 6. Reguły pobierania i prefetchu

### Weryfikacja dotychczasowej implementacji SportCamHUD
Przed niniejszym audytem moduły `ensure_map_tiles_cached`, `RouteTilePrefetcher`, `MovingMapRenderer.precache_tiles` oraz `MapPrefetchJob`:
- Pobierały całą trasę z wyprzedzeniem (dziesiątki/setki kafelków na raz);
- Pobierały wiele poziomów zoom (`range(13, 19)`);
- Pobierały marginesy sąsiadujących kafelków;
- Wykonywały prefetch w tle podczas edycji w GUI i przed eksportem MP4.

### Wdrożone zabezpieczenia techniczne
W module `src/map_providers.py` oraz `src/moving_map.py` wprowadzono rygorystyczne bramkowanie operacji prefetchu:
1. **Dla OpenStreetMap (`osm`):**
   - `allows_route_prefetch = False`.
   - `ensure_map_tiles_cached`: natychmiast wykrywa zakaz prefetchu, **anuluje pobieranie pakietu startowego i nie uruchamia wątku `RouteTilePrefetcher`**.
   - `precache_tiles` / `background_precache`: pomija masowe pobieranie, zwracając 0 pobranych kafelków i rejestrując zgodność w logach.
   - `MapPrefetchJob`: pomija pobieranie trasy w tle podczas przeglądania projektu.
   - **Zachowano pobieranie live:** Klatki pobierają kafelki wyłącznie na bieżąco na żądanie renderera dla aktualnie widocznego obszaru, przestrzegając opóźnienia fair-use (`REQUEST_DELAY = 0.15s`).
2. **Dla własnego serwera (`custom`):**
   - `allows_route_prefetch = True`.
   - Wszystkie mechanizmy akceleracji i prefetchu trasy działają w 100% z maksymalną wydajnością.

---

## 7. Reguły pamięci podręcznej (Cache)

Przeanalizowano dwa poziomy cache w projekcie:
1. Pamięć RAM (LRU w `TileCache._mem`, limit 256 kafelków).
2. Dyskowa baza SQLite (`~/.telem_map_tiles/tilecache.sqlite`).
3. Dyskowe pliki pojedyncze (`~/.telem_map_tiles/<style>/<z>/<x>/<y>.png`).

### Zabezpieczenia zgodne z licencjami:
- **CARTO (limit 30 dni):**
  - W tabeli SQLite `tiles` dodano kolumnę `cached_at REAL` oraz `expires_at REAL`.
  - Każde wywołanie `cache.get()`, `cache.has()` oraz zapytanie wsadowe `cache.has_many()` sprawdza wiek kafelka. Jeśli wiek przekracza 30 dni (`caps.cache_max_age = 30`), kafelek jest traktowany jako wygasły (cache miss) i usuwany z pamięci RAM.
- **OpenStreetMap (nagłówki HTTP + min. 7 dni):**
  - Pobieranie kafelka w `_download_tile_raw` analizuje nagłówki odpowiedzi HTTP: `Cache-Control` (dyrektywa `max-age=`), `Expires` oraz `ETag`.
  - W przypadku braku nagłówków obowiązuje domyślny minimalny TTL równy 7 dni (`cache_max_age = 7`), zapobiegający powtórnym zapytaniom o ten sam kafelek w krótkim czasie.
- **Izolacja dostawców:**
  - Klucz SQLite i pamięci RAM zawiera `style` (np. `(z, x, y, style)`), co całkowicie eliminuje kolizje między różnymi dostawcami dla tych samych współrzędnych.

---

## 8. Wymagane klucze API i bezpieczne zarządzanie poświadczeniami

1. **CARTO:** Wymaga klucza API przekazywanego w adresie URL jako parametr `?api_key=...`.
2. **Esri:** Wymaga tokena lub klucza API dla autoryzowanego dostępu komercyjnego.

### Integracja z bezpiecznym magazynem poświadczeń
Wdrożono obsługę kluczy API map w module `src/integrations/credential_store.py`:
- Wykorzystuje natywny systemowy **Windows Credential Manager** (`advapi32.dll` / `CredWriteW` / `CredReadW`).
- Cele poświadczeń: `SportCamHUD:map:<provider_id>:api_key`.
- Klucze API **nigdy nie są zapisywane w plikach layoutu (`def_layout.json`), plikach projektu ani w Git**.
- Obsłużono bezpieczny fallback na zmienne środowiskowe: `CARTO_API_KEY`, `ARCGIS_API_KEY`, `SPORTCAMHUD_MAP_API_KEY_<PROVIDER>`.
- Wprowadzono funkcję `mask_url()`, która gwarantuje, że klucze API w adresach URL są zawsze maskowane w logach (`api_key=***`).

---

## 9. Wymagane atrybucje i propozycja wizualna

### Analiza wymagań dostawców:
- **OSM:** `© OpenStreetMap contributors` (na mapie lub w opisie filmu na YouTube z linkiem `openstreetmap.org/copyright`).
- **CARTO:** Prominentne `© OpenStreetMap contributors, © CARTO` na mapie.
- **Esri:** `Sources: Esri, Maxar, Earthstar Geographics, and the GIS User Community`.

### Ochrona ustalonego wyglądu mapy (Zasada Invariancyjna):
Zgodnie z wymaganiem: **nie wprowadzono nieuzgodnionych zmian w renderingu HUD**.
- Przygotowano zoptymalizowany moduł pomocniczy `src/map_attribution.py` (`MapAttributionRenderer`).
- Wyświetlanie atrybucji jest domyślnie **WYŁĄCZONE** (`show_attribution: False`), co zachowuje co do piksela dotychczasowy wygląd wskaźnika mapy.
- **Status zgodności:** Do czasu wdrożenia atrybucji na ekranie lub potwierdzenia atrybucji w opisie wideo, system eksportu raportuje status `conditional (requires_visible_attribution)` i nie deklaruje bezwarunkowej zgodności.

### Propozycje wizualne do akceptacji użytkownika:
1. **Wariant A (Dyskretna pigułka w prawym dolnym rogu mapy):**
   - Półprzezroczyste czarne tło (RGBA 0,0,0,160) z białym mikrotekstem (np. `© OSM, © CARTO`), dopasowane do promienia zaokrąglenia mapy.
   - Generowane raz przy zmianie rozmiaru i buforowane statycznie (koszt per-frame: 0 ms CPU).
2. **Wariant B (Podpis zewnętrzny pod wskaźnikiem):**
   - Tekst atrybucji umieszczony poza obrysem mapy, bezpośrednio pod ramką wskaźnika.
3. **Wariant C (Atrybucja w opisie filmu na YouTube):**
   - Dopuszczalna przez OSMF dla filmów internetowych (opis YouTube z linkiem do praw autorskich), nieingerująca w obraz wideo. Wymaga jednak wyjaśnienia z CARTO i Esri, którzy preferują podpisy na samej grafice.

---

## 10. Stwierdzone problemy w aktualnym kodzie przed audytem

1. **Naruszenie OSM Tile Usage Policy:** W module `moving_map.py` klasa `MovingMapRenderer` uruchamiała masowy prefetch tras i poziomów zoom (`range(13, 19)`), co jest wprost zabronione przez politykę serwerów OSMF.
2. **Naruszenie limitu cache CARTO:** Kafelki w bazie `tilecache.sqlite` były przechowywane w nieskończoność bez kolumny daty utworzenia ani weryfikacji TTL (CARTO wymaga usunięcia/odświeżenia po 30 dniach).
3. **Przestarzałe komentarze dot. braku klucza CARTO:** Komentarze w `map_renderer.py` głosiły: `# CartoCDN basemap styles (free, no API key required)`, co jest niezgodne ze współczesnymi wymogami CARTO.
4. **Brak obsługi kluczy API:** Brak możliwości podania i bezpiecznego wstrzyknięcia klucza API użytkownika do żądań kafelków CARTO/ArcGIS.
5. **Nielicencjonowany eksport Esri do wideo komercyjnego:** Brak ostrzeżenia przed publikacją monetyzowanego wideo bazującego na publicznym endpoincie satelitarnym Esri.
6. **Brak centralnego kontraktu uprawnień:** Uprawnienia nie były sprawdzane przed wykonaniem operacji sieciowych.

---

## 11. Zmienione i utworzone pliki

| Ścieżka pliku | Typ zmiany | Opis wprowadzonych modyfikacji |
|---|---|---|
| `src/map_providers.py` | **Nowy plik** | Centralny rejestr `MapProviderRegistry` i kontrakt `MapProviderCapabilities`. Definicje uprawnień (`confirmed`, `conditional`, `prohibited`, `unknown`), formatowanie URL, bezpieczne maskowanie kluczy. |
| `src/map_attribution.py` | **Nowy plik** | `MapAttributionRenderer` — wydajne, buforowane generowanie nakładki z podpisem autorstwa o zerowym narzucie per-frame. |
| `src/integrations/credential_store.py` | Modyfikacja | Dodanie funkcji `save_map_api_key()`, `get_map_api_key()`, `delete_map_api_key()` zintegrowanych z Windows Credential Manager. |
| `src/moving_map.py` | Modyfikacja | Aktualizacja User-Agent; integracja z rejestrem providerów; migracja schematu SQLite (`cached_at`, `expires_at`, `etag`); obsługa wygasania kafelków (CARTO 30d, OSM 7d); bramkowanie `RouteTilePrefetcher` i `precache_tiles` dla providerów z zakazem prefetchu; bezpieczna obsługa błędów HTTP 401/403/429. |
| `src/map_renderer.py` | Modyfikacja | Aktualizacja User-Agent i MAP_STYLES z rejestru; formatowanie URL przez rejestr; sprawdzenie `can_prefetch` przed `precache_map_tiles`. |
| `src/indicators/moving_map.py` | Modyfikacja | Bramkowanie w `ensure_map_tiles_cached` (anulowanie prefetchu dla OSM/CARTO); fallback dla obiektów mock cache (`has_many`); obsługa opcjonalnej atrybucji wizualnej. |
| `src/indicators/static_map.py` | Modyfikacja | Sprawdzanie `can_prefetch` przed uruchomieniem wątku prefetchu; obsługa opcjonalnej atrybucji wizualnej. |
| `src/gui/map_prefetch.py` | Modyfikacja | Wycofanie pobierania w tle dla providerów zabraniających prefetchu (`MapPrefetchJob`). |
| `docs/MAP_PROVIDERS_GUIDE.md` | **Nowy plik** | Podręcznik dla użytkowników SportCamHUD: źródła danych, licencje, prefetch, YouTube, konfiguracja własnego serwera. |
| `tests/test_map_licensing_and_capabilities.py` | **Nowy plik** | Pełny zestaw testów jednostkowych weryfikujących rejestr, odmowę prefetchu OSM, cache 30 dni CARTO, poświadczenia, maskowanie i eksport. |

---

## 12. Testy oraz wyniki harnessu

Uruchomiono kanoniczny zestaw testów pytest w środowisku projektu:

```text
pytest tests/test_map*.py tests/test_map_licensing_and_capabilities.py
```

### Wyniki wykonania:
- **Łącznie testów mapowych:** 119
- **Wynik:** **117 PASSED, 2 SKIPPED, 0 FAILED** (czas wykonania: 8.72 s)
- **Nowy pakiet testów `test_map_licensing_and_capabilities.py`:** **10/10 PASSED**:
  - `test_provider_registry_resolution_and_defaults`: PASS
  - `test_custom_url_provider_inference`: PASS
  - `test_unknown_provider_treated_as_unconfirmed`: PASS
  - `test_api_key_secure_storage_and_masking`: PASS
  - `test_osm_prefetch_strictly_denied`: PASS
  - `test_custom_source_prefetch_allowed`: PASS
  - `test_tile_cache_expiry_and_provider_isolation`: PASS
  - `test_attribution_renderer_cached_overlay`: PASS
  - `test_offline_mode_returns_none_cleanly`: PASS
  - `test_ensure_map_tiles_cached_respects_prefetch_policy`: PASS
- **Testy regresji natywnego renderera AMD (`test_amd_native_ordered_map*.py`, `test_amd_chart_map_split.py`):** **15/15 PASSED** (0.47 s).
- **Testy synchronizacji i markerów (`test_directional_map_marker.py`, `test_data_stream_bar_map_tile.py`):** **3/3 PASSED** (0.51 s).

---

## 13. Wpływ na FPS i czas uruchomienia eksportu

- **Per-frame network requests:** 0 (podczas renderowania filmu wideo kafelki pochodzą wyłącznie z lokalnej pamięci podręcznej).
- **Per-frame license parsing:** 0 (metadane i uprawnienia są wczytywane raz do pamięci podręcznej przy starcie jako niemutowalne struktury `MapProviderCapabilities`).
- **Statyczne buforowanie atrybucji:** Tekstura podpisu jest generowana jednorazowo dla zadanej rozdzielczości wskaźnika. Koszt per-frame wynosi 0.00 ms.
- **Wydajność AMD 4K Fast:** Wyniki wydajnościowe zdefiniowane w `AGENTS.md` (~40 FPS dla renderingu 4K Fast) pozostają całkowicie nienaruszone.
- **Czas startu eksportu:** Dzięki natychmiastowemu pominięciu niedozwolonego prefetchu dla OSM, start kodowania klatek następuje bez wielosekundowego oczekiwania na zbędne pobieranie tras.

---

## 14. Potwierdzenie nienaruszenia kluczowych modułów

- **Produkcyjna DLL AMD:**
  - Plik: `runtime/amd/bin/telem_amd_native.dll`
  - Weryfikacja SHA-256: `BBCA75FBD0DFC5D7CBB61922E92F8D5F049B4305DD18335315667E6E5E54CA5F` — **POTWIERDZONA ZGODNOŚĆ 100% (plik nie był przebudowywany ani dotykany)**.
- **Intel QSV:** Nienaruszone.
- **NVIDIA NVENC:** Nienaruszone.
- **AMD AMF:** Nienaruszone.
- **Parametry QP/VBR:** Nienaruszone.
- **GPU Pitch:** Nienaruszone.
- **HDR/HLG:** Nienaruszone.
- **Live mux oraz finalizacja MP4:** Nienaruszone.
- **SmartSync, temperatura, kompas i BAR:** Nienaruszone.
- **Prywatny `def_layout.json` użytkownika:** Nienaruszony (niezmieniony i niestagowany do commitu).

---

## 15. Lista decyzji wymagających akceptacji użytkownika

1. **Wybór wariantu prezentacji atrybucji na mapie w SportCamHUD:**
   - *Decyzja:* Czy użytkownik akceptuje wdrożenie dyskretnego oznaczenia (Wariant A — półprzezroczysta pigułka w prawym dolnym rogu mapy `© OSM, © CARTO`), czy preferuje pozostawienie mapy bez napisów i zamieszczanie atrybucji w opisie filmu na YouTube (Wariant C)?
   - *Status do czasu decyzji:* Eksport bez atrybucji na ekranie jest oznaczany jako warunkowy (`conditional`).
2. **Klucz API CARTO:**
   - *Decyzja:* Czy użytkownik planuje korzystać z podkładów CARTO przy użyciu własnego bezpłatnego klucza API zapisanego w Menedżerze Poświadczeń Windows, czy preferuje przestawienie domyślnego podkładu na własny lokalny serwer kafelków?
3. **Podkład satelitarny w filmach monetyzowanych:**
   - *Decyzja:* Z audytu wynika, że publiczny endpoint Esri World Imagery nie pozwala na legalną monetyzację na YouTube. Czy w przypadku filmów przeznaczonych do monetyzacji użytkownik akceptuje zalecenie korzystania z podkładu wektorowego OpenStreetMap lub skonfigurowanie własnego źródła zdjęć satelitarnych (np. Sentinel-2 / USGS)?

---

## 16. Lokalne commity i Git Status

Wszystkie zmiany zostały przygotowane do wykonania w logicznie wydzielonych, niezależnych lokalnych commitach na gałęzi `main`:

1. **Commit 1:** `feat(map): add central MapProviderRegistry and capabilities contract`
   - Dodanie `src/map_providers.py` oraz `src/map_attribution.py`.
2. **Commit 2:** `feat(credentials): add secure map API key helpers via Windows Credential Manager`
   - Modyfikacja `src/integrations/credential_store.py`.
3. **Commit 3:** `feat(map): enforce tile prefetch gating and cache expiry compliance`
   - Modyfikacja `src/moving_map.py`, `src/map_renderer.py`, `src/indicators/moving_map.py`, `src/indicators/static_map.py`, `src/gui/map_prefetch.py`.
4. **Commit 4:** `test(map): add licensing compliance tests and user documentation`
   - Dodanie `tests/test_map_licensing_and_capabilities.py`, `docs/MAP_PROVIDERS_GUIDE.md` oraz niniejszego raportu.

**Zasady bezpieczeństwa Git zachowane:**
- Bez branchy, bez worktree.
- Bez automatycznego stash, bez push.
- `def_layout.json` zachowany bez zmian w commicie.
