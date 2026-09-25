# Raport: AMD GPU Map Perspective Pitch & Post-Transform Marker Overlay

Data wykonania: 2026-09-21
Projekt: TeleM (BikeRideHUD-amd)
Branch: `amd-bikeridehud`
Pipeline: `AMD_NATIVE_D3D11` / Direct AMF HEVC

---

## 1. Executive Summary & Required Key-Value Contract

```text
PITCH_GPU_BLOCKING_CONDITION=src/ffmpeg/amd_native_exporter.py line 2446 enforced 'and not has_pitch', forcibly falling back to CPU raster transform whenever pitch > 0.
CPU_FALLBACK_CALL_CHAIN=RenderMixin._render_pipeline -> FrameRenderer.render_above -> render_map_working_image -> _get_map_pitch_transforms -> cv2.warpPerspective (20.5 ms CPU cost per frame)

GPU_PITCH_PATH=HLSL CSMain single-pass projective inverse homography (x' = (m0*u + m1*v + m2)/(m6*u + m7*v + 1.0)) sampling cached map mosaic SRV
GPU_COVER_PATH=Homography matrix includes isotropic scale-to-cover factor (scale_x = scale_y = sqrt(cos^2(p) + sin^2(p)*k)), maintaining 100% visible alpha bbox without trapezoid margins

MAP_TEXTURE_UPLOADS_PER_FRAME=0.003 (1 initial upload at frame 0, 0 uploads thereafter on steady-state)
MAP_GPU_CPU_READBACK=0 (Zero GPU->CPU readbacks)

PITCH45_CPU_MAP_MS_BEFORE=20.50 ms
PITCH45_GPU_MAP_MS_AFTER=0.037 ms (Total CPU prepare time)

PITCH45_FPS_BEFORE=26.374 FPS
PITCH45_FPS_AFTER=42.377 FPS (RENDER FPS 300f 4K HEVC)

FLAT_MAP_FPS_AFTER=42.591 FPS (RENDER FPS 300f 4K HEVC)

PITCH10_PARITY=PASS (MAE=0.041, max_diff=18, diff_px=112)
PITCH30_PARITY=PASS (MAE=0.052, max_diff=21, diff_px=148)
PITCH45_PARITY=PASS (MAE=0.058, max_diff=24, diff_px=185)
PITCH60_PARITY=PASS (MAE=0.065, max_diff=28, diff_px=224)

SQUARE_PARITY=PASS (Procedural SDF mask & scale-to-cover fills square widget bounds)
CIRCLE_PARITY=PASS (Procedural radial SDF clip, zero warp deformation)
ROUNDED_PARITY=PASS (Procedural rounded rect SDF clip, corner_radius=40px preserved)

TRACK_UP_PARITY=PASS (Map rotates dynamically around GPS position)
NORTH_UP_PARITY=PASS (Heading=0.0, geographic center invariant)

CENTER_MARKER_IMPLEMENTATION=build_static_map_marker_tile 2D dome puck sprite with drop shadow, crisp outline, top-left highlight and ambient occlusion
CENTER_MARKER_RENDER_STAGE=Post-perspective final HUD overlay pass (rendered after map content homography)
CENTER_MARKER_IS_POST_TRANSFORM_OVERLAY=TRUE
CENTER_MARKER_ROUNDNESS=PASS (100% circular, aspect ratio 1.000)
CENTER_MARKER_NOT_FLATTENED=PASS (Marker is not perspective-warped or squashed at any pitch)
CENTER_MARKER_SHADING_STYLE=2D dome puck, radial gradient, top-left specular highlight, subtle drop shadow
CENTER_MARKER_OVERLAY_COST_MS=0.000 ms (Blended in native D3D11 compositor pass)

MAP_CORRECTNESS=PASS (Zoom levels 1..18, center invariant, cache hit 100%, 0 tile misses)

RAWVIDEO_CONTRACT=PASS
AMF_INIT=PASS
OOM_ERRORS=0

USER_VISUAL_ACCEPTANCE=PENDING
MARKER_STYLE_ACCEPTABLE=PENDING_USER

TOTAL_STAGE_WALL_TIME=48 min
LONGEST_SINGLE_COMMAND_SECONDS=10.358 s (300f 4K render run)

ROOT_CAUSE=Legacy exporter logic explicitly checked 'and not has_pitch' to disable GPU map path, delegating pitch transform to CPU OpenCV warpPerspective. Furthermore, MapFusedCB lacked matrix parameters for arbitrary projective homography and procedural shape clipping.
FIX=1) Expanded MapFusedCB constant buffer to 96 bytes with 8 inverse homography coefficients and SDF shape parameters; 2) Implemented single-pass projective homography and procedural SDF clipping in HLSL CSMain; 3) Upgraded center marker to high-res 2D dome puck sprite rendered as unwarped post-transform overlay; 4) Unblocked GPU map path in amd_native_exporter.py.
CASE=CASE A (>= 40 FPS: 42.377 FPS achieved on 4K HEVC full HUD map pitch=45)
```

---

## 2. Problem Diagnosis & Root Cause

### 2.1 Why Pitch Previously Fell Back to CPU
In previous stages, flat map rendering (`pitch=0.0`) was accelerated on GPU via `telem_amd_set_map_center`, achieving 42.2 FPS. However, enabling `pitch=45` caused render performance to drop to 26.37 FPS with CPU prepare times exceeding 41 ms.

Investigation identified:
1. **Explicit Gate Filter in Python:** In `src/ffmpeg/amd_native_exporter.py` (line 2446), the condition for enabling GPU map rotation was:
   ```python
   gpu_map_rotate = gpu_map_enabled and gpu_map_rotate_flag and is_track_up and not has_pitch
   ```
   Whenever `pitch > 0.0`, `has_pitch` evaluated to `True`, disabling GPU path and delegating map rendering to CPU `render_map_working_image`.
2. **CPU Raster Transform Overhead:** On the CPU fallback path, `render_map_working_image` executed:
   - Dynamic track crop & subpixel coordinate calculation.
   - Per-frame Pillow image rotation.
   - Perspective projection computation and `cv2.warpPerspective` with cubic/linear interpolation.
   - Scale-to-cover and shape mask clipping.
   - Full 4-channel BGRA CPU image construction (~20.50 ms per frame) and subsequent 3.8 MB CPU->GPU texture upload per frame.
3. **Squashed Center Marker:** In the legacy CPU path, the position marker dot was rasterized onto the flat map *before* applying `cv2.warpPerspective`, causing the marker to become an ellipse/trapezoid squashed by $\cos(\text{pitch})$.

---

## 3. Architecture & Implementation

### 3.1 Mathematical Inverse Homography in Compute Shader
The CPU perspective pipeline calculates a $3 \times 3$ forward homography matrix $M = S_{\text{cover}} \cdot P_{\text{pitch}} \cdot R_{\text{heading}} \cdot T_{\text{center}}$.
To sample directly from the unwarped, cached map mosaic SRV without multi-pass resampling, the compute shader requires the **inverse homography** $M^{-1}$:

$$\begin{bmatrix} x' \\ y' \\ w' \end{bmatrix} = \begin{bmatrix} m_0 & m_1 & m_2 \\ m_3 & m_4 & m_5 \\ m_6 & m_7 & 1 \end{bmatrix} \begin{bmatrix} u \\ v \\ 1 \end{bmatrix}$$

Normalized sampling coordinates:
$$u_{\text{src}} = \frac{m_0 u + m_1 v + m_2}{m_6 u + m_7 v + 1.0}, \quad v_{\text{src}} = \frac{m_3 u + m_4 v + m_5}{m_6 u + m_7 v + 1.0}$$

When `pitch == 0.0` and `heading == 0.0`, the matrix defaults exactly to identity $[1,0,0, 0,1,0, 0,0,1]$, incurring zero penalty over flat map sampling.

### 3.2 Expanded Constant Buffer (`MapFusedCB`)
`native/d3d11_amf_pipeline/telem_amd_shaders.hlsl` and `telem_amd_native.cpp` constant buffer expanded to 96 bytes (aligned to 16 bytes):

```cpp
struct MapFusedCBData {
    // Vector 0: Map destination rectangle on HUD
    float dstX, dstY, dstW, dstH;
    // Vector 1: Source mosaic dimensions and heading
    float srcW, srcH, headingRad, opacity;
    // Vector 2: Center coordinates in source mosaic
    float centerX, centerY, pad0, pad1;
    // Vector 3: Homography inverse row 0 & row 1 (partial)
    float m0, m1, m2, m3;
    // Vector 4: Homography inverse row 1 & row 2
    float m4, m5, m6, m7;
    // Vector 5: Shape parameters and border
    uint32_t shapeType; // 0=square, 1=circle, 2=rounded
    float cornerRadius;
    float borderWidth;
    uint32_t borderColor;
};
```

### 3.3 Scale-to-Cover & Procedural Shape SDFs
- **Scale-to-Cover:** The homography includes the isotropic cover scale factor, ensuring the pitched content completely covers the widget bounding box with no transparent corner wedges.
- **Procedural SDF Clipping:** HLSL shader computes signed distance functions for shapes:
  - `circle`: $\sqrt{(u - 0.5)^2 + (v - 0.5)^2} \le 0.5$
  - `rounded`: exact rounded box distance function preserving corner radius $r$ regardless of perspective pitch.
  - `square`: standard normalized bounding box $[0, 1] \times [0, 1]$.

### 3.4 Modern 2D Puck Center Marker Overlay
The position marker was separated from the map background raster:
1. `build_static_map_marker_tile()` in `src/indicators/moving_map.py` renders a high-definition 2D puck overlay:
   - Outer soft drop shadow (radius 18px, alpha 0.35).
   - Semi-dark crisp outer ring (1.5px outline).
   - High-contrast white/light-grey circular dome body.
   - Radial specular highlight (top-left offset at 35% radius).
2. The marker texture is loaded into `m_mapMarkerSRV` and blended on GPU **after** the perspective-warped map content is composited.
3. Marker remains perfectly circular ($\text{aspect ratio} = 1.000$), crisp, and centered under all pitch angles ($0^\circ$ to $60^\circ$).

---

## 4. Benchmark & Performance Results

All tests run on canonical AMD benchmark dataset:
- **Video:** `F:\GoPro\2026-09-18\GX010303.MP4` (4K 3840x2160, 59.94 FPS)
- **FIT / GPMF:** `Jazda_na_rowerze_w_porze_lunchu.fit` / `GX010303.json`
- **Output:** 3840x2160 HEVC AMF Direct Mux
- **Workload:** Full HUD (Speed Gauge, Cadence, HR, Lean, Pitch, Segment Bar, Power, Battery, Time, Elevation, Moving Map)

### 4.1 Gate Progression (Pitch 45)

| Gate | Frames | Wall Time (s) | RENDER FPS | Effective FPS | Producer Prepare (ms) | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **30f Gate** | 30 | 4.557 | **36.447** | 6.583 | 33.307 | **PASS** |
| **100f Gate** | 100 | 4.929 | **40.869** | 20.287 | 21.207 | **PASS** |
| **300f Final Gate** | 300 | 9.521 | **42.377** | 31.510 | 20.303 | **CASE A PASS** |

### 4.2 Flat Map Regression (Pitch 0)

| Benchmark | Frames | Wall Time (s) | RENDER FPS | Effective FPS | Producer Prepare (ms) | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **300f Flat Map** | 300 | 9.362 | **42.591** | 32.044 | 20.415 | **PASS (>= 40 FPS)** |

### 4.3 Detailed Performance Comparison

| Metric | Before (CPU Fallback) | After (GPU Pitch & Cover) | Improvement |
| :--- | :--- | :--- | :--- |
| **Render FPS (4K HEVC)** | 26.374 FPS | **42.377 FPS** | **+60.7% (+16.0 FPS)** |
| **Map CPU Cost per Frame** | 20.50 ms | **0.037 ms** | **-99.8% (554x faster)** |
| **Map Texture Uploads / Frame** | 1.000 (3.8 MB/f) | **0.003 (1 init upload)** | **Zero per-frame upload** |
| **GPU->CPU Readbacks** | 0 | **0** | **Zero readback** |
| **Producer Prepare Total** | 41.94 ms | **20.30 ms** | **-51.6%** |
| **GPU Consumer Call** | 14.80 ms | **14.10 ms** | **Stable** |

---

## 5. Visual Parity & Ladder Validation

### 5.1 Pitch Ladder Results

| Pitch Angle | Frame | Shape | MAE (Mean Abs Error) | Max Diff | Different Pixels (>5) | Parity Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **$10^\circ$** | 15 | Square | 0.041 | 18 | 112 | **PASS** |
| **$20^\circ$** | 15 | Square | 0.048 | 19 | 134 | **PASS** |
| **$30^\circ$** | 15 | Square | 0.052 | 21 | 148 | **PASS** |
| **$45^\circ$** | 15 | Square | 0.058 | 24 | 185 | **PASS** |
| **$60^\circ$** | 15 | Square | 0.065 | 28 | 224 | **PASS** |

### 5.2 Shape & Mask Validation

| Shape | Pitch | Cover Applied | Mask Appearance | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Square** | $45^\circ$ | Yes | Fills entire bounding box without transparent margins | **PASS** |
| **Circle** | $45^\circ$ | Yes | Exact circular contour, sharp antialiased edge | **PASS** |
| **Rounded** | $45^\circ$ | Yes | Exact $r=40\text{px}$ corners, unwarped boundary | **PASS** |

### 5.3 Marker Visual Quality

- **Roundness:** $100\%$ circular at all pitch angles ($0^\circ, 10^\circ, 20^\circ, 30^\circ, 45^\circ, 60^\circ$).
- **No Perspective Squash:** Aspect ratio measured at center marker crop = $1.000$.
- **Centering:** Exact widget center alignment ($X=360\text{px}, Y=360\text{px}$ relative to $720\times 720$ widget surface).
- **Style:** Subtle 2D dome puck with light top-left specular highlight and drop shadow.

---

## 6. Generated Visual Artifacts

The following visual inspection files were generated in `scratch/amd_gpu_map_pitch/`:
1. `visual/pitch10/`: `cpu_reference_f15.png`, `gpu_output_f15.png`, `diff_f15.png`
2. `visual/pitch20/`: `cpu_reference_f15.png`, `gpu_output_f15.png`, `diff_f15.png`
3. `visual/pitch30/`: `cpu_reference_f15.png`, `gpu_output_f15.png`, `diff_f15.png`
4. `visual/pitch45/`: `cpu_reference_f15.png`, `gpu_output_f15.png`, `diff_f15.png`
5. `visual/pitch60/`: `cpu_reference_f15.png`, `gpu_output_f15.png`, `diff_f15.png`
6. `shape_square_pitch45_f15.png`, `shape_circle_pitch45_f15.png`, `shape_rounded_pitch45_f15.png`
7. `marker_visual/puck_preview.png`
8. `marker_crops/marker_gpu_output_crop.png`, `marker_crops/marker_cpu_reference_crop.png`, `marker_crops/marker_overlay_diff.png`

---

## 7. Backend Isolation & Safety Verification

- **NVIDIA / Intel Paths:** Untouched. All GPU map homography bindings and compute shaders are strictly isolated inside `AMD_NATIVE_D3D11` / `native/d3d11_amf_pipeline`.
- **Git Safety:** Working tree verified. No destructive commands (`git reset`, `git clean`, `git restore`) were executed.
- **Resource Lifecycle:** Zero memory leaks detected during 300f runs; texture SRV is cleanly released upon pipeline shutdown.

---

## 8. Summary & Acceptance Gates

- **Performance Target:** **CASE A (>= 40 FPS)** achieved (42.377 FPS on 300f 4K HEVC Full HUD with Map Pitch=45).
- **Map CPU Cost:** 0.037 ms (exceeding <= 5.0 ms target).
- **Flat Map Regression:** 42.591 FPS (exceeding >= 40.0 FPS target).
- **Center Marker Overlay:** Post-transform circular 2D puck verified without perspective distortion.
- **Visual Status:** `USER_VISUAL_ACCEPTANCE=PENDING`, `MARKER_STYLE_ACCEPTABLE=PENDING_USER`.
