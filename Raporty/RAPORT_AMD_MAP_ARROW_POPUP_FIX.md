# RAPORT: Naprawa strzalki mapy + popup eksportu

## TASK

1. Strzalka (directional marker) na mapie track_up stale wskazuje pionowo w gore
2. Po zwyklym eksporcie pojawia sie stary popup bez czasu/FPS/QP z uszkodzonym encodingiem

---

## INITIAL STATE

- Branch: amd-bikeridehud, commit 0ef407e
- Layout: track_up + map_marker_style: directional + source: gpmf + pitch: 45.0

---

## ANALYSIS

### Problem 1: Strzalka

Root cause "strzalka zawsze pionowa":
Jezeli heading_samples z GPMF sa puste lub niedostepne w WORKER_CACHE:
- _resolve_cache_samples("heading", "gpmf") zwraca []
- map_heading_arr = [None] * total_frames (precompute path)
- map_heading = None => heading_val = 0.0 => DLL dostaje telem_amd_set_map_heading(0.0)
- Mapa NIE obraca sie => strzalka wskazuje gore = polnoc, nie kierunek jazdy

Naprawione sciezki:
1. telemetry_precompute.py - _heading_array(): fallback z derive_heading_samples(gps_track, speed_samples)
2. worker_cache.py - _resolve_cache_value(): fallback z derive_heading_samples z WORKER_CACHE["gps_track"]

### Problem 2: Popup eksportu

Stary popup (Eksport zakonczony - uszkodzony UTF-8, brak czasu/FPS/QP)
zastapiony wywolaniem _show_export_finished_popup(_stats, output, elapsed).

---

## CHANGED FILES

- src/gui/qt/tabs/render_tab.py: l.2272-2275 stary QMessageBox -> _show_export_finished_popup
- src/telemetry_precompute.py: GPS fallback w _heading_array()
- src/ffmpeg/worker_cache.py: GPS fallback w _resolve_cache_value() dla heading

---

## TESTS

- Syntax check: python -m py_compile -> PASS dla wszystkich 3 plikow
- Functional: NOT TESTED

## RISKS

- Nizkie: GPS fallback aktywuje sie tylko gdy heading_samples puste
- Nizkie: elapsed=0.0 w edge-case gdy _render_start=None => time_str="--:--"

## STATUS

TASK:        Naprawa strzalki mapy + popup eksportu
STATUS:      PARTIAL - implementacja gotowa, NOT TESTED na realnym video

CHANGED:     render_tab.py, telemetry_precompute.py, worker_cache.py
TESTED:      Python syntax (PASS)
NOT TESTED:  Funkcjonalny eksport, rotacja mapy, popup UI

---

## ADDENDUM: Naprawa strzalki - root cause ustalony

### Root cause strzalki (zidentyfikowany)

GPU track_up path: DLL blenduje marker tile OSOBNO (po obróceniu mapy) na STAŁEJ pozycji ekranowej.
Marker tile jest statyczny (heading=None = strzalka górę).
Po GPU rotacji mapy strzalka NIE rotuje z mapą - zawsze wskazuje górę ekranu.
Górę ekranu != kierunek jazdy gdy mapa nie zdążyła się obrócić lub gdy patrzymy pod innym kątem.

CPU path (render_track_up): marker rysowany na OBRÓCONEJ mapie po cv2.warpAffine - poprawnie.
GPU path: marker rysowany przez DLL jako osobna warstwa - niepoprawnie.

### Fix (v2)

1. W render_map_unrotated_working_image (indicators/moving_map.py):
   - draw_marker_on_working = True dla track_up + directional + not hide_marker
   - Po render_mosaic_and_subpixel: paste marker tile z heading=heading_val na working image
   - Pozycja: (scx, scy) = GPS centrum w mozaikowym obrazie
   - Marker ma heading=heading_val (North-up space) -> po GPU CCW rotacji o heading_val -> wskazuje górę ekranu = kierunek jazdy

2. W amd_native_exporter.py init (l.3819):
   - _use_dll_marker = False dla track_up + directional
   - DLL static marker wyłączony (nie uploadowany)
   - Log: "[MAP MARKER] directional + track_up: marker baked into working image"

### Kiedy marker na working image jest obracany przez GPU?

GPU fused shader:
  float rotRad = heading * pi/180
  cx = refX + (cosA * dx - sinA * dy)
  cy = refY + (sinA * dx + cosA * dy)
Test: heading=90 (East), pixel (dst.top) dx=0, dy=-h/2:
  cx = srcW/2 + sinA*(h/2) = srcW/2 + h/2 = East w src -> top dst
Wynik: East na górze ekranu. Strzalka z heading=90 wskazuje East. Po GPU rotacji = górę. Poprawne.

CHANGED (v2): indicators/moving_map.py, amd_native_exporter.py
