# NVIDIA NV2 — REAL GUI A/B (manual, użytkownik)

> ⚠️ **SUPERSEDED przez NV3 (2026-08-17).** NV2 potwierdzony w REAL GUI i utwardzony
> jako **production default**. CUDA ROT180 jest teraz domyślny dla NVIDIA rotation=180
> bez żadnej zmiennej; opt-out to **`TELEM_NV_ROT180_CPU_FALLBACK=1`**.
> Stary switch `TELEM_NV_ROT180_CUDA` już nie obowiązuje. Szczegóły: `Raporty/NVIDIA_NV3/RAPORT_NV3.md`.

Sprzęt: **NVIDIA Quadro P400 2 GB** · Materiał: **GX020079.MP4** (3840×2160, 29.97 FPS, HEVC Main10, 1131 frames, container rotation −180° / 180°)

Eksperymentalny switch: **`TELEM_NV_ROT180_CUDA`** (default **OFF**).

---

## 1. REFERENCE (baseline, ~33.5 FPS)

Nie ustawiaj zmiennej (lub ustaw `0`). Zwykły eksport = aktualna ścieżka production (CPU chain).

```powershell
# upewnij się, że zmienna nie jest ustawiona
Remove-Item Env:TELEM_NV_ROT180_CUDA -ErrorAction SilentlyContinue
python TeleMGP.py
```

W GUI: otwórz `Video\GX020079.MP4` + `Video\Morning_Ride.fit`, ustaw encoder **NVENC (nv)**, rozdzielczość **source**, wykonaj pełny eksport (1131 klatek). Zapisz output jako `ref_180.mp4`.

> ⚠️ **Uwaga (terminal):** `$env:TELEM_NV_ROT180_CUDA="1"` ustawione w terminalu zostaje w nim **do końca sesji**. Jeśli wcześniej uruchamiałeś EXPERIMENT w tym samym terminalu, zmienna wciąż tam jest i REFERENCE też uruchomi NV2. Zawsze sprawdzaj w **tym samym** terminalu, w którym odpalasz GUI:
> ```powershell
> Get-ChildItem Env:TELEM_NV*
> Remove-Item Env:TELEM_NV_ROT180_CUDA -ErrorAction SilentlyContinue
> ```
> Jeśli w logu eksportu zobaczysz `[NV2] ROT180 CUDA FAST PATH: ON` — zmienna nadal jest ustawiona.

## 2. EXPERIMENT (NV2 CUDA fast-path)

```powershell
$env:TELEM_NV_ROT180_CUDA="1"
python TeleMGP.py
```

W GUI: te same ustawienia (encoder **nv**, rozdzielczość **source**). Zapisz output jako `exp_180.mp4`.

W logu przy ON pojawi się wyłącznie:
```
[NV2] ROT180 CUDA FAST PATH: ON
...
[NV2] displaymatrix rotate=180 injected into ...: True
```
Przy OFF (env unset / "" / "0" / "false" / "no") **nie ma żadnego `[NV2]`** w logu i nie ma injection — wraca dokładnie reference CPU path.

---

## 3. Co sprawdzić po eksporcie

### 3.1. Metadata gate (wymagane)

```powershell
F:\_DEV\TeleM\ffprobe.exe -v error -show_entries stream_side_data=rotation -of json exp_180.mp4
```

**MUSI** pokazać `"rotation": -180` (albo 180) w `side_data_list` (prawdziwy Display Matrix). Jeśli `side_data_list` jest puste lub `rotation: 0` → FAIL.

### 3.2. Player correctness

- **MPV TeleM** (podgląd w GUI) — HUD i wideo muszą być prawidłowo zorientowane.
- **Drugi player** (VLC zalecany; WMP jest deprecated i headless niezweryfikowany) — sprawdź, czy obraca zgodnie z metadata. Jeśli którykolwiek ignoruje metadata → **raportuj** (rozwiązanie nie jest wtedy production-safe).

### 3.3. Correctness gate

- 1131 / 1131 klatek, drops = 0, audio = YES.
- Wideo — prawidłowa orientacja (po display rotation 180°).
- HUD — prawidłowa orientacja; teksty NIEodwrócone.
- Pozycje HUD — logicznie identyczne z REFERENCE.
- Mapa, charty, gauge — poprawne.
- Brak: green/magenta/black frames, alpha corruption.

### 3.4. Pixel A/B (opcjonalnie, ale zalecane)

```powershell
# Zdekoduj oba do display orientation i porównaj klatki 30, 300, 900:
F:\_DEV\TeleM\ffmpeg.exe -y -ss <T> -i ref_180.mp4  -frames:v 1 ref_<T>.png
F:\_DEV\TeleM\ffmpeg.exe -y -ss <T> -i exp_180.mp4 -frames:v 1 exp_<T>.png   # ffmpeg stosuje autorotate domyślnie
```

Porównaj MAE/MAX oraz wizualnie crop HUD/map/gauge.

### 3.5. Performance

- Zanotuj **TRUE FPS** z GUI dla REFERENCE i EXPERIMENT.
- Zanotuj `ffmpeg_write avg` / `P95` jeśli log je pokazuje.
- Obserwuj **VRAM** (`nvidia-smi` w trakcie eksportu) — P400 ma 2 GB; brak OOM.

---

## 4. Wymagane decyzje (raport)

1. Czy rotation=180 udało się utrzymać poza CPU base-video path?
2. Czy base video jest na CUDA od decode do NVENC?
3. Czy jedyną fizyczną rotacją CPU jest mały HUD canvas?
4. Czy metadata rotation działa w realnym MP4 (ffprobe + player)?
5. Czy HUD po odtworzeniu jest prawidłowy?
6. Czy layout jest identyczny z REFERENCE?
7. Jaki jest koszt rotate180 HUD (zmierzony: median ~3.7 ms)?
8. Jaki jest REAL GUI TRUE FPS?
9. Jaki jest gain względem 33.5 FPS?
10. Czy rozwiązanie nadaje się na production default? Jeśli NIE — dlaczego?

**STOP:** nie ustawiaj jako default. Nie wykonuj Vulkan fallback. Nie ruszaj AMD/Intel.
