# Intel VBR / presety / QP — audyt

Stan: `main`, HEAD `e21d625`, niezacommitowane poprzednie poprawki Intel, NVIDIA i live mux zachowane. Zastana zmiana `def_layout.json`: `auto_activity_source=garmin`; nie nadpisano jej. Instrukcje AGENTS.md i BENCHMARKS.md przeczytane.

Potwierdzone przyczyny:

1. Resolver profili zawierał 7/4/1, ale eksporter zapisywał wynik do `TELEM_INTEL_TARGET_USAGE`; kolejne zadanie czytało go jako override i mogło zachować poprzedni preset.
2. Fallback używał `veryfast` niezależnie od profilu. `append_bitrate_args` dla Intel ustawiał tylko `-b:v`.
3. Native ustawiał VBR, jednak nie odczytywał przyjętych parametrów. Bufor 10000/5000 KB był stały dla dowolnego bitrate, a bitrate obcinano do 65535 kbps zamiast użyć mnożnika.
4. Native zbierał jedynie AV1 z parsera o stałych offsetach nagłówka, nie ogólnego parsera AV1. Takich wyników nie można uznać za wiarygodne na wszystkich strumieniach; w nowej ścieżce nie będą publikowane bez potwierdzonego źródła.
5. oneVPL oferuje `mfxExtAVCEncodedFrameInfo` (nazwa historyczna), dołączany do bitstreamu przed EncodeFrameAsync. Query mode 1 pozwala badać obsługę. Na i7-1265U potwierdzono wsparcie H.264 i HEVC; część raportów HEVC jest zerowana, mimo niezerowego slice QP w bitstreamie. Takie próbki trzeba wstrzymać, a statystyki oznaczyć jako częściowe.
6. Źródła FFmpeg QSV dołączają tę informację i packet quality side data dla H.264. Dla HEVC ta ścieżka nie raportuje QP; progress sam nie daje dowodu QP i nie wolno zastępować go oszacowaniem z bitrate.

Plan wdrożony do prób: tylko VBR, MaxKbps=125% celu, bufor równy 2 sekundom celu, początkowe zapełnienie 50%. Przy 40M zachowuje to wcześniejsze 10000/5000 KB. Mnożnik reprezentuje większe bitrate. Native GetVideoParam oraz diagnostyki FFmpeg sprawdzają faktycznie przyjęty tryb i parametry. HRD pozostaje w próbie inicjalizacji także po ewentualnym odrzuceniu VSI.

Materiał użytkownika: `C:\GoPro\GX010378.MP4`, z tą samą wcześniej wskazaną parą FIT `C:\GoPro\2026-10-15_15-03-50.fit`. Snapshot bieżącego HUD: `intel_vbr_qp_20261017/layout.json`. Kanoniczny harness: `SportCamHUD.py --test-intel-export`, rozszerzony o profil i zamrożony layout. Audio bezpośrednio z oryginalnego MP4, bez osobnych plików audio.

Wstępne rzeczywiste testy: native HEVC Main10 HLG, VBR=2, TU=4 i TU=7; przyjęte 40000/50000 kbps, 10000/5000 KB, HRD ON. Nagłówki strumienia: HRD obecne, `cbr_flag=0`, 50 Mb/s i 80 Mb CPB. FFmpeg HEVC przyjął analogiczne wartości. Pełna macierz jest wykonywana; ten audyt nie deklaruje końcowego PASS ani wyników długiego benchmarku.

Źródła pierwotne: [oneVPL — encoded frame info](https://intel.github.io/libvpl/latest/API_ref/VPL_structs_encode.html), [FFmpeg qsvenc.c](https://github.com/FFmpeg/FFmpeg/blob/master/libavcodec/qsvenc.c), [Intel GPU runtime — HEVC encoded frame info](https://github.com/intel/vpl-gpu-rt/blob/main/_studio/mfx_lib/encode_hw/hevc/agnostic/base/hevcehw_base_encoded_frame_info.cpp). Lokalnie zachowano sklonowane źródła i logi diagnostyczne.
