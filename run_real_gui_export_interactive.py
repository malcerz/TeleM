import sys
from pathlib import Path

# Add the workspace root (TeleM) to Python path so that 'src' package can be imported
workspace_root = Path(r"f:/_DEV/TeleM").resolve()
if str(workspace_root) not in sys.path:
    sys.path.insert(0, str(workspace_root))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

# Import TeleM application entry point after adjusting sys.path
from src.gui.qt.application import main as telem_main
from src.gui.qt.signals import get_signals

def run_export():
    signals = get_signals()
    # Options that match what the Export button would produce (default UI values)
    options = {
        "encoder": "nv",
        "resolution": "source",
        "rotation": "auto",
        "update_rate": "Full",
        "bitrate": "40M",
        "output": "nv0_real_export.mp4",
    }
    # Trigger the export after a short delay to ensure UI is fully initialised
    QTimer.singleShot(500, lambda: signals.sig_render_requested.emit(options))

    # When rendering finishes, write the stats to a JSON report file and quit
    def on_finished(stats, output):
        import json
        report_path = Path(__file__).with_name("real_gui_report.json")
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump({"stats": stats, "output": str(output)}, f, indent=2)
            print(f"[SCRIPT] Render finished – stats written to {report_path}", flush=True)
        except Exception as e:
            print(f"[SCRIPT] Failed to write report: {e}", flush=True)
        QApplication.instance().quit()
    signals.sig_render_finished.connect(on_finished)

    # On error, also quit (so we don't hang)
    def on_error(msg: str):
        print(f"[SCRIPT] Render error: {msg}", flush=True)
        QApplication.instance().quit()
    signals.sig_error.connect(on_error)

if __name__ == "__main__":
    # Enable test mode so TeleM loads the known sample video (GX020079.mp4) and its FIT file
    sys.argv.append("-test")
    # Schedule the export shortly after the application starts
    QTimer.singleShot(500, run_export)
    telem_main()

