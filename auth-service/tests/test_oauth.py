"""Tests for OAuth routes — mocks external provider calls."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import AsyncMock, patch

from app.db import Base, get_db
from app.main import app

TEST_DB_URL = "sqlite:///./test_oauth.db"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


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
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


def test_google_login_redirects(client):
    resp = client.get("/oauth/google/login")
    assert resp.status_code == 307
    assert "accounts.google.com" in resp.headers["location"]


def test_github_login_redirects(client):
    resp = client.get("/oauth/github/login")
    assert resp.status_code == 307
    assert "github.com/login/oauth/authorize" in resp.headers["location"]


def test_google_callback(client):
    from app.routers import oauth as oauth_module

    state = "test-state-google"
    oauth_module._STATE_STORE[state] = "google"

    with (
        patch("app.routers.oauth.google_exchange_code", new=AsyncMock(return_value={"access_token": "goog-tok"})),
        patch(
            "app.routers.oauth.google_get_user",
            new=AsyncMock(
                return_value={"sub": "g123", "email": "guser@gmail.com", "name": "G User"}
            ),
        ),
    ):
        resp = client.get(f"/oauth/google/callback?code=authcode&state={state}")

    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data


def test_github_callback(client):
    from app.routers import oauth as oauth_module

    state = "test-state-github"
    oauth_module._STATE_STORE[state] = "github"

    with (
        patch("app.routers.oauth.github_exchange_code", new=AsyncMock(return_value={"access_token": "gh-tok"})),
        patch(
            "app.routers.oauth.github_get_user",
            new=AsyncMock(
                return_value={"id": "gh456", "login": "ghuser", "email": "ghuser@example.com"}
            ),
        ),
    ):
        resp = client.get(f"/oauth/github/callback?code=authcode&state={state}")

    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data


def test_invalid_state(client):
    resp = client.get("/oauth/google/callback?code=x&state=bad-state")
    assert resp.status_code == 400
