"""Run the real two-column Settings licence panel against dev or Portable.

Read-only: does not build/update Portable or load account credentials/preferences.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget
    from src.gui.qt.signals import get_signals
    from src.gui.qt.tabs.settings_tab import SettingsTab
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.app_root.resolve(); out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"
    if font_path.is_file():
        QFontDatabase.addApplicationFont(str(font_path))
        app.setFont(QFont("Segoe UI", 10))
    tab = SettingsTab.__new__(SettingsTab)
    QWidget.__init__(tab)
    tab.signals = get_signals(); tab.base_dir = root
    tab._render_job_active = tab._analysis_active = tab._garmin_busy = False
    tab._build_ui()
    tab._on_auto_source_changed(notify=False)
    tab.resize(1500, 950); tab.show(); QTest.qWait(100)
    ticks = []
    heartbeat = QTimer(); heartbeat.timeout.connect(lambda: ticks.append(1)); heartbeat.start(10)
    dialog = tab.licenses_panel
    for _ in range(3000):
        QTest.qWait(10)
        if dialog.documents.count(): break
    assert dialog.documents.count() > 0 and dialog.text.isReadOnly()
    labels = [dialog.documents.itemText(i) for i in range(dialog.documents.count())]
    target = next((i for i,label in enumerate(labels) if label == "THIRD_PARTY_NOTICES.txt"), 0)
    dialog.documents.setCurrentIndex(target); QTest.qWait(50)
    tab.grab().save(str(out / "settings.png"))
    dialog.grab().save(str(out / "licenses.png"))
    assert dialog.text.toPlainText()
    probes = {}
    for i in range(dialog.documents.count()):
        data = dialog.documents.itemData(i)
        if not isinstance(data, dict): continue
        dialog.documents.setCurrentIndex(i)
        for _ in range(500):
            QTest.qWait(10)
            if dialog._probe.state().value == 0: break
        text = dialog.text.toPlainText()
        assert "Copyright" in text and dialog._probe.exitCode() == 0
        name = Path(data["executable"]).stem
        (out / (name + "_license.txt")).write_text(text, encoding="utf-8")
        probes[name] = dict(executable=data["executable"], exit_code=dialog._probe.exitCode(),
                           sha256=hashlib.sha256(Path(data["executable"]).read_bytes()).hexdigest())
    result = dict(app_root=str(root), cwd=str(Path.cwd()), python=sys.executable, prefix=sys.prefix,
                  document_count=dialog.documents.count(), document_labels=labels,
                  heartbeat_ticks=len(ticks), probes=probes, read_only=dialog.text.isReadOnly())
    if (root / "python").exists():
        for i in range(dialog.documents.count()):
            data = dialog.documents.itemData(i)
            if isinstance(data,str): assert Path(data).is_relative_to(root)
    assert ticks
    (out / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    dialog.close(); tab.close(); app.processEvents()
    print(f"PASS documents={result['document_count']} heartbeat={len(ticks)} probes={list(probes)}")


if __name__ == "__main__":
    main()
