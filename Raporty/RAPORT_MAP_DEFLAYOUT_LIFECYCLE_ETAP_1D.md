# TeleM — MAP ETAP 1D: def_layout lifecycle

## 1. Reprodukcja

Aktualny `def_layout.json` zawiera `indicators.track_map.map_style = "satellite"`. Po ponownym uruchomieniu preload mapy był uruchamiany z domyślnym `provider="light_all"`. Main Preview widział więc kontekst Standard dla wskaźnika Satellite i pozostawał na placeholderze. Po usunięciu i ponownym dodaniu mapy GUI tworzyło konfigurację z `light_all`, dlatego mapa pojawiała się natychmiast.

## 2. Lifecycle mapy z def_layout

`src/gui/qt/controller.py::__init__()` wywołuje `_load_startup_preset()`, a następnie podczas ładowania pliku `src/gui/qt/_mixins/project_mixin.py` ładuje `def_layout.json` przez `normalize_layout()`.

Następnie `_on_files_selected()` parsuje FIT/GPX i wywołuje `_start_map_preload(map_gps, map_source)`. Przed poprawką brak jawnego providera oznaczał `light_all`. Worker aktualizował `MapContext`, a `sig_map_ready` wywoływał `_render_preview()`.

## 3. Lifecycle mapy dodanej ręcznie

`IndicatorMixin::_on_stream_clicked()` wywołuje `_create_indicator("track_map")`. `_create_indicator()` ustawia domyślnie:

```text
form = map
map_style = light_all
```

Render Main Preview pobiera aktualny `MapContext` i konfigurację wskaźnika. Po ponownym dodaniu oba providery były `light_all`, więc bramka renderera przepuszczała mapę.

## 4. Pierwsza różnica

Pierwsza różnica występowała przed renderowaniem:

```text
def_layout: track_map.map_style = satellite
preload: provider = light_all
```

Nie była to różnica w GPS, kafelkach ani `_STATIC_CACHE`.

## 5. MapContext identity/generation

Obie ścieżki korzystają z tego samego `self.map_context`, publikowanego do `map_prepare._CURRENT_MAP_CONTEXT`. Generation guard pozostaje bez zmian. Po poprawce preload tworzy kontekst z providerem wynikającym z layoutu; generation jest nadal zwiększany przez `_start_map_preload()`.

## 6. Cache

Hipoteza trwałego placeholdera w `_STATIC_CACHE` została odrzucona. `_STATIC_CACHE` z `src/indicators/helpers.py` przechowuje rastry statycznych elementów tekstu/gauge/chart; mapa nie zapisuje tam placeholdera.

Renderer `MovingMapRenderer` ma osobny cache zależny od track/zoom/provider/formy renderu. Błąd występował wcześniej — na bramce providera — więc usunięcie i ponowne dodanie wskaźnika jedynie zmieniało konfigurację providera i powodowało poprawne przejście.

## 7. sig_map_ready / preview refresh

`MapPreloadWorker` kończy pracę przez `project_mixin::_on_done()`, emituje `sig_map_ready`, a `controller::_connect_signals()` podłącza ten sygnał do `_render_preview()`. Odświeżenie działało; ponowny render nadal widział jednak `ctx.provider = light_all` przy `map_style = satellite`.

## 8. Faktyczna przyczyna

Startowy preload ignorował provider zapisany w aktywnym layoutie i używał Standard jako wartości domyślnej. Dla aktualnego `def_layout` powodowało to permanentny mismatch:

```text
MapContext.provider = light_all
indicator.map_style = satellite
```

## 9. Minimalna poprawka

Dodano `_map_provider_from_layout()` w `project_mixin.py` i przekazano wynik jawnie do obu startowych wywołań `_start_map_preload()` — dla FIT/GPX oraz fallbacku GPMF. Nie zmieniono MapPreload, pobierania kafelków, geometrii, cache providera ani Export Preview.

## 10. Test startup lifecycle

Dodano `tests/test_map_deflayout_lifecycle.py`:

- sprawdza, że aktualny `def_layout` wybiera Satellite dla initial preload;
- tworzy jeden istniejący wskaźnik Satellite, przygotowuje jego `MapContext` i sprawdza, że po ready zwracany jest obraz mapy, nie placeholder.

## 11. Test def_layout vs interactive

Test wykorzystuje tę samą konfigurację wskaźnika przez cały lifecycle. Nie usuwa i nie tworzy go ponownie. Różnica providerów między saved layout i dawnym interactive default została pokryta przez test wyboru providera oraz test renderu zgodnego Satellite context.

## 12. Standard/Satellite

Provider jest odczytywany z layoutu. Standard nadal pozostaje domyślny, gdy layout nie zawiera `map_style`; Satellite z `def_layout` otrzymuje Satellite preload i zgodny Main Preview.

## 13. Intel/vendor neutrality

Intel ujawnił problem, ale przyczyna jest backend-neutralna. Nie dodano warunku `if intel` i nie zmieniono QSV, AMF, NVENC, CUDA ani D3D11.

## 14. Regresja

Uruchomiono:

```text
python -m pytest -q tests/test_map_deflayout_lifecycle.py tests/test_map_overview_first.py tests/test_map_preload_etap1.py tests/test_map_sync.py
56 passed
```

## 15. Physical GUI

`PHYSICAL GUI VISUAL TEST: NOT EXECUTED`.

## 16. Deferred

- `45% / Wczytywanie JSON` — długi freeze, bez zmian w tym etapie;
- real mouse selection/drag;
- final render time overlap;
- Lean preview/final mismatch;
- altitude rotated text.

