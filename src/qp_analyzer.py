"""Analiza QP (quantization parameter) z zakodowanego bitstreamu.

Niezależne narzędzie diagnostyczne dla TeleM. Demultipleksuje MP4 przez FFmpeg
(``-c copy``), a następnie parsuje nagłówki slice HEVC/H.264 bez dekodowania
obrazu do RGB i bez ingerencji w pipeline GPU/renderingu.

WAŻNE O DOKŁADNOŚCI:
- HEVC: dokładne block/CTU QP jest możliwe z samych nagłówków slice WYŁĄCZNIE
  wtedy, gdy ``cu_qp_delta_enabled_flag == 0`` dla używanych PPS. Wtedy każdy
  CU w danym slice ma ``QpY = SliceQpY`` i histogram ważony liczbą CTU jest
  dokładny. Gdy flaga == 1, per-CU delty QP są kodowane w CABAC i ten lekki
  parser ich nie dekoduje; wynik jest wtedy jawnie oznaczony ``SLICE_ONLY``.
- H.264: ten moduł parsuje slice QP i waży go zakresem makrobloków. Nie dekoduje
  ``mb_qp_delta`` z CABAC/CAVLC, więc wynik H.264 jest oznaczony ``SLICE_ONLY``.
  FFmpeg ma osobny eksport per-block enc params dla H.264, ale nie dla HEVC;
  ta implementacja nie wymaga dodatkowej biblioteki libavcodec.

DOMENA RAPORTOWANEGO QP:
- HEVC: raportujemy natywne ``SliceQpY = 26 + init_qp_minus26 + slice_qp_delta``
  w domenie używanej przez enkodery (typowo 0..51; spec dla >8 bit dopuszcza też wartości ujemne). Dla >8 bit istnieje
  ``QpBdOffsetY`` używany wewnętrznie przez proces kwantyzacji, ale NIE dodajemy
  go do wartości prezentowanej użytkownikowi.
- H.264: analogicznie raportujemy natywne ``QpY`` z nagłówka slice.

Przepływ:
    MP4 --ffmpeg(demux, -c copy)--> Annex B --parser--> histogram QP
"""

from __future__ import annotations

import json
import math
import statistics
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Optional

from src.video_helpers import find_executable, find_local_tool, parse_fps


# ═════════════════════════════════════════════════════════════════════════
# Narzędzia bitowe / RBSP / Annex B
# ═════════════════════════════════════════════════════════════════════════

class BitReader:
    """Czytnik bitów po RBSP (po usunięciu emulation prevention)."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0  # pozycja bitowa

    def read(self, n: int) -> int:
        val = 0
        for _ in range(n):
            if self.pos >> 3 >= len(self.data):
                raise EOFError("koniec RBSP")
            byte = self.data[self.pos >> 3]
            val = (val << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return val

    def bit(self) -> int:
        return self.read(1)

    def ue(self) -> int:
        """Exp-Golomb unsigned."""
        z = 0
        while self.bit() == 0:
            z += 1
            if z > 31:
                raise ValueError("ue(): zbyt długa sekwencja zer")
        return (1 << z) - 1 + (self.read(z) if z else 0)

    def se(self) -> int:
        """Exp-Golomb signed."""
        k = self.ue()
        return (k + 1) // 2 if k & 1 else -(k // 2)

    def skip(self, n: int) -> None:
        self.pos += n


def rbsp(data: bytes) -> bytes:
    """Usuń bajty emulation prevention (00 00 03 → 00 00) z NAL payload."""
    out = bytearray()
    zeros = 0
    for b in data:
        if zeros >= 2 and b == 3:
            zeros = 0
            continue
        out.append(b)
        if b == 0:
            zeros += 1
        else:
            zeros = 0
    return bytes(out)


def iter_annexb_nalu(stream) -> Iterator[bytes]:
    """Generator NAL units (raw bytes włącznie z headerem) z Annex B."""
    buf = b""
    in_nal = False
    while True:
        chunk = stream.read(1 << 20)  # 1 MB
        if not chunk:
            break
        buf += chunk
        # przeszukaj bufory w poszukiwaniu start code'ów
        while True:
            sc = _find_start_code(buf)
            if sc < 0:
                break
            # buf[:sc] to dane NAL (albo puste), buf[sc:] zaczyna się od start code
            # znajdź koniec start code
            sc_end = _start_code_end(buf, sc)
            if sc_end < 0:
                break
            nxt = _find_start_code(buf, sc_end)
            if nxt < 0:
                # nie mamy jeszcze pełnego NAL — zachowaj od sc
                buf = buf[sc:]
                break
            nalu = buf[sc_end:nxt]
            if len(nalu) > 0:
                yield nalu
            buf = buf[nxt:]
            # jeśli został tylko start code na końcu, usuń
            if len(buf) >= 3 and buf[:3] == b"\x00\x00\x01":
                pass
    # ostatni NAL do końca strumienia
    sc = _find_start_code(buf)
    if sc >= 0:
        sc_end = _start_code_end(buf, sc)
        if sc_end >= 0:
            nalu = buf[sc_end:]
            if len(nalu) > 0:
                yield nalu


def _find_start_code(buf: bytes, start: int = 0) -> int:
    """Znajdź najwcześniejszy start code (00 00 01 lub 00 00 00 01).

    Używa bytes.find() (C-speed) — dla plików 4K skanowanie bajt-po-bajcie
    w Pythonie byłoby ~10× wolniejsze.
    """
    i4 = buf.find(b"\x00\x00\x00\x01", start)
    i3 = buf.find(b"\x00\x00\x01", start)
    if i4 < 0:
        return i3
    if i3 < 0:
        return i4
    return min(i4, i3)


def _start_code_end(buf: bytes, sc: int) -> int:
    n = len(buf)
    if sc + 3 <= n and buf[sc] == 0 and buf[sc + 1] == 0 and buf[sc + 2] == 1:
        return sc + 3
    if sc + 4 <= n and buf[sc] == 0 and buf[sc + 1] == 0 and buf[sc + 2] == 0 and buf[sc + 3] == 1:
        return sc + 4
    return -1


# ═════════════════════════════════════════════════════════════════════════
# Wyniki
# ═════════════════════════════════════════════════════════════════════════

@dataclass
class QPResult:
    codec: str
    bit_depth: int
    frames: int
    samples: int
    avg: Optional[float]
    median: Optional[float]
    minimum: Optional[int]
    maximum: Optional[int]
    elapsed_s: float
    histogram: dict[int, int] = field(default_factory=dict)
    qp_domain_note: str = ""
    error: Optional[str] = None

    # EXACT       - histogram odpowiada rzeczywistemu QP bloków w obsługiwanej
    #               domenie (HEVC tylko gdy cu_qp_delta_enabled_flag == 0).
    # SLICE_ONLY  - statystyki dotyczą bazowego QP slice; wewnątrz slice
    #               mogą istnieć per-CU/per-MB delty, których tu nie dekodujemy.
    accuracy: str = "UNKNOWN"
    exact_block_qp: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None and self.samples > 0 and self.avg is not None


# ═════════════════════════════════════════════════════════════════════════
# SPS / PPS / Slice — HEVC
# ═════════════════════════════════════════════════════════════════════════

# HEVC NAL unit types (nal_unit_type = (byte >> 1) & 0x3F)
HEVC_NAL_TRAIL_N = 0
HEVC_NAL_TRAIL_R = 1
HEVC_NAL_TSA_N = 2
HEVC_NAL_TSA_R = 3
HEVC_NAL_STSA_N = 4
HEVC_NAL_STSA_R = 5
HEVC_NAL_RADL_N = 6
HEVC_NAL_RADL_R = 7
HEVC_NAL_RASL_N = 8
HEVC_NAL_RASL_R = 9
HEVC_NAL_BLA_W_LP = 16
HEVC_NAL_BLA_W_RADL = 17
HEVC_NAL_BLA_N_LP = 18
HEVC_NAL_IDR_W_RADL = 19
HEVC_NAL_IDR_N_LP = 20
HEVC_NAL_CRA_NUT = 21
HEVC_NAL_VPS = 32
HEVC_NAL_SPS = 33
HEVC_NAL_PPS = 34


def _is_vcl(nal_type: int) -> bool:
    return 0 <= nal_type <= 31


def _skip_hevc_profile_tier_level(br: BitReader, max_sub_layers_minus1: int) -> None:
    """Pomiń profile_tier_level() dla typowych Main/Main10 strumieni HEVC.

    TeleM używa tego wyłącznie, aby dojść do pól SPS potrzebnych do QP. GoPro
    zapisuje Main/Main10 bez egzotycznych rozszerzeń profilu.
    """
    # general_profile_space/tier/profile_idc + compatibility + constraints + level
    br.skip(2 + 1 + 5 + 32 + 4 + 44 + 8)

    profile_present: list[int] = []
    level_present: list[int] = []
    for _ in range(max_sub_layers_minus1):
        profile_present.append(br.bit())
        level_present.append(br.bit())

    if max_sub_layers_minus1 > 0:
        # reserved_zero_2bits dla brakujących sub-layers do 8
        for _ in range(max_sub_layers_minus1, 8):
            br.skip(2)

    for i in range(max_sub_layers_minus1):
        if profile_present[i]:
            br.skip(2 + 1 + 5 + 32 + 4 + 44)
        if level_present[i]:
            br.skip(8)


def _parse_hevc_sps(data: bytes) -> dict:
    br = BitReader(rbsp(data))
    br.skip(4)                       # sps_video_parameter_set_id
    max_sub = br.read(3)             # sps_max_sub_layers_minus1
    br.skip(1)                       # sps_temporal_id_nesting_flag
    _skip_hevc_profile_tier_level(br, max_sub)

    sps_id = br.ue()
    chroma = br.ue()
    separate_colour_plane = 0
    if chroma == 3:
        separate_colour_plane = br.bit()

    pic_w = br.ue()
    pic_h = br.ue()
    if br.bit():                     # conformance_window_flag
        for _ in range(4):
            br.ue()

    bit_depth = br.ue() + 8          # bit_depth_luma_minus8
    br.ue()                          # bit_depth_chroma_minus8
    log2_poc_lsb = br.ue() + 4

    ordering = br.bit()              # sps_sub_layer_ordering_info_present_flag
    start_layer = 0 if ordering else max_sub
    for _ in range(start_layer, max_sub + 1):
        br.ue(); br.ue(); br.ue()

    min_cb = br.ue()                 # log2_min_luma_coding_block_size_minus3
    diff_cb = br.ue()                # log2_diff_max_min_luma_coding_block_size
    ctb_size = 1 << (min_cb + 3 + diff_cb)

    br.ue()                          # log2_min_luma_transform_block_size_minus2
    br.ue()                          # log2_diff_max_min_luma_transform_block_size
    br.ue()                          # max_transform_hierarchy_depth_inter
    br.ue()                          # max_transform_hierarchy_depth_intra

    if br.bit():                     # scaling_list_enabled_flag
        if br.bit():                 # sps_scaling_list_data_present_flag
            _skip_hevc_scaling_list(br)

    br.bit()                         # amp_enabled_flag
    sao_enabled = br.bit()           # sample_adaptive_offset_enabled_flag
    pcm_enabled = br.bit()
    if pcm_enabled:
        br.skip(4 + 4)               # pcm_sample_bit_depth_*_minus1
        br.ue(); br.ue()
        br.bit()                     # pcm_loop_filter_disabled_flag

    num_st_rps = br.ue()
    rps_delta_pocs: list[int] = []
    rps_used_by_curr: list[int] = []
    for i in range(num_st_rps):
        n_delta, n_used = _parse_hevc_st_ref_pic_set(
            br, i, num_st_rps, rps_delta_pocs
        )
        rps_delta_pocs.append(n_delta)
        rps_used_by_curr.append(n_used)

    long_term_present = br.bit()
    num_lt = 0
    lt_used_by_curr: list[int] = []
    if long_term_present:
        num_lt = br.ue()             # num_long_term_ref_pics_sps
        for _ in range(num_lt):
            br.skip(log2_poc_lsb)
            lt_used_by_curr.append(br.bit())

    temporal_mvp = br.bit()
    br.bit()                         # strong_intra_smoothing_enabled_flag

    # Dalsza część SPS (VUI/extensions) nie wpływa na pola wymagane do parsowania
    # slice_qp_delta. Nie próbujemy jej "na siłę" pomijać — to eliminuje ryzyko
    # rozjechania parsera na rozbudowanych HRD/VUI.
    return {
        "sps_id": sps_id,
        "width": pic_w,
        "height": pic_h,
        "bit_depth": bit_depth,
        "ctb_size": ctb_size,
        "chroma_format_idc": chroma,
        "separate_colour_plane": separate_colour_plane,
        "log2_poc_lsb": log2_poc_lsb,
        "sao_enabled": sao_enabled,
        "num_st_rps": num_st_rps,
        "rps_delta_pocs": rps_delta_pocs,
        "rps_used_by_curr": rps_used_by_curr,
        "long_term_present": long_term_present,
        "num_lt": num_lt,
        "lt_used_by_curr": lt_used_by_curr,
        "temporal_mvp": temporal_mvp,
    }


def _parse_hevc_st_ref_pic_set(br: BitReader, idx: int, num_sets: int,
                               rps_delta_pocs: list[int]) -> tuple[int, int]:
    """Pomiń short_term_ref_pic_set().

    Zwraca ``(NumDeltaPocs, NumUsedByCurrPic)``. Pierwsza wartość jest potrzebna
    do predykcji kolejnego RPS, druga do NumPicTotalCurr w slice header.
    """
    inter_pred = br.bit() if idx != 0 else 0
    if inter_pred:
        delta_idx_minus1 = br.ue() if idx == num_sets else 0
        br.bit()                    # delta_rps_sign
        br.ue()                     # abs_delta_rps_minus1

        ref_idx = idx - (delta_idx_minus1 + 1)
        if ref_idx < 0 or ref_idx >= len(rps_delta_pocs):
            raise ValueError("Nieprawidłowy RefRpsIdx w HEVC RPS")
        num_ref = rps_delta_pocs[ref_idx]

        n_delta = 0
        n_used = 0
        # j = 0 .. NumDeltaPocs[RefRpsIdx] (włącznie)
        for _ in range(num_ref + 1):
            used = br.bit()
            use_delta = 1 if used else br.bit()
            if used:
                n_used += 1
            if used or use_delta:
                n_delta += 1
        return n_delta, n_used

    num_neg = br.ue()
    num_pos = br.ue()
    n_used = 0
    for _ in range(num_neg):
        br.ue()
        n_used += br.bit()
    for _ in range(num_pos):
        br.ue()
        n_used += br.bit()
    return num_neg + num_pos, n_used


def _skip_hevc_scaling_list(br: BitReader) -> None:
    for size_id in range(4):
        for matrix_id in range(6):
            if br.bit():             # scaling_list_pred_mode_flag
                br.ue()              # scaling_list_pred_matrix_id_delta
            else:
                coef_num = min(64, 1 << (4 + (size_id << 1)))
                if size_id > 1:
                    br.se()          # scaling_list_dc_coef_minus8
                for _ in range(coef_num):
                    br.se()          # scaling_list_delta_coef


def _skip_hevc_vui(br: BitReader) -> None:
    # vui_parameters() — pomijamy, nie potrzebne do QP
    # aspect_ratio_info_present
    if br.bit():
        if br.read(8) == 255:
            br.skip(32)
    if br.bit():                     # overscan_info_present
        br.bit()
    if br.bit():                     # video_signal_type_present
        br.skip(3 + 1)
        if br.bit():                 # colour_description_present
            br.skip(24)
    if br.bit():                     # chroma_loc_info_present
        br.ue(); br.ue()
    br.bit()                         # neutral_chroma_indication_flag
    br.bit()                         # field_seq_flag
    br.bit()                         # frame_field_info_present_flag
    if br.bit():                     # default_display_window_flag
        for _ in range(4):
            br.ue()
    if br.bit():                     # vui_timing_info_present_flag
        br.skip(32 + 32)
        if br.bit():                 # vui_poc_proportional_to_timing_flag
            br.ue()                  # vui_num_ticks_poc_diff_one_minus1
        if br.bit():                 # vui_hrd_parameters_present_flag
            _skip_hevc_hrd(br)
    if br.bit():                     # bitstream_restriction_flag
        br.bit()                     # tiles_fixed_structure_flag
        br.bit()                     # motion_vectors_over_pic_boundaries_flag
        br.bit()                     # restricted_ref_pic_lists_flag
        br.ue()                      # min_spatial_segmentation_idc
        br.ue()                      # max_bytes_per_pic_denom
        br.ue()                      # max_bits_per_min_cu_denom
        br.ue()                      # log2_max_mv_length_horizontal
        br.ue()                      # log2_max_mv_length_vertical


def _skip_hevc_hrd(br: BitReader) -> None:
    br.bit()                         # nal_hrd_parameters_present_flag
    br.bit()                         # vcl_hrd_parameters_present_flag
    if br.bit():                     # sub_pic_hrd_params_present_flag
        br.skip(8 + 1 + 4 + 4)
    if br.bit():                     # hrd_parameters_present_flag
        br.skip(8 + 8 + 8 + 8 + 8)   # uprzednio zdefiniowane wartości — przybliżone
    # dokładne pomijanie HRD: cpb_cnt_minus1, bit_rate_scale, cpb_size_scale,
    # i dla każdej sub-layer: fixed_pic_rate, elemental_duration, low_delay, cpb
    br.skip(1 + 4 + 4 + 4)


def _parse_hevc_pps(data: bytes) -> dict:
    br = BitReader(rbsp(data))
    pps_id = br.ue()
    sps_id = br.ue()
    dep = br.bit()                   # dependent_slice_segments_enabled_flag
    out_flag = br.bit()              # output_flag_present_flag
    extra = br.read(3)               # num_extra_slice_header_bits
    br.bit()                         # sign_data_hiding_enabled_flag
    cabac_init = br.bit()            # cabac_init_present_flag
    num_ref_l0 = br.ue() + 1         # num_ref_idx_l0_default_active_minus1
    num_ref_l1 = br.ue() + 1
    init_qp = br.se()                # init_qp_minus26
    br.bit()                         # constrained_intra_pred_flag
    br.bit()                         # transform_skip_enabled_flag
    cu_qp_delta = br.bit()           # cu_qp_delta_enabled_flag
    if cu_qp_delta:
        br.ue()                      # diff_cu_qp_delta_depth
    br.se()                          # pps_cb_qp_offset
    br.se()                          # pps_cr_qp_offset
    br.bit()                         # pps_slice_chroma_qp_offsets_present_flag
    weighted_pred = br.bit()         # weighted_pred_flag
    weighted_bipred = br.bit()       # weighted_bipred_flag
    br.bit()                         # transquant_bypass_enabled_flag
    tiles = br.bit()                 # tiles_enabled_flag
    ecs = br.bit()                   # entropy_coding_sync_enabled_flag
    if tiles:
        num_cols = br.ue()
        num_rows = br.ue()
        if br.bit():                 # uniform_spacing_flag
            pass
        else:
            for _ in range(num_cols):
                br.ue()
            for _ in range(num_rows):
                br.ue()
        br.bit()                     # loop_filter_across_tiles_enabled_flag
    br.bit()                         # pps_loop_filter_across_slices_enabled_flag
    deblock_ctrl = br.bit()          # deblocking_filter_control_present_flag
    if deblock_ctrl:
        br.bit()                     # deblocking_filter_override_enabled_flag
        disabled = br.bit()          # pps_deblocking_filter_disabled_flag
        if not disabled:
            br.se()                  # pps_beta_offset_div2
            br.se()                  # pps_tc_offset_div2
    if br.bit():                     # pps_scaling_list_data_present_flag
        _skip_hevc_scaling_list(br)
    lists_mod = br.bit()             # lists_modification_present_flag
    br.ue()                          # log2_parallel_merge_level_minus2
    br.bit()                         # slice_segment_header_extension_present_flag
    br.bit()                         # pps_extension_present_flag
    return {
        "pps_id": pps_id,
        "sps_id": sps_id,
        "dependent_slice_segments_enabled": dep,
        "output_flag_present": out_flag,
        "num_extra_slice_header_bits": extra,
        "cabac_init_present": cabac_init,
        "init_qp_minus26": init_qp,
        "cu_qp_delta_enabled": cu_qp_delta,
        "num_ref_idx_l0": num_ref_l0,
        "num_ref_idx_l1": num_ref_l1,
        "weighted_pred": weighted_pred,
        "weighted_bipred": weighted_bipred,
        "lists_modification": lists_mod,
        "tiles_enabled": tiles,
        "entropy_coding_sync_enabled": ecs,
    }


# ── HEVC slice segment header ─────────────────────────────────────────────

# NAL unit types bez referencji (nal_ref_idc == 0):
# TRAIL_N, TSA_N, STSA_N, RADL_N, RASL_N
_HEVC_NON_REF = {0, 2, 4, 6, 8}


def _hevc_nal_ref_idc(nal_type: int) -> int:
    """nal_ref_idc dla HEVC (wyprowadzany z typu NAL, H.265 7.4.2.2).

    Typy *_N (parzyste 0/2/4/6/8) to non-reference → 0;
    wszystkie pozostałe VCL (w tym *_R i IRAP) → 1.
    """
    return 0 if nal_type in _HEVC_NON_REF else 1


def _hevc_ctus_bits(sps: dict) -> int:
    num_ctus = _num_ctus(sps)
    return 0 if num_ctus <= 1 else math.ceil(math.log2(num_ctus))


def _peek_hevc_slice_pps_id(data: bytes, nal_type: int) -> tuple[bool, int]:
    """Odczytaj tylko first_slice_segment_in_pic_flag i PPS id."""
    br = BitReader(rbsp(data))
    first = bool(br.bit())
    if first and 16 <= nal_type <= 23:
        br.bit()                     # no_output_of_prior_pics_flag
    return first, br.ue()


def _parse_hevc_slice(data: bytes, nal_type: int, sps: dict, pps: dict,
                      prev_qp_y: int | None) -> dict:
    """Parsuj część slice_segment_header() do ``slice_qp_delta``.

    Nie dotykamy danych CABAC po nagłówku slice. Zwracany ``slice_qp_y`` jest
    bazowym QP slice w natywnej domenie encoderów.
    """
    br = BitReader(rbsp(data))
    first = bool(br.bit())
    if first and 16 <= nal_type <= 23:
        br.bit()                     # no_output_of_prior_pics_flag
    pps_id = br.ue()
    if pps_id != pps.get("pps_id"):
        raise ValueError("HEVC slice używa innego PPS niż przekazany do parsera")

    seg_address = 0
    dependent = False
    if not first:
        if pps["dependent_slice_segments_enabled"]:
            dependent = bool(br.bit())
        bits = _hevc_ctus_bits(sps)
        seg_address = br.read(bits) if bits else 0

    if dependent:
        return {
            "first": first, "pps_id": pps_id, "address": seg_address,
            "dependent": True, "slice_type": None, "slice_qp_y": prev_qp_y,
        }

    for _ in range(pps["num_extra_slice_header_bits"]):
        br.bit()

    slice_type = br.ue()             # 0=B, 1=P, 2=I
    if slice_type > 2:
        raise ValueError(f"Nieprawidłowy HEVC slice_type={slice_type}")

    if pps["output_flag_present"]:
        br.bit()
    if sps.get("separate_colour_plane"):
        br.skip(2)                   # colour_plane_id

    num_poc_total_curr = 0
    slice_temporal_mvp_enabled = False

    if nal_type not in (HEVC_NAL_IDR_W_RADL, HEVC_NAL_IDR_N_LP):
        br.skip(sps["log2_poc_lsb"])

        num_st_rps = sps["num_st_rps"]
        st_sps = br.bit()             # short_term_ref_pic_set_sps_flag
        if st_sps and num_st_rps == 0:
            raise ValueError("HEVC short_term_ref_pic_set_sps_flag=1 bez SPS RPS")
        if not st_sps:
            _n_delta, n_used = _parse_hevc_st_ref_pic_set(
                br, num_st_rps, num_st_rps, sps["rps_delta_pocs"]
            )
            num_poc_total_curr += n_used
        else:
            if num_st_rps > 1:
                idx_bits = math.ceil(math.log2(num_st_rps))
                st_idx = br.read(idx_bits)
            else:
                st_idx = 0
            if st_idx >= num_st_rps:
                raise ValueError("HEVC short_term_ref_pic_set_idx poza zakresem")
            used = sps.get("rps_used_by_curr", [])
            if st_idx < len(used):
                num_poc_total_curr += used[st_idx]

        if sps["long_term_present"]:
            num_long_term_sps = br.ue() if sps["num_lt"] > 0 else 0
            num_long_term_pics = br.ue()
            if num_long_term_sps > sps["num_lt"]:
                raise ValueError("HEVC num_long_term_sps poza zakresem SPS")

            lt_used = sps.get("lt_used_by_curr", [])
            for i in range(num_long_term_sps + num_long_term_pics):
                if i < num_long_term_sps:
                    if sps["num_lt"] > 1:
                        idx_bits = math.ceil(math.log2(sps["num_lt"]))
                        lt_idx_sps = br.read(idx_bits)
                    else:
                        lt_idx_sps = 0
                    if lt_idx_sps < len(lt_used) and lt_used[lt_idx_sps]:
                        num_poc_total_curr += 1
                else:
                    br.skip(sps["log2_poc_lsb"])  # poc_lsb_lt
                    if br.bit():                  # used_by_curr_pic_lt_flag
                        num_poc_total_curr += 1

                if br.bit():                      # delta_poc_msb_present_flag
                    br.ue()                       # delta_poc_msb_cycle_lt

        if sps["temporal_mvp"]:
            slice_temporal_mvp_enabled = bool(br.bit())

    if sps["sao_enabled"]:
        br.bit()                                  # slice_sao_luma_flag
        if sps["chroma_format_idc"] != 0:
            br.bit()                              # slice_sao_chroma_flag

    num_ref_l0 = pps["num_ref_idx_l0"]
    num_ref_l1 = pps["num_ref_idx_l1"]

    if slice_type in (0, 1):                      # B/P
        if br.bit():                              # num_ref_idx_active_override_flag
            num_ref_l0 = br.ue() + 1
            if slice_type == 0:
                num_ref_l1 = br.ue() + 1

        if pps["lists_modification"] and num_poc_total_curr > 1:
            _skip_hevc_ref_pic_lists_modification(
                br, slice_type, num_poc_total_curr, num_ref_l0, num_ref_l1
            )

        if slice_type == 0:
            br.bit()                              # mvd_l1_zero_flag
        if pps["cabac_init_present"]:
            br.bit()                              # cabac_init_flag

        if slice_temporal_mvp_enabled:
            collocated_l0 = br.bit() if slice_type == 0 else 1
            if ((collocated_l0 and num_ref_l0 > 1) or
                    (not collocated_l0 and num_ref_l1 > 1)):
                br.ue()                           # collocated_ref_idx

        if ((pps["weighted_pred"] and slice_type == 1) or
                (pps["weighted_bipred"] and slice_type == 0)):
            _parse_hevc_pred_weight_table(
                br, slice_type, num_ref_l0, num_ref_l1,
                sps["chroma_format_idc"] != 0
            )

        # five_minus_max_num_merge_cand jest obecne dla slice P/B.
        br.ue()

    qp_delta = br.se()
    slice_qp_y = 26 + pps["init_qp_minus26"] + qp_delta

    return {
        "first": first, "pps_id": pps_id, "address": seg_address,
        "dependent": False, "slice_type": slice_type,
        "slice_qp_y": slice_qp_y,
    }


def _bits_for(n: int) -> int:
    return max(1, math.ceil(math.log2(max(n, 2))))


def _skip_hevc_ref_pic_lists_modification(
    br: BitReader, slice_type: int, num_pic_total_curr: int,
    num_ref_l0: int, num_ref_l1: int,
) -> None:
    """Pomiń ref_pic_lists_modification() zgodnie z aktywną liczbą referencji."""
    if num_pic_total_curr <= 1 or slice_type == 2:
        return
    bits = math.ceil(math.log2(num_pic_total_curr))

    if br.bit():                      # ref_pic_list_modification_flag_l0
        for _ in range(num_ref_l0):
            br.skip(bits)

    if slice_type == 0 and br.bit():  # ref_pic_list_modification_flag_l1
        for _ in range(num_ref_l1):
            br.skip(bits)


def _parse_hevc_pred_weight_table(br: BitReader, slice_type: int, num_ref_l0: int,
                                  num_ref_l1: int, has_chroma: bool) -> None:
    br.ue()                           # luma_log2_weight_denom
    if has_chroma:
        br.se()                       # delta_chroma_log2_weight_denom

    _hevc_pwt_list(br, num_ref_l0, has_chroma)
    if slice_type == 0:
        _hevc_pwt_list(br, num_ref_l1, has_chroma)


def _hevc_pwt_list(br: BitReader, num_ref: int, has_chroma: bool) -> None:
    # W HEVC najpierw zapisane są wszystkie flagi, a dopiero potem wartości.
    luma_flags = [br.bit() for _ in range(num_ref)]
    chroma_flags = [br.bit() for _ in range(num_ref)] if has_chroma else [0] * num_ref

    for i in range(num_ref):
        if luma_flags[i]:
            br.se()                   # delta_luma_weight_lX
            br.se()                   # luma_offset_lX
        if chroma_flags[i]:
            for _ in range(2):
                br.se()               # delta_chroma_weight_lX
                br.se()               # delta_chroma_offset_lX


def _num_ctus(sps: dict) -> int:
    ctb = sps.get("ctb_size", 64)
    w = math.ceil(sps.get("width", 1) / ctb)
    h = math.ceil(sps.get("height", 1) / ctb)
    return max(1, w * h)


# ═════════════════════════════════════════════════════════════════════════
# SPS / PPS / Slice — H.264
# ═════════════════════════════════════════════════════════════════════════

_H264_HIGH_PROFILES = {44, 83, 86, 100, 110, 118, 122, 128, 134, 135, 138, 139, 244}


def _parse_h264_sps(data: bytes) -> dict:
    br = BitReader(rbsp(data))
    profile_idc = br.read(8)
    br.skip(8)                        # constraint flags + reserved
    br.skip(8)                        # level_idc
    sps_id = br.ue()

    chroma_format_idc = 1
    separate_colour_plane = 0
    bit_depth = 8

    if profile_idc in _H264_HIGH_PROFILES:
        chroma_format_idc = br.ue()
        if chroma_format_idc == 3:
            separate_colour_plane = br.bit()
        bit_depth = br.ue() + 8
        br.ue()                       # bit_depth_chroma_minus8
        br.bit()                      # qpprime_y_zero_transform_bypass_flag
        if br.bit():                  # seq_scaling_matrix_present_flag
            _skip_h264_scaling_matrix(br, chroma_format_idc)

    log2_max_frame_num = br.ue() + 4
    pic_order_cnt_type = br.ue()
    log2_max_poc_lsb = 0
    delta_pic_order_always_zero = 0

    if pic_order_cnt_type == 0:
        log2_max_poc_lsb = br.ue() + 4
    elif pic_order_cnt_type == 1:
        delta_pic_order_always_zero = br.bit()
        br.se()
        br.se()
        n = br.ue()
        for _ in range(n):
            br.se()

    br.ue()                           # max_num_ref_frames
    br.bit()                          # gaps_in_frame_num_value_allowed_flag
    pic_width_mbs = br.ue() + 1
    pic_height_map_units = br.ue() + 1
    frame_mbs_only = br.bit()
    if not frame_mbs_only:
        br.bit()                      # mb_adaptive_frame_field_flag
    br.bit()                          # direct_8x8_inference_flag
    if br.bit():                      # frame_cropping_flag
        br.ue(); br.ue(); br.ue(); br.ue()

    # VUI nie jest potrzebne do parsowania slice_qp_delta.
    return {
        "sps_id": sps_id,
        "profile_idc": profile_idc,
        "chroma_format_idc": chroma_format_idc,
        "separate_colour_plane": separate_colour_plane,
        "bit_depth": bit_depth,
        "log2_max_frame_num": log2_max_frame_num,
        "pic_order_cnt_type": pic_order_cnt_type,
        "log2_max_poc_lsb": log2_max_poc_lsb,
        "delta_pic_order_always_zero": delta_pic_order_always_zero,
        "frame_mbs_only": frame_mbs_only,
        "pic_width_mbs": pic_width_mbs,
        "pic_height_map_units": pic_height_map_units,
    }


def _skip_h264_scaling_matrix(br: BitReader, chroma_format_idc: int) -> None:
    count = 8 if chroma_format_idc != 3 else 12
    for i in range(count):
        if br.bit():                  # seq_scaling_list_present_flag[i]
            _skip_h264_scaling_list_values(br, 16 if i < 6 else 64)


def _skip_h264_scaling_list_values(br: BitReader, size: int) -> None:
    last_scale = 8
    next_scale = 8
    for _ in range(size):
        if next_scale != 0:
            delta_scale = br.se()
            next_scale = (last_scale + delta_scale + 256) % 256
        if next_scale != 0:
            last_scale = next_scale


def _skip_h264_vui(br: BitReader) -> None:
    if br.bit():                      # aspect_ratio_info_present_flag
        if br.read(8) == 255:         # extended SAR
            br.skip(32)
    if br.bit():                      # overscan_info_present_flag
        br.bit()
    if br.bit():                      # video_signal_type_present_flag
        br.skip(3 + 1)                # video_format, video_full_range_flag
        if br.bit():                  # colour_description_present_flag
            br.skip(24)
    if br.bit():                      # chroma_loc_info_present_flag
        br.ue(); br.ue()
    if br.bit():                      # timing_info_present_flag
        br.skip(32 + 32)              # num_units_in_tick, time_scale
        br.bit()                      # fixed_frame_rate_flag
    nal_hrd = br.bit()                # nal_hrd_parameters_present_flag
    if nal_hrd:
        _skip_h264_hrd(br)
    vcl_hrd = br.bit()                # vcl_hrd_parameters_present_flag
    if vcl_hrd:
        _skip_h264_hrd(br)
    if nal_hrd or vcl_hrd:
        br.bit()                      # low_delay_hrd_flag
    br.bit()                          # pic_struct_present_flag
    if br.bit():                      # bitstream_restriction_flag
        br.bit()                      # motion_vectors_over_pic_boundaries_flag
        br.ue()                       # max_bytes_per_pic_denom
        br.ue()                       # max_bits_per_mb_denom
        br.ue()                       # log2_max_mv_length_horizontal
        br.ue()                       # log2_max_mv_length_vertical
        br.ue()                       # max_num_reorder_frames
        br.ue()                       # max_dec_frame_buffering


def _skip_h264_hrd(br: BitReader) -> None:
    cpb_cnt = br.ue() + 1             # cpb_cnt_minus1
    br.skip(4 + 4)                    # bit_rate_scale, cpb_size_scale
    for _ in range(cpb_cnt):
        br.ue()                       # bit_rate_value_minus1
        br.ue()                       # cpb_size_value_minus1
        br.bit()                      # cbr_flag
    br.skip(5 + 5 + 5 + 5)            # *_length_minus1 (4 pola po 5 bitów)


def _parse_h264_pps(data: bytes) -> dict:
    br = BitReader(rbsp(data))
    pps_id = br.ue()
    sps_id = br.ue()
    entropy_coding_mode = br.bit()
    bottom_field_poc = br.bit()
    num_slice_groups_minus1 = br.ue()
    if num_slice_groups_minus1 > 0:
        # FMO zmienia mapowanie first_mb_in_slice -> obszar obrazu. Bez pełnego
        # mapowania slice groups nie da się uczciwie ważyć QP makroblokami.
        raise ValueError("H.264 FMO/slice groups nie są obsługiwane")
    num_ref_l0 = br.ue() + 1
    num_ref_l1 = br.ue() + 1
    weighted_pred = br.bit()
    weighted_bipred = br.read(2)
    pic_init_qp_minus26 = br.se()
    br.se()                           # pic_init_qs_minus26
    br.se()                           # chroma_qp_index_offset
    br.bit()                          # deblocking_filter_control_present_flag
    br.bit()                          # constrained_intra_pred_flag
    redundant_pic_cnt = br.bit()
    return {
        "pps_id": pps_id,
        "sps_id": sps_id,
        "entropy_coding_mode": entropy_coding_mode,
        "bottom_field_poc": bottom_field_poc,
        "num_ref_l0": num_ref_l0,
        "num_ref_l1": num_ref_l1,
        "weighted_pred": weighted_pred,
        "weighted_bipred": weighted_bipred,
        "pic_init_qp_minus26": pic_init_qp_minus26,
        "redundant_pic_cnt_present": redundant_pic_cnt,
    }


def _peek_h264_slice_pps_id(data: bytes) -> tuple[int, int, int]:
    br = BitReader(rbsp(data))
    first_mb = br.ue()
    slice_type = br.ue()
    pps_id = br.ue()
    return first_mb, slice_type, pps_id


def _parse_h264_slice(data: bytes, nal_type: int, nal_ref_idc: int,
                      sps: dict, pps: dict) -> dict:
    """Parsuj nagłówek H.264 do ``slice_qp_delta``."""
    br = BitReader(rbsp(data))
    first_mb = br.ue()
    slice_type_raw = br.ue()
    pps_id = br.ue()
    if pps_id != pps.get("pps_id"):
        raise ValueError("H.264 slice używa innego PPS niż przekazany do parsera")

    if sps["separate_colour_plane"]:
        br.skip(2)

    frame_num = br.read(sps["log2_max_frame_num"])
    field_pic = False
    bottom = False
    if not sps["frame_mbs_only"]:
        field_pic = bool(br.bit())
        if field_pic:
            bottom = bool(br.bit())

    st = slice_type_raw % 5
    idr_pic_id = None
    if nal_type == 5:
        idr_pic_id = br.ue()

    poc_lsb = None
    if sps["pic_order_cnt_type"] == 0:
        poc_lsb = br.read(sps["log2_max_poc_lsb"])
        # delta_pic_order_cnt_bottom występuje dla FRAME, nie field.
        if pps["bottom_field_poc"] and not field_pic:
            br.se()
    elif sps["pic_order_cnt_type"] == 1 and not sps["delta_pic_order_always_zero"]:
        br.se()
        if pps["bottom_field_poc"] and not field_pic:
            br.se()

    if pps["redundant_pic_cnt_present"]:
        br.ue()

    if st == 1:
        br.bit()                      # direct_spatial_mv_pred_flag

    num_ref_l0 = pps["num_ref_l0"]
    num_ref_l1 = pps["num_ref_l1"]
    if st in (0, 1):
        if br.bit():
            num_ref_l0 = br.ue() + 1
            if st == 1:
                num_ref_l1 = br.ue() + 1
        _skip_h264_ref_pic_list_reordering(br, st)

        if ((pps["weighted_pred"] and st == 0) or
                (pps["weighted_bipred"] == 1 and st == 1)):
            _parse_h264_pred_weight_table(
                br, st, num_ref_l0, num_ref_l1,
                sps["chroma_format_idc"] != 0
            )

    if nal_ref_idc != 0:
        _skip_h264_dec_ref_pic_marking(br, nal_type == 5)

    if pps["entropy_coding_mode"] and st not in (2, 4):  # nie I/SI
        br.ue()                       # cabac_init_idc

    qp_delta = br.se()
    qp_y = 26 + pps["pic_init_qp_minus26"] + qp_delta

    return {
        "first_mb": first_mb,
        "slice_type": st,
        "pps_id": pps_id,
        "frame_num": frame_num,
        "field_pic": field_pic,
        "bottom_field": bottom,
        "idr_pic_id": idr_pic_id,
        "poc_lsb": poc_lsb,
        "qp_y": qp_y,
    }


def _skip_h264_ref_pic_list_reordering(br: BitReader, st: int) -> None:
    if st in (0, 1):
        for _list in (0, 1) if st == 1 else (0,):
            if br.bit():              # ref_pic_list_reordering_flag_lX
                while True:
                    idc = br.ue()
                    if idc == 3:
                        break
                    if idc in (0, 1):
                        br.ue()       # abs_diff_pic_num_minus1
                    elif idc == 2:
                        br.ue()       # long_term_pic_num


def _parse_h264_pred_weight_table(br: BitReader, st: int, num_ref_l0: int,
                                  num_ref_l1: int, has_chroma: bool) -> None:
    br.ue()                           # luma_log2_weight_denom
    if has_chroma:
        br.ue()                       # chroma_log2_weight_denom
    _h264_pwt_list(br, num_ref_l0, has_chroma)
    if st == 1:
        _h264_pwt_list(br, num_ref_l1, has_chroma)


def _h264_pwt_list(br: BitReader, num_ref: int, has_chroma: bool) -> None:
    for _ in range(num_ref):
        if br.bit():                  # luma_weight_lX_flag
            br.se(); br.se()
        if has_chroma:
            if br.bit():              # chroma_weight_lX_flag
                for _ in range(2):
                    br.se(); br.se()


def _skip_h264_dec_ref_pic_marking(br: BitReader, is_idr: bool) -> None:
    if is_idr:
        br.bit()                      # no_output_of_prior_pics_flag
        br.bit()                      # long_term_reference_flag
        return
    if br.bit():                      # adaptive_ref_pic_marking_mode_flag
        while True:
            op = br.ue()              # memory_management_control_operation
            if op == 0:
                break
            if op == 1:
                br.ue()               # difference_of_pic_nums_minus1
            elif op == 2:
                br.ue()               # long_term_pic_num
            elif op == 3:
                br.ue(); br.ue()
            elif op == 4:
                br.ue()
            elif op == 6:
                br.ue()


# ═════════════════════════════════════════════════════════════════════════
# Statystyki
# ═════════════════════════════════════════════════════════════════════════

def _stats_from_hist(hist: dict[int, int]) -> tuple[float | None, float | None, int | None, int | None]:
    """Statystyki ważone z histogramu QP.

    Mediana jest klasyczną medianą populacji: dla parzystej liczby próbek
    średnia z dwóch środkowych obserwacji. Dzięki temu wynik z histogramu jest
    identyczny z ``statistics.median`` policzonym na rozwiniętej populacji,
    bez materializowania milionów próbek QP w pamięci.
    """
    if not hist:
        return None, None, None, None

    total = sum(hist.values())
    if total <= 0:
        return None, None, None, None

    mean = sum(q * c for q, c in hist.items()) / total
    mn = min(hist)
    mx = max(hist)

    # Indeksy dwóch środkowych elementów w posortowanej populacji (0-based).
    # Dla nieparzystego ``total`` są identyczne.
    lo_idx = (total - 1) // 2
    hi_idx = total // 2
    lo_val: int | None = None
    hi_val: int | None = None
    cum = 0

    for q in sorted(hist):
        count = hist[q]
        if count <= 0:
            continue
        next_cum = cum + count
        if lo_val is None and lo_idx < next_cum:
            lo_val = q
        if hi_idx < next_cum:
            hi_val = q
            break
        cum = next_cum

    if lo_val is None:
        lo_val = mn
    if hi_val is None:
        hi_val = lo_val

    median = (lo_val + hi_val) / 2.0
    return mean, median, mn, mx


# ═════════════════════════════════════════════════════════════════════════
# Orkiestrator
# ═════════════════════════════════════════════════════════════════════════

def _resolve_tool(kind: str) -> str:
    base_dir = Path(__file__).resolve().parent.parent
    names = {"ffprobe": ["ffprobe.exe", "ffprobe"],
             "ffmpeg": ["ffmpeg.exe", "ffmpeg"]}[kind]
    local = find_local_tool(base_dir, names)
    exe = find_executable(str(local or names[-1]),
                          [str(base_dir / n) for n in names])
    return exe or names[-1]


def _ffprobe_meta(ffprobe: str, path: Path) -> dict:
    """Krótki odczyt metadanych strumienia wideo (bez dekodowania)."""
    cmd = [
        ffprobe, "-v", "error",
        "-show_entries",
        "stream=index,codec_type,codec_name,width,height,pix_fmt,"
        "bits_per_raw_sample,nb_frames,avg_frame_rate,duration",
        "-of", "json", str(path),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "ffprobe error").strip())
    data = json.loads(p.stdout or "{}")
    for s in data.get("streams", []) or []:
        if s.get("codec_type") == "video":
            return s
    return {}


def analyze_qp(video_path: str | Path, ffprobe_exe: str | None = None,
               ffmpeg_exe: str | None = None,
               progress_cb: Optional[Callable[[int, int], None]] = None,
               cancel_event: Optional[threading.Event] = None) -> QPResult:
    """Analizuj QP filmu (HEVC/H.264) z bitstreamu.

    progress_cb(percent, frames) — wywoływany rzadko (rzadko aktualizuje GUI).
    """
    start = time.time()
    path = Path(video_path)
    if not path.exists():
        return QPResult(codec="", bit_depth=0, frames=0, samples=0, avg=None,
                        median=None, minimum=None, maximum=None, elapsed_s=0.0,
                        error=f"Plik nie istnieje: {path}")

    ffprobe = ffprobe_exe or _resolve_tool("ffprobe")
    ffmpeg = ffmpeg_exe or _resolve_tool("ffmpeg")
    try:
        meta = _ffprobe_meta(ffprobe, path)
    except Exception as e:
        return QPResult(codec="", bit_depth=0, frames=0, samples=0, avg=None,
                        median=None, minimum=None, maximum=None, elapsed_s=0.0,
                        error=f"Nie udało się odczytać metadanych (ffprobe): {e}")

    codec = str(meta.get("codec_name", "")).lower()
    if codec not in ("hevc", "h264"):
        return QPResult(codec=codec or "—", bit_depth=0, frames=0, samples=0,
                        avg=None, median=None, minimum=None, maximum=None,
                        elapsed_s=0.0,
                        error=f"Nieobsługiwany kodek: {codec or '—'} (obsługiwane: HEVC, H.264)")

    total_frames = _estimate_total_frames(meta)
    try:
        if codec == "hevc":
            return _analyze_hevc(path, ffmpeg, meta, total_frames,
                                 progress_cb, cancel_event, start)
        return _analyze_h264(path, ffmpeg, meta, total_frames,
                             progress_cb, cancel_event, start)
    except subprocess.SubprocessError as e:
        return QPResult(codec=codec, bit_depth=0, frames=0, samples=0, avg=None,
                        median=None, minimum=None, maximum=None,
                        elapsed_s=time.time() - start,
                        error=f"Błąd subprocess: {e}")
    except Exception as e:
        return QPResult(codec=codec, bit_depth=0, frames=0, samples=0, avg=None,
                        median=None, minimum=None, maximum=None,
                        elapsed_s=time.time() - start,
                        error=f"Nie udało się odczytać QP: {e}")


def _estimate_total_frames(meta: dict) -> int:
    nb = _int(meta.get("nb_frames"))
    if nb and nb > 0:
        return nb
    dur = _float(meta.get("duration"))
    fps = parse_fps(str(meta.get("avg_frame_rate") or ""))
    if dur and dur > 0 and fps:
        return max(1, int(dur * fps))
    return 0


def _int(v):
    try:
        return int(float(v)) if v not in (None, "") else 0
    except (TypeError, ValueError):
        return 0


def _float(v):
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def _analyze_hevc(path: Path, ffmpeg: str, meta: dict, total_frames: int,
                  progress_cb, cancel_event, start: float) -> QPResult:
    sps_map: dict[int, dict] = {}
    pps_map: dict[int, dict] = {}
    current_sps: dict | None = None
    histogram: dict[int, int] = {}

    frames = 0
    picture_segments: list[tuple[int | None, int]] = []
    picture_sps: dict | None = None
    picture_tiles = False
    last_qp_y: int | None = None

    used_cu_qp_delta = False
    parse_errors = 0
    multi_slice_tiles = False
    last_pct = -1

    cmd = [ffmpeg, "-hide_banner", "-nostats", "-loglevel", "error",
           "-i", str(path), "-map", "0:v:0", "-c", "copy",
           "-bsf:v", "hevc_mp4toannexb", "-f", "hevc", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    if cancel_event is not None:
        cancel_event.clear()

    try:
        assert proc.stdout is not None
        for nalu in iter_annexb_nalu(proc.stdout):
            if cancel_event is not None and cancel_event.is_set():
                return _cancel_result("hevc", start)
            if len(nalu) < 2:
                continue

            nal_type = (nalu[0] >> 1) & 0x3F
            payload = nalu[2:]

            if nal_type == HEVC_NAL_SPS:
                try:
                    sps = _parse_hevc_sps(payload)
                    sps_map[sps["sps_id"]] = sps
                    current_sps = sps
                except Exception:
                    parse_errors += 1
                continue

            if nal_type == HEVC_NAL_PPS:
                try:
                    pps = _parse_hevc_pps(payload)
                    pps_map[pps["pps_id"]] = pps
                except Exception:
                    parse_errors += 1
                continue

            if not _is_vcl(nal_type):
                continue

            try:
                first_hint, pps_id = _peek_hevc_slice_pps_id(payload, nal_type)
                pps = pps_map.get(pps_id)
                if pps is None:
                    raise ValueError(f"Brak HEVC PPS id={pps_id}")
                sps = sps_map.get(pps["sps_id"])
                if sps is None:
                    raise ValueError(f"Brak HEVC SPS id={pps['sps_id']}")

                seg = _parse_hevc_slice(payload, nal_type, sps, pps, last_qp_y)
                if bool(seg["first"]) != bool(first_hint):
                    raise ValueError("Niespójny first_slice_segment_in_pic_flag")
            except Exception:
                parse_errors += 1
                continue

            if seg["first"] and picture_segments:
                if picture_sps is not None:
                    _finalize_picture(picture_segments, picture_sps, histogram)
                    if len(picture_segments) > 1 and picture_tiles:
                        # Gdy tiles są aktywne, proste ważenie różnicą adresów
                        # slice jest konserwatywnie oznaczane jako mniej pewne.
                        multi_slice_tiles = True
                frames += 1
                picture_segments = []
                picture_tiles = False

            if seg["first"]:
                picture_sps = sps
                picture_tiles = bool(pps.get("tiles_enabled"))
                last_qp_y = None
            else:
                picture_tiles = picture_tiles or bool(pps.get("tiles_enabled"))

            used_cu_qp_delta = used_cu_qp_delta or bool(pps.get("cu_qp_delta_enabled"))

            qp = seg["slice_qp_y"]
            if qp is not None:
                last_qp_y = qp
            elif seg["dependent"]:
                qp = last_qp_y

            # Trzeci element (pps_id) jest metadanym pomocniczym; finalize używa
            # tylko (qp,address), dlatego poniżej kompatybilnie przechowujemy 2-tuple.
            picture_segments.append((qp, seg["address"]))

            if progress_cb is not None and total_frames:
                pct = min(99, int(frames * 100 / total_frames))
                if pct > last_pct:
                    last_pct = pct
                    progress_cb(pct, frames)

    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    if picture_segments and picture_sps is not None:
        _finalize_picture(picture_segments, picture_sps, histogram)
        frames += 1

    if progress_cb is not None:
        progress_cb(100, frames)

    warnings: list[str] = []
    if used_cu_qp_delta:
        warnings.append(
            "cu_qp_delta_enabled_flag=1: per-CU QP jest kodowane w CABAC; "
            "statystyki dotyczą bazowego SliceQpY, nie pełnej mapy QP CU."
        )
    if parse_errors:
        warnings.append(f"Pominięto elementy bitstreamu z błędem parsowania: {parse_errors}.")
    if multi_slice_tiles:
        warnings.append(
            "Wykryto multi-slice z tiles; ważenie zakresów slice może być przybliżone."
        )

    exact = not used_cu_qp_delta and parse_errors == 0 and not multi_slice_tiles
    accuracy = "EXACT" if exact else "SLICE_ONLY"

    return _build_result(
        "hevc",
        current_sps.get("bit_depth", 8) if current_sps else 8,
        frames,
        histogram,
        start,
        accuracy=accuracy,
        exact_block_qp=exact,
        warnings=warnings,
    )


def _finalize_picture(segments, sps: dict, histogram: dict[int, int]) -> None:
    num_ctus = _num_ctus(sps)
    if not segments:
        return

    # W typowym GoPro/x265 jest jeden slice na obraz: wtedy cały obraz ma wagę
    # num_ctus. Dla wielu slice zakładamy monotoniczne adresy początku segmentu.
    segs = sorted((qp, int(addr)) for qp, addr in segments if qp is not None)
    if not segs:
        return

    # Odrzuć duplikaty adresów zachowując ostatni QP dla danego początku.
    by_addr: dict[int, int] = {}
    for qp, addr in segs:
        if 0 <= addr < num_ctus:
            by_addr[addr] = int(qp)

    addrs = sorted(by_addr)
    for i, addr in enumerate(addrs):
        qp = by_addr[addr]
        nxt = addrs[i + 1] if i + 1 < len(addrs) else num_ctus
        weight = max(0, nxt - addr)
        if weight:
            histogram[qp] = histogram.get(qp, 0) + weight


def _h264_num_mbs(sps: dict, field_pic: bool) -> int:
    width = int(sps["pic_width_mbs"])
    map_h = int(sps["pic_height_map_units"])
    if sps["frame_mbs_only"]:
        height = map_h
    else:
        frame_height = 2 * map_h
        height = frame_height // (2 if field_pic else 1)
    return max(1, width * height)


def _finalize_h264_picture(segments, sps: dict, field_pic: bool,
                           histogram: dict[int, int]) -> None:
    num_mbs = _h264_num_mbs(sps, field_pic)
    by_addr: dict[int, int] = {}
    for qp, first_mb in segments:
        addr = int(first_mb)
        if 0 <= addr < num_mbs:
            by_addr[addr] = int(qp)

    addrs = sorted(by_addr)
    for i, addr in enumerate(addrs):
        qp = by_addr[addr]
        nxt = addrs[i + 1] if i + 1 < len(addrs) else num_mbs
        weight = max(0, nxt - addr)
        if weight:
            histogram[qp] = histogram.get(qp, 0) + weight


def _analyze_h264(path: Path, ffmpeg: str, meta: dict, total_frames: int,
                  progress_cb, cancel_event, start: float) -> QPResult:
    sps_map: dict[int, dict] = {}
    pps_map: dict[int, dict] = {}
    current_sps: dict | None = None
    histogram: dict[int, int] = {}

    frames = 0
    last_pct = -1
    parse_errors = 0

    picture_key = None
    picture_segments: list[tuple[int, int]] = []
    picture_sps: dict | None = None
    picture_field_pic = False

    cmd = [ffmpeg, "-hide_banner", "-nostats", "-loglevel", "error",
           "-i", str(path), "-map", "0:v:0", "-c", "copy",
           "-bsf:v", "h264_mp4toannexb", "-f", "h264", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if cancel_event is not None:
        cancel_event.clear()

    try:
        assert proc.stdout is not None
        for nalu in iter_annexb_nalu(proc.stdout):
            if cancel_event is not None and cancel_event.is_set():
                return _cancel_result("h264", start)
            if not nalu:
                continue

            nal_type = nalu[0] & 0x1F
            nal_ref_idc = (nalu[0] >> 5) & 3
            payload = nalu[1:]

            if nal_type == 7:
                try:
                    sps = _parse_h264_sps(payload)
                    sps_map[sps["sps_id"]] = sps
                    current_sps = sps
                except Exception:
                    parse_errors += 1
                continue

            if nal_type == 8:
                try:
                    pps = _parse_h264_pps(payload)
                    pps_map[pps["pps_id"]] = pps
                except Exception:
                    parse_errors += 1
                continue

            if not (1 <= nal_type <= 5):
                continue

            try:
                _first_mb, _slice_type, pps_id = _peek_h264_slice_pps_id(payload)
                pps = pps_map.get(pps_id)
                if pps is None:
                    raise ValueError(f"Brak H.264 PPS id={pps_id}")
                sps = sps_map.get(pps["sps_id"])
                if sps is None:
                    raise ValueError(f"Brak H.264 SPS id={pps['sps_id']}")
                info = _parse_h264_slice(payload, nal_type, nal_ref_idc, sps, pps)
            except Exception:
                parse_errors += 1
                continue

            key = (
                info["frame_num"],
                info["field_pic"],
                info["bottom_field"],
                nal_type == 5,
                info["idr_pic_id"],
                info["poc_lsb"],
            )

            if picture_key is not None and key != picture_key and picture_segments:
                if picture_sps is not None:
                    _finalize_h264_picture(
                        picture_segments, picture_sps, picture_field_pic, histogram
                    )
                frames += 1
                picture_segments = []

            if not picture_segments:
                picture_key = key
                picture_sps = sps
                picture_field_pic = bool(info["field_pic"])

            picture_segments.append((info["qp_y"], info["first_mb"]))

            if progress_cb is not None and total_frames:
                pct = min(99, int(frames * 100 / total_frames))
                if pct > last_pct:
                    last_pct = pct
                    progress_cb(pct, frames)

    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    if picture_segments and picture_sps is not None:
        _finalize_h264_picture(
            picture_segments, picture_sps, picture_field_pic, histogram
        )
        frames += 1

    if progress_cb is not None:
        progress_cb(100, frames)

    warnings = [
        "H.264: mb_qp_delta z warstwy makrobloków nie jest dekodowane; "
        "statystyki są ważonym SliceQpY (SLICE_ONLY)."
    ]
    if parse_errors:
        warnings.append(f"Pominięto elementy bitstreamu z błędem parsowania: {parse_errors}.")

    return _build_result(
        "h264",
        current_sps.get("bit_depth", 8) if current_sps else 8,
        frames,
        histogram,
        start,
        accuracy="SLICE_ONLY",
        exact_block_qp=False,
        warnings=warnings,
    )


def _build_result(codec: str, bit_depth: int, frames: int,
                  histogram: dict[int, int], start: float, *,
                  accuracy: str = "UNKNOWN", exact_block_qp: bool = False,
                  warnings: Optional[list[str]] = None) -> QPResult:
    elapsed = time.time() - start
    samples = sum(histogram.values())
    avg, med, mn, mx = _stats_from_hist(histogram)
    warnings = list(warnings or [])

    qp_bd_offset = max(0, 6 * (int(bit_depth) - 8))
    if codec == "hevc":
        if exact_block_qp:
            population = (
                "Dokładny histogram CTU: dla używanych PPS "
                "cu_qp_delta_enabled_flag=0, więc QpY nie zmienia się wewnątrz slice."
            )
        else:
            population = (
                "Histogram bazowego SliceQpY ważony zakresem CTU slice; "
                "nie jest pełną mapą per-CU, gdy występują CU QP deltas."
            )
        domain_note = (
            "Raportowany QP = natywne HEVC SliceQpY "
            "(26 + init_qp_minus26 + slice_qp_delta), bez dodawania "
            f"QpBdOffsetY={qp_bd_offset}. Dla bit depth > 8 spec dopuszcza "
            "ujemne natywne QpY; Qp'Y używane wewnętrznie przez kwantyzację "
            "powstaje po dodaniu QpBdOffsetY. " + population
        )
    else:
        domain_note = (
            "Raportowany QP = natywne H.264 SliceQpY "
            "(26 + pic_init_qp_minus26 + slice_qp_delta), ważone zakresem "
            "makrobloków slice. Per-MB mb_qp_delta nie jest dekodowane."
        )

    error = None
    if samples <= 0 or avg is None:
        error = "Nie znaleziono poprawnych próbek QP w strumieniu."

    res = QPResult(
        codec=codec,
        bit_depth=bit_depth,
        frames=frames,
        samples=samples,
        avg=avg,
        median=med,
        minimum=mn,
        maximum=mx,
        elapsed_s=elapsed,
        histogram=histogram,
        qp_domain_note=domain_note,
        error=error,
        accuracy=accuracy,
        exact_block_qp=exact_block_qp,
        warnings=warnings,
    )
    _log_analysis(res)
    return res


def _cancel_result(codec: str, start: float) -> QPResult:
    return QPResult(
        codec=codec, bit_depth=0, frames=0, samples=0, avg=None,
        median=None, minimum=None, maximum=None,
        elapsed_s=time.time() - start, error="Anulowano analizę.",
        accuracy="CANCELLED", exact_block_qp=False,
    )


def _log_analysis(res: QPResult) -> None:
    print("QP ANALYSIS", flush=True)
    print(f"codec: {res.codec}", flush=True)
    print(f"accuracy: {res.accuracy}", flush=True)
    print(f"exact_block_qp: {res.exact_block_qp}", flush=True)
    print(f"frames: {res.frames}", flush=True)
    print(f"blocks/cells: {res.samples}", flush=True)
    print(f"avg: {res.avg if res.avg is None else round(res.avg, 2)}", flush=True)
    print(f"median: {res.median}", flush=True)
    print(f"min: {res.minimum}", flush=True)
    print(f"max: {res.maximum}", flush=True)
    print(f"elapsed: {res.elapsed_s:.3f} s", flush=True)
    if res.elapsed_s > 0 and res.frames > 0:
        print(f"analysis speed: {res.frames / res.elapsed_s:.2f} fps", flush=True)
    print(f"QP samples: {res.samples}", flush=True)
    for warning in res.warnings:
        print(f"warning: {warning}", flush=True)
    if res.error:
        print(f"error: {res.error}", flush=True)
