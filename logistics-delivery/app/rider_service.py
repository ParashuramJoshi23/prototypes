from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import LocationHistory, Rider, RiderStatus
from .schemas import RiderCreate, RiderLocationUpdate, RiderStatusUpdate


def create_rider(db: Session, data: RiderCreate) -> Rider:
    rider = Rider(
        name=data.name,
        phone=data.phone,
        vehicle_type=data.vehicle_type,
    )
    db.add(rider)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Phone number '{data.phone}' is already registered")
    db.refresh(rider)
    return rider


def get_rider(db: Session, rider_id: int) -> Optional[Rider]:
    return db.query(Rider).filter(Rider.id == rider_id, Rider.is_active == True).first()


def list_riders(db: Session, status: Optional[RiderStatus] = None) -> list[Rider]:
    q = db.query(Rider).filter(Rider.is_active == True)
    if status:
        q = q.filter(Rider.status == status)
    return q.all()


def update_status(db: Session, rider_id: int, data: RiderStatusUpdate) -> Optional[Rider]:
    rider = get_rider(db, rider_id)
    if not rider:
        return None
    rider.status = data.status
    db.commit()
    db.refresh(rider)
    return rider


def update_location(db: Session, rider_id: int, data: RiderLocationUpdate) -> Optional[Rider]:
    rider = get_rider(db, rider_id)
    if not rider:
        return None

    rider.current_lat = data.lat
    rider.current_lng = data.lng
    rider.last_location_update = datetime.utcnow()

    history = LocationHistory(
        rider_id=rider_id,
        lat=data.lat,
        lng=data.lng,
        order_id=data.order_id,
    )
    db.add(history)
    db.commit()
    db.refresh(rider)
    return rider


def get_active_order_for_rider(db: Session, rider_id: int):
    from .models import Order, OrderStatus

    active_statuses = [
        OrderStatus.RIDER_ASSIGNED,
        OrderStatus.PICKUP_IN_PROGRESS,
        OrderStatus.PICKED_UP,
        OrderStatus.IN_TRANSIT,
    ]
    return (
        db.query(Order)
        .filter(Order.rider_id == rider_id, Order.status.in_(active_statuses))
        .first()
    )


def get_location_history(db: Session, rider_id: int, limit: int = 50) -> list[LocationHistory]:
    return (
        db.query(LocationHistory)
        .filter(LocationHistory.rider_id == rider_id)
        .order_by(LocationHistory.recorded_at.desc())
        .limit(limit)
        .all()
    )
