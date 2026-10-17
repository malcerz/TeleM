# SPORTCAMHUD — RAPORT ZABEZPIECZENIA DIRECT COPY AUDIO W GIT

Data: 2026-10-14  
Repozytorium: `C:\_DEV\BikeRideHUD-main-new`  
Gałąź: `fix/gui-freeze-hud-composite`  
Aktualny HEAD: `e76d6b1da0bcf1487e5061d16b05d7916adefb3b` (`fix(amd): use bitrate-targeted VBR instead of constant QP`)  
Status pełnego eksportu wieloplikowego: **NOT TESTED** (oczekuje na test produkcyjny użytkownika)

---

## 1. Cel i reguły wykonania

Zadanie miało na celu zabezpieczenie w Git nowej bezstratnej implementacji Direct Copy Audio dla AMD (potwierdzonej wcześniejszym raportem `Raporty/RAPORT_SPORTCAMHUD_AMD_DIRECT_COPY_AUDIO_WINDOWS.md`), przy zachowaniu ścisłych rygorów bezpieczeństwa:
- Brak modyfikacji `def_layout.json`.
- Brak poleceń niszczących: `reset`, `clean`, `stash`, `rebase`, `merge`, `push`.
- Ochrona niezacommitowanych prac użytkownika (Intel, NVIDIA, GUI layout).
- Bezwzględny zakaz wprowadzania rekompresji audio lub fallbacku do AAC 256k.
- Zgodnie z Punktem 7 instrukcji: w przypadku wykrycia nierozerwalnego wymieszania zależności z innymi nieukończonymi pracami — przedstawienie dokładnej macierzy zależności i zatrzymanie się przed wykonaniem commita.

---

## 2. Przegląd diffu nowej implementacji Direct Copy Audio

Implementacja Direct Copy Audio AMD składa się z:
1. `src/ffmpeg/mp4_audio_feed.py` (nieśledzony):
   - Odczyt próbek AAC bezpośrednio z tablic próbek MP4 (`stsz`, `stco`/`co64`, `stsc`, `stts`).
   - Opakowywanie próbek w locie w nagłówki ADTS w pamięci.
   - Serwer Win32 Named Pipe (`AacPipeFeeder`) strumieniujący próbki z synchronizacją z FFmpeg bez dotykania strumienia wideo.
   - Prawidłowe zwalnianie zasobów Win32 (`CancelSynchronousIo`, `DisconnectNamedPipe`, `CloseHandle`).
2. `src/ffmpeg/amd_native_exporter.py` (zmodyfikowany):
   - Funkcja guardująca `_require_amd_audio_copy` odrzucająca `concat_filter`, filtry `filter_complex` oraz kodek inny niż `-c:a copy`.
   - Zintegrowany start `AacPipeFeeder` podpiętego do wejścia FFmpeg `-f aac -i \\.\pipe\... -c copy`.
   - Przekazywanie `raw_video_timestamp_args` z filtrem `-bsf:v setts=...`, wymuszającym live interleave audio i wideo.
   - Likwidacja cichego fallbacku do Stage C / file muxera przy błędach tworzenia pipe lub startu FFmpeg – zgłaszanie jawnego wyjątku `AMDNativeFinalizationError`.
3. `src/ffmpeg/streaming.py` (zmodyfikowany):
   - Likwidacja fallbacku ze ścieżki natywnej AMD do programowej; fail-closed `AMDNativeFinalizationError`.
4. `tests/test_mp4_audio_feed.py` (nieśledzony):
   - Testy bit-exact odczytu pakietów AAC ze źródła.
5. `tests/test_amd_direct_mp4_mux.py` (zmodyfikowany):
   - Cykl życia Single Live Mux dla pojedynczego i wielu plików, wycięcie przestarzałego parametru `-ss` z wywołania FFmpeg i weryfikacja obsługi błędów fail-closed.
6. `tests/test_amd_live_mux_audio_finalization.py` (zmodyfikowany):
   - Testy weryfikujące `_require_amd_audio_copy`, potok named pipe, `thread_queue_size 512` i zakaz rekompresji.

---

## 3. Stan niezacommitowanych prac w working tree

W drzewie roboczym zidentyfikowano następujące niezacommitowane prace:
- `def_layout.json` (Modified): Zmiany układu graficznego wskaźników i cieni (wykluczone z commita).
- `src/ffmpeg/intel_native_exporter.py` (Modified): Niezacommitowany kod Live Mux backendu Intel (używający `build_live_audio_inputs` z rekompresją 256k).
- `src/ffmpeg/nvidia_native_exporter.py` (Modified): Niezacommitowany kod Live Mux backendu NVIDIA (używający `build_live_audio_inputs` z rekompresją 256k).
- `tests/test_live_av_mux.py` (Untracked): Testy modułu `live_av_mux.py` (weryfikujące m.in. `concat_filter` i 256k).
- `src/ffmpeg/live_av_mux.py` (Untracked): Moduł bazowy łączący struktury współdzielone oraz funkcje rekompresji.
- Pliki raportów w `Raporty/`.

---

## 4. Wykrycie nierozerwalnej zależności (Punkt 7 Instrukcji)

Zgodnie z punktem 7 zlecenia:
> *„Jeżeli zmiany są nierozerwalnie wymieszane z innymi pracami, przedstaw dokładną listę zależności i zatrzymaj się przed commitem. Podaj SHA commita lub konkretny powód, dlaczego nie można bezpiecznie go utworzyć.”*

### Przyczyna wstrzymania commita:
Wszystkie komponenty Direct Copy Audio (`mp4_audio_feed.py`, `amd_native_exporter.py` oraz testy) importują typy danych i funkcje pomocnicze z nieśledzonego pliku `src/ffmpeg/live_av_mux.py`:
- `AudioSegment`
- `LiveAudioInputs`
- `LiveMuxConfigError`
- `raw_video_timestamp_args`
- `audio_segments_from_timeline`
- `ffmpeg_supports_input_bsf`

Jednocześnie ten sam nieśledzony plik `src/ffmpeg/live_av_mux.py` zawiera:
- `LIVE_AUDIO_AAC_BITRATE = "256k"`
- `build_live_audio_inputs()` — funkcję tworzącą graf `-filter_complex concat` i rekompresującą audio do AAC 256k dla backendów Intel i NVIDIA.

### Kolizja wariantów:
1. **Commit bez `live_av_mux.py`:** Powoduje `ModuleNotFoundError: No module named 'src.ffmpeg.live_av_mux'` na każdym czystym checkout/klonie. Kod AMD jest niesamodzielny.
2. **Commit z włączeniem `live_av_mux.py`:** Wprowadza do historii repozytorium kod rekompresji 256k i filtr concat, co narusza punkty 3 i 12 zlecenia, a także pozostawia osierocone pliki Intel i NVIDIA, które jako jedyne korzystają z tej gałęzi.
3. **Modyfikacja kodu przed commitem (rozdzielenie struktur):** Zabroniona przez punkty 10 i 11 zlecenia (*„Nie zmieniaj FFmpeg, DLL AMD, VBR ani HUD”*, *„Nie uruchamiaj ponownie 40 testów ani pełnej regresji”*), ponieważ unieważniłaby zatwierdzony stan testowy (40/40 PASS).

Dlatego zgodnie z regułą fail-safe zatrzymano się przed utworzeniem commita.

---

## 5. Dostępne decyzje dla użytkownika

1. **Wariant 1 (Zatwierdzenie commita z `live_av_mux.py`):**
   Włączenie do jednego logicznego commita plików:
   - `src/ffmpeg/live_av_mux.py`
   - `src/ffmpeg/mp4_audio_feed.py`
   - `src/ffmpeg/amd_native_exporter.py`
   - `src/ffmpeg/streaming.py`
   - `tests/test_mp4_audio_feed.py`
   - `tests/test_amd_direct_mp4_mux.py`
   - `tests/test_amd_live_mux_audio_finalization.py`
   *(Pliki `intel_native_exporter.py`, `nvidia_native_exporter.py`, `test_live_av_mux.py` oraz `def_layout.json` pozostają w working tree).*

2. **Wariant 2 (Czysta separacja kodu):**
   Wydzielenie struktur współdzielonych do dedykowanego modułu bez gałęzi rekompresji 256k, aktualizacja importów w AMD i dopiero wtedy wykonanie commita.
