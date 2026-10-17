# SPORTCAMHUD — ETAP 5Z.2: obsługa HLG HDR / SDR w eksporcie AMD

Data: 2026-10-16. **STATUS: PARTIAL** — oba tryby (Zachowaj HDR i Konwertuj do SDR) działają i przeszły kanoniczne testy eksportu; anulowanie, ponowienie i wieloplikowy HLG sprawdzono tylko testami jednostkowymi (bez rzeczywistego eksportu), a fizycznego ekranu HDR nie testowano (szczegóły w §22–23).

| obszar | wynik |
|---|---|
| Wykrywanie HDR | PASS |
| GUI HDR/SDR (wybór, zapis, kolejka) | PASS |
| HLG → SDR | PASS |
| HLG → HLG Main10 | PASS |
| AMD VBR/QP | PASS |
| Direct Copy Audio | PASS |
| SDR bez regresji | PASS (bitowo identyczny strumień) |

## 1. Git
- Start: HEAD `f3ba1bc`, gałąź `fix/gui-freeze-hud-composite`. Zmiany zastane i **nietknięte**: `def_layout.json`, `src/ffmpeg/intel_native_exporter.py`, `src/ffmpeg/nvidia_native_exporter.py`, raport 5R_F; nieśledzone: `src/ffmpeg/live_av_mux.py`, `tests/test_live_av_mux.py`, `runtime/amd/`, kopie `.bak_*`.
- Commity tego etapu:
  - `1a389f85248f336899ba42e50962f87ab3c9eb7c` feat(export): detect HLG and persist HDR export mode
  - `a94781f6fe659969a106dc7498134b92995f66b6` feat(amd): HLG to SDR tonemapping and HEVC Main10 HLG preservation
- Kroki B i C są w jednym commicie natywnym, bo zmieniają te same funkcje (`ProcessFrame`, inicjalizacja puli/kompozytora, koder); rozdzielenie na dwa commity wymagałoby sztucznego cięcia fragmentów.
- Bez reset/clean/stash/rebase/merge/push. DLL, MP4 i `def_layout.json` nie są commitowane.

## 2. Zmienione pliki
Python: `src/ffmpeg/hdr_color.py` (nowy), `src/ffmpeg/amd_native_exporter.py`, `src/ffmpeg/render_errors.py`, `src/ffmpeg/streaming.py` (przekazanie trybu), `src/gui/qt/tabs/render_tab.py`, `src/gui/qt/controller.py`, `src/gui/qt/signals.py`, `src/gui/qt/_mixins/{preset,project,render}_mixin.py`, `src/gui/qt/application.py` (harness: `--hdr-mode`, `--queue-hdr-modes`), `tests/test_hdr_export_mode.py` (nowy, 22 testy).
Natywne: `d3d11_vp_pipeline.{cpp,h}`, `telem_amd_native.cpp`, `d3d11_amf_encoder.{cpp,h}`.
Nie zmieniono: Intel/NVIDIA, mapy, LEAN, Compass, Gauge, BAR, audio i live mux, FIT/GPX, Garmin, SmartSync, portable, MSIX, presetów jakości, VBR/QP.

## 3. Wykrywanie HLG (`src/ffmpeg/hdr_color.py`)
Odczyt ffprobe dla **każdego segmentu**: kodek, profil, pix_fmt i głębia bitowa, transfer, primaries, macierz, zakres, rozdzielczość, FPS, rotacja.
- **HLG** tylko wtedy, gdy `color_transfer = arib-std-b67` **oraz** głębia ≥10 bit, primaries BT.2020, macierz bt2020nc i znany zakres. Jeśli transfer to HLG, ale reszta oznaczeń się nie zgadza → `ambiguous`: eksport jest odrzucany z opisem problemu.
- Plik 10-bit, plik BT.2020 bez transferu HLG albo plik z GoPro → **nie** jest HDR (test jednostkowy).
- **PQ/HDR10** (`smpte2084`) jest rozpoznawany i jawnie odrzucany („nie jest jeszcze obsługiwany… aby nie wykonać błędnej konwersji”). Nigdy nie trafia do shadera HLG.
- **Wiele plików**: mieszanka HLG i SDR, HLG o różnym zakresie, różnej rozdzielczości lub FPS oraz rotacja inna niż 0/180° → konkretny błąd przed renderem.
- **Nieczytelne metadane** (ffprobe zawodzi, brak dowodu HDR) → ścieżka SDR bez zmian, czyli zachowanie sprzed etapu.
- [VIDEO TEST] GX020079 (oraz GX010114/115, GX010298): `hlg, 10-bit, bt2020/arib-std-b67/bt2020nc, full, 3840x2160@30000/1001, rot=180`. DJI_0010 → `sdr8`.

## 4. GUI i zapis
- W zakładce Eksport (opcje AMD) dodano „**Tryb HDR:**” z dwiema pozycjami: „Zachowaj HDR (HLG 10-bit)” (**domyślna**) i „Konwertuj do SDR (tone mapping)”. Pod listą wyświetla się opis wybranego trybu (teksty zgodne z zadaniem), a nad nią informacja „Wykryto materiał HLG HDR (BT.2020, 10-bit, pełny zakres)”.
- Selektor jest widoczny **tylko dla HLG**. Dla SDR jest ukryty, a dla PQ, mieszanych i niespójnych plików pokazuje się pomarańczowa informacja zamiast wyboru.
- Zapis: `layout.global.amd_hdr_mode` przez istniejący „Zapisz ustawienia” (ta sama ścieżka co `amd_encoder_quality`). Odczyt przy starcie przez `sig_amd_hdr_mode_restored`. Stary plik bez klucza → wartość domyślna (zachowaj HDR). Zmiana zakładki nie resetuje wyboru, bo stan trzyma kontrolka.
- [VIDEO TEST, harness] `hdr_selector_visible=True` dla GX020079, log `[HDR GUI] source kind=hlg hdr_selector=VISIBLE`. Testy GUI nie zapisują `def_layout.json`; jego hash jest niezmieniony.

## 5. Kolejka
- `amd_hdr_mode` trafia do `options` zadania w chwili dodania (`_build_options_from_gui`). Wykonanie czyta wyłącznie `options` zadania.
- Stare zadania bez klucza → domyślnie Zachowaj HDR.
- [VIDEO TEST, harness `Q2_queue`] Do kolejki dodano dwa zadania (Zachowaj HDR, potem Konwertuj do SDR), a następnie **zmieniono tryb w GUI** przed startem. Wynik:
  - zadanie 1: hvcC Main10 10/10 bit, colr 9/18/9 full;
  - zadanie 2: Main 8-bit, colr 1/1/1 limited;
  - zamrożone opcje: `[preserve_hlg, tonemap_sdr]`.
- [testy jednostkowe] Tryb przetrwa persist → reload i `requeue_job` (ponowienie).

## 6. Implementacja HDR → SDR
Model przeniesiony z sondy 5Z.1:
1. BT.2100 HLG: odwrotny OETF, OOTF z Lw = 1000 cd/m² i γ = 1,2.
2. BT.2020 → BT.709 (liniowo).
3. **BT.2390 na max(R,G,B)** w PQ, 1000 → 203 cd/m², co zachowuje odcień nieba.
4. BT.1886⁻¹, Y′CbCr BT.709 limited, dithering Bayer 4×4 przy redukcji 10 → 8 bit.

Stałe PQ liczone są raz na CPU. Parametry (1000/203/203) siedzą w stałych shadera, więc można je później kalibrować bez zmiany GUI. Nie ma dodatkowych korekt saturacji, kontrastu ani jasności. Shader **zastępuje `VideoProcessorBlt`** dla HLG: jeden Dispatch na teksturze dekodera, z wynikiem w istniejącej puli NV12. Bez CPU i bez nowych kopii.

## 7. Implementacja HDR Main10
Tor: dekoder MF (P010) → kopia compute P010 → **pula P010** (zamiast NV12) → kompozytor HUD HLG (in-place) → AMF HEVC.
- Ustawienia kodera: `PROFILE_MAIN_10`, `COLOR_BIT_DEPTH_10`, `Init(AMF_SURFACE_P010)`, VUI BT.2020/ARIB-STD-B67/BT.2020 i zakres źródła. Dotychczasowe VBR, bitrate, preset i FPS bez zmian.
- Po `Init` DLL sprawdza `profile=2, bit_depth=10`; jeśli się nie zgadza, odmawia.
- `telem_amd_probe_hevc_main10()` wykonuje rzeczywiste kodowanie Main10 (Init P010 i pakiety) produkcyjną klasą kodera. Wynik jest buforowany w Pythonie. `CAP_MAX_PROFILE` nie jest używany, bo zaniża możliwości (5Z.1).
- Brak Main10 → komunikat „Ten procesor graficzny nie zakodował strumienia HEVC Main10… Wybierz tryb »Konwertuj do SDR«” (`HDR_MODE_UNAVAILABLE`, to główna treść okna błędu). Tryb nie zmienia się automatycznie.

## 8. Ścieżki P010/NV12
| źródło / tryb | etap bazowy | pula | HUD | koder |
|---|---|---|---|---|
| SDR (bez zmian) | VideoProcessorBlt | NV12 | fused NV12 (normalizacja full→limited) | AMF NV12 Main |
| HLG → SDR | CS `etap5z2_hlg_to_sdr` | NV12 | fused NV12 bez zmian | AMF NV12 Main + VUI 709 |
| HLG → HLG | CS `etap5z2_hlg_copy` | **P010** | CS `etap5z2_hlg_hud` (P010) | AMF **P010 Main10** + VUI 2020/HLG |

Rotacja 180° (wszystkie pliki GoPro mają −180°) jest realizowana w shaderach. 90/270° dla HLG jest odrzucane w Pythonie i w DLL. Skalowanie przez próbkowanie dwuliniowe (przy 1:1 odczyt jest dokładny). Nie ma pośredniego NV12 w trybie HDR. Tryby VP GHLG/G2084 nie są używane.

## 9. Kontrakt zakresu (full/limited)
- Fused NV12 czyta bazę i **raz** mapuje full→limited (`L = (219F+127)/255+16`, chroma `ScaleChroma`). Shader HLG→SDR wylicza docelowy kod limited z ditheringiem, a następnie zapisuje **jednoznaczny przeciwobraz F** tego mapowania. Na wyjściu fused jest więc dokładnie docelowy kod limited, bez podwójnej konwersji i bez podwójnej kwantyzacji. Gdy HUD jest wyłączony (fused nie działa), shader zapisuje limited bezpośrednio.
- Do AMF trafia NV12 limited; MP4 zgłasza `tv`. Tryb HDR zachowuje zakres źródła (GoPro: full → `pc`).
- Zakres źródła pochodzi z metadanych (`AMD_NATIVE_SOURCE_RANGE`), nie z założenia.

## 10. VUI i MP4 (finalne pliki po Single Live Mux; `verify_mp4_color.py` czyta hvcC i colr z kontenera, SPS/VUI przez trace_headers oraz piksele)
| plik | hvcC profil / bit | colr nclx (P/T/M/full) | SPS VUI | ffprobe |
|---|---|---|---|---|
| HLG → HLG (T2) | 2 / 10 / 10 | 9 / 18 / 9 / true | 9 / 18 / 9, full=1, bitdepth−8=2 | Main 10, yuv420p10le, pc, bt2020nc/arib-std-b67/bt2020 |
| HLG → SDR (T1) | 1 / 8 / 8 | 1 / 1 / 1 / false | 1 / 1 / 1, full=0 | Main, yuv420p, tv, bt709/bt709/bt709 |
| SDR (bez zmian) | 1 / 8 / 8 | brak | primaries 0 (jak przed etapem) | bez zmian |

Brak fikcyjnych metadanych HDR10 (MDCV/CLL) w HLG. HLG nie jest oznaczany jako PQ.
Rzeczywista głębia HDR: 74,8% próbek luma nie jest wielokrotnością 4, a zakres kodów wynosi 0…1023.

## 11. Kompozycja HUD w HLG
- Konwersja: kod sRGB → **BT.1886 (γ 2,4)** → ×203 cd/m² (biel grafiki wg BT.2408) → BT.709→BT.2020 → odwrotny OOTF HLG (Lw 1000, γ 1,2) → OETF HLG → Y′CbCr BT.2020 w zakresie źródła. To kolorymetryczna transformacja, nie mnożnik RGB.
- Dlaczego BT.1886, a nie odcinkowy sRGB: tak wyświetlany jest HUD w dotychczasowym eksporcie SDR, więc wskaźniki zachowują dotychczasowy wygląd. Różnica dotyczy tylko najciemniejszych tonów.
- **Blending alfa** odbywa się w sygnale zakodowanym (HLG), tak jak w ścieżce SDR (zakodowany BT.709 / YCbCr). Krawędzie tekstu, półprzezroczyste cienie i ramki zachowują się tak samo jak w SDR. Blending liniowy byłby droższy i zmieniłby wygląd krawędzi względem SDR, dlatego go nie wybrano.
- Chroma pochodzi z lewego górnego piksela kwadratu, jak w kompozytorze SDR. Pikseli z alfą 0 kompozytor nie zapisuje, więc wideo pozostaje nietknięte.
- [MEASURED, `hud_fidelity_check_interior.json`, płótno HUD z tego samego przebiegu, wnętrza nieprzezroczystych elementów]:
  - biel HUD: **Y = 766** (wzór: 767, czyli HLG 75%); maksimum Y w HUD wynosi 844 przy 1023 dostępnych (bez przepalania);
  - błąd Y względem wzoru: **6,31** kodu w jednostkach 8-bit; ścieżka SDR bez zmian: 6,34 (ten sam poziom, wynikający z kompresji HEVC map i tekstu).

## 12. Porównanie kolorów (klatki 30/150/270, centrum bez HUD i regiony; `cmp_T1/compare.json`, `cmp_T1/sheet_f*.jpg`)
| klatka 30 | śr. luma | clip ≥250 | czerń ≤5 | nasycenie |
|---|---|---|---|---|
| stary eksport (błędny) | 150 | 25,3% | 0,40% | 0,260 |
| **nowy HLG → SDR** | 149 | 26,7% | **0,01%** | **0,339** |
| libplacebo bt.2390 statyczny | 157 | 31,4% | 0,01% | 0,305 |
| libplacebo domyślny (peak detect) | 133 | 23,8% | 0,02% | 0,324 |

- Klatka 270 (cienie): czysta czerń spada z **5,57%** w starym eksporcie do **0,49%**.
- Wyniki zgadzają się z wariantem max(RGB) z 5Z.1 (luma 148, clip 27,3%, nasycenie 0,343).
- Wizualnie: niebieskie niebo bez przesunięcia w cyjan, poprawne cienie i kolory BT.2020 przeniesione do BT.709. Nowy wynik jest jaśniejszy od domyślnego libplacebo, bo nie stosuje dynamicznej detekcji szczytu. To wybór modelu, nie błąd.
- HDR (T2) względem źródła P010, centrum: PSNR luma 35,2 / 32,8 / 40,0 dB (kompresja 40 Mb/s), średnie przesunięcie luma −0,13 / −0,28 / +0,46 kodu, zakres 0…1023, 1024 poziomy. Brak 8-bit, brak zmiany zakresu i transferu, brak clippingu.
- Ograniczenia: miary 8-bit RGB nie są percepcyjne (nie ΔE ITP). Wygląd HDR oceniono przez tone mapping libplacebo na ekranie SDR. **Fizycznego ekranu HDR nie testowano.**
- Podgląd eksportu w trybie HDR pokazuje dane P010 przez VP z macierzą i zakresem BT.2020 G2.2 (bez tone mappingu, zgodnie z ograniczeniem ekranu SDR). Zrzut klatek w checkpointach NV12 jest dla P010 wyłączony.

## 13. Render FPS (4K, 300 klatek, FAST, 40M, layout 5Y, GX020079 + FIT; ten sam materiał i ustawienia)
| wariant | przebiegi Render FPS | średnia | Effective FPS |
|---|---|---|---|
| stara wersja (HLG jako błędne SDR) | 41,78 / 41,33 | 41,6 | 26,7 / 27,6 |
| **HLG → SDR** | 40,61 / 39,61 / 41,51 / 41,32 / 41,07 / 40,71 | **40,8 (−1,9%)** | 25,9–27,3 |
| **HLG → HLG Main10** | 38,99 / 40,57 / 41,82 / 41,75 / 41,32 / 41,24 | **40,9 (−1,7%)** | 24,5–27,5 |
| SDR DJI_0010 stara / nowa | 38,82*, 36,88 / 37,59, 38,03, 37,55, 38,58 | 37,9 / 37,9 | 21,1–27,8 |

\* pierwszy przebieg z zimnym cache telemetrii.

Spadek jest poniżej 5% i mieści się w rozrzucie między przebiegami.

Czas GPU (MEASURED, `AMD_GPU_TIMESTAMP_PROFILE=1`, osie czasu `run/G2_*.gpu.csv`, `run/G3_*.gpu.csv`, klatki ≥30):
| ms/klatkę | SDR (VP) | HLG → SDR | HLG → HLG |
|---|---|---|---|
| konwersja bazowa | 2,84 (VP Blt) | 6,25–7,73 (CS) | 2,92 (kopia CS) |
| mapa | — | 0,52–0,58 | 0,63 |
| HUD | 2,39 | 3,15–3,40 | 3,24 |
| łącznie GPU | 5,3 | 10,1–11,7 | 6,8 |

- Uwaga: przebieg SDR (DJI_0010) nie ma mapy z FIT, więc nie jest porównywalny 1:1 z HLG.
- W potoku shader tone mappingu kosztuje więcej niż w izolowanej sondzie (2,95 ms), co wynika z konkurencji z dekoderem i koderem. Łączny czas GPU ~11 ms jest jednak wyraźnie poniżej 24 ms/klatkę przy 41 FPS, więc wąskim gardłem pozostaje przygotowanie HUD na CPU.
- Starej ścieżki VP dla HLG nie zmierzono timestampami (stara DLL nie zapisuje CSV); 5Z.1 izolowanie: 3,0–4,0 ms.
- Transfery CPU↔GPU: **0 nowych**. Pamięć: pula P010 (8 × 24,9 MB) zamiast NV12 (8 × 12,4 MB) tylko w trybie HDR [ESTIMATED z formatów].
- AMF encode i czas finalizacji nie są osobno mierzone przez harness. Effective FPS powyżej obejmuje przygotowanie i finalizację.

## 14. Direct Copy Audio
We wszystkich eksportach (SDR, HLG→SDR, HLG→HLG, kolejka) jest `[AMD AAC FEED] … completed=True` z identyczną liczbą bajtów, a strumień AAC LC 48 kHz 2 ch ma 469 pakietów, `start_time=0`. MD5 strumienia audio jest identyczne ze starym eksportem. Nigdzie nie pojawia się audio_cache, M4A ani ADTS. Live mux działa bez zmian. Komunikat `[in#1/aac] Error during demuxing` występował już w baseline (B0) i nie jest nowy.

## 15. QP/VBR
- VBR 40M (szczyt 60M), FAST — bez zmian. Bitrate wyjścia: 38,6 Mb/s.
- Sprzętowy QP: `samples=300`, `ok=300 fail=0` w obu trybach HLG (avg 33,4 SDR-TM / 33,6 Main10). Main10 nie wymaga innej obsługi właściwości QP: flaga na powierzchni działa tak samo.

## 16. Mapa, Track-Up, LEAN, polskie znaki
Wszystkie trzy tryby, klatka 30 (`cmp_hud/full_frames_f30.jpg`, `cmp_hud/hud_crop_f30.jpg`):
- mapa GPU z zaokrąglonymi rogami i ramką oraz markerem, Track-Up;
- Gauge, wykresy HR i kadencji, BAR, kompas;
- LEAN „PRZECHYŁ” ze skalą i linią;
- napisy „ŚREDNIA…”, „Ł”, symbol stopni („--°”) widoczne i w tych samych pozycjach.

Geometria HUD nie zmieniła się. Tylko w trybie HDR kolory są kodowane do HLG.

## 17. SDR bez regresji
DJI_0010, 300 klatek, warunki identyczne:
- MD5 strumienia wideo: produkcyjna DLL (drugi przebieg) = kandydat ×2 = finalna DLL = `43e50a3206e54a4e52e5459d59c895a5`;
- MD5 audio: `1b9e2120932feaf5cad50faffdc66677` we wszystkich przebiegach.

**Bitstream jest identyczny.** Pierwszy przebieg produkcyjny (B0_r1) różnił się w klatkach 0–119 z powodu zimnego cache telemetrii (log: `cache_key … does not match`, przebudowa danych wykresów), niezależnie od DLL.

## 18. DLL
- **Stara:** `5ad042bb8f61db32af52df2a3ea1fdd77c40b253866ce28724c6fe01e4a3c0df`, source_hash `64eb32c3af5d`. Kopie: `Raporty/etap5z2_artifacts/dll_backup/telem_amd_native.dll.pre5z2` i `native_bin.pre5z2`.
- **Nowa (zainstalowana do `runtime/amd/bin` i `native/d3d11_amf_pipeline/bin`):** `2ceb50cc4d85343237f9aaf6634c7a2d93bb8de1375388166533d71227e0761e`, build_id `telem-amd-native/1.0.0+f3ba1bc3494f.srcaf13d557cc7c` (source_hash `af13d557cc7c` = źródła z commita `a94781f`).
- Budowano wyłącznie w izolowanej kopii (`Raporty/etap5z2_artifacts/native_build`), a testy prowadzono przez `TELEM_AMD_NATIVE_DLL`. Instalacja nastąpiła dopiero po testach.

## 19. ABI
**ABI 9 bez zmian** (rozszerzenie wyłącznie addytywne). Nowe eksporty:
- `telem_amd_get_color_features()` (bit 0 = HLG→SDR, bit 1 = HLG preserve);
- `telem_amd_get_color_pipeline(handle)`;
- `telem_amd_probe_hevc_main10()`.

Tryb wybiera zmienna środowiskowa `AMD_NATIVE_COLOR_PIPELINE` (+ `AMD_NATIVE_SOURCE_RANGE`), ustawiana przez Pythona przy każdym eksporcie, także na `SDR`, więc nic nie przecieka między zadaniami. Opcjonalnie diagnostyczny `AMD_GPU_TIMELINE_PATH`.

Zgodność wstecz:
- stara DLL + SDR → działa jak dotąd;
- stara DLL + HLG → jawny błąd „Załadowana biblioteka AMD … nie obsługuje …”, bez eksportu [VIDEO TEST, `B0_HLG_prod_r3`, `G_prod`];
- po `telem_amd_create` Python porównuje tryb zastosowany z żądanym i przerywa przy niezgodności.

## 20. SHA commitów
`1a389f85248f336899ba42e50962f87ab3c9eb7c`, `a94781f6fe659969a106dc7498134b92995f66b6`.

## 21. def_layout.json
`65fa8390d1cda70ed8d115631a75e35559b24b9990e1ca15f944f0fb371606f4` przed i po etapie (plik był zmieniony względem HEAD przed etapem i nie był dotykany). Każdy przebieg harnessu sprawdzał hash: `def_layout_unchanged True`.

## 22. Otwarte problemy i ograniczenia
1. **Anulowanie i ponowienie** w trybach HDR zweryfikowano testami jednostkowymi (`test_direct_mp4_mux_user_cancellation`, `requeue`), a nie rzeczywistym eksportem; harness nie ma opcji anulowania.
2. **Wieloplikowy HLG** (np. GX010114–116, ~31 GB): klasyfikacja i blokady mają testy jednostkowe, rzeczywisty eksport wieloplikowy HLG nie był uruchamiany. Dodatkowy GX010361 nie był testowany.
3. **Ekran HDR**: nie testowano fizycznie. Dane HDR zweryfikowano metadanymi i pikselami, a wygląd przez tone mapping libplacebo.
4. **PQ/HDR10**: tylko rozpoznanie i odmowa (zgodnie z zakresem etapu).
5. **HLG → SDR** jest statycznym BT.2390 bez dynamicznej detekcji szczytu. Sceny słoneczne są jaśniejsze niż w domyślnym libplacebo. Kalibracja (biel 203, szczyt 1000) jest możliwa w stałych shadera.
6. **Podgląd eksportu HDR** pokazuje dane HLG bez tone mappingu (macierz i zakres BT.2020). Checkpointy NV12 są dla P010 niedostępne.
7. **Rotacja 90/270°** dla HLG jest nieobsługiwana (jawny błąd); GoPro używa 0/180°.
8. **Ścieżka x265/8K** i diagnostyczne tryby kompozytora odrzucają tryby HLG (jawny błąd).
9. **Istniejące, niezwiązane porażki testów** są identyczne na czystym `f3ba1bc`: `test_export_queue_basic` (1), `test_font_persistence_v2` (1), `test_amd_live_mux_audio_finalization` (6–11, zależnie od platformy Qt), `test_amd_decode_gui_switch` (2 w trybie z oknami). Testy GUI uruchamiane bez `QT_QPA_PLATFORM=offscreen` otwierają prawdziwe okna komunikatów. To one spowodowały okna „Brak wczytanego pliku wideo” widoczne w trakcie etapu; aplikacja nie była wtedy używana.
10. **SDR ze starego toru** nadal ma VUI primaries=0 i macierz BT.601 dla HUD. Nie zmieniono tego celowo, żeby zachować identyczny bitstream.

## 23. Status kroków
| krok | status | testy |
|---|---|---|
| A — wykrywanie, GUI, zapis, kolejka, walidacja, brak cichego fallbacku | **PASS** | 22 testy jednostkowe + harness (selektor widoczny, kolejka) |
| B — HLG → SDR w D3D11 | **PASS** | eksport 4K ×6, VUI/MP4, kolory, FPS, brak crasha |
| C — HLG Main10 P010 | **PASS** | eksport 4K ×6, Main10 10-bit, VUI/MP4/colr, HUD, QP/VBR, FPS |
| D — GUI + kolejka w obu trybach | **PARTIAL** | eksport bezpośredni i kolejka naprzemienna: PASS; ponowienie i anulowanie: tylko testy jednostkowe |

Ścieżki: `Raporty/etap5z2_artifacts/` zawiera `run/*.json|log|stdout.txt|color.json|gpu.csv`, `cmp_T1/`, `cmp_hud/`, `run/hud_fidelity_check*.json`, `dll_backup/` oraz skrypty `build_candidate.sh`, `run_5z2_export.py`, `verify_mp4_color.py`, `compare_export_frames.py` i `hud_and_fidelity_check.py`. Duże MP4 usunięto po pomiarach.

ntfy: wysłane po zapisaniu raportu (wynik w odpowiedzi końcowej).
