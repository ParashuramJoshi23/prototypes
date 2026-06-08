"""Tests for username/password auth and JWT refresh."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app

TEST_DB_URL = "sqlite:///./test_auth.db"
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
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_register(client):
    resp = client.post("/auth/register", json={"email": "alice@example.com", "password": "secret123"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "alice@example.com"
    assert "id" in data


def test_register_duplicate_email(client):
    body = {"email": "alice@example.com", "password": "secret123"}
    client.post("/auth/register", json=body)
    resp = client.post("/auth/register", json=body)
    assert resp.status_code == 409


def test_login(client):
    client.post("/auth/register", json={"email": "alice@example.com", "password": "secret123"})
    resp = client.post("/auth/login", json={"email": "alice@example.com", "password": "secret123"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client):
    client.post("/auth/register", json={"email": "alice@example.com", "password": "secret123"})
    resp = client.post("/auth/login", json={"email": "alice@example.com", "password": "wrong"})
    assert resp.status_code == 401


def test_me(client):
    client.post("/auth/register", json={"email": "alice@example.com", "password": "secret123"})
    login = client.post("/auth/login", json={"email": "alice@example.com", "password": "secret123"})
    token = login.json()["access_token"]

    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "alice@example.com"


def test_me_no_token(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_refresh_token(client):
    client.post("/auth/register", json={"email": "alice@example.com", "password": "secret123"})
    login = client.post("/auth/login", json={"email": "alice@example.com", "password": "secret123"})
    refresh_token = login.json()["refresh_token"]

    resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["refresh_token"] != refresh_token  # token was rotated


def test_refresh_token_replay(client):
    """A refresh token cannot be used twice (rotation invalidates it)."""
    client.post("/auth/register", json={"email": "alice@example.com", "password": "secret123"})
    login = client.post("/auth/login", json={"email": "alice@example.com", "password": "secret123"})
    refresh_token = login.json()["refresh_token"]

    client.post("/auth/refresh", json={"refresh_token": refresh_token})
    resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 401
