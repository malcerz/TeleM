# SPORTCAMHUD — ETAP 5W: zgodność ustawień HUD z podglądem i eksportem AMD

2026-10-15, Europe/Warsaw. **STATUS: PASS** (Mapa PASS, Tekst PASS, BAR PASS, podgląd/eksport PASS).

Etap wykonały dwie kolejne sesje. Pierwsza (do 17:43) zrobiła tekst i BAR oraz zaczęła mapę; po jej wyłączeniu druga sesja przejęła stan working tree, uzyskała zgodę użytkownika na przebudowę DLL („tak”, 16:30 UTC) i dokończyła mapę. Wyniki pierwszej sesji dla tekstu/BAR są przytoczone z jej artefaktów (`etap5w_artifacts/`) i ponownie sprawdzone testami.

## 1. Git
- HEAD na starcie etapu: `cbe0dd4`; przy przejęciu: `f35cd4c`; końcowy: `8af7934`. Gałąź `fix/gui-freeze-hud-composite`.
- Commity etapu:
  - `62960ef4780b83fbe48df1d413a20865514ceb0b` fix(hud): apply text unit offsets
  - `f35cd4c68158add6932276985e9ed12e41f07780` test(hud): verify segmented fonts and AMD preview parity
  - `8af7934006def51b4f13f1a6181890e3a77a3451` fix(hud): honor map shape corner radius and border
- Status po etapie: niezacommitowane pozostają wyłącznie cudze/wcześniejsze zmiany (`def_layout.json`, eksportery Intel/NVIDIA, `live_av_mux.py`, raport 5R‑F) oraz nieśledzone artefakty i `tools/validate_5w_map_gpu.py` (sonda pierwszej sesji, niedziałająca także ze starą DLL — nie commitowana).
- Nie wykonano reset/clean/stash/rebase/merge/push. Binarki DLL nie są w commitach (`.gitignore`).
- `def_layout.json`: SHA256 `65fa8390…606f4` przed i po każdym przebiegu (sprawdzane skryptem po każdym eksporcie), niemodyfikowany.

## 2. Weryfikacja ustaleń raportu przeglądu
| | Ustalenie | Wynik |
|---|---|---|
| A1 | `map_shape` „Zaokrąglony” rysowany jako kwadrat | **potwierdzone**: `apply_map_shape` obsługiwał tylko `round/circle`. „Prostokąt” bez maski był poprawny (viewport jest jeden, kwadratowy). |
| A2 | `map_corner_radius`, `map_border_width`, `map_border_color` nieczytane | **potwierdzone** w podglądzie i w AMD. Dodatkowo: przy Track‑Up GPU maska koła była nakładana tylko przy `angle==0` na teksturę źródłową, więc obracała się z mapą/znikała. |
| A4 | `text_distance`, `unit_offset_x/y` nieczytane | **potwierdzone**; `text_distance` nie było też widoczne w GUI (schemat tekstu nie włączał `with_distance`). |
| A5 | osobne fonty BAR Segments martwe | **niepotwierdzone (błąd raportu)**: `_render_segments` czyta je przez f‑string w `_resolve_seg_font`; analiza statyczna szukała literałów. Dodano tylko testy kontraktu. |

## 3. Mapa (A1/A2) — przyczyna i poprawka (`8af7934`)
- `helpers.map_style_layers`: jeden styl w przestrzeni docelowej viewportu, z cache `lru_cache` według (rozmiar, kształt, promień, grubość, kolor): pokrycie AA (supersampling 4×) i pierścień ramki. Promień i grubość ograniczone do połowy krótszego boku; wartości w pikselach 1080p skalowane `min(W,H)/1080`. Zapisane nazwy bez zmian: `square`, `rectangle` (bez zaokrągleń), `rounded` (promień = `map_corner_radius`), `round`/`circle` (koło). Ramka podąża za kształtem; 0 = brak ramki. `square/rectangle` bez ramki → brak stylu (obraz identyczny jak przed zmianą).
- Podgląd: `apply_map_shape` stosuje styl na końcowym viewporcie po resize/rotacji (`moving_map.py`, `static_map.py`), bez mutacji źródła. W GUI promień może teraz wynosić 0.
- AMD: nowy addytywny eksport `telem_amd_update_map_style` (ABI 9 bez zmian). Styl (R = pokrycie, G = ramka, kolor w constant buffer) jest wysyłany do statycznej tekstury GPU raz, przy ustawieniu geometrii mapy (log: `[AMD MAP STYLE] … uploads=1 bytes=996004`). Shadery mapy (blend, fused, two‑pass) nakładają styl we współrzędnych docelowych **po** obrocie Track‑Up, więc kształt i ramka stoją, a mapa się obraca. Marker jest tylko przycinany pokryciem. Brak transferu GPU→CPU→GPU, brak rasteryzacji maski na klatkę, brak renderu mapy na CPU.
- `amd_native_exporter.py`: przekazuje styl; jeśli styl jest wymagany, a DLL nie ma API — jawny błąd zamiast cichego złego wyglądu.

### DLL
- Stara (produkcyjna, z poprawką QP): `6c43f398fbb1421c6dbb21928309f996e9967afea8040c2d42af6c72ba7f29ca`, kopia `runtime/amd/bin/telem_amd_native.dll.bak_pre_5w`.
- Nowa: `5ad042bb8f61db32af52df2a3ea1fdd77c40b253866ce28724c6fe01e4a3c0df`, zainstalowana w `runtime/amd/bin/`. ABI 9, zachowane `telem_amd_get_encoder_qp_feedback_diag`, dodane `telem_amd_update_map_style`.

### Testy mapy
- Celowane (`tests/test_map_style_5w.py`, 15 przypadków): prostokąt, zaokrąglony, koło/circle, 3 proporcje (96×64, 64×96, 96×96), promień 0, promień większy niż połowa boku (clamp), ramka 0 i niezerowa, różne kolory, cache (1 miss na 50 wywołań), skalowanie DPI, brak mutacji źródła, AA na krawędzi. Poprawiono tolerancję krawędzi AA (±1 LSB) w teście pierwszej sesji.
- Eksport AMD (kanoniczny harness `--test-amd-export`, para z BENCHMARKS.md `GX020079.mp4 + GX020079.fit`, 300 klatek, 4K, HEVC FAST 40M, Track‑Up, tymczasowe layouty w `etap5w_map_artifacts/run/`, kopia `def_layout.json` z podmienionymi tylko polami mapy):
  - domyślny kształt (kwadrat, bez ramki): **MP4 bajtowo identyczny** stara vs nowa DLL (SHA `80f21814…`), więc bez stylu wynik się nie zmienia;
  - `rounded`, promień 40, ramka 4 px `#FF3010` oraz `round`, ramka 6 px `#00C8FF`: kształt i ramka widoczne w klatce MP4, w rogach widać wideo, marker nie jest przycięty, sąsiednie wskaźniki nietknięte (`run/map_crops_f150.png`);
  - Track‑Up z ruchem: klatki 20 i 280 (`run/B1_trackup_f20_f280.png`) — ramka i zaokrąglenie stałe, treść mapy obrócona/przesunięta. Klip ma małe zmiany kursu, obrót jest niewielki.

### Zgodność podglądu i eksportu (mapa)
Podgląd i AMD używają tej samej funkcji `map_style_layers` (te same bajty maski trafiają do GPU). Raster sprawdzono na zdekodowanej klatce 150 (`style_parity.py`, `preview_vs_export.py`; porównanie po kodowaniu HEVC 4:2:0, bo pre‑encode readback HUD nie jest podłączony w eksporterze produkcyjnym):
| | ramka: błąd luminancji MAE / p95 | wnętrze vs eksport bez stylu MAE | podgląd (styl Pillow na tej samej klatce) vs eksport GPU: max_diff / MAE / pikseli >16 |
|---|---|---|---|
| rounded | 6.0 / 16.3 | 8.66 | 192 / 9.28 / 71 057 z 249 001 |
| round | 11.4 / 23.9 | 9.10 | 230 / 8.25 / 66 599 z 249 001 |

Różnice wynikają z kompresji (oddzielne bitstreamy, chroma 4:2:0 na cienkiej, nasyconej ramce); wizualnie kształt, promień, grubość i kolor ramki są zgodne (`run/preview_vs_export_f150.png`). Nie jest to porównanie pre‑encode bit‑exact — **NOT PROVEN** na poziomie pikseli przed kodowaniem.

## 4. Tekst (A4) — `62960ef` (pierwsza sesja)
`unit_offset_x/y` przesuwają jednostkę w ułamkach canvasu jak Text X/Y; `text_distance` to dodatkowy odstęp w pikselach 1080p skalowany `min_dim/1080`; 0 = brak zmian. Pozycja wartości liczbowej nie zmienia się; graficzny symbol stopni (`draw_graphic_degree_symbol`) przesuwa się razem z „C”. Wartości domyślne pikselowo identyczne z `cbe0dd4`. Testy: 3 rozmiary fontu, bez jednostki / km/h / °C, 3 ustawienia przesunięć, rotacje 0/90/180/270, cache A→B→A, PropertyEditor → JSON → raster. Podgląd Qt (DPR 1 i 2) vs raster HUD do AMD: max_diff 0, MAE 0, different_pixels 0 (`etap5w_artifacts/preview_native_raster_parity.json`).

## 5. BAR Segments (A5) — `f35cd4c` (pierwsza sesja)
Każdy z `value_font`, `label_font`, `range_font` zmienia raster niezależnie, kolejne wywołanie trafia w cache, powrót A daje obraz A, pusty font = dotychczasowy raster. W krótkim eksporcie AMD użyto Courier/Times/Arial; podgląd = raster AMD (max_diff 0). `bar.py` bez zmian.

## 6. Wyniki testów (ten przebieg)
`pytest` celowane: test_map_style_5w, test_text_unit_offsets, test_segment_font_contract_5w, test_graphic_degree_unit, test_text_indicator_opt_etap3c, test_font_selection, test_amd_vbr_qp_status, test_amd_qp_governance, test_amd_vbr_governance — **94 passed**. `tests/test_track_up_map.py::test_track_map_heading_is_source_aware_in_reference_and_precompute` nie przechodzi także na HEAD sprzed zmian mapy (`etap5w_map_artifacts/preexisting_trackup_failure.txt`); niezwiązane z 5W, zostawione do osobnego zadania. Zestawu 200+ i pełnego filmu nie uruchamiano.

## 7. Wydajność (Render FPS, 300 klatek, ta sama para/ustawienia)
| przebieg | DLL | mapa | Render FPS | Process eff. FPS |
|---|---|---|---|---|
| A0 / A0b | stara | kwadrat | 41.913 / 42.069 | 28.69 / — |
| B0 / B0b | nowa | kwadrat | 39.997 / 41.645 | 27.39 / — |
| B1 / B1b | nowa | rounded + ramka | 39.995 / 41.889 | 27.32 / — |
| B2 | nowa | round + ramka | 41.796 | 28.88 |

Rozrzut powtórzeń tej samej konfiguracji ~1.7 FPS; średnio stara 41.99, nowa 40.8–41.8. Spadek, jeśli istnieje, mieści się w szumie krótkiego przebiegu i nie jest dowiedziony; dla domyślnego kształtu bitstream jest identyczny. Koszt stylu: jeden upload ~1 MB na eksport, jedno próbkowanie tekstury na piksel mapy w shaderze. Pełny benchmark 1131 klatek: NOT TESTED.

## 8. Ochrona funkcji produkcyjnych
Bez zmian: koder AMF, VBR, QP feedback, Direct Copy Audio (`-c copy`), Single Live Mux, finalizacja, setts, Intel/NVIDIA, FIT/GPX/SmartSync/Garmin, „Pomiń pauzy”, pozostałe wskaźniki. Brak osobnych plików audio i dodatkowego remuxu. MP4 testowe usunięto po pomiarach (zostały klatki PNG, logi, JSON).

## 9. Ograniczenia i nierozwiązane
- Porównanie mapy po kodowaniu, nie pre‑encode (readback HUD istnieje w DLL, ale eksporter go nie używa).
- Portable `C:\_DEV\SportCamHUD-portable` nadal ma DLL sprzed QP i 5W.
- Ścieżki Intel/NVIDIA dla mapy nie dostały stylu (poza zakresem; podgląd ma styl).
- `tools/validate_5w_map_gpu.py` nie działa (VP compositor 0x80004005 także na starej DLL), nie commitowany.
- Preexisting failure `test_track_up_map` (powyżej).

## 10. Artefakty
`Raporty/etap5w_artifacts/` (tekst/BAR, pierwsza sesja), `Raporty/etap5w_map_artifacts/` (mapa): `run_map_export.py`, `style_parity.py`, `preview_vs_export.py`, `crop_compare.py`, `run/*.log|json|png`, `run/layout_*.json`.

## 11. ntfy
Wysyłane jedno powiadomienie po zapisaniu tego raportu; wynik dopisany poniżej.

Wynik: wysłano, id=8zf0G47anj9j.
