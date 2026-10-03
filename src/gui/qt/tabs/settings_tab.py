"""Zakładka Ustawienia — konfiguracja programu."""

import json
from pathlib import Path
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QFormLayout, QComboBox,
    QSpinBox, QPushButton, QLineEdit, QHBoxLayout, QFileDialog,
    QStyleFactory, QCheckBox, QMessageBox, QLabel,
)
from PySide6.QtGui import QFontDatabase

from src.gui.qt.signals import get_signals


class SettingsTab(QWidget):
    """Zakładka ustawień aplikacji."""

    sig_garmin_status = Signal(str, str)
    sig_strava_status = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.signals = get_signals()
        self.base_dir = Path(__file__).resolve().parent.parent.parent.parent
        self._render_job_active = False
        self._analysis_active = False
        self.sig_garmin_status.connect(self._update_garmin_status)
        self.sig_strava_status.connect(self._update_strava_status)
        self._build_ui()
        self._load_integration_settings()
        # Przywróć font z kontrolera po jego inicjalizacji (emitowany przez sig_global_font_restored)
        self.signals.sig_global_font_restored.connect(self._on_global_font_restored)
        self.signals.sig_render_state.connect(self._on_render_state)
        self.signals.sig_progress.connect(self._on_progress)

    def _build_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setAlignment(Qt.AlignTop)
        vbox.setContentsMargins(24, 24, 24, 24)

        # ── Ogólne ────────────────────────────────────────────────────
        general = QGroupBox("Ogólne")
        general.setStyleSheet("QGroupBox { font-size: 13px; font-weight: bold; }")
        form = QFormLayout(general)
        form.setSpacing(10)

        self.cmb_lang = QComboBox()
        self.cmb_lang.addItems(["Polski", "English"])
        form.addRow("Język:", self.cmb_lang)

        self.cmb_theme = QComboBox()
        self.cmb_theme.addItems(QStyleFactory.keys())
        current = QStyleFactory.keys()
        if "Fusion" in current:
            self.cmb_theme.setCurrentText("Fusion")
        form.addRow("Motyw:", self.cmb_theme)

        # Startowy preset
        row_preset = QHBoxLayout()
        self.edit_startup_preset = QLineEdit("")
        self.edit_startup_preset.setMinimumHeight(28)
        self.edit_startup_preset.setPlaceholderText("(domyślny def_layout.json)")
        self.edit_startup_preset.textChanged.connect(
            lambda txt: self.signals.sig_settings_changed.emit("startup_preset", txt)
        )
        row_preset.addWidget(self.edit_startup_preset)
        btn_preset = QPushButton("Wybierz")
        btn_preset.setMinimumHeight(28)
        btn_preset.clicked.connect(
            lambda: self._browse_file(self.edit_startup_preset, "preset")
        )
        row_preset.addWidget(btn_preset)
        btn_clear = QPushButton("Wyczyść")
        btn_clear.setMinimumHeight(28)
        btn_clear.clicked.connect(lambda: self.edit_startup_preset.setText(""))
        row_preset.addWidget(btn_clear)
        form.addRow("Startowy preset:", row_preset)

        vbox.addWidget(general)

        # ── Czcionka HUD ──────────────────────────────────────────────
        font_group = QGroupBox("Czcionka HUD")
        font_group.setStyleSheet("QGroupBox { font-size: 13px; font-weight: bold; }")
        font_form = QFormLayout(font_group)
        font_form.setSpacing(10)

        self.cmb_font = QComboBox()
        families = QFontDatabase().families()
        self.cmb_font.addItems(families)
        if "Arial" in families:
            self.cmb_font.setCurrentText("Arial")
        self.cmb_font.currentTextChanged.connect(
            lambda f: self.signals.sig_settings_changed.emit("font", f)
        )
        font_form.addRow("Czcionka:", self.cmb_font)

        self.spin_outline = QSpinBox()
        self.spin_outline.setRange(0, 10)
        self.spin_outline.setValue(3)
        self.spin_outline.valueChanged.connect(
            lambda v: self.signals.sig_settings_changed.emit("outline", v)
        )
        font_form.addRow("Obramowanie:", self.spin_outline)

        # Przycisk jawnego zapisu ustawień globalnych
        self.btn_save_settings = QPushButton("Zapisz ustawienia")
        self.btn_save_settings.setMinimumHeight(32)
        self.btn_save_settings.setToolTip(
            "Persystuje wybrany font i obramowanie do def_layout.json "
            "(będą przywrócone po ponownym uruchomieniu)"
        )
        self.btn_save_settings.setStyleSheet(
            "QPushButton { background-color: #2a5a2a; color: #aaffaa; "
            "font-weight: bold; border-radius: 4px; padding: 4px 12px; }"
            "QPushButton:hover { background-color: #3a7a3a; }"
        )
        self.btn_save_settings.clicked.connect(
            lambda: self.signals.sig_save_global_settings.emit()
        )
        font_form.addRow(self.btn_save_settings)

        vbox.addWidget(font_group)

        # ── Wydajność ─────────────────────────────────────────────────
        perf_group = QGroupBox("Wydajność")
        perf_group.setStyleSheet("QGroupBox { font-size: 13px; font-weight: bold; }")
        perf_form = QFormLayout(perf_group)
        perf_form.setSpacing(10)

        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(1, 32)
        self.spin_threads.setValue(8)
        self.spin_threads.valueChanged.connect(
            lambda v: self.signals.sig_settings_changed.emit("threads", v)
        )
        perf_form.addRow("Liczba wątków:", self.spin_threads)

        row_cache = QHBoxLayout()
        self.edit_cache = QLineEdit("cache/")
        self.edit_cache.setMinimumHeight(28)
        row_cache.addWidget(self.edit_cache)
        btn_cache = QPushButton("Wybierz")
        btn_cache.setMinimumHeight(28)
        btn_cache.clicked.connect(lambda: self._browse_dir(self.edit_cache))
        row_cache.addWidget(btn_cache)
        self.btn_clear_cache = QPushButton("Czyść cache")
        self.btn_clear_cache.setMinimumHeight(28)
        self.btn_clear_cache.setToolTip(
            "Cache można wyczyścić po zakończeniu aktywnego zadania."
        )
        self.btn_clear_cache.clicked.connect(self._clear_generated_cache)
        row_cache.addWidget(self.btn_clear_cache)
        perf_form.addRow("Katalog cache:", row_cache)

        # Ścieżka ffmpeg
        row_ffmpeg = QHBoxLayout()
        self.edit_ffmpeg = QLineEdit("")
        self.edit_ffmpeg.setMinimumHeight(28)
        self.edit_ffmpeg.setPlaceholderText("(auto-wykrywanie)")
        row_ffmpeg.addWidget(self.edit_ffmpeg)
        btn_ffmpeg = QPushButton("Wybierz")
        btn_ffmpeg.setMinimumHeight(28)
        btn_ffmpeg.clicked.connect(lambda: self._browse_file(self.edit_ffmpeg, "ffmpeg"))
        row_ffmpeg.addWidget(btn_ffmpeg)
        perf_form.addRow("Ścieżka ffmpeg:", row_ffmpeg)

        vbox.addWidget(perf_group)

        # ── Wykresy ───────────────────────────────────────────────────
        charts_group = QGroupBox("Wykresy")
        charts_group.setStyleSheet("QGroupBox { font-size: 13px; font-weight: bold; }")
        charts_form = QFormLayout(charts_group)
        charts_form.setSpacing(10)

        self.chk_skip_pauses = QCheckBox("Pomiń pauzy aktywności")
        self.chk_skip_pauses.setChecked(False)
        self.chk_skip_pauses.toggled.connect(
            lambda v: self.signals.sig_settings_changed.emit("charts_skip_pauses", v)
        )
        charts_form.addRow(self.chk_skip_pauses)

        vbox.addWidget(charts_group)

        # ── Integracje / Dane aktywności ──────────────────────────────
        integ_group = QGroupBox("Integracje / Dane aktywności")
        integ_group.setStyleSheet("QGroupBox { font-size: 13px; font-weight: bold; }")
        integ_form = QFormLayout(integ_group)
        integ_form.setSpacing(10)

        self.cmb_auto_source = QComboBox()
        self.cmb_auto_source.addItem("Nic", "none")
        self.cmb_auto_source.addItem("Garmin Connect", "garmin")
        self.cmb_auto_source.addItem("Strava", "strava")
        integ_form.addRow("Automatyczne źródło aktywności:", self.cmb_auto_source)

        # Garmin panel
        self.garmin_container = QWidget()
        garmin_layout = QFormLayout(self.garmin_container)
        garmin_layout.setContentsMargins(0, 4, 0, 4)
        garmin_layout.setSpacing(8)

        self.edit_garmin_user = QLineEdit("")
        self.edit_garmin_user.setMinimumHeight(28)
        self.edit_garmin_user.setPlaceholderText("np. user@example.com")
        self.edit_garmin_user.textChanged.connect(self._on_garmin_user_changed)
        garmin_layout.addRow("Login / e-mail:", self.edit_garmin_user)

        self.edit_garmin_pass = QLineEdit("")
        self.edit_garmin_pass.setMinimumHeight(28)
        self.edit_garmin_pass.setEchoMode(QLineEdit.Password)
        self.edit_garmin_pass.setPlaceholderText("(wprowadź hasło)")
        self.edit_garmin_pass.textChanged.connect(self._on_garmin_pass_changed)
        garmin_layout.addRow("Hasło:", self.edit_garmin_pass)

        row_garmin_btn = QHBoxLayout()
        self.btn_garmin_test = QPushButton("Zaloguj / Sprawdź połączenie")
        self.btn_garmin_test.setMinimumHeight(28)
        self.btn_garmin_test.clicked.connect(self._on_garmin_test_clicked)
        row_garmin_btn.addWidget(self.btn_garmin_test)
        self.lbl_garmin_status = QLabel("Status: Niepołączono")
        self.lbl_garmin_status.setStyleSheet("color: #888888;")
        row_garmin_btn.addWidget(self.lbl_garmin_status, 1)
        garmin_layout.addRow("", row_garmin_btn)

        integ_form.addRow(self.garmin_container)

        # Strava panel
        self.strava_container = QWidget()
        strava_layout = QFormLayout(self.strava_container)
        strava_layout.setContentsMargins(0, 4, 0, 4)
        strava_layout.setSpacing(8)

        self.edit_strava_client_id = QLineEdit("")
        self.edit_strava_client_id.setMinimumHeight(28)
        self.edit_strava_client_id.setPlaceholderText("np. 123456")
        self.edit_strava_client_id.textChanged.connect(self._on_strava_client_id_changed)
        strava_layout.addRow("Client ID:", self.edit_strava_client_id)

        self.edit_strava_client_secret = QLineEdit("")
        self.edit_strava_client_secret.setMinimumHeight(28)
        self.edit_strava_client_secret.setEchoMode(QLineEdit.Password)
        self.edit_strava_client_secret.setPlaceholderText("(wprowadź client secret)")
        self.edit_strava_client_secret.textChanged.connect(self._on_strava_client_secret_changed)
        strava_layout.addRow("Client Secret:", self.edit_strava_client_secret)

        row_strava_btn = QHBoxLayout()
        self.btn_strava_connect = QPushButton("Połącz ze Strava")
        self.btn_strava_connect.setMinimumHeight(28)
        self.btn_strava_connect.clicked.connect(self._on_strava_connect_clicked)
        row_strava_btn.addWidget(self.btn_strava_connect)

        self.btn_strava_test = QPushButton("Sprawdź połączenie")
        self.btn_strava_test.setMinimumHeight(28)
        self.btn_strava_test.clicked.connect(self._on_strava_test_clicked)
        row_strava_btn.addWidget(self.btn_strava_test)

        self.lbl_strava_status = QLabel("Status: Niepołączono")
        self.lbl_strava_status.setStyleSheet("color: #888888;")
        row_strava_btn.addWidget(self.lbl_strava_status, 1)
        strava_layout.addRow("", row_strava_btn)

        integ_form.addRow(self.strava_container)

        self.cmb_auto_source.currentIndexChanged.connect(self._on_auto_source_changed)

        vbox.addWidget(integ_group)

        vbox.addStretch()

    def _on_auto_source_changed(self, _index: int = 0) -> None:
        source = str(self.cmb_auto_source.currentData() or "none")
        self.garmin_container.setVisible(source == "garmin")
        self.strava_container.setVisible(source == "strava")
        self.signals.sig_settings_changed.emit("auto_activity_source", source)

    def _on_garmin_user_changed(self, text: str) -> None:
        self.signals.sig_settings_changed.emit("garmin_username", text.strip())

    def _on_garmin_pass_changed(self, text: str) -> None:
        if text:
            from src.integrations import credential_store
            credential_store.save_garmin_password(text, username=self.edit_garmin_user.text().strip())

    def _on_garmin_test_clicked(self) -> None:
        self.btn_garmin_test.setEnabled(False)
        self.lbl_garmin_status.setText("Logowanie i sprawdzanie połączenia...")
        self.lbl_garmin_status.setStyleSheet("color: #ffa500;")
        threading.Thread(target=self._bg_test_garmin, daemon=True).start()

    def _bg_test_garmin(self) -> None:
        from src.integrations import credential_store
        from src.integrations.garmin_connect import GarminProvider
        user = self.edit_garmin_user.text().strip()
        pwd = self.edit_garmin_pass.text()
        if pwd:
            credential_store.save_garmin_password(pwd, username=user)
        provider = GarminProvider(username=user)
        ok, msg = provider.test_connection()
        if ok:
            self.sig_garmin_status.emit(f"Status: Połączono jako {msg}", "#44ff44")
        else:
            self.sig_garmin_status.emit(f"Status: {msg}", "#ff5555")

    def _update_garmin_status(self, text: str, color: str) -> None:
        self.btn_garmin_test.setEnabled(True)
        self.lbl_garmin_status.setText(text)
        self.lbl_garmin_status.setStyleSheet(f"color: {color};")

    def _on_strava_client_id_changed(self, text: str) -> None:
        self.signals.sig_settings_changed.emit("strava_client_id", text.strip())

    def _on_strava_client_secret_changed(self, text: str) -> None:
        if text:
            from src.integrations import credential_store
            credential_store.save_strava_client_secret(text.strip())

    def _on_strava_connect_clicked(self) -> None:
        self.btn_strava_connect.setEnabled(False)
        self.lbl_strava_status.setText("Oczekiwanie na autoryzację w przeglądarce...")
        self.lbl_strava_status.setStyleSheet("color: #ffa500;")
        threading.Thread(target=self._bg_connect_strava, daemon=True).start()

    def _bg_connect_strava(self) -> None:
        from src.integrations import credential_store
        from src.integrations.strava import run_strava_oauth_flow
        cid = self.edit_strava_client_id.text().strip()
        sec = self.edit_strava_client_secret.text().strip() or credential_store.get_strava_client_secret() or ""
        ok, msg = run_strava_oauth_flow(cid, sec)
        if ok:
            self.sig_strava_status.emit(f"Status: Połączono jako {msg}", "#44ff44")
        else:
            self.sig_strava_status.emit(f"Status: {msg}", "#ff5555")

    def _on_strava_test_clicked(self) -> None:
        self.btn_strava_test.setEnabled(False)
        self.lbl_strava_status.setText("Sprawdzanie połączenia...")
        self.lbl_strava_status.setStyleSheet("color: #ffa500;")
        threading.Thread(target=self._bg_test_strava, daemon=True).start()

    def _bg_test_strava(self) -> None:
        from src.integrations.strava import StravaProvider
        cid = self.edit_strava_client_id.text().strip()
        provider = StravaProvider(client_id=cid)
        ok, msg = provider.test_connection()
        if ok:
            self.sig_strava_status.emit(f"Status: Połączono jako {msg}", "#44ff44")
        else:
            self.sig_strava_status.emit(f"Status: {msg}", "#ff5555")

    def _update_strava_status(self, text: str, color: str) -> None:
        self.btn_strava_connect.setEnabled(True)
        self.btn_strava_test.setEnabled(True)
        self.lbl_strava_status.setText(text)
        self.lbl_strava_status.setStyleSheet(f"color: {color};")

    def _load_integration_settings(self) -> None:
        def_layout_path = self.base_dir / "def_layout.json"
        integrations: dict = {}
        if def_layout_path.exists():
            try:
                data = json.loads(def_layout_path.read_text(encoding="utf-8"))
                integrations = data.get("integrations", {})
            except Exception:
                pass

        auto_source = integrations.get("auto_activity_source", "none").lower()
        idx = self.cmb_auto_source.findData(auto_source)
        if idx >= 0:
            self.cmb_auto_source.setCurrentIndex(idx)
        else:
            self.cmb_auto_source.setCurrentIndex(0)

        garmin_user = integrations.get("garmin_username", "")
        self.edit_garmin_user.setText(garmin_user)

        strava_cid = integrations.get("strava_client_id", "")
        self.edit_strava_client_id.setText(strava_cid)

        from src.integrations import credential_store
        garmin_pass = credential_store.get_garmin_password()
        garmin_session = credential_store.get_garmin_session()
        if garmin_pass or garmin_session:
            self.edit_garmin_pass.setPlaceholderText("(hasło zapisane w bezpiecznym magazynie)")
            self.lbl_garmin_status.setText("Status: Skonfigurowano")
            self.lbl_garmin_status.setStyleSheet("color: #aaffaa;")

        strava_tokens = credential_store.get_strava_tokens()
        strava_sec = credential_store.get_strava_client_secret()
        if strava_sec:
            self.edit_strava_client_secret.setPlaceholderText("(secret zapisany w bezpiecznym magazynie)")
        if strava_tokens:
            athlete = strava_tokens.get("athlete", {})
            name = f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip() or "Połączono"
            self.lbl_strava_status.setText(f"Status: Połączono jako {name}")
            self.lbl_strava_status.setStyleSheet("color: #aaffaa;")

        self._on_auto_source_changed(self.cmb_auto_source.currentIndex())

    def _browse_dir(self, target: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, "Wybierz katalog")
        if path:
            target.setText(path)

    def _browse_file(self, target: QLineEdit, _name: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Wybierz plik", "", "Wszystkie (*)",
        )
        if path:
            target.setText(path)

    def _refresh_cache_button_state(self) -> None:
        active = self._render_job_active or self._analysis_active
        self.btn_clear_cache.setEnabled(not active)
        if active:
            self.btn_clear_cache.setToolTip(
                "Cache można wyczyścić po zakończeniu aktywnego zadania."
            )
        else:
            self.btn_clear_cache.setToolTip(
                "Usuń wygenerowany cache telemetryczny BikeRideHUD."
            )

    def _on_render_state(self, snapshot: object) -> None:
        state = str(getattr(snapshot, "state", "")).lower()
        self._render_job_active = state in {
            "running", "rendering", "preparing", "finalizing", "cancelling",
        }
        self._refresh_cache_button_state()

    def _on_progress(self, percent: int, text: str) -> None:
        status = str(text or "").lower()
        loading = any(token in status for token in ("analiza gpmf", "wczytywanie telemetrii"))
        if loading and int(percent) < 100:
            self._analysis_active = True
        elif "metadane gotowe" in status or int(percent) >= 100:
            self._analysis_active = False
        self._refresh_cache_button_state()

    def _clear_generated_cache(self) -> None:
        if self._render_job_active or self._analysis_active:
            return
        answer = QMessageBox.question(
            self,
            "Czyść cache",
            "Czy wyczyścić cache BikeRideHUD?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            from src.telemetry_cache_manager import clear_generated_cache
            result = clear_generated_cache()
            files = int(result.get("files_removed", 0))
            bytes_removed = int(result.get("bytes_removed", 0))
            megabytes = bytes_removed / (1024 * 1024)
            QMessageBox.information(
                self,
                "Czyść cache",
                f"Wyczyszczono cache.\nUsunięto: {files} plików\nZwolniono: {megabytes:.2f} MB",
            )
            print(
                f"[TelemetryCache] cleared files={files} bytes={bytes_removed}",
                flush=True,
            )
        except Exception as exc:
            print(f"[TelemetryCache] Cleanup failed: {exc}", flush=True)
            QMessageBox.warning(
                self,
                "Czyść cache",
                f"Nie udało się wyczyścić cache:\n{exc}",
            )

    def _on_global_font_restored(self, family_name: str) -> None:
        """Przywraca zaznaczenie fontu w cmb_font bez emitowania sig_settings_changed."""
        if not family_name:
            return
        # Blokuj sygnał currentTextChanged na czas programowej zmiany
        self.cmb_font.blockSignals(True)
        idx = self.cmb_font.findText(family_name)
        if idx >= 0:
            self.cmb_font.setCurrentIndex(idx)
        else:
            # Font nieznany systemowi — dodaj jako opcję (może być zainstalowany pod inną nazwą)
            self.cmb_font.insertItem(0, family_name)
            self.cmb_font.setCurrentIndex(0)
        self.cmb_font.blockSignals(False)

    def set_font(self, family_name: str) -> None:
        """Publiczna metoda ustawiająca font (np. wywoływana z MainWindow)."""
        self._on_global_font_restored(family_name)
