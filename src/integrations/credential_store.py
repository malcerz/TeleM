"""Credential Store for BikeRideHUD.

Secure storage for sensitive credentials (passwords, tokens, client secrets)
using Windows Credential Manager (via advapi32.dll) with in-memory mock support
for headless testing. Secrets are never saved to plain text files, layout JSON,
project JSON, or git repositories.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import sys
from typing import Optional

_TARGET_GARMIN_PASSWORD = "BikeRideHUD:garmin:password"
_TARGET_GARMIN_SESSION = "BikeRideHUD:garmin:session"
_TARGET_STRAVA_SECRET = "BikeRideHUD:strava:client_secret"
_TARGET_STRAVA_TOKENS = "BikeRideHUD:strava:tokens"

# In-memory store for unit testing or fallback
_MOCK_STORE: dict[str, str] = {}
_FORCE_MOCK = os.environ.get("TELEM_CREDENTIAL_STORE_MOCK", "").lower() in ("1", "true", "yes")


def set_mock_mode(enabled: bool) -> None:
    """Enable or disable in-memory mock credential store (useful for tests)."""
    global _FORCE_MOCK
    _FORCE_MOCK = enabled
    if not enabled:
        _MOCK_STORE.clear()


def is_mock_mode() -> bool:
    return _FORCE_MOCK or sys.platform != "win32"


# ---------------------------------------------------------------------------
# Windows Credential Manager via ctypes
# ---------------------------------------------------------------------------

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2


class _FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.c_char_p),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _win_write_credential(target: str, secret: str, username: str = "BikeRideHUD") -> bool:
    try:
        advapi32 = ctypes.windll.advapi32
        blob = secret.encode("utf-8")
        cred = _CREDENTIALW()
        cred.Flags = 0
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = target
        cred.Comment = "BikeRideHUD Secure Credential"
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = blob
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = username

        ret = advapi32.CredWriteW(ctypes.byref(cred), 0)
        return bool(ret != 0)
    except Exception:
        return False


def _win_read_credential(target: str) -> Optional[str]:
    try:
        advapi32 = ctypes.windll.advapi32
        pcred = ctypes.POINTER(_CREDENTIALW)()
        ret = advapi32.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pcred))
        if ret == 0 or not pcred:
            return None
        try:
            blob = ctypes.string_at(pcred.contents.CredentialBlob, pcred.contents.CredentialBlobSize)
            return blob.decode("utf-8")
        finally:
            advapi32.CredFree(pcred)
    except Exception:
        return None


def _win_delete_credential(target: str) -> bool:
    try:
        advapi32 = ctypes.windll.advapi32
        ret = advapi32.CredDeleteW(target, CRED_TYPE_GENERIC, 0)
        return bool(ret != 0)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public generic API
# ---------------------------------------------------------------------------

def set_credential(target: str, secret: str, username: str = "BikeRideHUD") -> bool:
    """Save a secret string associated with target."""
    if is_mock_mode():
        _MOCK_STORE[target] = secret
        return True
    return _win_write_credential(target, secret, username=username)


def get_credential(target: str) -> Optional[str]:
    """Retrieve secret string associated with target, or None if not set."""
    if is_mock_mode():
        return _MOCK_STORE.get(target)
    return _win_read_credential(target)


def delete_credential(target: str) -> bool:
    """Delete a secret associated with target."""
    if is_mock_mode():
        _MOCK_STORE.pop(target, None)
        return True
    return _win_delete_credential(target)


# ---------------------------------------------------------------------------
# Specific helpers for Garmin & Strava
# ---------------------------------------------------------------------------

def save_garmin_password(password: str, username: str = "") -> bool:
    if not password:
        return delete_credential(_TARGET_GARMIN_PASSWORD)
    return set_credential(_TARGET_GARMIN_PASSWORD, password, username=username or "garmin")


def get_garmin_password() -> Optional[str]:
    return get_credential(_TARGET_GARMIN_PASSWORD)


def delete_garmin_password() -> bool:
    return delete_credential(_TARGET_GARMIN_PASSWORD)


def save_garmin_session(session_data: str) -> bool:
    if not session_data:
        return delete_credential(_TARGET_GARMIN_SESSION)
    return set_credential(_TARGET_GARMIN_SESSION, session_data, username="garmin_session")


def get_garmin_session() -> Optional[str]:
    return get_credential(_TARGET_GARMIN_SESSION)


def delete_garmin_session() -> bool:
    return delete_credential(_TARGET_GARMIN_SESSION)


def save_strava_client_secret(secret: str) -> bool:
    if not secret:
        return delete_credential(_TARGET_STRAVA_SECRET)
    return set_credential(_TARGET_STRAVA_SECRET, secret, username="strava_secret")


def get_strava_client_secret() -> Optional[str]:
    return get_credential(_TARGET_STRAVA_SECRET)


def delete_strava_client_secret() -> bool:
    return delete_credential(_TARGET_STRAVA_SECRET)


def save_strava_tokens(token_dict: dict) -> bool:
    if not token_dict:
        return delete_credential(_TARGET_STRAVA_TOKENS)
    try:
        raw = json.dumps(token_dict)
        return set_credential(_TARGET_STRAVA_TOKENS, raw, username="strava_tokens")
    except Exception:
        return False


def get_strava_tokens() -> Optional[dict]:
    raw = get_credential(_TARGET_STRAVA_TOKENS)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def delete_strava_tokens() -> bool:
    return delete_credential(_TARGET_STRAVA_TOKENS)


def clear_all_credentials() -> None:
    delete_garmin_password()
    delete_garmin_session()
    delete_strava_client_secret()
    delete_strava_tokens()
