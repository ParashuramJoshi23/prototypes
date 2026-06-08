import math


EARTH_RADIUS_KM = 6371.0

# Average speeds by vehicle type (km/h) used for ETA estimates
VEHICLE_SPEED_KMH = {
    "bicycle": 15,
    "motorcycle": 30,
    "car": 25,  # lower than motorcycle due to traffic
}


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres between two GPS coordinates."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def estimate_eta(distance_km: float, vehicle_type: str = "motorcycle") -> int:
    """Return estimated travel time in minutes, adding a 5-minute pickup buffer."""
    speed = VEHICLE_SPEED_KMH.get(vehicle_type, 25)
    travel_minutes = (distance_km / speed) * 60
    return max(1, round(travel_minutes + 5))


def is_within_radius(
    point_lat: float, point_lng: float,
    center_lat: float, center_lng: float,
    radius_km: float,
) -> bool:
    return haversine(point_lat, point_lng, center_lat, center_lng) <= radius_km
