"""Browser SSO -> DI OAuth2, ported from TanitaGarminSync 2815107.

Only a one-time service ticket enters this module, never a Garmin password.
Network methods must be called from a worker, not the Qt GUI thread.
"""

from __future__ import annotations

import base64
import re
import threading
import time
from urllib.parse import unquote, urlparse

import requests

from src.integrations import credential_store

SSO_LOGIN_BASE = "https://sso.garmin.com/sso/embed"
SSO_LOGIN_URL = (
    SSO_LOGIN_BASE + "?id=gauth-widget&embedWidget=true"
    "&gauthHost=https%3A%2F%2Fsso.garmin.com%2Fsso"
    "&clientId=GarminConnect&locale=en_US"
    "&redirectAfterAccountLoginUrl=https%3A%2F%2Fsso.garmin.com%2Fsso%2Fembed"
    "&service=https%3A%2F%2Fsso.garmin.com%2Fsso%2Fembed"
)
DI_TOKEN_URL = "https://diauth.garmin.com/di-oauth2-service/oauth/token"
DI_GRANT_TYPE = "https://connectapi.garmin.com/di-oauth2-service/oauth/grant/service_ticket"
DI_CLIENT_IDS = (
    "GARMIN_CONNECT_MOBILE_ANDROID_DI_2025Q2",
    "GARMIN_CONNECT_MOBILE_ANDROID_DI_2024Q4",
    "GARMIN_CONNECT_MOBILE_ANDROID_DI",
    "GARMIN_CONNECT_MOBILE_IOS_DI",
)
API_BASE = "https://connectapi.garmin.com"
NATIVE_HEADERS = {
    "User-Agent": "GCM-Android-5.23",
    "X-Garmin-User-Agent": (
        "com.garmin.android.apps.connectmobile/5.23; ; "
        "Google/sdk_gphone64_arm64/google; Android/33; Dalvik/2.1.0"
    ),
    "X-Garmin-Paired-App-Version": "10861",
    "X-Garmin-Client-Platform": "Android",
    "X-App-Ver": "10861",
    "X-Lang": "pl",
    "X-GCExperience": "GC5",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.7",
    "Accept": "application/json, text/plain, */*",
}
_AUTH_LOCK = threading.RLock()


class GarminAuthError(RuntimeError):
    """A safe, user-facing error; never includes response bodies or URLs."""


def is_garmin_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    return parsed.scheme == "https" and (host == "garmin.com" or host.endswith(".garmin.com"))


def extract_service_ticket(text: str) -> str | None:
    match = re.search(r"\bST-[A-Za-z0-9-]+", unquote(text or ""))
    return match.group(0) if match else None


class GarminAuthClient:
    def __init__(self, timeout: float = 20.0, session=None, clock=time.time):
        self.session = session if session is not None else requests.Session()
        self.timeout = (timeout, max(timeout, 40.0))
        self.clock = clock

    def _request(self, method: str, url: str, **kwargs):
        try:
            return self.session.request(method, url, timeout=self.timeout, allow_redirects=False, **kwargs)
        except requests.Timeout:
            raise GarminAuthError("Garmin Connect: przekroczono czas oczekiwania na serwis.") from None
        except requests.RequestException:
            raise GarminAuthError("Garmin Connect: brak połączenia lub serwis niedostępny.") from None

    def _token_request(self, client_id: str, form: dict):
        headers = dict(NATIVE_HEADERS)
        basic = base64.b64encode((client_id + ":").encode()).decode("ascii")
        headers["Authorization"] = "Basic " + basic
        return self._request("POST", DI_TOKEN_URL, data=form, headers=headers)

    def _parse_tokens(self, response, client_id: str, previous: dict | None = None) -> dict:
        try:
            body = response.json()
            access = body.get("access_token")
            refresh = body.get("refresh_token") or (previous or {}).get("refresh_token")
            if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
                raise ValueError
            now = int(self.clock())
            refresh_in = int(body.get("refresh_token_expires_in", 0) or 0)
            return {
                "client_id": client_id,
                "access_token": access,
                "refresh_token": refresh,
                "expires_at": now + max(60, int(body.get("expires_in", 3600))),
                "refresh_expires_at": (
                    now + refresh_in if refresh_in > 0 else (previous or {}).get("refresh_expires_at")
                ),
            }
        except (ValueError, TypeError, AttributeError):
            raise GarminAuthError("Garmin Connect: nieprawidłowa odpowiedź wymiany tokenów.") from None

    def exchange_service_ticket(self, ticket: str, cancelled: threading.Event | None = None) -> None:
        if not re.fullmatch(r"ST-[A-Za-z0-9-]+", ticket or ""):
            raise GarminAuthError("Garmin Connect: nieprawidłowe potwierdzenie logowania.")
        with _AUTH_LOCK:
            for client_id in DI_CLIENT_IDS:
                if cancelled is not None and cancelled.is_set():
                    raise GarminAuthError("Anulowano logowanie Garmin Connect.")
                response = self._token_request(client_id, {
                    "client_id": client_id,
                    "service_ticket": ticket,
                    "grant_type": DI_GRANT_TYPE,
                    "service_url": SSO_LOGIN_BASE,
                })
                if 200 <= response.status_code < 300:
                    tokens = self._parse_tokens(response, client_id)
                    if cancelled is not None and cancelled.is_set():
                        raise GarminAuthError("Anulowano logowanie Garmin Connect.")
                    if not credential_store.save_garmin_tokens(tokens):
                        raise GarminAuthError("Nie udało się zapisać sesji w Windows Credential Manager.")
                    return
            raise GarminAuthError("Garmin Connect: wymiana ticketu na tokeny nie powiodła się. Połącz ponownie.")

    def valid_access_token(self, force_refresh: bool = False) -> str:
        with _AUTH_LOCK:
            current = credential_store.get_garmin_tokens()
            if not current:
                raise GarminAuthError("Niepołączono z Garmin Connect — wybierz Połącz z Garmin Connect.")
            now = self.clock()
            if not force_refresh and current["expires_at"] > now + 90:
                return current["access_token"]
            expiry = current.get("refresh_expires_at")
            if expiry is not None and expiry <= now + 30:
                credential_store.delete_garmin_tokens()
                raise GarminAuthError("Sesja wygasła — połącz ponownie z Garmin Connect.")
            response = self._token_request(current["client_id"], {
                "grant_type": "refresh_token",
                "client_id": current["client_id"],
                "refresh_token": current["refresh_token"],
            })
            if not 200 <= response.status_code < 300:
                if response.status_code in (400, 401):
                    credential_store.delete_garmin_tokens()
                    raise GarminAuthError("Sesja wygasła — połącz ponownie z Garmin Connect.")
                raise GarminAuthError("Garmin Connect: nie udało się odświeżyć sesji.")
            tokens = self._parse_tokens(response, current["client_id"], current)
            if not credential_store.save_garmin_tokens(tokens):
                raise GarminAuthError("Nie udało się zapisać odświeżonej sesji w Windows Credential Manager.")
            return tokens["access_token"]

    def api_get(self, path: str, **kwargs):
        if not path.startswith("/") or path.startswith("//"):
            raise GarminAuthError("Nieprawidłowy endpoint Garmin Connect.")
        for attempt in range(2):
            headers = dict(NATIVE_HEADERS)
            headers["Authorization"] = "Bearer " + self.valid_access_token(force_refresh=attempt == 1)
            response = self._request("GET", API_BASE + path, headers=headers, **kwargs)
            if response.status_code == 401 and attempt == 0:
                continue
            if response.status_code == 401:
                raise GarminAuthError("Sesja wygasła — połącz ponownie z Garmin Connect.")
            if not 200 <= response.status_code < 300:
                raise GarminAuthError(f"Garmin Connect: serwis zwrócił błąd HTTP {response.status_code}.")
            return response
        raise GarminAuthError("Sesja wygasła — połącz ponownie z Garmin Connect.")

    def logout(self) -> None:
        with _AUTH_LOCK:
            if not credential_store.delete_garmin_tokens():
                raise GarminAuthError("Nie udało się usunąć sesji z Windows Credential Manager.")
            credential_store.delete_garmin_session()
            credential_store.delete_garmin_password()
