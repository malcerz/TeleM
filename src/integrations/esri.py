"""Esri BYOK transport. No secret-bearing URL or server error text escapes here.

Call network methods only from workers. Credentials are read on each request so
replacement/deletion takes effect without restarting. No persistent tile cache.
"""
from __future__ import annotations

import io
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote

from PIL import Image
from src.integrations.credential_store import get_map_api_key

SERVICE = "https://ibasemaps-api.arcgis.com/arcgis/rest/services/World_Imagery/MapServer"
STYLE = "https://basemapstyles-api.arcgis.com/arcgis/rest/services/styles/v2/styles/arcgis/imagery/standard"
INSTRUCTIONS = "https://developers.arcgis.com/documentation/security-and-authentication/api-key-authentication/"


class EsriError(Exception):
    """Contains only an allowlisted, user-facing message."""


def error_message(code: int, message: str = "") -> str:
    # Inspect but never display raw responses: proxies can echo credentials.
    if "expir" in message.lower():
        return "Klucz wygasł"
    return {400: "Nieprawidłowe żądanie (HTTP 400)",
            401: "Nieprawidłowy klucz", 498: "Nieprawidłowy klucz lub klucz wygasł",
            499: "Brak klucza", 403: "Brak uprawnień",
            429: "Limit zapytań Esri (HTTP 429) — spróbuj później"}.get(
                code, "Błąd usługi Esri (HTTP 5xx)" if code >= 500 else "Błąd odpowiedzi Esri")


class EsriClient:
    def __init__(self):
        self._lock = threading.RLock()
        self.generation = 0
        self._validated_key = None
        self._status = "Brak klucza"
        self._retry_at = 0.0
        self.attribution = ""
        self._tiles = {}

    def credentials_changed(self):
        # Never wait on the network lock in the GUI thread.
        self.generation += 1
        self._validated_key = None
        self._retry_at = 0.0
        self.attribution = ""
        self._tiles.clear()
        self._status = "Klucz zapisany — sprawdź połączenie" if get_map_api_key("esri") else "Brak klucza"

    @property
    def status(self):
        if not get_map_api_key("esri"):
            return "Brak klucza — Ustawienia → Integracje → Esri World Imagery"
        if self._status == "Brak klucza":
            return "Klucz zapisany — sprawdź połączenie"
        return self._status

    def _request(self, url, key):
        # The World Imagery MapServer did not accept Bearer headers in live
        # probes (499); its documented transport is a token query parameter.
        # The style service supports Bearer and echoToken=false.
        if url.startswith(SERVICE):
            url += ("&" if "?" in url else "?") + "token=" + quote(key, safe="")
        request = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + key, "User-Agent": "SportCamHUD/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                data = response.read()
            if data.lstrip().startswith(b"{"):
                body = json.loads(data)
                if "error" in body:
                    err = body["error"]
                    raise EsriError(error_message(int(err.get("code", 0)), str(err.get("message", ""))))
            return data
        except urllib.error.HTTPError as exc:
            raise EsriError(error_message(exc.code)) from None
        except (socket.timeout, TimeoutError):
            raise EsriError("Przekroczono czas połączenia z Esri") from None
        except urllib.error.URLError:
            raise EsriError("Brak internetu lub błąd połączenia z Esri") from None
        except EsriError:
            raise
        except Exception:
            raise EsriError("Nieprawidłowa odpowiedź Esri") from None

    def _validate(self, key):
        if self._validated_key == key:
            return
        metadata = json.loads(self._request(SERVICE + "?f=json", key))
        info = metadata.get("tileInfo", {})
        sr = info.get("spatialReference", {})
        if (info.get("rows"), info.get("cols")) != (256, 256) or sr.get("latestWkid", sr.get("wkid")) not in (3857, 102100):
            raise EsriError("Nieobsługiwany układ kafelków Esri")
        style = json.loads(self._request(STYLE + "?f=json&echoToken=false", key))
        # Only take attribution, never retain a style document (may contain a token).
        from html import unescape
        import re
        credits = [source.get("attribution", "") for source in style.get("sources", {}).values()]
        credits = list(dict.fromkeys(unescape(re.sub(r"<[^>]*>", "", c)).strip() for c in credits if c))
        credit = "; ".join(credits) or metadata.get("copyrightText", "")
        if not credit or key in credit:
            raise EsriError("Brak poprawnej atrybucji Esri")
        self.attribution = "Powered by Esri | " + credit
        self._validated_key = key

    def tile(self, z, x, y, *, force=False):
        with self._lock:
            key = get_map_api_key("esri")
            if not key:
                self._status = "Brak klucza"
                raise EsriError(self.status)
            if not force and time.monotonic() < self._retry_at:
                raise EsriError(self._status)
            cached = self._tiles.get((int(z), int(x), int(y)))
            if not force and self._validated_key == key and self._status == "Połączono" and cached:
                return cached[0]
            try:
                self._validate(key)
                data = self._request(f"{SERVICE}/tile/{int(z)}/{int(y)}/{int(x)}", key)
                with Image.open(io.BytesIO(data)) as image:
                    if image.size != (256, 256) or image.format not in ("JPEG", "PNG"):
                        raise EsriError("Nieobsługiwany format kafelka Esri")
                    image.load()
                # Do not publish a request completed after key replacement/deletion.
                if get_map_api_key("esri") != key:
                    raise EsriError("Klucz został zmieniony — ponów połączenie")
                self._status = "Połączono"
                if len(self._tiles) >= 256:
                    self._tiles.pop(next(iter(self._tiles)))
                with Image.open(io.BytesIO(data)) as image:
                    self._tiles[(int(z), int(x), int(y))] = (data, image.convert("RGBA"))
                return data
            except EsriError as exc:
                if self._status == "Połączono":
                    self.generation += 1
                    self._tiles.clear()
                self._status = str(exc)
                self._retry_at = time.monotonic() + 30
                raise
            except Exception:
                self._status = "Nieprawidłowy format odpowiedzi Esri"
                self._retry_at = time.monotonic() + 30
                raise EsriError(self._status) from None

    def cached_image(self, z, x, y):
        if self._validated_key != get_map_api_key("esri") or self._status != "Połączono":
            return None
        cached = self._tiles.get((z, x, y))
        if cached is None:
            return None
        return cached[1].copy()

    def test_connection(self):
        try:
            self.tile(0, 0, 0, force=True)
            return True, "Połączono"
        except EsriError as exc:
            return False, str(exc)


esri_client = EsriClient()
