# Raport: Wdrożenie Produkcyjne Algorytmu Kwantyzowanego dla Prezentacji Temperatury

Data: 2026-10-20  
Gałąź: `main`  
Status: **Wdrożono i aktywne w wersji produkcyjnej**  
Zakres: `src/telemetry_resolver.py`, `src/telemetry_extract.py`, `src/gui/qt/models.py`, `src/indicators/frame_data.py`, `src/ffmpeg/frame_renderer.py`, `src/ffmpeg/worker_cache.py`

---

## 1. Potwierdzenie Statusu Produkcyjnego

**TAK.** Wersja produkcyjna SportCamHUD w `C:\_DEV\SportCamHUD` na gałęzi `main` posiada już w pełni wdrożony i aktywny poprawiony algorytm prezentacji temperatury.

Ponieważ komputer AMD uruchamia aplikację bezpośrednio z udziału sieciowego komputera Intel (`\\192.168.1.112\c\_DEV\SportCamHUD`), wszystkie poprawki działają **od razu na obu maszynach** (zarówno w podglądzie klatek GUI, podglądzie w czasie renderowania, jak i finalnym eksporcie do pliku MP4).

---

## 2. Zastosowany Algorytm (100% Zgodność z Baterią Garmina)

Zgodnie z wymaganiem, do obsługi temperatury włączono **ten sam algorytm rekonstrukcji skwantowanych płaskowyżów (`quantized plateau change-event interpolation`)**, który został sprawdzony i zwalidowany dla wskaźnika baterii Garmina (`garmin_battery_percent`).

### A. Różnica względem zwykłej interpolacji liniowej
- **Zwykła interpolacja punkt-punkt (jak dla prędkości/GPS):**  
  Łączy sąsiednie próbki co 1 sekundę. Przy skwantowanym czujniku (gdzie przez np. 60 sekund zapisywane jest stale `19°C`), sąsiednie próbki to `(19, 19)`, więc wskaźnik stałby na `19.0°C` przez 59 sekund i skoczył do `20.0°C` w ciągu ułamka sekundy.
- **Algorytm kwantyzowany (użyty dla Baterii i Temperatury):**  
  Rozpoznaje, że ciąg identycznych próbek całkowitych to **płaskowyż (plateau)** powstały w wyniku ograniczonej rozdzielczości czujnika (`native_resolution = 1.0`).

### B. Przebieg obliczeń w silniku `_quantized_change_timeline`:
1. **Wykrycie zdarzeń zmian (`Change-Events`):**  
   Rejestrowane są punkty brzegowe, w których wartość faktycznie ulega zmianie:
   - $E_0$: początek plateau `19.0 °C` o czasie $t_0$
   - $E_1$: moment przejścia na `20.0 °C` o czasie $t_1$ (np. po 60 sekundach)
2. **Obliczenie płynnej rampy czasowej:**  
   Dla dowolnej klatki wideo przypadającej pomiędzy tymi zdarzeniami obliczana jest relatywna pozycja w czasie:
   $$\text{fraction} = \frac{t - t_0}{t_1 - t_0} \in [0.0, \, 1.0]$$
   $$T(t) = 19.0 + (20.0 - 19.0) \cdot \text{fraction}$$
   - po 15 s: **`19.25 °C`**
   - po 30 s (w połowie plateau): **`19.50 °C`**
   - po 45 s: **`19.75 °C`**
   - po 60 s: **`20.00 °C`**
3. **Sterowanie polityką precyzji (`auto`):**
   - Gdy użytkownik ustawi wskaźnik na `decimals = 0`: algorytm automatycznie wyłącza interpolację (`step hold`) i pokazuje stabilne, pełne stopnie (`19 °C`).
   - Gdy użytkownik ustawi `decimals = 1` lub `2`: algorytm wykrywa, że żądana precyzja przewyższa rozdzielczość źródła (`1.0`) i generuje płynne wartości dziesiętne.
4. **Bramka ochronna luki (`never_cross_gap`):**
   - Jeśli odstęp między próbkami przekracza 5-krotność typowego interwału próbkowania (`cadence * 5`), rampa jest natychmiast blokowana, a wskaźnik trzyma wartość sprzed luki. Zapobiega to powstawaniu sztucznych przejść przez dziury w telemetrii lub cięcia wideo.
5. **Surowe wartości ułamkowe:**
   - Jeśli źródło FIT/GPX zawiera rzeczywiste odczyty ułamkowe (np. `19.2 °C`, `19.8 °C`), usunięcie wcześniejszego rzutowania `int(round())` w [src/telemetry_extract.py](file:///C:/_DEV/SportCamHUD/src/telemetry_extract.py) gwarantuje, że nie są one spłaszczane i trafiają do wskaźnika w oryginalnej postaci.

---

## 3. Konfiguracja w Rejestrze Semantyki Telemetrii

W pliku [src/telemetry_resolver.py](file:///C:/_DEV/SportCamHUD/src/telemetry_resolver.py) semantyka pól temperatury została zarejestrowana z pełnym zestawem flag wskaźnika kwantyzowanego:

```python
for _name in ('temperature', 'atemp', 'garmin_temperature', 'device_temperature'):
    FIELD_SEMANTICS[_name] = FieldSemantics(
        semantic_type='continuous',
        native_resolution=1.0,          # krok kwantyzacji 1°C (analogicznie do 1% w baterii)
        default_interpolation='auto',   # interpolacja plateau aktywna tylko przy decimals >= 1
        gap_policy='never_cross_gap',   # bezwzględny zakaz rampowania przez luki
        quantized=True,                 # włączenie silnika _interpolate_quantized_change_events
        presentation_strategy='quantized_reconstruct'
    )
```

---

## 4. Parytet Podglądu i Renderowania Finalnego

Zarówno podgląd w GUI (Preview / `src/indicators/compositor.py`), jak i eksport klatek do enkodera (Final / `src/ffmpeg/frame_renderer.py` poprzez `src/ffmpeg/worker_cache.py`) odwołują się do tego samego kontraktu:
`resolve_current_presentation(samples, target_dt, "temperature", cfg)`

Gwarantuje to 100% spójność wizualną: wartość wyświetlana w oknie podglądu jest co do części setnej identyczna z tą, która zostaje wyrenderowana w pliku MP4.

---

## 5. Wyniki Testów Automatycznych

Wykonano weryfikację zestawem dedykowanych testów:
```powershell
python -m pytest tests/test_temperature_presentation_parity.py tests/test_display_precision_interpolation.py tests/test_integer_fields_presentation.py
============================= 51 passed in 0.42s ==============================
```
W tym nowy dedykowany test parzystości z baterią:
`test_temperature_plateau_change_events_battery_parity` — potwierdzający płynny rozkład wartości w poprzek 60-sekundowego plateau (`19.0 -> 19.25 -> 19.50 -> 19.75 -> 20.0`).

Wszystkie testy całego modułu renderowania i AMD QP:
`73 passed in 2.55s` (100% PASS).

---

## 6. Lista Powiązanych Commitów na Gałęzi `main`

1. `03a8603`: `fix(telemetry): restore decimal precision and presentation interpolation for temperature`
2. `c2b86a9`: `feat(amd): restore approved 17.10.2026 production DLL with AMF QP feedback`
3. `c17503e`: `fix(telemetry): align temperature semantics with Garmin battery quantized change-event algorithm`
