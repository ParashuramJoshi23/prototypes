import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app

TEST_DB_URL = "sqlite:///./test_logistics.db"

engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def rider(client):
    resp = client.post("/riders", json={
        "name": "Arjun Kumar",
        "phone": "9876543210",
        "vehicle_type": "motorcycle",
    })
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture
def online_rider(client, rider):
    # Set rider online with a known location (Bangalore city center)
    client.patch(f"/riders/{rider['id']}/status", json={"status": "available"})
    client.post(f"/riders/{rider['id']}/location", json={"lat": 12.9716, "lng": 77.5946})
    resp = client.get(f"/riders/{rider['id']}")
    return resp.json()


@pytest.fixture
def order_payload():
    return {
        "customer_id": "cust_001",
        "pickup_address": "MG Road, Bangalore",
        "pickup_lat": 12.9750,
        "pickup_lng": 77.6100,
        "delivery_address": "Koramangala, Bangalore",
        "delivery_lat": 12.9352,
        "delivery_lng": 77.6245,
    }
