"""Comprehensive tests for Universal Export Logging across all backends.

Tests:
- AMD, Intel, NVIDIA, and CPU logging
- Direct and queue render modes
- Secret and credential masking
- MSIX / read-only directory fallback to %LOCALAPPDATA%/SportCamHUD/logs
- Compass checkpoint diagnostics
- Session lifecycle (start, milestones, cancel, fail, completed summary)
- Backward compatibility with legacy amd_export_logging_enabled
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from src.export_log import (
    append_export_log,
    begin_export_log_session,
    end_export_log_session,
    export_log_path,
    get_user_logs_dir,
    log_export_progress,
    resolve_export_logging,
    sample_compass_checkpoints,
    sanitize_log_text,
)
from src.export_paths import (
    load_amd_export_logging_enabled,
    load_app_preferences,
    load_export_logging_enabled,
    update_app_preferences,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_DEF_LAYOUT = REPO_ROOT / "def_layout.json"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def isolated_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    before = hashlib.sha256(REPO_DEF_LAYOUT.read_bytes()).hexdigest()
    yield
    assert hashlib.sha256(REPO_DEF_LAYOUT.read_bytes()).hexdigest() == before, (
        "repository def_layout.json must not be modified"
    )


# ---------------------------------------------------------------------------
# 1. Secret & Credential Redaction (Requirement 7)
# ---------------------------------------------------------------------------

def test_secret_redaction():
    # Esri ArcGIS token in URL
    raw_esri = "https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/tile/1/2/3?token=AAPK12345678abcdef"
    clean_esri = sanitize_log_text(raw_esri)
    assert "token=[REDACTED]" in clean_esri
    assert "AAPK12345678abcdef" not in clean_esri

    # CARTO API key
    raw_carto = "https://cartodb-basemaps-a.global.ssl.fastly.net/rastertiles/voyager/1/2/3.png?api_key=secret_carto_key_999"
    clean_carto = sanitize_log_text(raw_carto)
    assert "api_key=[REDACTED]" in clean_carto
    assert "secret_carto_key_999" not in clean_carto

    # HTTP Authorization header
    raw_auth = "GET /activity HTTP/1.1\r\nAuthorization: Bearer my_super_secret_oauth_token\r\nHost: api.strava.com"
    clean_auth = sanitize_log_text(raw_auth)
    assert "Authorization: Bearer [REDACTED]" in clean_auth
    assert "my_super_secret_oauth_token" not in clean_auth

    # Password in json/query
    raw_pass = "user credentials: {'password': 'MySecretPassword123'}"
    clean_pass = sanitize_log_text(raw_pass)
    assert "[REDACTED]" in clean_pass
    assert "MySecretPassword123" not in clean_pass


# ---------------------------------------------------------------------------
# 2. Settings Persistence & Migration (Requirement 3)
# ---------------------------------------------------------------------------

def test_export_logging_migration_and_persistence(qapp, tmp_path):
    # Case 1: Fresh install -> defaults to True
    assert load_export_logging_enabled() is True
    assert load_amd_export_logging_enabled() is True

    # Case 2: Legacy preference present ('amd_export_logging_enabled': False)
    update_app_preferences({"amd_export_logging_enabled": False})
    assert load_export_logging_enabled() is False

    # Case 3: Explicit new preference ('export_logging_enabled': True)
    update_app_preferences({"export_logging_enabled": True})
    assert load_export_logging_enabled() is True

    # Case 4: UI integration (SettingsTab)
    from src.gui.qt.tabs.settings_tab import SettingsTab
    from src.gui.qt.signals import get_signals

    tab = SettingsTab.__new__(SettingsTab)
    QWidget.__init__(tab)
    tab.signals = get_signals()
    tab.base_dir = tmp_path
    tab._render_job_active = False
    tab._analysis_active = False
    tab._garmin_dialog = None
    tab._garmin_busy = False
    tab._build_ui()
    tab._load_integration_settings()
    tab._load_app_preferences_into_form()

    assert tab.chk_export_logging.isChecked() is True
    assert tab.chk_amd_export_logging.isChecked() is True

    # Toggle off and save
    tab.chk_export_logging.setChecked(False)
    tab._on_save_settings_clicked()

    prefs = load_app_preferences()
    assert prefs["export_logging_enabled"] is False
    assert prefs["amd_export_logging_enabled"] is False
    assert load_export_logging_enabled() is False


# ---------------------------------------------------------------------------
# 3. Path Resolution & MSIX / Protected Directory Fallback (Requirement 6)
# ---------------------------------------------------------------------------

def test_export_log_path_and_fallback(tmp_path):
    # Standard writable path
    video_out = tmp_path / "exports" / "render_20261016_1305.mp4"
    log_p = export_log_path(video_out, backend="INTEL")
    assert log_p == tmp_path / "exports" / "render_20261016_1305.log"

    # Part suffix stripping
    part_out = tmp_path / "exports" / "clip.part.mp4"
    assert export_log_path(part_out, backend="INTEL") == tmp_path / "exports" / "clip.log"

    # Append write fallback when target path is unwritable (e.g. read-only dir / MSIX)
    unwritable_file = Path(r"//invalid_nonexistent_share_999/unwritable_dir/video.log")
    append_export_log(unwritable_file, "Diagnostic line")
    
    # Check that fallback file was written in user logs dir
    user_logs = get_user_logs_dir()
    fallback_file = user_logs / "video.log"
    assert fallback_file.is_file()
    assert "Diagnostic line" in fallback_file.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 4. Compass Diagnostics Sampling (Requirement 9)
# ---------------------------------------------------------------------------

def test_compass_checkpoint_sampling():
    import datetime

    class FakeTelemetry:
        def __init__(self):
            self.start_dt_utc = datetime.datetime(2026, 10, 16, 13, 6, 5, tzinfo=datetime.timezone.utc)
            self.duration_s = 60.0
            self._compass_hybrid_result = SimpleNamespace(samples=[1, 2, 3])

        def resolve_value(self, name, dt, source=None, indicator_key=None):
            if indicator_key == "compass":
                return 185.4
            if source == "fit":
                return 180.2
            return None

    layout = {
        "indicators": {
            "compass": {
                "source": "hybrid",
                "hybrid_enabled": True,
            }
        }
    }
    telem = FakeTelemetry()
    checkpoints = sample_compass_checkpoints(telem, layout=layout, duration_s=60.0, checkpoints_count=3)
    joined = "\n".join(checkpoints)
    assert "Hybrid Compass Enabled: YES" in joined
    assert "Hybrid Samples Available: 3" in joined
    assert "raw_heading=180.2° (FIT)" in joined
    assert "hybrid_heading=185.4°" in joined
    assert "cache=OK" in joined


# ---------------------------------------------------------------------------
# 5. Session Lifecycle Across All 4 Backends (AMD, Intel, NVIDIA, CPU)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("backend", ["intel", "amd", "nvidia", "cpu"])
def test_export_log_lifecycle_all_backends(tmp_path, backend):
    out_file = tmp_path / f"export_{backend}.mp4"
    log_p = export_log_path(out_file, backend=backend)

    # 1. Start session
    begin_export_log_session(
        log_p,
        output=out_file,
        backend=backend.upper(),
        encoder=backend,
        codec="hevc",
        profile="balanced",
        job_id=f"job_{backend}_001",
        generation_id=1,
        mode="DIRECT",
        video_paths=[str(tmp_path / "source.mp4")],
        resolution="3840x2160",
        target_fps=30.0,
        bitrate="40M",
    )
    assert log_p.is_file()
    content = log_p.read_text(encoding="utf-8")
    assert "[SPORTCAMHUD EXPORT LOG SESSION START]" in content
    assert f"Target Backend:   {backend.upper()}" in content
    assert "Operating System:" in content
    assert "CPU:" in content

    # 2. Log progress milestone
    log_export_progress(log_p, frame=500, total=1000, fps=35.2, elapsed_s=14.2)
    content = log_p.read_text(encoding="utf-8")
    assert "[PROGRESS] frame=500/1000 ( 50.0%) fps= 35.2 elapsed=  14.2s" in content

    # 3. End session (completed)
    stats = {
        "frames_rendered": 1000,
        "render_fps": 35.2,
        "user_effective_fps": 31.8,
        "total_wall_seconds": 31.4,
        "frame_render_seconds": 28.4,
        "finalization_seconds": 0.42,
    }
    end_export_log_session(log_p, "completed", detail=f"output={out_file}", stats=stats)
    content = log_p.read_text(encoding="utf-8")
    assert "[SPORTCAMHUD EXPORT LOG SESSION END]" in content
    assert "Final Status:       COMPLETED" in content
    assert "Render FPS (Loop):  35.20 FPS" in content
    assert "User Effective FPS: 31.80 FPS" in content
    assert "Finalization Time:  0.42 s" in content


def test_export_log_cancellation_and_failure(tmp_path):
    out_file = tmp_path / "test_cancel.mp4"
    log_p = export_log_path(out_file, backend="INTEL")

    # Start session
    begin_export_log_session(log_p, output=out_file, backend="INTEL", encoder="intel")
    
    # End session cancelled
    end_export_log_session(log_p, "cancelled", detail="User pressed Stop")
    content = log_p.read_text(encoding="utf-8")
    assert "Final Status:       CANCELLED" in content
    assert "Detail / Error:     User pressed Stop" in content

    # Re-run same output (append mode)
    begin_export_log_session(log_p, output=out_file, backend="INTEL", encoder="intel")
    end_export_log_session(log_p, "failed", detail="Hardware error 0x80070057")
    content = log_p.read_text(encoding="utf-8")
    assert content.count("[SPORTCAMHUD EXPORT LOG SESSION START]") == 2
    assert "previous sessions kept above" in content
    assert "Final Status:       FAILED" in content
    assert "Detail / Error:     Hardware error 0x80070057" in content


# ---------------------------------------------------------------------------
# 6. Pipeline Integration & Queue Snapshot Verification
# ---------------------------------------------------------------------------

class _PipelineOwner:
    def __init__(self, tmp_path, export_logging_enabled=True):
        self.video_path = None
        self.video_paths = []
        self.telemetry = None
        self.video_timeline = None
        self._user_preset_path = ""
        self._cut_regions = ()
        self.ffprobe_exe = "ffprobe"
        self.layout = {}
        self.base_dir = tmp_path
        self.export_logging_enabled = export_logging_enabled
        self.amd_export_logging_enabled = export_logging_enabled
        self.signals = SimpleNamespace(
            sig_export_path_warning=SimpleNamespace(emit=lambda *a: None),
            sig_render_finished=SimpleNamespace(emit=lambda *a: None),
            sig_render_stopped=SimpleNamespace(emit=lambda *a: None),
            sig_error=SimpleNamespace(emit=lambda *a: None),
            sig_progress=SimpleNamespace(emit=lambda *a: None),
        )

    def _resolve_render_output_path(self, target):
        return Path(target)


def test_pipeline_creates_log_for_intel_and_cpu(monkeypatch, tmp_path):
    import src.gui.qt._mixins.render_mixin as render_module
    from src.ffmpeg.render_errors import RenderError

    monkeypatch.setattr(render_module, "_test_encoder", lambda *_a: True)

    for backend in ("intel", "cpu"):
        out_dir = tmp_path / f"exports_{backend}"
        out_dir.mkdir(exist_ok=True)
        output = out_dir / f"test_{backend}.mp4"
        owner = _PipelineOwner(tmp_path, export_logging_enabled=True)
        options = {"encoder": backend, "output": str(output)}

        with pytest.raises(RenderError) as info:
            render_module.RenderMixin._render_pipeline(owner, options)

        assert info.value.code in ("SOURCE_MISSING", "NO_SOURCES")
        log = out_dir / f"test_{backend}.log"
        assert log.is_file(), f"Log file must be created for backend {backend}"
        text = log.read_text(encoding="utf-8")
        assert f"Target Backend:   {backend.upper()}" in text
