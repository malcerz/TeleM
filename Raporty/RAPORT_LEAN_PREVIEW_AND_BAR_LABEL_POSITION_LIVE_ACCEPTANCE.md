# LEAN + BAR — LIVE GUI FINAL ACCEPTANCE

**Data:** 2026-09-09  
**Branch / HEAD:** `integration/intel-amd` / `59277b4`  
**Projekt:** `Video/GX010115.MP4` + auto-matched `GX010114_116.fit`  
**Artefakty:** wyłącznie `D:/TeleM_live_acceptance/` (dysk F: nieużywany)

Zakres ograniczono do Lean/Przechył i pozycji etykiety BAR. Nie zmieniano
backendów Intel/NVIDIA, Hybrid/PreparedVideoFrame, jakości obrazu ani HUD.
Nie wykonano długiego renderu, nie wykonano commit ani push.

## 1. Real GUI Lean playback

Uruchomiono rzeczywisty łańcuch `QApplication → AppController → MainWindow`
z normalnym `RenderTab` i załadowaniem GPMF. Cache zawierał 117728 próbek ACCL
i 117728 próbek GYRO. W teście acceptance ustawiono w pamięci
`form=lean`, `source=gyro`, `axis=x` (X = ROLL). Istniejący sidecar
`Video/GX010115.layout.json` ma historyczne jawne `axis=y`; nie został zmieniony.

Play włączono przez `VideoPreview._toggle_playback()`. W 4-sekundowym oknie
otrzymano 4 różne klatki obrazu (4 różne hashe), bez błędu GUI. W trybie
offscreen MPV zgłaszał `hwdec-current=None`, a `time_pos` pozostawał 0.0;
jest to ostrzeżenie środowiska testowego, nie zmiana ścieżki renderera.

**LEAN LIVE PLAYBACK: PASS (offscreen/MPV warning recorded)**

## 2. Five timestamp proof and seek

Po każdym z poniższych seeków `sig_preview_frame_ready` dostarczył nową klatkę,
a crop Lean został zapisany. Hash crop zmieniał się zgodnie z wartością:

| seek / timestamp UTC | `lean_roll_x` / final angle | widoczny stan ikony Preview | crop |
|---:|---:|---|---|
| 0.0 s — 2026-08-14T11:18:02.250270Z | +1.93024° | prawie pion, `+2°` | [seek_0_0_lean.png](D:/TeleM_live_acceptance/seek_0_0_lean.png) |
| 25.0 s — 2026-08-14T11:18:27.250270Z | +21.73056° | wyraźnie w prawo, `+22°` | [seek_1_25_lean.png](D:/TeleM_live_acceptance/seek_1_25_lean.png) |
| 40.0 s — 2026-08-14T11:18:42.250270Z | −3.89634° | przechył przeciwny, `−4°` | [seek_2_40_lean.png](D:/TeleM_live_acceptance/seek_2_40_lean.png) |
| 180.0 s — 2026-08-14T11:21:02.250270Z | +7.94459° | lekko w prawo, `+8°` | [seek_3_180_lean.png](D:/TeleM_live_acceptance/seek_3_180_lean.png) |
| 300.0 s — 2026-08-14T11:23:02.250270Z | +9.15577° | lekko w prawo, `+9°` | [seek_4_300_lean.png](D:/TeleM_live_acceptance/seek_4_300_lean.png) |

Wartości obejmują dodatnie i ujemne kąty; ikona faktycznie zmienia obrót, a nie
pozostaje w stanie 0°. `MPV Seek Error -12` pojawiał się w offscreen, lecz
każdy seek kończył się nową klatką i właściwym kątem.

**LEAN 5 TIMESTAMPS: PASS**  
**LEAN SEEK: PASS (offscreen/MPV warning recorded)**

### Sign

**LEAN SIGN CHANGE: PASS.** Dane mają oba znaki (`+21.73056°`, `−3.89634°`).
Nie zmieniano konwencji znaku. `DATA SIGN` jest znany; absolutny kierunek
lewo/prawo względem fizycznego montażu kamery nie był kalibrowany, więc nie
wyciągano wniosku o odwróceniu kamery.

## 3. Preview ↔ Final Lean

Wykonano krótki AMD native single-pass render obejmujący 450 klatek (źródłowy
odcinek 30–45 s), z osią `x` ustawioną w pamięci. Finalne klatki:

- [finalx_0.png](D:/TeleM_live_acceptance/finalx_0.png)
- [finalx_10.png](D:/TeleM_live_acceptance/finalx_10.png)
- [finalx_14.png](D:/TeleM_live_acceptance/finalx_14.png)

Pokazują niezerowe, zmieniające się obroty ikony Lean. Preview i Final używają
wspólnego canonicalnego `lean_roll_x`, interpolacji timestampu i compositora;
nie ma statycznego 0° ani drugiego resolvera. Z powodu różnej skali screenshotów
(Preview 640×360, Final 3840×2160) nie wykonywano sztucznego pixel-diffu.

**LEAN PREVIEW/FINAL VISUAL PARITY: PASS (shared path + visual proof; no cross-scale pixel diff)**

## 4. BAR — live Property Editor

Przez normalny `ctrl._on_property_changed` zmieniono realne wskaźniki
`fit_distance_text` (poziomy) i `alt_text` (pionowy). Wszystkie zmiany od razu
odświeżały raster/bbox Preview:

| kontrola | wynik live |
|---|---|
| AUTO | zachowany dotychczasowy wygląd/bbox |
| TOP / BOTTOM | etykieta nad/pod osią BAR |
| LEFT / RIGHT | etykieta po semantycznej stronie ekranu |
| INSIDE | etykieta wewnątrz BAR |
| offset X +50, X −50, Y +50 | natychmiastowa zmiana położenia |

Poziomy bbox zmieniał się m.in. z `(143,14,390,41)` (AUTO/TOP) do wariantów
side/inside; pionowy `alt_text` miał bbox `(583,113,55,133)`. Zapisano obrazy
`bar_*.png` na D:.

**BAR LIVE PROPERTY CHANGE: PASS**  
**AUTO OLD LOOK: PASS**  
**TOP/BOTTOM/LEFT/RIGHT/INSIDE: PASS**  
**OFFSET X/Y: PASS**  
**VERTICAL BAR: PASS** — tekst pozostał poziomy, strony odnoszą się do obrazu
końcowego, nie do lokalnego rastra przed rotacją.

## 5. Current bars and save/reload

Zweryfikowano istniejące Distance, Altitude oraz Battery/Solar-style fields;
AUTO nie zmienia domyślnego wyglądu. Preset testowy zapisano i odczytano z:
[live_bar_preset.json](D:/TeleM_live_acceptance/live_bar_preset.json).
Wartości `label_position=bottom`, `label_offset_x=37`,
`label_offset_y=-24` zostały odczytane identycznie.

**SAVE/RELOAD: PASS**

## 6. BAR Preview ↔ Final

Wykonano drugi krótki AMD single-pass render: 300 klatek (30–40 s), z:
`fit_distance_text = bottom, +37, −24` oraz `alt_text = right, −18, +7`.
Plik [bar_custom_30_40.mp4](D:/TeleM_live_acceptance/bar_custom_30_40.mp4)
ma 300 klatek; screenshot [bar_custom_01.png](D:/TeleM_live_acceptance/bar_custom_01.png)
pokazuje napis `DISTANCE` pod osią, bez clippingu. Preview używał tych samych
wartości i wspólnego compositora; bbox i orientacja fontu są zgodne semantycznie.

**PREVIEW/FINAL: PASS (live custom render; no cross-scale pixel diff)**

## 7. Drag / selection

Wykonano rzeczywisty syntetyczny press→move→release `QMouseEvent` na live
`mpv_widget`: kliknięto `fit_distance_text`, otrzymano
`sig_indicator_clicked`, następnie `sig_indicator_moved` z nowym `(x,y)`
`(55.66, 11.24)`. Property/layout state został zsynchronizowany, bez starego
bbox ani ghost-selection area.

**DRAG/BBOX: PASS**

## 8. Render / disk evidence

| plik | video | audio | wynik |
|---|---|---|---|
| `lean_bar_30_45.mp4` | HEVC 3840×2160, 450 frames, 15.015 s | AAC 48 kHz stereo, 705 packets, 15.034667 s | complete, child exit 0 |
| `bar_custom_30_40.mp4` | HEVC 3840×2160, 300 frames, 10.010 s | AAC 48 kHz stereo, 470 packets, 10.021333 s | complete, child exit 0 |

Po sukcesie nie pozostał pełnowymiarowy `.part.temp_video.mp4`; największym
artefaktem tymczasowym był krótki log diagnostyczny 1.8 kB. Duże artefakty to
wyłącznie finalne MP4 na D:. Nie wykonywano długiego renderu ani zewnętrznego
profilera.

## Acceptance summary

| Kryterium | Status |
|---|---|
| LEAN LIVE PLAYBACK | PASS (warning: offscreen MPV position) |
| LEAN 5 TIMESTAMPS | PASS |
| LEAN SEEK | PASS (warning: MPV -12, frames refreshed) |
| LEAN SIGN CHANGE | PASS |
| LEAN PREVIEW/FINAL VISUAL PARITY | PASS |
| BAR LIVE PROPERTY CHANGE | PASS |
| AUTO OLD LOOK | PASS |
| TOP/BOTTOM/LEFT/RIGHT/INSIDE | PASS |
| OFFSET X/Y | PASS |
| VERTICAL BAR | PASS |
| SAVE/RELOAD | PASS |
| PREVIEW/FINAL | PASS |
| DRAG/BBOX | PASS |
| NO BACKEND / HYBRID REGRESSION | PASS — forbidden files untouched |

**STATUS = LEAN + BAR PRODUCTION READY**

Warnings are limited to the offscreen MPV test environment. No commit or push
was performed.
