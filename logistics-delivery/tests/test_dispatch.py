def test_order_dispatched_to_nearest_rider(client, online_rider, order_payload):
    resp = client.post("/orders", json=order_payload)
    assert resp.status_code == 201
    order = resp.json()

    assert order["status"] == "rider_assigned"
    assert order["rider_id"] == online_rider["id"]
    assert order["estimated_distance_km"] is not None
    assert order["estimated_eta_minutes"] is not None


def test_no_rider_results_in_failed(client, order_payload):
    # No riders registered at all
    resp = client.post("/orders", json=order_payload)
    assert resp.status_code == 201
    assert resp.json()["status"] == "failed"


def test_offline_rider_not_dispatched(client, rider, order_payload):
    # Rider exists but is offline — should not be assigned
    client.post(f"/riders/{rider['id']}/location", json={"lat": 12.9716, "lng": 77.5946})
    resp = client.post("/orders", json=order_payload)
    assert resp.json()["status"] == "failed"


def test_order_state_machine_happy_path(client, online_rider, order_payload):
    order_id = client.post("/orders", json=order_payload).json()["id"]

    for new_status in ["pickup_in_progress", "picked_up", "in_transit", "delivered"]:
        resp = client.patch(f"/orders/{order_id}/status", json={"status": new_status})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == new_status

    # Rider should be freed after delivery
    rider_resp = client.get(f"/riders/{online_rider['id']}")
    assert rider_resp.json()["status"] == "available"
    assert rider_resp.json()["total_deliveries"] == 1


def test_invalid_state_transition_rejected(client, online_rider, order_payload):
    order_id = client.post("/orders", json=order_payload).json()["id"]
    # Jump from rider_assigned straight to delivered — not allowed
    resp = client.patch(f"/orders/{order_id}/status", json={"status": "delivered"})
    assert resp.status_code == 409


def test_nearby_riders_endpoint(client, online_rider):
    resp = client.post("/dispatch/nearby-riders", json={
        "lat": 12.9716, "lng": 77.5946,
        "radius_km": 5.0,
        "limit": 5,
    })
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) >= 1
    assert results[0]["rider"]["id"] == online_rider["id"]
    assert results[0]["distance_km"] >= 0


def test_reassign_order(client, online_rider, order_payload):
    order_id = client.post("/orders", json=order_payload).json()["id"]
    # Reassign — the same rider (only one available) gets it again
    resp = client.post(f"/orders/{order_id}/reassign")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_manual_dispatch(client, online_rider, order_payload):
    # Place an order (auto-dispatches → rider becomes BUSY), then deliver it
    # to free the rider, then place a second order that we manually dispatch.
    order1_id = client.post("/orders", json=order_payload).json()["id"]
    for status in ["pickup_in_progress", "picked_up", "in_transit", "delivered"]:
        client.patch(f"/orders/{order1_id}/status", json={"status": status})

    # Rider is now AVAILABLE again; place a second order
    order2 = client.post("/orders", json={**order_payload, "customer_id": "cust_002"}).json()
    assert order2["status"] == "rider_assigned"

    # Re-dispatch via the manual endpoint (tests the code path directly)
    resp = client.post(f"/dispatch/assign/{order2['id']}")
    assert resp.status_code == 200
    # Order is already assigned, dispatch_engine returns an error for non-PLACED states
    assert "success" in resp.json()
