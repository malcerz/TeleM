from pathlib import Path

from PIL import Image

from src.gui.qt._mixins.project_mixin import _canonical_project_video_paths
from src.gui.qt._mixins.preview_mixin import PreviewMixin
from src.gui.qt._mixins.indicator_mixin import IndicatorMixin
from src.gui.layout_manager import normalize_layout


def test_multifile_input_snapshot_keeps_only_explicit_order(tmp_path: Path) -> None:
    selected = [
        tmp_path / "GX010114.MP4",
        tmp_path / "GX010115.MP4",
        tmp_path / "GX010116.MP4",
    ]
    paths = _canonical_project_video_paths([str(path) for path in selected])
    assert [path.name for path in paths] == [
        "GX010114.MP4", "GX010115.MP4", "GX010116.MP4",
    ]
    assert "output_h265.mp4" not in [path.name for path in paths]


def test_layout_visual_invalidation_preserves_telemetry_state() -> None:
    class Dummy:
        indicator_bboxes = {"speed": (1, 2, 3, 4)}
        _chart_data_cache = {"old": True}
        _prepare_cache = {"range": 1}
        last_src_pil = Image.new("RGBA", (8, 8), (1, 2, 3, 4))
        last_src_qimg = object()
        _preview_visual_generation = 4

    dummy = Dummy()
    PreviewMixin._invalidate_layout_visual_state(dummy)
    assert dummy._preview_visual_generation == 5
    assert dummy.indicator_bboxes == {}
    assert dummy._chart_data_cache is None
    assert dummy._prepare_cache == {}
    assert dummy.last_src_pil is None
    assert dummy.last_src_qimg is None


def test_reset_replaces_full_layout_once() -> None:
    controller = IndicatorMixin.__new__(IndicatorMixin)
    controller.layout = {"indicators": {"old": {}, "old_2": {}}, "custom_texts": [{"text": "old"}]}
    controller.layout_mgr = None
    controller.base_dir = Path.cwd()
    controller.src_img = Image.new("RGB", (1280, 720))
    controller._render_preview = lambda: None
    controller.telemetry = object()
    telemetry_before = controller.telemetry

    controller._on_reset_layout()
    controller._on_reset_layout()

    expected = normalize_layout(Path.cwd() / "def_layout.json", 1280, 720)
    assert controller.layout == expected
    assert controller.telemetry is telemetry_before
