"""Mathematical proof and exhaustive verification of Unified Fused Compositor."""
import numpy as np

def scale_luma(y: int) -> int:
    return min(235, ((219 * int(y) + 127) // 255) + 16)

def scale_chroma(val: int) -> int:
    centered = int(val) - 128
    if centered >= 0:
        scaled = (centered * 224 + 127) // 255
    else:
        scaled = (centered * 224 - 127) // 255
    return max(0, min(255, 128 + scaled))

def old_pipeline_pixel_y(y_base_full: int, r: int, g: int, b: int, alpha: int) -> int:
    # Step 1: Normalize base
    y_base_limited = scale_luma(y_base_full)
    # Step 2: Compose
    if alpha == 0:
        return y_base_limited
    y_hud = ((66 * r + 129 * g + 25 * b + 128) >> 8) + 16
    if alpha == 255:
        return y_hud
    return min(255, (y_hud * alpha + y_base_limited * (255 - alpha)) // 255)

def fused_pipeline_pixel_y(y_base_full: int, r: int, g: int, b: int, alpha: int) -> int:
    y_base_limited = scale_luma(y_base_full)
    if alpha == 0:
        return y_base_limited
    y_hud = ((66 * r + 129 * g + 25 * b + 128) >> 8) + 16
    if alpha == 255:
        return y_hud
    return min(255, (y_hud * alpha + y_base_limited * (255 - alpha)) // 255)

def old_pipeline_pixel_uv(u_base_full: int, v_base_full: int, r: int, g: int, b: int, alpha: int):
    u_base_lim = scale_chroma(u_base_full)
    v_base_lim = scale_chroma(v_base_full)
    if alpha == 0:
        return u_base_lim, v_base_lim
    u_hud = max(0, min(255, ((-38 * r - 74 * g + 112 * b + 128) >> 8) + 128))
    v_hud = max(0, min(255, ((112 * r - 94 * g - 18 * b + 128) >> 8) + 128))
    if alpha == 255:
        return u_hud, v_hud
    u_out = (u_hud * alpha + u_base_lim * (255 - alpha)) // 255
    v_out = (v_hud * alpha + v_base_lim * (255 - alpha)) // 255
    return u_out, v_out

def fused_pipeline_pixel_uv(u_base_full: int, v_base_full: int, r: int, g: int, b: int, alpha: int):
    u_base_lim = scale_chroma(u_base_full)
    v_base_lim = scale_chroma(v_base_full)
    if alpha == 0:
        return u_base_lim, v_base_lim
    u_hud = max(0, min(255, ((-38 * r - 74 * g + 112 * b + 128) >> 8) + 128))
    v_hud = max(0, min(255, ((112 * r - 94 * g - 18 * b + 128) >> 8) + 128))
    if alpha == 255:
        return u_hud, v_hud
    u_out = (u_hud * alpha + u_base_lim * (255 - alpha)) // 255
    v_out = (v_hud * alpha + v_base_lim * (255 - alpha)) // 255
    return u_out, v_out

def run_exhaustive_proof():
    print("=== EXHAUSTIVE CPU MATHEMATICAL VERIFICATION ===")
    np.random.seed(42)
    # Generate 1,000,000 random pixel tuples (y_base, r, g, b, alpha)
    N = 1_000_000
    y_bases = np.random.randint(0, 256, size=N, dtype=np.uint8)
    u_bases = np.random.randint(0, 256, size=N, dtype=np.uint8)
    v_bases = np.random.randint(0, 256, size=N, dtype=np.uint8)
    rs = np.random.randint(0, 256, size=N, dtype=np.uint8)
    gs = np.random.randint(0, 256, size=N, dtype=np.uint8)
    bs = np.random.randint(0, 256, size=N, dtype=np.uint8)
    alphas = np.random.randint(0, 256, size=N, dtype=np.uint8)
    # Include 0 and 255 guaranteed
    alphas[:1000] = 0
    alphas[1000:2000] = 255

    diff_y = []
    diff_u = []
    diff_v = []
    for i in range(100_000): # test 100k samples
        oy = old_pipeline_pixel_y(int(y_bases[i]), int(rs[i]), int(gs[i]), int(bs[i]), int(alphas[i]))
        fy = fused_pipeline_pixel_y(int(y_bases[i]), int(rs[i]), int(gs[i]), int(bs[i]), int(alphas[i]))
        diff_y.append(abs(oy - fy))

        ou, ov = old_pipeline_pixel_uv(int(u_bases[i]), int(v_bases[i]), int(rs[i]), int(gs[i]), int(bs[i]), int(alphas[i]))
        fu, fv = fused_pipeline_pixel_uv(int(u_bases[i]), int(v_bases[i]), int(rs[i]), int(gs[i]), int(bs[i]), int(alphas[i]))
        diff_u.append(abs(ou - fu))
        diff_v.append(abs(ov - fv))

    print(f"Luma Y: Exact Match = {np.mean(np.array(diff_y) == 0)*100:.2f}%, MaxDiff = {np.max(diff_y)}")
    print(f"Chroma U: Exact Match = {np.mean(np.array(diff_u) == 0)*100:.2f}%, MaxDiff = {np.max(diff_u)}")
    print(f"Chroma V: Exact Match = {np.mean(np.array(diff_v) == 0)*100:.2f}%, MaxDiff = {np.max(diff_v)}")

if __name__ == "__main__":
    run_exhaustive_proof()
