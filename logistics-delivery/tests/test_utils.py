import pytest
from app.utils import haversine, estimate_eta, is_within_radius


def test_haversine_same_point():
    assert haversine(12.97, 77.59, 12.97, 77.59) == 0.0


def test_haversine_known_distance():
    # Bangalore to Mumbai ≈ 845 km
    dist = haversine(12.9716, 77.5946, 19.0760, 72.8777)
    assert 840 < dist < 860


def test_estimate_eta_motorcycle():
    # 6 km at 30 km/h = 12 min + 5 buffer = 17 min
    assert estimate_eta(6.0, "motorcycle") == 17


def test_estimate_eta_bicycle():
    # 3 km at 15 km/h = 12 min + 5 = 17 min
    assert estimate_eta(3.0, "bicycle") == 17


def test_estimate_eta_minimum_one():
    assert estimate_eta(0.01, "motorcycle") >= 1


def test_is_within_radius_true():
    assert is_within_radius(12.9716, 77.5946, 12.9716, 77.5946, 1.0)


def test_is_within_radius_false():
    # Bangalore vs Chennai
    assert not is_within_radius(12.9716, 77.5946, 13.0827, 80.2707, 10.0)
