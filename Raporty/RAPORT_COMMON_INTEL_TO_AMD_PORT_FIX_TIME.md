# RAPORT: Naprawa Regresji `_time NameError` Podczas Wczytywania Projektu

**Projekt:** TeleM  
**Zadanie:** Identyfikacja i minimalna naprawa błędu `name '_time' is not defined` po selektywnym przeniesieniu wspólnych zmian z gałęzi Intel  
**Data:** 25 sierpnia 2026  
**Status:** ZAKOŃCZONY SUKCESEM  

---

## 1. Root Cause (Przyczyna Źródłowa)

Podczas selektywnego przenoszenia zmian z gałęzi Intel (`origin/intel-render`, commit `e019a6b45278f09f718f528642767f505ea87934`) przeniesiono instrumentację etapów profilowania czasu wczytywania (`profile_cb` rejestrujące czasy poszczególnych podetapów parsowania GPMF).

W pliku [telemetry_manager.py](file:///c:/_DEV/TeleM/src/gui/telemetry_manager.py):
* Użyto wywołań `_time.perf_counter()` w metodzie `load_gpmf_records`, lecz na początku pliku brakowało importu `import time as _time`.
* W metodzie `load_gps_track` brakowało obsługi opcjonalnego parametru `profile_cb=None`.

W efekcie po analizie strumienia MP4 (przy ok. 28–30% paska postępu GUI), gdy wywoływana była faza `Analiza GPMF...`, Python rzucał `NameError: name '_time' is not defined`.

---

## 2. Identyfikacja Miejsca Błędu i Powiązanie z Mapą

```text
LOAD STAGE: Analiza GPMF / Parsowanie rekordów telemetrii (28-30% progress)
FUNCTION: TelemetryDataManager.load_gpmf_records / TelemetryDataManager.load_gps_track
RELATED TO MAP LOAD/CACHE: NO (błąd dotyczył profilera parsowania surowych rekordów GPMF, przed fazą pobierania kafelków mapy)
SOURCE COMMIT: e019a6b ("Poprawki i korety", gałąź intel-render)
```

---

## 3. Zastosowane Minimalne Zmiany

1. **[src/gui/telemetry_manager.py](file:///c:/_DEV/TeleM/src/gui/telemetry_manager.py)**:
   - Dodano import `import time as _time`.
   - Zaktualizowano `load_gps_track(self, records: list[dict], profile_cb=None)` z bezpiecznym przechwytywaniem czasu wydobycia śladu GPS.
2. **[src/telemetry_extract.py](file:///c:/_DEV/TeleM/src/telemetry_extract.py)**:
   - Potwierdzono obecność `import time as _time` na poziomie modułu.

---

## 4. Wyniki Testu Workflow `Wczytaj`

Wykonano test weryfikacyjny dokładnie według zadanej procedury:
1. **Wideo:** `Video/GX020079.mp4`
2. **FIT:** `Video/Morning_Ride.fit`
3. **Akcja:** Pełne wykonanie `_on_files_selected` (odpowiednik przycisku `Wczytaj` w GUI).

### Przebieg i Rezultat:
* Brak jakichkolwiek wyjątków `NameError` lub `TypeError`.
* Pasek postępu przeszedł płynnie przez wszystkie etapy: `0% -> 15% -> 30% -> 45% -> 55% -> 75% -> 80% -> 85% -> 90% -> 95% -> 100% (Gotowe)`.
* Załadowano poprawnie:
  - 378 próbek prędkości GPMF, 378 punktów trasy GPS GPMF,
  - 16 pól telemetrii FIT (w tym kadencja, tętno, moc wirtualna),
  - Kontekst mapy (`map_context`) zainicjalizowany, `overview_image` poprawnie wygenerowany w tle w 1.37s.
* **Testy jednostkowe (Pytest):** `75 passed in 15.05s`.

---

## 5. Podsumowanie Zgodne z Instrukcją

_time NameError: FIXED  
LOAD COMPLETES: PASS  
MAP LOAD: PASS  
AMD RENDERER UNCHANGED  
NVIDIA UNCHANGED  
INTEL RENDERER UNCHANGED  
