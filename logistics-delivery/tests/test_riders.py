def test_register_rider(client):
    resp = client.post("/riders", json={
        "name": "Priya Sharma",
        "phone": "9999999999",
        "vehicle_type": "bicycle",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Priya Sharma"
    assert data["status"] == "offline"
    assert data["total_deliveries"] == 0


def test_duplicate_phone_rejected(client, rider):
    resp = client.post("/riders", json={
        "name": "Someone Else",
        "phone": rider["phone"],
        "vehicle_type": "car",
    })
    assert resp.status_code == 409


def test_update_status(client, rider):
    resp = client.patch(f"/riders/{rider['id']}/status", json={"status": "available"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "available"


def test_update_location(client, rider):
    resp = client.post(f"/riders/{rider['id']}/location", json={
        "lat": 12.9716, "lng": 77.5946
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["current_lat"] == 12.9716
    assert data["current_lng"] == 77.5946
    assert data["last_location_update"] is not None


def test_invalid_lat_rejected(client, rider):
    resp = client.post(f"/riders/{rider['id']}/location", json={
        "lat": 200.0, "lng": 77.5946
    })
    assert resp.status_code == 422


def test_list_riders_filter_by_status(client, online_rider):
    resp = client.get("/riders?status=available")
    assert resp.status_code == 200
    riders = resp.json()
    assert all(r["status"] == "available" for r in riders)
    assert any(r["id"] == online_rider["id"] for r in riders)


def test_location_history(client, rider):
    for lat, lng in [(12.97, 77.59), (12.98, 77.60), (12.99, 77.61)]:
        client.post(f"/riders/{rider['id']}/location", json={"lat": lat, "lng": lng})
    resp = client.get(f"/riders/{rider['id']}/location-history")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


def test_rider_not_found(client):
    assert client.get("/riders/9999").status_code == 404
