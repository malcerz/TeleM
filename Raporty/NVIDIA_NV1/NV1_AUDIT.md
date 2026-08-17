# NVIDIA NV1 — filter_complex_threads A/B

## Audyt (BRAMKA 1)

### CURRENT FILTER_COMPLEX_THREADS
**NIE USTAWIANE.** Brak tej flagi w całym repo (grep — zero wyników).
FFmpeg używa własnego domyślnego zachowania (zazwyczaj = 1 dla filter_complex).

### FILE TO MODIFY
`src/ffmpeg/command_builder.py`
Sekcja: linia ~457 (po audio_input_args, przed filter_complex).

### OVERRIDE DESIGN
Env var TELEM_NV_FILTER_COMPLEX_THREADS:
- jesli nieustawiony: zero zmian, identyczne production behavior,
- jesli ustawiony na poprawna int >= 1: wstrzykuje -filter_complex_threads N do cmd,
- walidacja: ignoruje puste stringi i bledne wartosci (ValueError, <1).

Flaga wstrzykiwana przed -filter_complex, co jest poprawnym miejscem w CLI FFmpeg.

### AMD IMPACT: NONE
Blok if encoder == "nv" — AMD nigdy nie wchodzi w ten code path.

### INTEL IMPACT: NONE
Jak wyzej.

---

## Implementacja — STATUS: DONE

Zmieniony plik: src/ffmpeg/command_builder.py

Dodano import os na gorze pliku.

Wstrzykniety blok NV1 po audio_input_args, przed -filter_complex:

    _nv_fct_raw = os.environ.get("TELEM_NV_FILTER_COMPLEX_THREADS", "").strip()
    _nv_fct: int | None = None
    if encoder == "nv" and _nv_fct_raw:
        try:
            _nv_fct = int(_nv_fct_raw)
            if _nv_fct < 1:
                _nv_fct = None
        except ValueError:
            _nv_fct = None

    if _nv_fct is not None:
        cmd.extend(["-filter_complex_threads", str(_nv_fct)])
        print(f"[NV1] filter_complex_threads={_nv_fct}", flush=True)

---

## Walidacja komend

### REFERENCE (brak env)
Pipeline identyczny z production. Brak -filter_complex_threads w cmd.
Zawiera:
- scale_cuda={render_w}:{render_h}:format=yuv420p  OK
- format=rgba,scale=3840:2160:flags=bilinear,hwupload_cuda  OK
- overlay_cuda  OK
- hevc_nvenc  OK

### Wariant A (TELEM_NV_FILTER_COMPLEX_THREADS=2)
Jedyna roznica wzgledem REFERENCE: dodatkowy argument -filter_complex_threads 2 przed -filter_complex.
Wszystkie elementy pipeline frozen.

### Wariant B (TELEM_NV_FILTER_COMPLEX_THREADS=4)
Jedyna roznica: -filter_complex_threads 4.
Wszystkie elementy pipeline frozen.

---

## Instrukcja A/B dla uzytkownika

Uruchom TeleM normalnie przez GUI dla kazdego wariantu.
Wykonaj pelny real export GX020079.MP4 -> 4K HEVC NVIDIA.

### REFERENCE (obecny production baseline — brak env)
  python TeleMGP.py

### Wariant A
  $env:TELEM_NV_FILTER_COMPLEX_THREADS = "2"; python TeleMGP.py

### Wariant B
  $env:TELEM_NV_FILTER_COMPLEX_THREADS = "4"; python TeleMGP.py

Weryfikacja aktywacji:
W logu/konsoli powinno pojawic sie [NV1] filter_complex_threads=N.
Brak tej linii = env nie byl ustawiony = REFERENCE mode.

---

## Po kazdym runie podaj

| Metryka               | REFERENCE | Wariant A (=2) | Wariant B (=4) |
|-----------------------|-----------|----------------|----------------|
| Klatki                | /1131     | /1131          | /1131          |
| TRUE FPS              | ~33.5     | ?              | ?              |
| Czas (s)              | ~33       | ?              | ?              |
| ffmpeg_write avg (ms) | ~25.51    | ?              | ?              |
| ffmpeg_write P95 (ms) | ~29.22    | ?              | ?              |
| drops                 | 0         | ?              | ?              |
| audio                 | YES        | ?              | ?              |

---

## Correctness gate

Kazdy wariant musi dac:
- 1131/1131 klatek
- drops = 0
- audio YES
- brak artefaktow (green/magenta, zmiana layoutu)

Zmiana filter_complex_threads jest numerycznie neutralna — nie wplywa na obraz.

---

## STOP

Po zebraniu wynikow A/B — decyzja o NV1 PASS / INCONCLUSIVE / NV1b (6/8 threads).
