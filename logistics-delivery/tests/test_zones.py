BANGALORE_CENTER = {"center_lat": 12.9716, "center_lng": 77.5946}


def test_create_zone(client):
    resp = client.post("/zones", json={
        "name": "Bangalore Central",
        **BANGALORE_CENTER,
        "radius_km": 10.0,
        "surge_multiplier": 1.0,
    })
    assert resp.status_code == 201
    assert resp.json()["name"] == "Bangalore Central"


def test_point_inside_zone(client):
    client.post("/zones", json={
        "name": "Test Zone",
        **BANGALORE_CENTER,
        "radius_km": 5.0,
    })
    # Same coordinates → definitely inside
    resp = client.get(f"/zones/check?lat=12.9716&lng=77.5946")
    assert resp.status_code == 200
    data = resp.json()
    assert data["covered"] is True
    assert len(data["zones"]) == 1


def test_point_outside_zone(client):
    client.post("/zones", json={
        "name": "Small Zone",
        **BANGALORE_CENTER,
        "radius_km": 1.0,
    })
    # Chennai is ~350 km away — well outside
    resp = client.get("/zones/check?lat=13.0827&lng=80.2707")
    assert resp.json()["covered"] is False


def test_inactive_zone_not_matched(client):
    resp = client.post("/zones", json={
        "name": "Inactive Zone",
        **BANGALORE_CENTER,
        "radius_km": 50.0,
    })
    zone_id = resp.json()["id"]
    client.patch(f"/zones/{zone_id}", json={"is_active": False})

    resp = client.get(f"/zones/check?lat=12.9716&lng=77.5946")
    assert resp.json()["covered"] is False


def test_surge_multiplier_returned(client):
    client.post("/zones", json={
        "name": "Surge Zone",
        **BANGALORE_CENTER,
        "radius_km": 5.0,
        "surge_multiplier": 1.8,
    })
    resp = client.get("/zones/check?lat=12.9716&lng=77.5946")
    zones = resp.json()["zones"]
    assert zones[0]["surge_multiplier"] == 1.8


def test_update_zone(client):
    zone_id = client.post("/zones", json={
        "name": "Updatable Zone",
        **BANGALORE_CENTER,
        "radius_km": 3.0,
    }).json()["id"]
    resp = client.patch(f"/zones/{zone_id}", json={"radius_km": 8.0, "surge_multiplier": 1.5})
    assert resp.status_code == 200
    assert resp.json()["radius_km"] == 8.0


def test_delete_zone(client):
    zone_id = client.post("/zones", json={
        "name": "Deletable Zone",
        **BANGALORE_CENTER,
        "radius_km": 2.0,
    }).json()["id"]
    assert client.delete(f"/zones/{zone_id}").status_code == 204
    assert client.get(f"/zones/{zone_id}").status_code == 404
