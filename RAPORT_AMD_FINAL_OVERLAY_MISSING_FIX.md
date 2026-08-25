# Raport AMD — brak overlay w finalnym MP4

## Wynik

Regresja została odtworzona i naprawiona. Przy konfiguracji
`CPU_REFERENCE + GPU_HUD_D3D11VA` finalny encoder otrzymywał powierzchnię
`pOutNV12Tex`, ale bez naniesionego HUD. Po poprawce CPU/reference ponownie
generuje pełną klatkę video+HUD przed AMF.

## Gdzie rozdzielały się preview i final

Preview korzystał z gotowego `composed_img`, natomiast final AMD przechodził
przez `telem_amd_process_frame()`. W native compositorze warunek GPU HUD jest:

```text
hudEnabled && hudMode == GPU_HUD && enable_hud
```

W trybie `CPU_REFERENCE` był więc wyłączony. Jednocześnie przy D3D11VA nie
wykonywał się CPU `BlendRGBAToNV12`, bo ten blend jest związany z uploadem
CPU-NV12. W efekcie encoder dostawał `pOutNV12Tex`, lecz ta powierzchnia była
bazowym video bez overlay.

W produkcyjnym `GPU_HUD + D3D11VA` handoff jest prawidłowy:

```text
base texture != VP output texture
VP output texture == AMF input texture
```

## Checkpointy frame 30

| Etap | Plik | Wymiary | Wynik |
|---|---|---:|---|
| A — HUD_RGBA | `01_python_hud_30.png` | 1280×720 RGBA | poprawny HUD; alpha bbox `(21,22)-(127,373)` |
| A — backing buffer | `02_buffer_sent_to_dll.png` | 1280×720 RGBA | zgodny z A |
| B — final composite przed AMF | `D_after_gpu_hud.png` | 1280×720 RGBA | video + pełny HUD, alpha opaque |
| C — tekstura wejściowa AMF | `E_amf_input.png` | 1280×720 RGBA | video + pełny HUD, identyczne z B |
| F — zapisany MP4 | `F_final_mp4.png` | 1280×720 RGB | HUD widoczny |

`D_after_gpu_hud.png` i `E_amf_input.png` mają identyczny obraz
(`difference bbox = None`).

## Minimalna naprawa

W `src/ffmpeg/amd_native_exporter.py`:

- `CPU_REFERENCE` z żądanym D3D11VA jest automatycznie kierowany do
  istniejącego `GPU_HUD_CPU_DECODE_REFERENCE`, aby wykonać CPU
  `BlendRGBAToNV12` przed AMF;
- `CPU_REFERENCE` wymusza istniejące CPU warianty map/chart/gauge, aby split
  GPU nie pozostawał poza finalną klatką, gdy GPU HUD jest wyłączony;
- nie zmieniono rendererów wskaźników, telemetry, preview ani DLL/native
  NVIDIA.

## Weryfikacja

- test jednostkowy routingu: `2 passed`;
- CPU/reference A/B przed poprawką: `60` klatek, `BlendRGBAToNV12=0`, MP4 bez HUD;
- CPU/reference po poprawce: `60/60` klatek, `BlendRGBAToNV12=60`, pełny HUD;
- AMD GPU smoke po poprawce: 5 s, `150/150` klatek, `150/150` AMF submit/output,
  `150/150` GPU HUD, finalny MP4 z overlay;
- diagnostyczny eksport frame 30: `VP output == AMF input`.

NVIDIA nie została zmieniona.
