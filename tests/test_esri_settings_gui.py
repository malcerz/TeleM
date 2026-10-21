"""Exercise real Qt controls with mock HTTP and an isolated credential store."""
import os
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QLineEdit
from src.integrations import credential_store as store
from src.integrations.esri import esri_client
from src.gui.qt.tabs.settings_tab import SettingsTab


def test_gui_save_restart_replace_delete_and_async_status():
    app = QApplication.instance() or QApplication([])
    previous = store._FORCE_MOCK
    store.set_mock_mode(True)
    store._MOCK_STORE.clear()
    tabs = []
    try:
        tab = SettingsTab()
        tabs.append(tab)
        assert tab.edit_esri_key.echoMode() == QLineEdit.Password
        tab.edit_esri_key.setText("synthetic-ui-first")
        tab.btn_esri_save.click()
        assert store.get_map_api_key("esri") == "synthetic-ui-first"
        assert tab.edit_esri_key.text() == ""
        restarted = SettingsTab()
        tabs.append(restarted)
        assert restarted.edit_esri_key.text() == ""
        restarted.edit_esri_key.setText("synthetic-ui-second")
        restarted.btn_esri_save.click()
        assert store.get_map_api_key("satellite") == "synthetic-ui-second"
        with patch.object(esri_client, "test_connection", return_value=(False,"Brak uprawnień")):
            restarted.btn_esri_test.click()
            deadline = time.monotonic() + 3
            while not restarted.btn_esri_test.isEnabled() and time.monotonic() < deadline:
                app.processEvents()
            assert restarted.btn_esri_test.isEnabled()
            assert restarted.lbl_esri_status.text() == "Brak uprawnień"
        restarted.btn_esri_delete.click()
        assert store.get_map_api_key("esri") is None
        assert "Brak klucza" in restarted.lbl_esri_status.text()
    finally:
        for tab in tabs:
            tab.close()
        store._MOCK_STORE.clear()
        store.set_mock_mode(previous)
        esri_client.credentials_changed()
