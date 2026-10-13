"""Nonmodal Garmin browser login, using TanitaGarminSync's ticket capture.

The unnamed WebEngine profile is off the record: no login cookies, form data,
or passwords are persisted to disk. Only DI tokens reach Credential Manager.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLabel, QPushButton
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView

from src.integrations.garmin_auth import (
    GarminAuthClient, GarminAuthError, SSO_LOGIN_URL, extract_service_ticket, is_garmin_url,
)
from src.integrations.garmin_connect import GarminProvider


# As in Tanita, listen for SSO postMessage and inspect only for the ST ticket.
# Return only the ticket; never send the HTML or form contents to Python.
_CAPTURE_SCRIPT = r"""+(function () {
    if (location.protocol !== 'https:' ||
        !(location.hostname === 'garmin.com' || location.hostname.endsWith('.garmin.com'))) return;
    window.__bikeGarminTicket = '';
    window.addEventListener('message', function (ev) {
        try {
            var origin = new URL(ev.origin);
            if (origin.protocol !== 'https:' ||
                !(origin.hostname === 'garmin.com' || origin.hostname.endsWith('.garmin.com'))) return;
            var value = typeof ev.data === 'string' ? ev.data : JSON.stringify(ev.data);
            var match = (value || '').match(/\bST-[A-Za-z0-9-]+/);
            if (match) window.__bikeGarminTicket = match[0];
        } catch (e) {}
    }, false);
})();
"""
_SCAN_SCRIPT = r"""+(function () {
    if (window.__bikeGarminTicket) return window.__bikeGarminTicket;
    var h = document.documentElement ? document.documentElement.outerHTML : '';
    var m = h.match(/ticket=(ST-[A-Za-z0-9-]+)/);
    if (m) return m[1];
    var t = document.body ? document.body.innerText : '';
    m = t.match(/\bST-[A-Za-z0-9-]+/);
    return m ? m[0] : '';
})();
"""


class _GarminPage(QWebEnginePage):
    ticket_seen = Signal(str)

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        text = url.toString()
        if is_garmin_url(text):
            ticket = extract_service_ticket(text)
            if ticket:
                self.ticket_seen.emit(ticket)
        return super().acceptNavigationRequest(url, navigation_type, is_main_frame)

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        # Garmin page console messages/URLs could contain authentication data.
        pass


class _ExchangeBridge(QObject):
    result = Signal(bool, str)
    finished = Signal()


class GarminLoginDialog(QDialog):
    auth_finished = Signal(bool, str)

    def __init__(self, parent=None, timeout_ms=300_000, auth=None):
        super().__init__(parent)
        self.setWindowTitle("Garmin Connect — logowanie")
        self.resize(620, 760)
        self.setModal(False)
        self._done = False
        self._ticket_handled = False
        self._cancelled = threading.Event()
        QApplication.instance().aboutToQuit.connect(self._cancelled.set)
        self.auth = auth if auth is not None else GarminAuthClient()
        layout = QVBoxLayout(self)
        self.status = QLabel(
            "Zaloguj się na stronie Garmin. Jeśli Garmin poprosi o MFA, "
            "potwierdź kod na tej stronie. Hasło pozostaje u Garmina."
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.view = QWebEngineView(self)
        self.profile = QWebEngineProfile(self)
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.NoPersistentCookies)
        self.profile.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
        self.page = _GarminPage(self.profile, self.view)
        self.view.setPage(self.page)
        script = QWebEngineScript()
        script.setName("BikeRideHUD Garmin SSO ticket")
        script.setInjectionPoint(QWebEngineScript.DocumentCreation)
        script.setWorldId(QWebEngineScript.MainWorld)
        script.setRunsOnSubFrames(False)
        script.setSourceCode(_CAPTURE_SCRIPT)
        self.page.scripts().insert(script)
        layout.addWidget(self.view)
        self.cancel_button = QPushButton("Anuluj")
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button)
        self.page.ticket_seen.connect(self._accept_ticket)
        self.view.urlChanged.connect(self._url_changed)
        self.view.loadFinished.connect(self._load_finished)
        self.rejected.connect(self._on_cancelled)
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(500)
        self.poll_timer.timeout.connect(self._scan)
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self._on_timeout)
        self.deadline.start(timeout_ms)
        self.poll_timer.start()
        self.view.load(QUrl(SSO_LOGIN_URL))

    def _url_changed(self, url):
        if is_garmin_url(url.toString()):
            self._accept_ticket(extract_service_ticket(url.toString()) or "")

    def _load_finished(self, ok):
        if self._done or self._ticket_handled:
            return
        if not ok:
            self.status.setText("Nie udało się wczytać strony Garmin. Sprawdź połączenie z Internetem.")
        self._scan()

    def _scan(self):
        if self._done or self._ticket_handled or not is_garmin_url(self.view.url().toString()):
            return
        self.page.runJavaScript(_SCAN_SCRIPT, QWebEngineScript.MainWorld, self._scan_result)

    def _scan_result(self, value):
        if not self._done and is_garmin_url(self.view.url().toString()):
            self._accept_ticket(value if isinstance(value, str) else "")

    def _accept_ticket(self, value):
        ticket = extract_service_ticket(value)
        if self._done or self._ticket_handled or not ticket:
            return
        self._ticket_handled = True
        self.poll_timer.stop()
        self.view.hide()
        self.status.setText("Logowanie potwierdzone. Pobieranie tokenów i sprawdzanie połączenia…")
        # The worker must never own the dialog: its last Python reference could
        # otherwise destroy WebEngine objects on a non-GUI thread after cancel.
        bridge = _ExchangeBridge(QApplication.instance())
        bridge.result.connect(self._on_exchange_result)
        bridge.finished.connect(bridge.deleteLater)
        threading.Thread(target=GarminLoginDialog._exchange,
                         args=(ticket, self.auth, self._cancelled, bridge), daemon=True).start()

    @staticmethod
    def _exchange(ticket, auth, cancelled, bridge):
        try:
            auth.exchange_service_ticket(ticket, cancelled)
            if cancelled.is_set():
                return
            ok, message = GarminProvider(auth=auth).test_connection()
        except GarminAuthError as exc:
            ok, message = False, str(exc)
        except Exception:
            ok, message = False, "Garmin Connect: autoryzacja nie powiodła się. Połącz ponownie."
        finally:
            # This signal only schedules disposal on the GUI thread.
            try:
                if not cancelled.is_set():
                    bridge.result.emit(ok, message)
                bridge.finished.emit()
            except RuntimeError:
                pass  # QApplication has already shut down.

    def _finish(self, ok, message):
        if self._done:
            return
        self._done = True
        self._cancelled.set()
        self.poll_timer.stop()
        self.deadline.stop()
        self.view.stop()
        self.view.setUrl(QUrl("about:blank"))
        self.auth_finished.emit(ok, message)
        self.accept() if ok else self.reject()

    @Slot(bool, str)
    def _on_exchange_result(self, ok, message):
        self._finish(ok, message)

    def _on_cancelled(self):
        self._finish(False, "Anulowano logowanie Garmin Connect.")

    def _on_timeout(self):
        self._finish(False, "Garmin Connect: przekroczono czas oczekiwania na potwierdzenie logowania.")
