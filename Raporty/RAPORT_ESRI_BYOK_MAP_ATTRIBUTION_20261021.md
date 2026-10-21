# Esri BYOK i atrybucja map — 2026-10-21

**Status: CZĘŚCIOWA IMPLEMENTACJA / NIE GOTOWE DO WYDANIA. Kryterium zakończenia NIE ZOSTAŁO spełnione.**

Brak prawdziwego klucza w Windows Credential Manager, brak kanonicznego materiału benchmarkowego oraz oczekiwanie na zatwierdzenie większego podpisu. Nie deklarujemy rzeczywistego E2E ani zgodności gotowego eksportu. Transport i GUI są przygotowane; docelowa atrybucja Preview/Final NIE jest jeszcze wdrożona. Nie wydawać tej zmiany jako gotowej integracji satelitarnej.

## 1. Stan kodu przed zmianami

- Gałąź `main`, HEAD `e26f76b`, 38 commitów przed `origin/main`.
- `def_layout.json` miał niezapisane zmiany użytkownika (88 dodanych / 54 usunięte linie). Zachowano je i nie dodano do commitów.
- Liczne nieśledzone raporty, logi i kopie DLL istniały przed zadaniem; nie usuwano ich ani nie dodawano do commitów.
- Przeczytano AGENTS.md, BENCHMARKS.md, raport audytu dostawców z 2026-10-20, map_providers, map_attribution, credential_store, moving_map, map_renderer, map_prefetch oraz SettingsTab, sygnały, kontroler i MainWindow.
- Istniały save/get/delete_map_api_key, mask_url, MapProviderRegistry i MapAttributionRenderer.
- Esri wskazywało publiczny server.arcgisonline.com; helper dodawał token do URL. Nie było panelu klucza Esri.
- Renderer atrybucji: domyślnie wyłączony, klucz cache nie uwzględniał tekstu/fontu/paddingu, skracał źródła do niezweryfikowanego „© Esri & contributors”. Podpis był tylko w niektórych gałęziach renderowania. Nie wolno uznać go za gotowe rozwiązanie Preview/AMD Final.
- Gałąź final mapy statycznej zawiera odwołanie do `os` bez importu. Dodano brakujący import; test porównawczy wykonujący źródło HEAD nadal wykazuje `before is None`.

## 2. Wykorzystane moduły i zmienione pliki

Wykorzystano istniejący Windows Credential Manager przez produkcyjne API credential_store oraz istniejące planowanie viewportów, rejestr, rate limiting/cooldown i ścieżki map. Nie dodano drugiego magazynu poświadczeń ani lokalnego serwera.

- `src/integrations/esri.py`: kontrolowany transport, weryfikacja stylu, metadanych i obrazu, bezpieczne komunikaty, cache sesyjny, deduplikacja.
- `src/integrations/credential_store.py`: wspólny cel poświadczeń aliasów Esri; bez odtwarzania usuniętego klucza ze zmiennych środowiskowych.
- `src/map_providers.py`: oficjalny URL; helper formatowania nie zwraca sekretu; jawna numeryczna generacja cache.
- `src/moving_map.py`, `src/map_renderer.py`: transport Esri i wyłączenie odczytu/zapisu trwałego cache Esri; pozostałe źródła zachowują swoje ścieżki.
- `src/indicators/moving_map.py`, `src/indicators/static_map.py`: unieważnianie cache po zmianie klucza, brak wykorzystania starego cache satelitarnego.
- `src/gui/qt/tabs/settings_tab.py`, `signals.py`, `main_window.py`, `controller.py`: panel i status z przejściem do ustawień, aktualizacja Preview po zmianie klucza.
- `tests/test_esri_byok.py`, `tests/test_esri_settings_gui.py`: syntetyczne klucze, mock HTTP, testowy magazyn.
- `src/map_attribution.py`: NIE ZMIENIONO — większa ingerencja wizualna oczekuje na zatwierdzenie zgodnie z poleceniem użytkownika.

## 3. Endpoint i autoryzacja

Kafelki: `https://ibasemaps-api.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}`.
Metadane: ten sam MapServer z `f=json`.
Walidacja klucza: `https://basemapstyles-api.arcgis.com/arcgis/rest/services/styles/v2/styles/arcgis/imagery/standard?f=json&echoToken=false` z `Authorization: Bearer`.

**Istotny wynik rzeczywistych, niskokosztowych prób:** MapServer zwrócił JSON `499 Token Required` dla brakującego tokenu oraz dla syntetycznego tokenu przesłanego w Authorization i X-Esri-Authorization. Udokumentowany parametr query `token` umożliwił pobranie metadanych. Zatem MapServer używa tokenu w URL wyłącznie wewnątrz hermetycznego transportu; helpery, cache i diagnostyka nie otrzymują tego adresu.

**Kafelek 0/0/0 zwrócono również przy celowo nieprawidłowym tokenie query (HTTP 200, JPEG, 14401 bajtów). Nie jest to dowód poprawnej autoryzacji!** Przed kafelkami aplikacja wymaga pozytywnej walidacji klucza przez usługę stylów. Produkcyjny klient z syntetycznym błędnym kluczem odrzucił połączenie jako „Nieprawidłowy klucz”. Nie wykonano fallbacku pobierania kafelków z publicznego endpointu.

Treść błędów serwera i wyjątki urllib mogą zawierać sekret, dlatego nie są przekazywane GUI/logom. Użyto zamkniętego katalogu komunikatów, `raise ... from None`, zachowano mask_url dla pozostałych downloaderów i usunięto wypisywanie surowego HTTPError.

## 4. Uprawnienia

Usługa stylów wymaga `premium:user:basemaps`. Klucz i koszty należą do użytkownika. Panel zawiera oficjalny link i taką informację. Własny klucz nie potwierdza praw do MP4, trwałego archiwum ani pobierania trasy.

## 5. Przechowywanie poświadczeń

Cel Windows Credential Manager: `SportCamHUD:map:esri:api_key`, Generic Credential, istniejąca implementacja CredWriteW/CredReadW/CredDeleteW. Alias satellite/arcgis wskazuje ten sam cel.

Pole Password jest puste po odtworzeniu panelu, czyszczone po zapisie, nie jest połączone z ogólnym sig_settings_changed ani zapisem JSON. Nie dodano pól klucza do layoutów/projektów/presetów. Nie pobrano ani nie zapisano prawdziwego sekretu w raportach, plikach tymczasowych lub Git.

Zapis, odtworzenie panelu, wymiana, odczyt przez API i usunięcie: PASS z testowym magazynem. **Rzeczywisty zapis/odczyt użytkownika w Windows Credential Manager: NOT TESTED.** Stan na początku: brak kluczy esri/satellite/arcgis według produkcyjnego API; tryb mock wyłączony podczas sprawdzenia obecności.

## 6. Brak klucza i błędy

Bez klucza klient nie wykonuje HTTP. Pozostałe wskaźniki i źródła nie zależą od Esri. Pasek stanu dla aktywnej mapy Esri pokazuje komunikat i link do Ustawienia → Integracje, przewijający panel do klucza. Nie dodano spinnera. Przywrócenie zapisanej wartości nie ujawnia sekretu.

Sprawdzenie połączenia działa w workerze; sygnał Qt aktualizuje GUI. Wyniki starej generacji są ignorowane. Zmiana klucza nie czeka na blokadę sieciową; generacja cache nie zawiera sekretu ani jego skrótu.

Obsługiwane: HTTP 400/401/403/429/5xx, ArcGIS JSON error w HTTP 200, 498/499, timeout, błąd połączenia. Cooldown 30 s po błędzie ogranicza ponawianie. Jawne „Sprawdź połączenie” może ponowić próbę wcześniej. Jeśli 498 nie rozróżnia wygaśnięcia i nieprawidłowości, status jest uczciwie łączony. Wyraźny komunikat wygaśnięcia z JSON jest mapowany na „Klucz wygasł”.

## 7. Testy klucza

Automatyczne testy: wyłącznie syntetyczne wartości, mock HTTP i testowy magazyn. Potwierdzono pozytywną walidację na fixture, odrzucenie błędnego klucza przed kafelkiem, brak klucza bez sieci, wygaśnięcie, uprawnienia, limity, offline i timeout. Sprawdzono brak sekretu w zwracanym URL, bezpiecznych wyjątkach i komunikatach; pozostałe źródła nie dostają klucza Esri.

Żywa usługa z syntetycznym błędnym kluczem: odrzucona przez usługę stylów. **Prawidłowy klucz użytkownika i cała sekwencja GUI → Credential Manager → Esri → Preview → MP4: NOT TESTED.**

## 8. Wygląd na małej mapie

Makieta do zatwierdzenia: [attribution_proposal.png](esri_byok_20261021/attribution_proposal.png). Dwie mapy 240/280 px, szary tekst na ciemnym tle, zaokrąglone narożniki, bez logo; pełny podpis wymaga kilku wierszy. Tło to schemat, NIE rzeczywista mapa i NIE screenshot Preview.

Użytkownik wymaga zatwierdzenia większej ingerencji wizualnej. Wysłano pytanie o akceptację tej makiety. **Brak odpowiedzi nie stanowi zgody.** Nie wdrożono większego panelu, nie uznano „© Esri” za wystarczające. Istniejąca niepełna atrybucja nie stanowi spełnienia kryterium.

## 9. Informacje o źródłach

Klient pobiera atrybucję źródeł ze stylu `sources.*.attribution`, usuwa znaczniki HTML i dekoduje encje. Jeżeli styl nie podaje źródeł, odczytuje `copyrightText` z oficjalnego uwierzytelnionego MapServer. Przechowuje tylko tekst, a nie cały JSON stylu, który mógłby zawierać token.

Publiczne metadane odczytane wyłącznie jako materiał porównawczy podają aktualnie: `Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community`. Starszy rejestr wymienia Maxar; dlatego statyczna lista nie może zastąpić bieżących metadanych. Klient dokłada `Powered by Esri`. Docelowe przekazanie tego tekstu do MapAttributionRenderer i wybór danych właściwych dla zasięgu wymagają dalszej implementacji/walidacji.

## 10. Wymagania i ograniczenia licencyjne

Dokumentacja wymaga oznaczenia Esri oraz dostawców danych. Brak potwierdzenia, że „© Esri” lub „© Esri & contributors” jest wystarczające. Przy MP4 nie można polegać wyłącznie na oknie źródeł w aplikacji, bo widz filmu nie ma do niego dostępu.

Do potwierdzenia z Esri: utrwalanie i dystrybucja World Imagery w MP4, zastosowanie modelu tile usage do sekwencji filmowej, granice cache sesyjnego, ewentualne warunki dla monetyzacji filmu, kontekstowe źródła dla poszczególnych zasięgów oraz minimalny rozmiar/forma atrybucji dla małego HUD. Darmowy Microsoft Store i BYOK same nie rozstrzygają tych praw. Nie zmieniono istniejącego restrykcyjnego kontraktu eksportu na „confirmed”.

Źródła oficjalne sprawdzone 2026-10-21:

- [Service data i układ z/y/x](https://developers.arcgis.com/rest/basemap-styles/service-data/)
- [Imagery standard, Bearer i echoToken](https://developers.arcgis.com/rest/basemap-styles/arcgis-imagery-standard-style-get/)
- [Wprowadzenie: uprawnienia i układ Web Mercator](https://developers.arcgis.com/documentation/mapping-and-location-services/mapping/basemaps/introduction-basemap-styles-service/)
- [Atrybucja Esri i danych](https://developers.arcgis.com/documentation/esri-and-data-attribution/) — adres obecnie zwraca pustą treść narzędziu; obowiązek obu oznaczeń potwierdza poniższy oficjalny przewodnik.
- [Oficjalny przykład pełnej atrybucji](https://developers.arcgis.com/openlayers/maps/vector-tile-basemaps/display-a-map/)
- [Warunki obrazów statycznych — nie są automatycznym potwierdzeniem MP4](https://doc.arcgis.com/en/arcgis-online/reference/static-maps.htm)
- [Instrukcja klucza](https://developers.arcgis.com/documentation/security-and-authentication/api-key-authentication/)

Prefetch całej trasy pozostaje wyłączony. Esri nie czyta wcześniejszego dyskowego cache i nie zapisuje nowych zdjęć na dysk; do 256 ostatnich kafelków przechowywane jest tylko w pamięci sesji. Nie kasowano starych plików użytkownika. Deduplikacja w kliencie zapobiega drugiemu żądaniu tej samej płytki przy zbiegu workerów. Zmiana/usunięcie klucza unieważnia dostęp do cache i złożonych map.

**Nierozwiązany kontrakt eksportu:** ensure_map_tiles_cached kończy przygotowanie bez pobierania dla dostawcy zakazującego prefetchu, zwracając liczbę braków. AMD exporter następnie wywołuje `set_map_network_allowed(True)`. Nie potwierdzono więc obietnicy z AGENTS.md „HTTP=0 podczas renderu” dla zimnego cache Esri. Nie zmieniano tego mechanizmu ani nie dodano niedozwolonego prefetchu. Wymaga rozwiązania przed wydaniem: jawne sprawdzenie kompletności legalnego cache/odpowiedni tryb pobierania zatwierdzony przez Esri, obsługa braków bez zastępowania nieautoryzowanymi zdjęciami.

## 11. Zrzuty Preview i Final

- [Rzeczywisty widget ustawień Qt, brak klucza](esri_byok_20261021/settings_no_key.png), renderowany offscreen z Arial do czytelnej inspekcji; NIE pełne E2E aplikacji.
- Preview z prawdziwą mapą i nową atrybucją: NOT TESTED / brak zrzutu.
- Final MP4 z nową atrybucją: NOT TESTED / brak zrzutu.
- Testy mała/duża mapa, 1080p/4K, wszystkie maski, marker, seek, kilka map, zgodność pikseli poza podpisem: dla nowej atrybucji NOT TESTED.
- Metadane World Imagery potwierdzają 256×256 JPEG, EPSG:3857 (102100), północny początek siatki i LOD 0–23. Nie zmieniono projekcji, zoomu, markerów, rotacji, pitch ani proporcji. Rzeczywista zgodność kolorów/orientacji i mozaiki: NOT PROVEN.

## 12. Sprzętowy eksport AMD i testy

Wybrany zestaw: **104 passed, 7.45 s**:

```text
python -m pytest tests/test_esri_byok.py tests/test_esri_settings_gui.py tests/test_map_licensing_and_capabilities.py tests/test_preview_map_panel_parity.py tests/test_map_style_5w.py tests/test_map_pitch_keeps_shape.py tests/test_map_first_render_parity.py tests/test_amd_vbr_governance.py tests/test_amd_qp_governance.py tests/test_amd_direct_mp4_mux.py tests/test_amd_native_ordered_map.py -q
```

Szerszy zestaw z `test_preview_map_cache_miss.py`: **114 passed, 1 failed**. Nieudana próba referencji dla static_map wykonuje kod z Git HEAD i uzyskuje `before is None`; nie stanowi poprawnego porównania pikselowego. Oddzielny zestaw z `test_track_up_map.py`: **38 passed, 1 failed**, oczekiwana lista resolvera kierunku nie uwzględnia dodatkowego wywołania `distance/fit/fit_distance_text` w niezmienionym module przygotowania telemetrii. Nie naprawiano synchronizacji FIT/IMU ani tego testu poza zakresem zadania.

Testy kontraktów QP/VBR/live mux/kolejności nie są sprzętowym renderem. **Sprzętowy eksport, HLG Main10, AAC live mux i finalizacja MP4: NOT TESTED.** Kanoniczna para `Video/GX020079.MP4` + `Video/GX020079.fit` nie istnieje w repo, w C:/_DEV/TeleM ani w sprawdzonej lokalizacji portable. Nie zastąpiono jej innym FIT. Nie uruchomiono historycznego harnessu z niekanonicznymi wpisanymi ścieżkami ani testową DLL.

## 13. Wydajność

FPS, czas przygotowania rzeczywistej mapy, parytet rastra i koszt docelowej atrybucji: **NOT MEASURED**. Nie przedstawiono testów fixture jako benchmarku AMD. Brak zmian rasteryzacji fontów w produkcji; cache warstwy podpisu i jednokrotny upload GPU pozostają do wdrożenia po akceptacji projektu.

## 14. Chroniona DLL i izolacja

Przed i po zmianach SHA-256 `runtime/amd/bin/telem_amd_native.dll`:

`BBCA75FBD0DFC5D7CBB61922E92F8D5F049B4305DD18335315667E6E5E54CA5F`

Nie zmieniono DLL, native AMD, eksportera, QP/VBR, HLG/HDR, live mux, audio, finalizacji, kompasu, BAR, temperatury ani synchronizacji FIT/IMU. Brak Dockera, serwera, nowej gałęzi/worktree i push. Zmiany współdzielone ograniczono do transportu/cache Esri oraz obsługi GUI; źródła OSM/CARTO/Custom pozostają dostępne i nie otrzymują klucza Esri.

## 15. Lokalne commity

`45f09db4024778ead8b226d1b13e7df4a252aee1` — `feat(esri): add BYOK settings and validated transport; attribution pending approval`. Osobny commit dokumentacji dodaje zrzuty i końcowy stan; jego własne SHA jest dostępne w `git log -1` (raport nie może zawierać własnego SHA). Nie wykonano push.

## 16. Końcowy Git i warunki kontynuacji

Po commicie implementacji: `main`, jedyna zmiana śledzonego pliku to zastana ` M def_layout.json`; 103 zastane pliki/katalogi nieśledzone. Po commicie dokumentacji brak zmian implementacji w working tree. Gałąź będzie 40 commitów przed origin/main. Istniejące zmiany użytkownika pozostają poza staged/commit. Zrzuty PNG dodano jawnie mimo globalnego ignorowania PNG, ponieważ stanowią wymagany materiał raportu. Pełne zakończenie wymaga:

1. Odpowiedzi na przedstawioną propozycję atrybucji (zgodnie z poleceniem użytkownika).
2. Zapisania rzeczywistego klucza przez nowe GUI — nigdy w rozmowie ani w pliku.
3. Implementacji zatwierdzonej warstwy we wszystkich ścieżkach, w tym AMD GPU Track-Up bez obracania napisu.
4. Rozwiązania kontraktu eksportu bez niedozwolonego prefetchu i sprawdzenia kompletności map.
5. Dostępnej kanonicznej pary VIDEO/FIT, testu rzeczywistego E2E, zrzutów i pomiarów.

**PASS: testowana część GUI/transport/magazyn testowy i zachowanie DLL. FAIL / NOT PROVEN: kryterium końcowe całego zadania.**
