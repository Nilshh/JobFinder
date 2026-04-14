"""Tests für den In-Memory API-Cache."""
import os
import sys
import time
import tempfile
from unittest.mock import patch, MagicMock

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server


def _fake_response(json_data, status=200):
    m = MagicMock()
    m.json.return_value = json_data
    m.status_code = status
    return m


def setup_function():
    server._api_cache.clear()


def test_cache_hit_avoids_second_network_call():
    with patch("server.requests.get", return_value=_fake_response({"ok": True})) as mock_get:
        d1, s1 = server._cached_api_get("test", "https://example.com", {"q": "x"})
        d2, s2 = server._cached_api_get("test", "https://example.com", {"q": "x"})
    assert d1 == d2 == {"ok": True}
    assert s1 == s2 == 200
    assert mock_get.call_count == 1  # zweiter Aufruf kam aus Cache


def test_cache_miss_on_different_params():
    with patch("server.requests.get", return_value=_fake_response({"ok": True})) as mock_get:
        server._cached_api_get("test", "https://example.com", {"q": "a"})
        server._cached_api_get("test", "https://example.com", {"q": "b"})
    assert mock_get.call_count == 2


def test_cache_skips_error_responses():
    with patch("server.requests.get", return_value=_fake_response({"err": 1}, status=500)) as mock_get:
        server._cached_api_get("test", "https://example.com", {"q": "z"})
        server._cached_api_get("test", "https://example.com", {"q": "z"})
    # Fehler-Antwort wird nicht gecacht → zweiter Aufruf geht wieder raus
    assert mock_get.call_count == 2


def test_cache_expires_after_ttl():
    original_ttl = server._API_CACHE_TTL
    server._API_CACHE_TTL = 0  # sofortiger Ablauf
    try:
        with patch("server.requests.get", return_value=_fake_response({"ok": True})) as mock_get:
            server._cached_api_get("test", "https://example.com", {"q": "ttl"})
            time.sleep(0.01)
            server._cached_api_get("test", "https://example.com", {"q": "ttl"})
        assert mock_get.call_count == 2
    finally:
        server._API_CACHE_TTL = original_ttl
