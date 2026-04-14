"""Integrations-Tests für Auth-Endpoints über Flask-Testclient."""
import os
import sys
import tempfile
import pytest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("SECRET_KEY", "test-secret")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server


@pytest.fixture
def client():
    server.app.config["TESTING"] = True
    with server.app.test_client() as c:
        yield c


def test_register_and_login(client):
    # Unique username je Testlauf
    import uuid
    name = "test_" + uuid.uuid4().hex[:8]
    r = client.post("/auth/register", json={"username": name, "password": "supersecret123"})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    # Doppelte Registrierung schlägt fehl
    r2 = client.post("/auth/register", json={"username": name, "password": "supersecret123"})
    assert r2.status_code == 409

    # Login mit korrektem Passwort
    r3 = client.post("/auth/login", json={"username": name, "password": "supersecret123"})
    assert r3.status_code == 200

    # Login mit falschem Passwort
    r4 = client.post("/auth/login", json={"username": name, "password": "wrong"})
    assert r4.status_code == 401


def test_register_validation(client):
    r = client.post("/auth/register", json={"username": "ab", "password": "supersecret123"})
    assert r.status_code == 400  # zu kurzer Username

    r2 = client.post("/auth/register", json={"username": "validname", "password": "short"})
    assert r2.status_code == 400  # zu kurzes Passwort


def test_me_without_session(client):
    r = client.get("/auth/me")
    assert r.status_code == 200
    assert r.get_json()["user"] is None


def test_vapid_public_key_endpoint(client):
    r = client.get("/push/vapid-public-key")
    assert r.status_code == 200
    assert "key" in r.get_json()


def test_meta_legal(client):
    r = client.get("/meta/legal")
    assert r.status_code == 200
    data = r.get_json()
    assert "operator_name" in data
