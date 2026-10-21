"""BYOK tests use only synthetic secrets and a mocked HTTP transport."""
import io
import json
import socket
import urllib.error
from unittest.mock import patch

import pytest
from PIL import Image
from src.integrations import credential_store as store
from src.integrations.esri import EsriClient, EsriError, SERVICE, STYLE
from src.map_providers import MapProviderRegistry, mask_url


@pytest.fixture(autouse=True)
def credentials():
    previous = store._FORCE_MOCK
    store.set_mock_mode(True)
    store._MOCK_STORE.clear()
    yield
    store._MOCK_STORE.clear()
    store.set_mock_mode(previous)


def tile_bytes():
    image = Image.new("RGB", (256, 256), (10, 40, 90))
    buf = io.BytesIO()
    image.save(buf, "JPEG")
    return buf.getvalue()


class Response(io.BytesIO):
    pass


def good_response(request, **kwargs):
    if request.full_url.startswith(STYLE):
        return Response(json.dumps({"sources": {"imagery": {"attribution": "Esri, Test imagery provider"}}}).encode())
    if "/tile/" in request.full_url:
        return Response(tile_bytes())
    return Response(json.dumps({"tileInfo": {"rows": 256, "cols": 256,
                     "spatialReference": {"wkid": 102100, "latestWkid": 3857}}}).encode())


def test_save_replace_restart_delete_and_aliases(monkeypatch):
    monkeypatch.setenv("ESRI_API_KEY", "ambient-must-not-resurrect")
    assert store.get_map_api_key("esri") is None
    assert store.save_map_api_key("esri", "synthetic-first")
    assert store.get_map_api_key("satellite") == "synthetic-first"
    assert store.save_map_api_key("satellite", "synthetic-second")
    assert store.get_map_api_key("esri") == "synthetic-second"
    assert store.delete_map_api_key("esri")
    assert store.get_map_api_key("satellite") is None


def test_authentication_scheme_xyz_and_image():
    store.save_map_api_key("esri", "synthetic-secret")
    client = EsriClient()
    with patch("urllib.request.urlopen", side_effect=good_response) as http:
        data = client.tile(16, 36500, 21000)
        assert Image.open(io.BytesIO(data)).size == (256, 256)
        requests = [c.args[0] for c in http.call_args_list]
        style = next(r for r in requests if r.full_url.startswith(STYLE))
        assert style.get_header("Authorization") == "Bearer synthetic-secret"
        assert "echoToken=false" in style.full_url
        assert "synthetic-secret" not in style.full_url
        tile = next(r for r in requests if "/tile/" in r.full_url)
        assert "/tile/16/21000/36500?token=" in tile.full_url
        assert "synthetic-secret" not in mask_url(tile.full_url)
        assert "synthetic-secret" not in MapProviderRegistry.format_tile_url("satellite",16,36500,21000)
        assert client.cached_image(16,36500,21000) is not None
        store.delete_map_api_key("esri")
        assert client.cached_image(16,36500,21000) is None


@pytest.mark.parametrize("code,phrase", [(400,"400"),(401,"Nieprawidłowy"),(403,"Brak uprawnień"),
    (429,"429"),(500,"5xx"),(503,"5xx"),(498,"wygasł"),(499,"Brak klucza")])
def test_safe_errors_and_backoff(code, phrase):
    store.save_map_api_key("esri", "synthetic-secret")
    client = EsriClient()
    error = urllib.error.HTTPError(SERVICE+"?token=synthetic-secret",code,"synthetic-secret",{},None)
    with patch("urllib.request.urlopen", side_effect=error) as http:
        ok, message = client.test_connection()
        assert not ok and phrase in message and "synthetic-secret" not in message
        with pytest.raises(EsriError) as exc:
            client.tile(0,0,0)
        assert "synthetic-secret" not in str(exc.value)
        assert http.call_count == 1


@pytest.mark.parametrize("error,phrase", [(socket.timeout(),"czas"),
    (urllib.error.URLError("synthetic-secret"),"Brak internetu")])
def test_timeout_offline(error,phrase):
    store.save_map_api_key("esri", "synthetic-secret")
    with patch("urllib.request.urlopen",side_effect=error):
        ok, message = EsriClient().test_connection()
    assert not ok and phrase in message and "synthetic-secret" not in message


def test_missing_key_no_network():
    with patch("urllib.request.urlopen") as http:
        ok, message = EsriClient().test_connection()
        assert not ok and "Brak klucza" in message
        http.assert_not_called()


def test_arcgis_json_error_even_when_http_200():
    store.save_map_api_key("esri", "synthetic-secret")
    with patch("urllib.request.urlopen",return_value=Response(b'{"error":{"code":498,"message":"Token expired synthetic-secret"}}')):
        assert EsriClient().test_connection() == (False,"Klucz wygasł")


def test_invalid_key_never_downloads_a_tile():
    store.save_map_api_key("esri", "synthetic-secret")
    def response(request, **kwargs):
        if request.full_url.startswith(STYLE):
            return Response(b'{"error":{"code":401,"message":"Invalid"}}')
        return good_response(request, **kwargs)
    with patch("urllib.request.urlopen", side_effect=response) as http:
        assert not EsriClient().test_connection()[0]
        assert not any("/tile/" in c.args[0].full_url for c in http.call_args_list)


def test_old_disk_cache_not_used_and_no_disk_write(tmp_path):
    from src.moving_map import TileCache
    cache = TileCache(tmp_path)
    with patch("src.integrations.esri.esri_client", EsriClient()):
        cache.put(0,0,0,"satellite",tile_bytes())
        assert cache.get(0,0,0,"satellite") is None
        assert not cache.has(0,0,0,"satellite")
        import sqlite3
        with sqlite3.connect(str(cache._db)) as db:
            assert db.execute("select count(*) from tiles where style='satellite'").fetchone()[0] == 0


def test_other_provider_does_not_receive_esri_key():
    store.save_map_api_key("esri","synthetic-secret")
    for style in ("osm","light_all","custom"):
        assert "synthetic-secret" not in MapProviderRegistry.format_tile_url(style,0,0,0)


def test_replacement_invalidates_and_uses_new_key_without_restart():
    store.save_map_api_key("esri", "synthetic-first")
    client = EsriClient()
    with patch("urllib.request.urlopen", side_effect=good_response) as http:
        client.tile(0,0,0)
        previous_calls = http.call_count
        client.tile(0,0,0)
        assert http.call_count == previous_calls  # deduplicated session tile
        store.save_map_api_key("esri", "synthetic-second")
        client.credentials_changed()
        assert client.cached_image(0,0,0) is None
        client.tile(0,0,0)
        assert http.call_count == previous_calls * 2
        assert http.call_args.args[0].get_header("Authorization") == "Bearer synthetic-second"


def test_errors_do_not_leak_through_map_downloader(capsys):
    from src.moving_map import _download_tile_raw
    store.save_map_api_key("esri", "synthetic-secret")
    with patch("src.integrations.esri.esri_client", EsriClient()):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("synthetic-secret")):
            assert _download_tile_raw(0,0,0,"satellite") is None
    captured = capsys.readouterr()
    assert "synthetic-secret" not in captured.out + captured.err


def test_reject_malformed_tile_without_echoing_response():
    store.save_map_api_key("esri", "synthetic-secret")
    def response(request, **kwargs):
        if "/tile/" in request.full_url:
            return Response(b"synthetic-secret: not an image")
        return good_response(request, **kwargs)
    with patch("urllib.request.urlopen", side_effect=response):
        ok, message = EsriClient().test_connection()
        assert not ok and "synthetic-secret" not in message
