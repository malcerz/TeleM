# SPORTCAMHUD — ETAP 5Z.4: podgląd HDR/HLG na monitorze SDR

Data: 2026-10-16. **STATUS: PASS** (po zgodzie użytkownika na minimalną zmianę DLL — §26). Wcześniejsza wersja raportu miała status PARTIAL.

| obszar | wynik |
|---|---|
| podgląd edytora (mpv) | **naprawiony bez zmian w DLL** |
| podgląd eksportu w trybie „Konwertuj do SDR” | zgodny z MP4 z założenia: pokazuje tę samą finalną klatkę NV12, która trafia do kodera |
| podgląd eksportu w trybie „Zachowaj HDR” | **BLOCKED** — wymaga zmiany w DLL; zgodnie z zadaniem zatrzymałem się przed nią (§11) |

## 1. Git
- Start: HEAD `f62331b`. Zastane zmiany (Intel/NVIDIA, `def_layout.json`, `live_av_mux.py`, raport 5R_F) nietknięte.
- Commit etapu: `b05db3bdd9696be2f9db081e7a180d129f9ae5b7` — fix(preview): apply correct HLG to SDR presentation.

## 2. Architektura podglądu przed zmianą (krok A — PASS)
| ścieżka | źródło obrazu | konwersja koloru | HUD |
|---|---|---|---|
| A. Podgląd filmu w edytorze | libmpv 0.41 (`vo` gpu-next/libplacebo, `hwdec=d3d11va`, kontekst d3d11), osadzony przez `wid` (`playback_mixin.py`, `mpv_hwdec.build_mpv_options`) | mpv sam tone-mapuje HLG→SDR, ale na ustawieniach `auto`: dynamiczna detekcja szczytu, automatyczny gamut, contrast recovery | — |
| B. Podgląd z HUD w edytorze | ten sam mpv | jw. | HUD (sRGB z Pillow) w przezroczystym oknie Qt nad mpv (`video_preview.TopLevelHUDWindow`): najpierw wideo SDR, potem HUD, bez podwójnego mapowania |
| C. Podgląd podczas eksportu AMD | GPU frame tap z **finalnej klatki eksportera** (`SubmitPreviewTap`: VP → BGRA 960×540, ~2 FPS, bez dodatkowego dekodera i FFmpeg) | SDR i HLG→SDR: klatka NV12 po tone mappingu i z HUD (zgodna z MP4). Zachowaj HDR: P010 HLG przez VP z macierzą i zakresem BT.2020 G2.2, **bez tone mappingu** | HUD jest już w finalnej klatce |
| D. Inne backendy (podgląd etykiety, NVIDIA) | bez zmian, poza zakresem | | |

Odpowiedzi na pytania z zadania:
1. Czy mpv sam tone-mapuje HLG? Tak.
2. Z jakimi parametrami? `tone-mapping=auto`, `hdr-compute-peak=auto`, `gamut-mapping-mode=auto`, contrast recovery domyślnie.
3. Gdzie jest błąd? Dotyczył obu ścieżek: mpv mapował według innego modelu niż eksport, a natywny tap w trybie „Zachowaj HDR” nie mapował wcale.
4. Czy podgląd eksportu bierze klatkę eksportera? Tak (ścieżka C).
5. Kiedy dodawany jest HUD? W edytorze po konwersji. W eksporcie — w finalnej klatce (dla HDR zakodowany w HLG).
6. Czy istnieje konwersja tylko do prezentacji? Tak: VP w tapie podglądu oraz zarządzanie kolorem w mpv.

## 3. Różnice edytor ↔ eksport (przed zmianą, zmierzone)
Rzeczywisty libmpv (zrzut okna `screenshot-raw window`, 1280×720), HLG GX020079 w porównaniu z wyeksportowanym SDR MP4 (B_tm, ten sam mpv), centrum bez HUD: **MAE 20,3 / 20,2 / 17,9** (kl. 30/150/270). Podgląd był ciemniejszy o ~15 poziomów luma.

## 4–5. Sposób prezentacji SDR (krok B — PASS)
Dobór parametrów zmierzyłem libplacebo (ta sama biblioteka co mpv; `mpv_param_match.py`). Średnie MAE względem eksportu SDR:

| wariant | MAE |
|---|---|
| auto (stan sprzed zmiany) | 19,31 |
| bt.2390 static, clip | 8,47 |
| bt.2390 static, perceptual | 8,10 |
| bt.2390 static, perceptual, contrast recovery 0 | 7,95 |
| **bt.2390 static, relative, contrast recovery 0** | **6,17** |
| spline static | 16,78 |

Wybrano najbliższy wariant. W `build_mpv_options` (wszyscy dostawcy GPU i CPU) ustawiono `tone_mapping=bt.2390`, `hdr_compute_peak=no`, `gamut_mapping_mode=relative`, `hdr_contrast_recovery=0`. mpv potwierdza zastosowanie (`tone-mapping=bt.2390`, `hdr-compute-peak=false`, `gamut-mapping-mode=relative`, `hdr-contrast-recovery=0.0`).

**Rzeczywisty mpv po zmianie: MAE 7,56 / 7,83 / 6,02 (średnio 7,14)**, różnica średniej luma −0,28 / −0,04 / −5,61. Wizualnie: niebieskie niebo, czytelne cienie, nasycone kolory jak w MP4 (`Raporty/etap5z4_artifacts/mpv_tuned_f*.jpg`, lewo podgląd HLG, prawo eksport SDR; dla porównania `mpv_default_f*.jpg`).

Resztkowe różnice nie są korygowane mnożnikami. Wynikają z:
- tone mappingu max(R,G,B) w eksporcie wobec mapowania libplacebo;
- gamut mappingu `relative` wobec twardego clipu w eksporcie;
- ditheringu i kompresji HEVC 40 Mb/s;
- skalowania 4K → 720p.

## 6–8. Pliki i shadery
- Zmienione: `src/gui/qt/mpv_hwdec.py` oraz nowy test `tests/test_mpv_hdr_preview_options.py` (5/5).
- Użyto istniejącego tone mappingu mpv. **Nie powstał nowy shader.**

## 9–10. Zakres i gamut
- mpv sam interpretuje tagi źródła: pełny zakres, BT.2020, ARIB HLG. Wyjście idzie na wyświetlacz SDR (`target` auto).
- BT.2020→BT.709 jest liniowe, w trybie `relative` (kolory spoza gamutu mapowane względnie, bez desaturacji całości).
- Nie ma podwójnego full→limited, bo mpv nie zapisuje danych do pliku.

## 11. Podgląd w trybie „Zachowaj HDR” — **BLOCKED (wymaga DLL)**
- **Edytor:** poprawny (§5); tryb eksportu nie wpływa na edytor.
- **Podgląd w trakcie eksportu (stan przed zgodą; rozwiązane w §26):** `D3D11VideoProcessorPipeline::ConfigurePreviewTap` / `SubmitPreviewTap` w `d3d11_vp_pipeline.cpp` konwertują finalną klatkę P010 do BGRA przez VideoProcessorBlt z `YCBCR_FULL_G22_LEFT_P2020 → RGB_FULL_G22_NONE_P709`. To tylko macierz i zakres, bez transferu HLG. Tryby VP GHLG crashują sterownik (5Z.1). Python dostaje gotowe BGRA, a transformacja wewnątrz sterownika jest nieznana i nieodwracalna (clip), więc poprawnej korekty po stronie Pythona nie da się zrobić.
- **Minimalna proponowana zmiana (nie wykonana, wymaga zgody):**
  - w trybie `HLG_PRESERVE` tap zamiast VP uruchamia już istniejący shader HLG→SDR (`kHlgToSdrHlsl`, ten sam model co eksport, bez przeciwobrazu fused) z finalnej tekstury P010 do małej tekstury 960×540;
  - następnie konwersja do BGRA (BT.709) i ten sam staging oraz readback co dziś.
- ABI bez zmian (9), bez nowych eksportów.
- Koszt (ESTIMATED): ok. 0,1–0,3 ms GPU na klatkę podglądu przy ~2 FPS, czyli pomijalny wpływ na Render FPS.
- Plik Main10 nie zmienia się: tap tylko czyta finalną klatkę po jej przekazaniu do kodera.
- HUD jest w klatce zakodowany w HLG (biel 203 cd/m²), więc po tym samym tone mappingu wraca do bieli SDR, bez przepalenia.
- Test: harness `--preview-hud --hdr-mode preserve_hlg`, porównanie klatki tapu z kl. eksportu HLG→SDR, MD5 i VUI pliku Main10 bez zmian, Render FPS 300 kl.
- Do tego czasu ograniczenie jest opisane w GUI (etykieta HLG z 5Z.3).

## 12. „Konwertuj do SDR” — **PASS**
- Edytor: §5 (MAE 7,1 do MP4).
- Podgląd eksportu: tap czyta finalną klatkę NV12 po tone mappingu i HUD — dokładnie te dane, które dostaje koder. Konwersja VP NV12 BT.709 → BGRA to ta sama ścieżka co dla zwykłego SDR. Zgodność wynika z konstrukcji; tej ścieżki nie zmieniano.

## 13. HUD — **PASS (edytor)**
HUD nie jest tone-mapowany (okno Qt nad wideo). Geometria, fonty i kolory bez zmian. W MP4 HUD ma te same kolory (5Z.2: dokładność HUD 6,3 kodu, jak w SDR).

## 14. Porównania
Artefakty: `param_match.json`, `mpv_default.json`, `mpv_tuned.json`, `mpv_*_f{30,150,270}.jpg`. Format po obu stronach: wyrenderowane okno mpv (RGB8 SDR display) dla podglądu HLG i dla MP4 SDR. Ta sama ścieżka prezentacji, centrum bez HUD, skala 1280×720.

## 15–17. Płynność, opóźnienie, dekodery
- Odtwarzanie 4K HLG w mpv, 2 × 10 s na wariant, `hwdec=d3d11va`, 29,97 FPS, odtwarzanie w czasie rzeczywistym:
  - przed zmianą: 98 i 134 zgubionych klatek, 0 opóźnionych;
  - po zmianie: 129 i 96 zgubionych, 0 opóźnionych.
- Różnice mieszczą się w rozrzucie (monitor 32 Hz). Wyłączenie dynamicznej detekcji szczytu usuwa jedno przejście compute na klatkę.
- Zwykłe SDR (DJI_0010) renderowane przez mpv przed i po zmianie: **różnica pikseli 0,0** (identyczne).
- Nowe dekodery: **0**. Nowe kopie CPU/GPU: **0**. Nowe procesy FFmpeg: **0**. Opóźnienie odświeżania HUD (5 FPS) bez zmian, bo zmiana nie dotyka kodu HUD.

## 18–20. Eksport (krok E — PASS)
- Kod eksportu niezmieniony.
- Kontrolnie (300 kl., GX020079):
  - HLG→SDR (przed zmianą): 41,67 FPS;
  - Main10 przed / po: 41,62 / **41,64 FPS**.
- Po zmianie MP4: profil 2, 10/10 bit, colr 9/18/9 full, 74,8% próbek „prawdziwie” 10-bit.
- QP: 300 próbek; VBR 40M; AAC FEED 320 071 B `completed=True` (Direct Copy, Single Live Mux).

## 21–23.
- DLL: `2ceb50cc4d85343237f9aaf6634c7a2d93bb8de1375388166533d71227e0761e` przed i po — **UNCHANGED**.
- `def_layout.json`: `65fa8390d1cda70ed8d115631a75e35559b24b9990e1ca15f944f0fb371606f4` przed i po.
- Commit: `b05db3bdd9696be2f9db081e7a180d129f9ae5b7`.

## 24. Ograniczenia
1. Podgląd w trakcie eksportu w trybie „Zachowaj HDR” nadal bez tone mappingu (§11, wymaga zgody na DLL).
2. Ekran HDR: niesprawdzone. mpv z `target` auto może przełączyć się na wyjście HDR, jeśli Windows ma aktywne HDR — nie testowano (brak takiego ekranu). Ustawione parametry dotyczą tylko mapowania na cel SDR.
3. Zgodność edytora z MP4 jest przybliżona (MAE ~7), bo model mpv/libplacebo ≠ shader max(R,G,B). Pełną zgodność dałby tylko ten sam shader, a to wymagałoby własnego renderera podglądu — poza zakresem.
4. Testy E (przełączanie klipów w edytorze) i D (przełączanie trybu) nie były osobno automatyzowane. Mapowanie mpv nie zależy od trybu eksportu ani klipu (opcje stałe, metadane z każdego pliku), więc stan nie może „zalegać”. Oznaczam jako NOT TESTED interaktywnie.

## 25. Status kroków
| krok | status |
|---|---|
| A | PASS |
| B | PASS |
| C | PASS (edytor); podgląd eksportu HDR — BLOCKED (DLL) |
| D | PARTIAL (edytor i eksport zmierzone; brak interaktywnego testu przełączania trybu/klipów) |
| E | PASS |

ntfy: wysłane po zapisaniu raportu, "id":"RgGsuQf6gb9k", HTTP 200.


## 26. Kontynuacja po zgodzie na zmianę DLL — podgląd eksportu „Zachowaj HDR” (PASS)
Zgoda użytkownika: „w trybie HLG_PRESERVE tap podglądu eksportu ma używać istniejącego shadera HLG→SDR zamiast VideoProcessorBlt (ABI 9 bez zmian)”.

**Implementacja** (`d3d11_vp_pipeline.{cpp,h}`, commit `2004bf69cbbfa906dd4bebdffc9477863a3bba2b`):
- W HLG_PRESERVE `ConfigurePreviewTap` nie tworzy VideoProcessora. Tworzy 2 tekstury 960×540 RGBA8 z UAV oraz te same stagingi i zapytania co wcześniej.
- `SubmitPreviewTap` uruchamia `CSPreview`, czyli **istniejącą funkcję `ToSdr` z shadera eksportu HLG→SDR** (te same stałe 1000/203, BT.2390 max(RGB), BT.2020→BT.709, BT.1886). Bez nowego algorytmu. Próbkuje finalną klatkę P010 (już obróconą, z HUD zakodowanym w HLG) i zapisuje bajty w układzie BGRA. Odczyt idzie dotychczasową ścieżką.
- Koszt: jeden mały dispatch tylko z częstotliwością tapu (~2 FPS).
- Nowych dekoderów: 0. Nowych procesów FFmpeg: 0. Kopia CPU: tylko istniejący readback podglądu.
- ABI 9 bez zmian.
- Diagnostyka (Python, domyślnie wyłączona): `TELEM_EXPORT_PREVIEW_DUMP_DIR` zrzuca klatki BGRA tapu (`amd_hevc_preview.py`).

**Testy** (harness `--preview-hud`, GX020079, 300 kl., kandydat budowany w izolacji). Klatki tapu dopasowane do klatek MP4 HLG→SDR, BT.709 limited→RGB, 960×540, z HUD (`tap_compare.json`):

| tap | średnie MAE | różnica luma |
|---|---|---|
| **Zachowaj HDR — nowy** | **7,45** | +1,23 |
| Zachowaj HDR — stary (VP G2.2, bez TM) | 17,65 | −10,06 |
| Konwertuj do SDR — tap NV12 (bez zmian), względem własnego MP4 | 9,98 | +1,29 |

Nowy podgląd HDR jest tak samo bliski plikowi SDR jak dotychczasowy podgląd SDR (resztę stanowią skalowanie i kompresja). Biel HUD po tone mappingu wraca do bieli SDR (luma +1,2, bez przepalenia).

**Rozdzielenie ścieżek:**
- Main10 z nowym tapem i ze starą DLL (oba z podglądem): **MD5 wideo `5053b230d1bb93b283eae7ee3aae5adb` i audio `913c9de6…` identyczne**.
- MP4: profil 2, 10/10 bit, colr 9/18/9 full, QP 300 próbek.

**Regresje:**
- SDR DJI_0010 z nową DLL (stan rozgrzany): wideo `43e50a32…`, audio `1b9e2120…` — **identyczne**. Pierwszy przebieg dał `3f2dc4…`, czyli znany wariant zimnego cache telemetrii z 5Z.2.
- Render FPS naprzemiennie, te same warunki, Zachowaj HDR: produkcja 40,04 / 40,07, nowa DLL 40,16 / 41,25 — **brak regresji**.
- Dodatkowo nowa DLL: HLG→SDR 40,55 / 40,36, Main10 40,15 / 40,04.

**DLL:**
- przed etapem: `2ceb50cc4d85343237f9aaf6634c7a2d93bb8de1375388166533d71227e0761e` (kopia: `Raporty/etap5z4_artifacts/dll/telem_amd_native.dll.pre5z4`);
- **po: `e359d7784d2ff3d2b1aefb6cf56dc1ba3c38a67260fd8d87e27851ef0d55ee89`**, ABI 9, source_hash `848324a035d9…` — **CHANGED**, zainstalowana dopiero po testach.

`def_layout.json` bez zmian (`65fa8390…`).

**Status kroków (zaktualizowany):** A PASS, B PASS, C PASS, D PASS dla podglądu edytora i eksportu w obu trybach (interaktywne przełączanie trybu/klipów w GUI nadal nie zautomatyzowane), E PASS.

Commity etapu: `b05db3bdd9696be2f9db081e7a180d129f9ae5b7` (mpv), `2004bf69cbbfa906dd4bebdffc9477863a3bba2b` (tap HLG).

ntfy (kontynuacja, po aktualizacji raportu): "id":"oCvjETSsdXmc", HTTP 200.
