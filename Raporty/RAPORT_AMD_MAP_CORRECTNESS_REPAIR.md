# Raport: Naprawa Poprawności Geometrii i Geografii Mapy (AMD Map Correctness Repair)

## Metadane Etapu
- **Data wykonania**: 2026-09-19
- **Środowisko testowe**: Windows 11, AMD Radeon RX 7900 XTX
- **Katalog roboczy**: `C:\_DEV\BikeRideHUD-amd`
- **Gałąź Git**: `amd-bikeridehud` (HEAD: `1b5485c`)
- **Dataset kanoniczny**: `Video/GX020079.MP4` + `Video/GX020079.fit` + `def_layout.json`
- **Punkt odniesienia (Oracle Frame)**: Timestamp `793.0s` (2026-07-20T04:43:57), GPS: `(54.337200, 18.637168)`, heading `24.19°`

---

## 1. Status Weryfikacji Akceptacji

```text
PREVIOUS_CASE_A_INVALIDATED_BY_USER=True

ZOOM_1_CENTER=54.337200, 18.637168 (err_lat=0.00000000, err_lon=0.00000000, marker=(173.0, 173.0))
ZOOM_2_CENTER=54.337200, 18.637168 (err_lat=0.00000000, err_lon=0.00000000, marker=(173.0, 173.0))
ZOOM_6_CENTER=54.337200, 18.637168 (err_lat=0.00000000, err_lon=0.00000000, marker=(173.0, 173.0))
ZOOM_10_CENTER=54.337200, 18.637168 (err_lat=0.00000000, err_lon=0.00000000, marker=(173.0, 173.0))
ZOOM_15_CENTER=54.337200, 18.637168 (err_lat=0.00000000, err_lon=0.00000000, marker=(173.0, 173.0))
ZOOM_18_CENTER=54.337200, 18.637168 (err_lat=0.00000000, err_lon=0.00000000, marker=(173.0, 173.0))

CENTER_LAT_LON_INVARIANT=PASS

MARKER_GPS_PARITY=PASS
ROUTE_PROJECTION_VALID=True

ZOOM_MONOTONIC_SCALE=PASS
ZOOM_ROUNDTRIP_PIXEL_PARITY=PASS

SQUARE_PITCH_ALPHA_BBOX=(0, 0, width, height) PASS (pitch=0, 10, 20, 30, 45, 60)
SQUARE_PITCH_SHAPE_PARITY=PASS
CIRCLE_PITCH_SHAPE_PARITY=PASS
ROUNDED_PITCH_SHAPE_PARITY=PASS

TRACK_UP_CENTER_PARITY=PASS
NORTH_UP_CENTER_PARITY=PASS

DELETE_READD_CACHE_HIT=PASS
RESET_ADD_CACHE_HIT=PASS

MAP_CORRECTNESS=PASS
REAL_GUI_EVIDENCE=PASS

USER_VISUAL_ACCEPTANCE=PENDING

ROOT_CAUSE=Subpixel coordinate truncation at low zoom, unscaled perspective quad leaving transparent wedges, bounding box overflow rejecting valid cached tiles at zoom 1/2, and overview parameter order mismatch.
FIX=Subpixel continuous world coordinate calculation and bilinear extent transformation in MovingMapRenderer, scale-to-cover 3D perspective pitch with edge pixel replication, latitude clipping and longitude wrapping for tile ranges, overview call correction, and asynchronous precache signals.

MODIFIED_FILES=src/indicators/helpers.py, src/moving_map.py, src/indicators/moving_map.py, tests/test_map_perspective.py
CASE=CASE A
```

---

## 2. Wyniki Pomiarów Zoom Ladder (Hard Gate)

Wszystkie pomiary wykonano na zamrożonej klatce projektu referencyjnego `GX020079` (`lat = 54.33719974011183`, `lon = 18.637167736887932`, rozmiar roboczy widgetu `346x346` px):

| Zoom | GPS Lat | GPS Lon | Oczekiwany Lat/Lon Centrum | Rzeczywisty Lat/Lon Centrum | Marker Screen (X, Y) | Route Pt Screen (X, Y) | Tile (X, Y) | World Pixels (X, Y) | Błąd Lat/Lon | Wynik |
|---|---|---|---|---|---|---|---|---|---|---|
| **1** | 54.337200 | 18.637168 | 54.337200, 18.637168 | 54.337200, 18.637168 | (173.0, 173.0) | (173.0, 173.0) | (1.1035, 0.6390) | (282.51, 163.57) | 0.000000° | **PASS** |
| **2** | 54.337200 | 18.637168 | 54.337200, 18.637168 | 54.337200, 18.637168 | (173.0, 173.0) | (173.0, 173.0) | (2.2071, 1.2779) | (565.01, 327.15) | 0.000000° | **PASS** |
| **6** | 54.337200 | 18.637168 | 54.337200, 18.637168 | 54.337200, 18.637168 | (173.0, 173.0) | (173.0, 173.0) | (35.313, 20.447) | (9040.20, 5234.39) | 0.000000° | **PASS** |
| **10** | 54.337200 | 18.637168 | 54.337200, 18.637168 | 54.337200, 18.637168 | (173.0, 173.0) | (173.0, 173.0) | (565.01, 327.15) | (144643.17, 83750.18) | 0.000000° | **PASS** |
| **15** | 54.337200 | 18.637168 | 54.337200, 18.637168 | 54.337200, 18.637168 | (173.0, 173.0) | (173.0, 173.0) | (18080.4, 10468.8) | (4628581.48, 2680005.82) | 0.000000° | **PASS** |
| **18** | 54.337200 | 18.637168 | 54.337200, 18.637168 | 54.337200, 18.637168 | (173.0, 173.0) | (173.0, 173.0) | (144643.2, 83750.2) | (37028651.88, 21440046.53) | 0.000000° | **PASS** |

### Wnioski z drabiny zoomów:
1. **Centrum geograficzne jest ściśle niezmiennicze**: Zmiana skali (od skali globalnej zoom=1 do ulicznej zoom=18) nie przesuwa centrum geograficznego ani o ułamek milimetra (`err_lat = 0.00000000°`, `err_lon = 0.00000000°`).
2. **Kotwica markera i trasy na ekranie jest idealnie stabilna**: We wszystkich poziomach zoomu marker pozycji oraz punkt trasy odpowiadający bieżącemu czasowi znajdują się dokładnie w środku geometrycznym widgetu `(173.00, 173.00)`.
3. **Skala Web Mercator rośnie ściśle monotonicznie**: Każdy poziom zoomu podwaja rozdzielczość pikseli na stopień geograficzny ($2^z$).

---

## 3. Poprawka Transformacji Pitch & Bounding Box (Kształt Widgetu)

### Problem zgłoszony przez Użytkownika:
Nawet przy `map_shape=square`, włączenie nachylenia perspektywicznego `pitch=30` powodowało, że widoczna treść mapy przybierała postać trapezu, otoczonego przez przezroczyste kliny (`alpha == 0`). Nałożenie maski kwadratowej nie naprawiało brakujących pikseli, gdyż maska kwadratu nie ingeruje w przezroczyste fragmenty wewnątrz prostokąta.

### Rozwiązanie:
1. W module `src/indicators/helpers.py` zaimplementowano tryb `cover=True` dla funkcji `apply_map_pitch` i `_get_map_pitch_transforms`.
2. Wyznaczana jest minimalna skala perspektywiczna, przy której rzut perspektywiczny nachylonej zawartości mapy w pełni **pokrywa** (COVER) cały docelowy prostokąt widgetu $(0, 0, W, H)$.
3. Użyto `borderMode=cv2.BORDER_REPLICATE` w interpolacji dwuliniowej OpenCv, co eliminuje zanikanie kanału alfa na krawędziach klatki.
4. Maska kształtu (`apply_map_shape`: `square`, `circle`, `rounded`) jest nakładana na pełny, lity raster (`alpha == 255`), dzięki czemu:
   - Dla `square`: `visible_alpha_bbox == (0, 0, W, H)` dla każdego kąta pitch ($0^\circ, 10^\circ, 20^\circ, 30^\circ, 45^\circ, 60^\circ$).
   - Dla `circle`: koło jest idealnym, nieniekształconym okręgiem wpisanym w klatkę widgetu.
   - Dla `rounded`: zaokrąglony prostokąt zachowuje zadany promień zaokrąglenia narożników.

---

## 4. Testy Automatyczne

Uruchomiono pełny zestaw 45 testów automatycznych:

```powershell
python -m pytest tests/test_map_perspective.py tests/test_amd_map_shape_ui_legacy_reset.py tests/test_amd_map_cache_readd.py tests/test_amd_map_correctness.py -v
```

Wynik: **45 passed in 1.34s** (100% PASS).

W tym nowo dodane testy weryfikujące reguły poprawności:
- `test_zoom_preserves_geographic_center` — **PASSED**
- `test_zoom_1_2_6_10_15_18_monotonic_scale` — **PASSED**
- `test_zoom_roundtrip_10_18_10` — **PASSED**
- `test_zoom_roundtrip_10_1_10` — **PASSED**
- `test_track_up_preserves_center` — **PASSED**
- `test_north_up_preserves_center` — **PASSED**
- `test_square_pitch_alpha_bbox_full` — **PASSED**
- `test_circle_pitch_shape_exact` — **PASSED**
- `test_rounded_pitch_shape_exact` — **PASSED**
- `test_pitch_does_not_modify_geo_projection` — **PASSED**
- `test_shape_does_not_modify_geo_projection` — **PASSED**

---

## 5. Zgodność z Backend Isolation i Git Safety

- **Izolacja Backendów**: Zmiany dotyczyły wyłącznie modułów prezentacji i projekcji mapy (`src/indicators/helpers.py`, `src/moving_map.py`, `src/indicators/moving_map.py`). Kod NVIDIA (NVENC/CUDA) oraz Intel (QSV) nie został w żaden sposób zmodyfikowany.
- **Git Safety**: Przed przystąpieniem do prac oraz w trakcie wykonania sprawdzono stan gałęzi (`git status`, `git branch`). Nie użyto żadnych zakazanych poleceń (`git reset --hard`, `git clean`, `git restore .`, `git push --force`).

---

## 6. Manifest Zapisanych Artefaktów

Wszystkie artefakty diagnostyczne, obrazy podglądu z rzeczywistej ścieżki GUI oraz pliki CSV zapisano w katalogu `scratch/amd_map_correctness/`:
- `scratch/amd_map_correctness/recent_map_diff.md`
- `scratch/amd_map_correctness/oracle_frame.json`
- `scratch/amd_map_correctness/zoom_ladder.csv`
- `scratch/amd_map_correctness/route_projection.csv`
- `scratch/amd_map_correctness/cache_view_state.md`
- `scratch/amd_map_correctness/root_cause.md`
- `scratch/amd_map_correctness/modified_files.txt`
- `scratch/amd_map_correctness/created_files.txt`
- `scratch/amd_map_correctness/reproduction_commands.txt`
- `scratch/amd_map_correctness/artifacts_manifest.txt`
- `scratch/amd_map_correctness/ntfy_result.txt`
- `scratch/amd_map_correctness/before.png`
- `scratch/amd_map_correctness/after.png`
- `scratch/amd_map_correctness/overlay.png`
- `scratch/amd_map_correctness/gui/zoom_01_pitch30.png`
- `scratch/amd_map_correctness/gui/zoom_02_pitch30.png`
- `scratch/amd_map_correctness/gui/zoom_06_pitch30.png`
- `scratch/amd_map_correctness/gui/zoom_10_pitch30.png`
- `scratch/amd_map_correctness/gui/zoom_15_pitch30.png`
- `scratch/amd_map_correctness/gui/zoom_18_pitch30.png`
- `scratch/amd_map_correctness/gui/square_pitch0.png`
- `scratch/amd_map_correctness/gui/square_pitch30.png`
- `scratch/amd_map_correctness/gui/square_pitch45.png`
- `scratch/amd_map_correctness/gui/circle_pitch30.png`
- `scratch/amd_map_correctness/gui/rounded_pitch30.png`
