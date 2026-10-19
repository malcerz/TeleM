"""Read the licence documents actually present in this application/runtime.

No licence is inferred from a package or binary name. Missing documents remain
missing; the bundled notices are displayed verbatim, not certified by this UI.
"""
from pathlib import Path
import sys
import sysconfig
import threading

from PySide6.QtCore import Signal, QProcess
from PySide6.QtWidgets import QWidget, QDialog, QVBoxLayout, QLabel, QComboBox, QPlainTextEdit, QDialogButtonBox


def license_documents(app_root: Path) -> list[tuple[str, Path]]:
    root = Path(app_root).resolve()
    documents: dict[Path, str] = {}

    def add(path: Path, base: Path, prefix: str = "") -> None:
        resolved = path.resolve()
        if path.is_file() and resolved.is_relative_to(base.resolve()):
            documents[resolved] = prefix + path.relative_to(base).as_posix()

    def scan(base: Path, prefix: str = "") -> None:
        if not base.is_dir():
            return
        for path in base.rglob("*"):
            in_license_directory = any(part.lower() in {"licenses", "license", "licences", "licence", "notices"}
                                       for part in path.relative_to(base).parts[:-1])
            if in_license_directory or path.name.lower().startswith(("license", "licence", "copying", "notice", "copyright")):
                add(path, base, prefix)

    for name in ("THIRD_PARTY_NOTICES.txt", "LICENSE", "LICENSE.txt", "portable_manifest.json"):
        add(root / name, root)
    for directory in ("runtime/telemetry_parser", "third_party/gpmf-parser", "runtime/common/ffmpeg", "mpv-dev"):
        scan(root / directory, directory + "/")
    embedded = root / "python"
    if embedded.is_dir():
        python_root = embedded
        site = embedded / "Lib/site-packages"
        prefix = "python/"
    else:
        python_root = Path(sys.base_prefix)
        site = Path(sysconfig.get_path("purelib"))
        prefix = "Środowisko developerskie: "
    for name in ("LICENSE", "LICENSE.txt", "LICENSE.md"):
        add(python_root / name, python_root, prefix)
    if site.is_dir():
        for metadata in sorted(site.glob("*.dist-info")):
            scan(metadata, prefix + "Lib/site-packages/" + metadata.name + "/")
    return sorted(((label, path) for path, label in documents.items()), key=lambda row: row[0].casefold())


class LicensePanel(QWidget):
    documents_ready = Signal(object)

    def __init__(self, app_root: Path, parent=None):
        super().__init__(parent)
        self.app_root = Path(app_root).resolve()
        self._probe = None
        self.setObjectName("licensePanel")
        self.setStyleSheet("QWidget#licensePanel { background: white; color: black; } "
                           "QWidget#licensePanel QLabel, QWidget#licensePanel QPlainTextEdit, "
                           "QWidget#licensePanel QComboBox { background: white; color: black; }")
        layout = QVBoxLayout(self)
        title = QLabel("Licencje zewnętrznych komponentów")
        title.setStyleSheet("font-weight: bold; padding: 4px;")
        layout.addWidget(title)
        note = QLabel("Dokumenty dołączone do aplikacji i używanego środowiska Python. "
                      "Wyświetlane są oryginalne treści; brak dokumentu nie potwierdza licencji komponentu. "
                      "THIRD_PARTY_NOTICES może zawierać informacje ogólne zależne od wydania.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.documents = QComboBox()
        self.documents.setMinimumContentsLength(35)
        self.documents.currentIndexChanged.connect(self._show_document)
        layout.addWidget(self.documents)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlainText("Wczytywanie dokumentów...")
        layout.addWidget(self.text)
        self.documents_ready.connect(self._populate)

        def collect():
            try:
                found = license_documents(self.app_root)
            except OSError as exc:
                found = str(exc)
            try:
                self.documents_ready.emit(found)
            except RuntimeError:
                pass  # The parent window may have closed while scanning files.
        self._collect_documents = collect
        self._documents_started = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._documents_started:
            self._documents_started = True
            threading.Thread(target=self._collect_documents, daemon=True, name="LicenseDocuments").start()

    def _populate(self, documents):
        if isinstance(documents, str):
            self.text.setPlainText("Nie udało się odczytać dokumentów: " + documents)
            return
        for label, path in documents:
            self.documents.addItem(label, str(path))
        for name in ("ffmpeg.exe", "ffprobe.exe"):
            for directory in (self.app_root / "runtime/common/ffmpeg", self.app_root):
                executable = directory / name
                if executable.is_file():
                    self.documents.addItem(name + " — licencja zgłoszona przez dołączony program", {"executable": str(executable)})
                    break
        if not self.documents.count():
            self.text.setPlainText("W tym katalogu aplikacji nie znaleziono dokumentów licencyjnych.")

    def _show_document(self, _index):
        path = self.documents.currentData()
        if self._probe is not None:
            self._probe.kill()
            self._probe = None
        if isinstance(path, dict):
            self.text.setPlainText("Odczytywanie informacji z dołączonego programu...")
            probe = self._probe = QProcess(self)
            probe.setProcessChannelMode(QProcess.MergedChannels)
            def finished(code, _status):
                if self._probe is probe:
                    output = bytes(probe.readAllStandardOutput()).decode("utf-8", "replace")
                    self.text.setPlainText(output if code == 0 else "Odczyt licencji nie powiódł się.\n" + output)
            probe.finished.connect(finished)
            probe.errorOccurred.connect(lambda _error: self.text.setPlainText("Nie udało się uruchomić odczytu licencji.") if self._probe is probe else None)
            probe.start(path["executable"], ["-L"])
            return
        if path:
            try:
                self.text.setPlainText(Path(path).read_text(encoding="utf-8-sig", errors="replace"))
            except OSError as exc:
                self.text.setPlainText("Nie udało się odczytać dokumentu: " + str(exc))

    def stop_probe(self):
        if self._probe is not None:
            self._probe.kill()
            self._probe = None

    def closeEvent(self, event):
        self.stop_probe()
        super().closeEvent(event)


class LicenseDialog(QDialog):
    """Compatibility wrapper for focused document reading and tests."""
    def __init__(self, app_root: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Licencje zewnętrznych komponentów")
        self.resize(850, 600)
        layout = QVBoxLayout(self)
        self.panel = LicensePanel(app_root, self)
        self.documents = self.panel.documents
        self.text = self.panel.text
        layout.addWidget(self.panel)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    @property
    def _probe(self):
        return self.panel._probe

    def closeEvent(self, event):
        self.panel.stop_probe()
        super().closeEvent(event)
