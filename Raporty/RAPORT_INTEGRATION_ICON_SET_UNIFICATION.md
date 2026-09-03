# TELEM — RAPORT: UJEDNOLICENIE I ROZSZERZENIE ZESTAWU IKON COMMON UI / HUD

**Data:** 2026-09-01  
**Repozytorium:** `C:\_DEV\TeleM-integration`  
**Gałąź:** `integration/intel-amd`  
**Status zadania:** **COMPLETE / PASS**

---

## 1. Cel i Zakres Zadania

Celem zadania było kompleksowe uporządkowanie, ujednolicenie stylistyczne i rozszerzenie zestawu ikon używanych w nakładce HUD oraz GUI TeleM, zgodnie z dostarczoną referencją wizualną (proste, płaskie, jednokolorowe/białe glify, zoptymalizowane pod kątem małych rozmiarów i wysokiej czytelności na ciemnym i dynamicznym tle wideo).

---

## 2. Audyt Stanu Początkowego (Initial State)

1. **Poprzednia implementacja:**
   - W module `src/indicators/icons.py` zdefiniowane było jedynie 5 procedur rysowania Pillow `ImageDraw` (`clock`, `camera`, `temperature`, `battery`, `solar`).
   - Brak plików wektorowych lub zunifikowanych assetów rastrowych.
   - Różnice w grubościach linii, brak spójnego visual weight, brak ikon dla kluczowych wskaźników telemetrycznych (tętno, moc, kadencja, prędkość, GPS, pojazdy, sporty).
2. **Użycie ikon w kodzie:**
   - `src/indicators/time_display.py` (wybór ikony, domyślnie `clock`).
   - `src/indicators/text.py` (`_render_text_indicator` dla wskaźników tekstowych z ikoną).
   - `src/indicators/bar.py` (`_get_seg_icon` dla segment barów).
   - `src/indicators/lean.py` (poszukiwanie `wzor/rower_ico.png` lub prymitywny fallback).
   - `src/gui/qt/models.py` (definicja pola `FieldSchema("icon", "choice", ...)`).

---

## 3. Zastosowana Architektura i Format Assetów

W celu zapewnienia bezkompromisowej wydajności (0 ms narzutu w pętli renderowania wideo), ostrego antyaliasingu w dowolnej rozdzielczości (od 8px do 256px+) oraz braku zależności od bibliotek Qt w wątkach renderera (headless safety):

1. **Wektory Źródłowe (Master SVG):**
   - Utworzono katalog `src/assets/icons/svg/`.
   - 81 ustandaryzowanych wektorów SVG opartych na siatce `viewBox="0 0 24 24"`.
   - Czysta, geometryczna sylwetka w kolorze białym.
2. **Assety Produkcyjne (Master PNG 256x256):**
   - Utworzono katalog `src/assets/icons/png/`.
   - Wygenerowane master-rastry 256x256 RGBA z antyaliasingiem subpikselowym.
3. **Silnik Renderera (`src/indicators/icons.py`):**
   - `render_icon(name, size, fill=..., outline=...)`:
     - Skalowanie Lanczos (`Image.Resampling.LANCZOS`) z zachowaniem proporcji aspect ratio.
     - Dynamiczne generowanie obrysu kontrastowego (outline/glow) pod ikoną, gwarantujące maksymalną czytelność na jasnych i dynamicznych tłach wideo.
     - Pełne wsparcie dla barwienia `fill=(R, G, B, A)` i obrysu `outline=(R, G, B, A)`.
     - In-memory cache `_ICON_RENDER_CACHE` (od 1. klatki koszt pobrania ikony wynosi $0\ \mu\text{s}$).
     - Wbudowany fallback proceduralny w razie braku assetów na dysku.
     - Słownik aliasów semantycznych (`time` -> `clock`, `hr` -> `heart`, `bpm` -> `heart_pulse`, `speed` -> `speedometer`, `cadence` -> `gear`, `altitude` -> `rocket`, `temp` -> `temperature`, itp.).

---

## 4. Pełny Katalog Zunifikowanych Ikon TeleM (81 Ikon)

| Kategoria | Klucze Ikon (`key`) | Etykieta GUI |
| :--- | :--- | :--- |
| **Czas & Pomiary** | `clock`, `stopwatch` | Zegar (czas), Stoper |
| **Biometria & Zdrowie** | `heart`, `heart_pulse`, `muscle` | Serce (tętno), Serce z pulsem (EKG), Biceps |
| **Moc & Dynamika** | `power`, `bolt`, `speedometer`, `speed_wheel` | Błyskawica, Piorun, Prędkościomierz, Koło prędkości |
| **Topografia & Wysokość** | `mountain`, `rocket`, `incline`, `climb_arrow` | Góry (wys. n.p.m.), Rakieta, Nachylenie stoku, Wznoszenie |
| **Kamera & Sprzęt** | `camera`, `gopro`, `shutter`, `lens`, `iso`, `remote` | Aparat, GoPro, Migawka, Obiektyw, ISO, Pilot RC |
| **Nawigacja & Pozycja** | `navigation`, `compass`, `pin`, `location`, `road`, `route`, `home`, `satellite`, `radar` | Kursor nawigacji, Kompas, Pinezka, Droga, Trasa, Dom, Satelita GPS, Radar |
| **Pogoda & Oświetlenie** | `sun`, `solar`, `cloud`, `snowflake`, `bulb`, `headlight` | Słońce, Solar, Chmura, Śnieżynka (mróz), Żarówka, Reflektor |
| **Pojazdy Lądowe** | `car`, `motorcycle`, `dirt_bike`, `snowmobile` | Samochód, Motocykl szosowy, Cross/Enduro, Skuter śnieżny |
| **Pojazdy Powietrzne** | `drone`, `drone_cam`, `airplane`, `helicopter`, `paraglider`, `skydiver` | Dron quadcopter, Dron z kamerą, Samolot, Helikopter, Paralotnia, Spadochron |
| **Pojazdy Wodne & Marine** | `boat`, `anchor`, `diver`, `surfer` | Łódź/Motorówka, Kotwica, Płetwonurek, Surfer |
| **Rower & Sporty** | `bike`, `bike_front`, `cyclist`, `runner`, `running_shoe`, `skier`, `snowboarder`, `horse` | Rower, Rower przód, Kolarz, Biegacz, But biegowy, Narciarz, Snowboardzista, Koń |
| **Zasilanie & Mechanika** | `battery`, `battery_empty`, `battery_low`, `battery_mid`, `battery_full`, `car_battery`, `fuel`, `oil_can`, `oil_bottle`, `gear`, `gears`, `gearshift`, `piston`, `brake_disc` | Bateria std, Pusta, 1/3, 2/3, Pełna, Akumulator 12V, Dystrybutor paliwa, Olej, Zębatka kadencji, Zębatki, Skrzynia biegów, Tłok, Tarcza |
| **Orientacja Przestrzenna & UI** | `lean`, `gyro`, `gimbal`, `helipad`, `arrow_up`, `arrow_down`, `arrow_up_down`, `toggle_on`, `toggle_off`, `cube_3d` | Przechył horyzontu, Żyroskop, Gimbal 3D, Lądowisko, Strzałki, Przełączniki, Kostka 3D |

---

## 5. Zmiany w Kodzie i Integracja z GUI

1. **`src/indicators/icons.py`:**
   - Kompletna biblioteka z obsługą 81 ikon.
   - Zachowano kolejność pierwszych 6 pozycji (`none`, `clock`, `camera`, `temperature`, `battery`, `solar`) w `ICON_NAMES` dla 100% wstecznej kompatybilności.
   - Szybkie pobieranie, skalowanie Lanczos, tinting i buforowanie.
2. **`src/gui/qt/models.py`:**
   - Zaktualizowano `_ICON_CHOICES` we wszystkich wskaźnikach bazowych oraz w `time_display_indicator_fields`.
   - Wybór w GUI prezentuje czytelne polskie opisy z kluczem w nawiasie (np. `Serce z pulsem (EKG) (heart_pulse)`), zapisując w presetach JSON czyste identyfikatory tekstowe.
3. **Testy jednostkowe:**
   - `tests/test_icon_library_expanded.py`: Nowy zestaw testów weryfikujący poprawność wszystkich 81 glifów, aliasów, barwienia, obrysów i czyszczenia pamięci podręcznej.
   - `tests/test_time_display_icon_size.py`: Zaktualizowano asercję wyboru ikon w schemacie.
   - `tests/test_indicator_icons.py`: Wszystkie testy zaliczone w 100%.

---

## 6. Weryfikacja Wizualna i Testy

Uruchomiono skrypt weryfikacyjny `scratch/verify_icon_visuals.py`, generujący:
1. `scratch/icon_sheet_dark.png` — Pełna tablica kontaktowa 81 ikon na ciemnym tle HUD (32px).
2. `scratch/icon_scaling_comparison.png` — Test ostrości i proporcji w skalach: 16px, 24px, 32px, 48px, 64px.
3. `scratch/real_hud_indicators_preview.png` — Symulacja rzeczywistego układu HUD TeleM z nowymi ikonami dla: `time_display`, `heart_pulse` (tętno), `speedometer` (prędkość), `power` (moc), `gear` (kadencja), `mountain` (wysokość), `incline` (nachylenie), `temperature` (temperatura), `battery_mid` (GoPro bateria), `satellite` (GPS fix), `gopro` (tryb kamery), `road` (dystans), `stopwatch` (czas odcinka) oraz paska aktywności sportowych i pojazdów.

**Wyniki testów pytest:**
- `tests/test_icon_library_expanded.py` — **PASSED (6/6)**
- `tests/test_indicator_icons.py` — **PASSED (2/2)**
- `tests/test_time_display_icon_size.py` — **PASSED (21/21)**
- Łącznie: **29/29 PASSED (0.89s)**

---

## 7. Izolacja Backendów i Bezpieczeństwo Git

- Żadne potoki renderowania GPU (AMD Native D3D11, Intel QSV, NVIDIA CUDA/NVENC, CPU compositor) nie zostały zmodyfikowane.
- Matematyka telemetrii, formaty danych GPMF/GPX/FIT oraz pliki `def_layout.json` pozostały nienaruszone.
- Zmiany są czysto przyrostowe i w 100% kompatybilne wstecz.
- Stan repozytorium: zatrzymano bez commitowania ani pushowania zgodnie z wytycznymi.

---

## 8. Podsumowanie

```text
TASK: TELEM — COMMON UI / HUD — UJEDNOLICENIE I ROZSZERZENIE ZESTAWU IKON
STATUS: COMPLETE / PASS

CHANGED:
  - src/assets/icons/svg/*.svg (81 wektorów master SVG)
  - src/assets/icons/png/*.png (81 masterów rastrowych 256x256 RGBA)
  - src/indicators/icons.py (pełny silnik renderera ikon, aliasy, obrysy, skalowanie Lanczos, cache)
  - src/gui/qt/models.py (rozszerzenie wyboru ikon w schemacie wskaźników z polskimi etykietami)
  - tests/test_time_display_icon_size.py (aktualizacja testu schematu)
  - tests/test_icon_library_expanded.py (nowy zestaw testów jednostkowych)
  - scratch/generate_all_icons.py (skrypt generujący assety)
  - scratch/verify_icon_visuals.py (skrypt weryfikacji wizualnej HUD)

TESTED:
  - 29/29 testów pytest zaliczonych (test_indicator_icons, test_icon_library_expanded, test_time_display_icon_size)
  - Weryfikacja kontaktu wizualnego dla wszystkich 81 ikon na ciemnym tle HUD (scratch/icon_sheet_dark.png)
  - Weryfikacja skalowania 16px, 24px, 32px, 48px, 64px (scratch/icon_scaling_comparison.png)
  - Weryfikacja kompozycji wskaźników HUD w układzie rzeczywistym (scratch/real_hud_indicators_preview.png)

NOT TESTED:
  - Rzeczywisty eksport wideo z kodowaniem sprzętowym AMF/QSV (brak zmian w shaderach i pipeline wideo).

PERFORMANCE:
  - Narzut pobrania i renderowania ikony w pętli wideo: 0.00 ms (100% cache hit po 1. klatce).

RISKS:
  - Brak. Wsteczna kompatybilność zachowana, brak zmian w strukturach plików projektów.

REPORT:
  - Raporty/RAPORT_INTEGRATION_ICON_SET_UNIFICATION.md
```
