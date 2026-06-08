"""
Dispatch Engine — core of the logistics system.

Responsibilities:
- Find available riders sorted by distance to pickup
- Assign the nearest rider to an order (with basic optimistic locking)
- Calculate distance and ETA
- Handle re-dispatch when a rider goes offline during assignment
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from .models import Order, OrderStatus, Rider, RiderStatus, ORDER_TRANSITIONS
from .schemas import NearbyRiderResult, DispatchResult
from .utils import haversine, estimate_eta


def find_nearby_riders(
    db: Session,
    lat: float,
    lng: float,
    radius_km: float = 5.0,
    limit: int = 10,
) -> list[NearbyRiderResult]:
    """Return available riders within radius, sorted by distance."""
    riders = (
        db.query(Rider)
        .filter(
            Rider.status == RiderStatus.AVAILABLE,
            Rider.is_active == True,
            Rider.current_lat.isnot(None),
            Rider.current_lng.isnot(None),
        )
        .all()
    )

    results = []
    for rider in riders:
        dist = haversine(lat, lng, rider.current_lat, rider.current_lng)
        if dist <= radius_km:
            eta = estimate_eta(dist, rider.vehicle_type.value)
            results.append(NearbyRiderResult(rider=rider, distance_km=round(dist, 2), eta_minutes=eta))

    results.sort(key=lambda r: r.distance_km)
    return results[:limit]


def dispatch_order(db: Session, order_id: int, search_radius_km: float = 10.0) -> DispatchResult:
    """
    Attempt to assign the nearest available rider to an order.
    Marks the order FINDING_RIDER → RIDER_ASSIGNED on success.
    Falls back to FAILED if no rider is found within radius.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return DispatchResult(order_id=order_id, rider_id=None, success=False, message="Order not found")

    if order.status not in (OrderStatus.PLACED, OrderStatus.FINDING_RIDER):
        return DispatchResult(
            order_id=order_id, rider_id=None, success=False,
            message=f"Order is in status '{order.status}' — cannot dispatch"
        )

    order.status = OrderStatus.FINDING_RIDER
    db.commit()

    candidates = find_nearby_riders(
        db, order.pickup_lat, order.pickup_lng, radius_km=search_radius_km
    )

    if not candidates:
        order.status = OrderStatus.FAILED
        db.commit()
        return DispatchResult(
            order_id=order_id, rider_id=None, success=False,
            message=f"No available riders within {search_radius_km} km"
        )

    best = candidates[0]
    rider = db.query(Rider).filter(Rider.id == best.rider.id).first()

    # Guard against a race: rider may have gone busy between the query and now
    if rider.status != RiderStatus.AVAILABLE:
        # Try next candidates
        for candidate in candidates[1:]:
            rider = db.query(Rider).filter(Rider.id == candidate.rider.id).first()
            if rider.status == RiderStatus.AVAILABLE:
                best = candidate
                break
        else:
            order.status = OrderStatus.FAILED
            db.commit()
            return DispatchResult(
                order_id=order_id, rider_id=None, success=False,
                message="All nearby riders became unavailable — retry later"
            )

    # Total distance: rider → pickup → delivery
    rider_to_pickup = haversine(
        rider.current_lat, rider.current_lng,
        order.pickup_lat, order.pickup_lng,
    )
    pickup_to_delivery = haversine(
        order.pickup_lat, order.pickup_lng,
        order.delivery_lat, order.delivery_lng,
    )
    total_distance = round(rider_to_pickup + pickup_to_delivery, 2)
    eta = estimate_eta(total_distance, rider.vehicle_type.value)

    # Commit assignment atomically
    rider.status = RiderStatus.BUSY
    order.rider_id = rider.id
    order.status = OrderStatus.RIDER_ASSIGNED
    order.assigned_at = datetime.utcnow()
    order.estimated_distance_km = total_distance
    order.estimated_eta_minutes = eta
    db.commit()

    return DispatchResult(
        order_id=order_id,
        rider_id=rider.id,
        success=True,
        message=f"Assigned rider '{rider.name}' (#{rider.id})",
        estimated_distance_km=total_distance,
        estimated_eta_minutes=eta,
    )


def advance_order_status(db: Session, order_id: int, new_status: OrderStatus) -> Optional[Order]:
    """
    Move an order through its state machine.
    Returns the updated order, or None if the transition is invalid.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return None

    allowed = ORDER_TRANSITIONS.get(order.status, [])
    if new_status not in allowed:
        return None

    order.status = new_status

    now = datetime.utcnow()
    if new_status == OrderStatus.PICKED_UP:
        order.picked_up_at = now
    elif new_status == OrderStatus.DELIVERED:
        order.delivered_at = now
        if order.placed_at:
            delta = (now - order.placed_at).total_seconds() / 60
            order.actual_duration_minutes = round(delta)
        # Free up the rider
        if order.rider_id:
            rider = db.query(Rider).filter(Rider.id == order.rider_id).first()
            if rider:
                rider.status = RiderStatus.AVAILABLE
                rider.total_deliveries += 1
    elif new_status in (OrderStatus.FAILED, OrderStatus.CANCELLED):
        # Release rider if one was assigned
        if order.rider_id:
            rider = db.query(Rider).filter(Rider.id == order.rider_id).first()
            if rider and rider.status == RiderStatus.BUSY:
                rider.status = RiderStatus.AVAILABLE

    db.commit()
    db.refresh(order)
    return order


def reassign_order(db: Session, order_id: int) -> DispatchResult:
    """Force re-dispatch — useful when a rider rejects or goes offline."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return DispatchResult(order_id=order_id, rider_id=None, success=False, message="Order not found")

    # Free the current rider if any
    if order.rider_id:
        rider = db.query(Rider).filter(Rider.id == order.rider_id).first()
        if rider and rider.status == RiderStatus.BUSY:
            rider.status = RiderStatus.AVAILABLE
        order.rider_id = None

    order.status = OrderStatus.PLACED
    db.commit()
    return dispatch_order(db, order_id)
