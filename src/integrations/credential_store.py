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
import uuid
from typing import Optional

_TARGET_GARMIN_PASSWORD = "BikeRideHUD:garmin:password"
_TARGET_GARMIN_SESSION = "BikeRideHUD:garmin:session"
_TARGET_GARMIN_DI_SESSION = "BikeRideHUD/Garmin/session"
_GARMIN_PART_PREFIX = "BikeRideHUD/Garmin/session/"
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
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _credential_api():
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))]
    api.CredReadW.restype = wintypes.BOOL
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredFree.restype = None
    return api


def _win_write_credential(target: str, secret: str, username: str = "BikeRideHUD") -> bool:
    try:
        advapi32 = _credential_api()
        blob = secret.encode("utf-8")
        if len(blob) > 2560:
            return False
        blob_buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = _CREDENTIALW()
        cred.Flags = 0
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = target
        cred.Comment = "BikeRideHUD Secure Credential"
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = blob_buffer
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = username

        ret = advapi32.CredWriteW(ctypes.byref(cred), 0)
        return bool(ret != 0)
    except Exception:
        return False


def _win_read_credential(target: str) -> Optional[str]:
    try:
        advapi32 = _credential_api()
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
        advapi32 = _credential_api()
        ret = advapi32.CredDeleteW(target, CRED_TYPE_GENERIC, 0)
        return bool(ret != 0) or ctypes.get_last_error() == 1168
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


def _garmin_parts() -> list[str]:
    raw = get_credential(_TARGET_GARMIN_DI_SESSION)
    try:
        manifest = json.loads(raw or "{}")
        parts = manifest.get("parts", [])
        if (manifest.get("format") == "DI_OAUTH2_V1" and isinstance(parts, list)
                and 0 < len(parts) <= 16
                and all(isinstance(p, str) and p.startswith(_GARMIN_PART_PREFIX) for p in parts)):
            return parts
    except (ValueError, TypeError, AttributeError):
        pass
    return []


def save_garmin_tokens(tokens: dict) -> bool:
    """Atomically replace the DI session, entirely inside Windows Credential Manager.

    DI JWTs can exceed the 2560-byte credential blob limit. ASCII JSON is split
    into 2000-byte credentials; the manifest is committed last, then old parts
    are removed. No file-backed or plaintext-config fallback is used.
    """
    try:
        raw = json.dumps(tokens, ensure_ascii=True, separators=(",", ":"))
        if len(raw) > 32000 or not tokens.get("access_token") or not tokens.get("refresh_token"):
            return False
        old_parts = _garmin_parts()
        generation = uuid.uuid4().hex
        parts = []
        for index, offset in enumerate(range(0, len(raw), 2000)):
            target = f"{_GARMIN_PART_PREFIX}{generation}/{index}"
            parts.append(target)
            if not set_credential(target, raw[offset:offset + 2000], "garmin_di"):
                for part in parts:
                    delete_credential(part)
                return False
        manifest = json.dumps({"format": "DI_OAUTH2_V1", "parts": parts})
        if not set_credential(_TARGET_GARMIN_DI_SESSION, manifest, "garmin_di"):
            for part in parts:
                delete_credential(part)
            return False
        for part in old_parts:
            delete_credential(part)
        # An obsolete password/session is no longer needed after browser SSO.
        delete_garmin_password()
        delete_garmin_session()
        return True
    except (TypeError, ValueError):
        return False


def get_garmin_tokens() -> Optional[dict]:
    parts = _garmin_parts()
    if not parts:
        return None
    chunks = [get_credential(p) for p in parts]
    if any(c is None for c in chunks):
        return None
    try:
        tokens = json.loads("".join(chunks))
        if (not isinstance(tokens, dict)
                or any(not isinstance(tokens.get(key), str) or not tokens[key]
                       for key in ("access_token", "refresh_token", "client_id"))):
            return None
        tokens["expires_at"] = int(tokens["expires_at"])
        if tokens.get("refresh_expires_at") is not None:
            tokens["refresh_expires_at"] = int(tokens["refresh_expires_at"])
        return tokens
    except (ValueError, TypeError, KeyError):
        return None


def delete_garmin_tokens() -> bool:
    parts = _garmin_parts()
    if not delete_credential(_TARGET_GARMIN_DI_SESSION):
        return False
    result = True
    for part in parts:
        result = delete_credential(part) and result
    return result


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
    delete_garmin_tokens()
    delete_garmin_password()
    delete_garmin_session()
    delete_strava_client_secret()
    delete_strava_tokens()
