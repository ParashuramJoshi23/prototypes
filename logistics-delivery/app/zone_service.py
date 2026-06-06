from typing import Optional

from sqlalchemy.orm import Session

from .models import DeliveryZone
from .schemas import ZoneCreate, ZoneUpdate
from .utils import is_within_radius


def create_zone(db: Session, data: ZoneCreate) -> DeliveryZone:
    zone = DeliveryZone(**data.model_dump())
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return zone


def get_zone(db: Session, zone_id: int) -> Optional[DeliveryZone]:
    return db.query(DeliveryZone).filter(DeliveryZone.id == zone_id).first()


def list_zones(db: Session, active_only: bool = False) -> list[DeliveryZone]:
    q = db.query(DeliveryZone)
    if active_only:
        q = q.filter(DeliveryZone.is_active == True)
    return q.all()


def update_zone(db: Session, zone_id: int, data: ZoneUpdate) -> Optional[DeliveryZone]:
    zone = get_zone(db, zone_id)
    if not zone:
        return None
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(zone, field, value)
    db.commit()
    db.refresh(zone)
    return zone


def delete_zone(db: Session, zone_id: int) -> bool:
    zone = get_zone(db, zone_id)
    if not zone:
        return False
    db.delete(zone)
    db.commit()
    return True


def check_coverage(
    db: Session, lat: float, lng: float
) -> list[dict]:
    """Return all active zones that cover the given coordinate."""
    zones = db.query(DeliveryZone).filter(DeliveryZone.is_active == True).all()
    matched = []
    for zone in zones:
        if is_within_radius(lat, lng, zone.center_lat, zone.center_lng, zone.radius_km):
            matched.append({
                "zone_id": zone.id,
                "zone_name": zone.name,
                "surge_multiplier": zone.surge_multiplier,
            })
    return matched


def is_deliverable(db: Session, lat: float, lng: float) -> bool:
    """True if the coordinate falls within at least one active delivery zone."""
    return len(check_coverage(db, lat, lng)) > 0
