"""Tests for SCIM 2.0 user provisioning."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import Base, get_db
from app.main import app

TEST_DB_URL = "sqlite:///./test_scim.db"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
settings = get_settings()

SCIM_TOKEN = settings.scim_bearer_token
HEADERS = {"Authorization": f"Bearer {SCIM_TOKEN}"}


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _create_user(client, email="bob@example.com"):
    return client.post(
        "/scim/v2/Users",
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": email,
            "emails": [{"value": email, "primary": True}],
            "active": True,
        },
        headers=HEADERS,
    )


def test_service_provider_config(client):
    resp = client.get("/scim/v2/ServiceProviderConfig", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["patch"]["supported"] is True


def test_create_user(client):
    resp = _create_user(client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["userName"] == "bob@example.com"
    assert data["active"] is True
    assert "id" in data


def test_get_user(client):
    created = _create_user(client).json()
    resp = client.get(f"/scim/v2/Users/{created['id']}", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_list_users(client):
    _create_user(client, "a@example.com")
    _create_user(client, "b@example.com")
    resp = client.get("/scim/v2/Users", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["totalResults"] == 2


def test_filter_user(client):
    _create_user(client, "alice@example.com")
    _create_user(client, "carol@example.com")
    resp = client.get('/scim/v2/Users?filter=userName eq "alice@example.com"', headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["totalResults"] == 1
    assert data["Resources"][0]["userName"] == "alice@example.com"


def test_patch_deactivate(client):
    created = _create_user(client).json()
    resp = client.patch(
        f"/scim/v2/Users/{created['id']}",
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "active", "value": False}],
        },
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["active"] is False


def test_delete_user(client):
    created = _create_user(client).json()
    resp = client.delete(f"/scim/v2/Users/{created['id']}", headers=HEADERS)
    assert resp.status_code == 204

    resp = client.get(f"/scim/v2/Users/{created['id']}", headers=HEADERS)
    assert resp.status_code == 404


def test_unauthorized_without_token(client):
    resp = client.get("/scim/v2/Users")
    assert resp.status_code in (401, 403)
