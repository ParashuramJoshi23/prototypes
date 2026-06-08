from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .db import Base, engine, get_db
from .models import Order, OrderStatus, RiderStatus
from .schemas import (
    DispatchResult,
    NearbyRiderQuery,
    NearbyRiderResult,
    OrderCreate,
    OrderResponse,
    OrderStatusUpdate,
    RiderCreate,
    RiderLocationUpdate,
    RiderResponse,
    RiderStatusUpdate,
    ZoneCreate,
    ZoneResponse,
    ZoneUpdate,
)
from . import rider_service, dispatch_engine, zone_service
from .tracking import order_tracking_stream

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Logistics & Delivery Management", version="1.0.0")


# ── Riders ────────────────────────────────────────────────────────────────────

@app.post("/riders", response_model=RiderResponse, status_code=201, tags=["Riders"])
def register_rider(data: RiderCreate, db: Session = Depends(get_db)):
    return rider_service.create_rider(db, data)


@app.get("/riders", response_model=list[RiderResponse], tags=["Riders"])
def list_riders(
    status: RiderStatus | None = Query(None),
    db: Session = Depends(get_db),
):
    return rider_service.list_riders(db, status=status)


@app.get("/riders/{rider_id}", response_model=RiderResponse, tags=["Riders"])
def get_rider(rider_id: int, db: Session = Depends(get_db)):
    rider = rider_service.get_rider(db, rider_id)
    if not rider:
        raise HTTPException(404, "Rider not found")
    return rider


@app.patch("/riders/{rider_id}/status", response_model=RiderResponse, tags=["Riders"])
def update_rider_status(rider_id: int, data: RiderStatusUpdate, db: Session = Depends(get_db)):
    rider = rider_service.update_status(db, rider_id, data)
    if not rider:
        raise HTTPException(404, "Rider not found")
    return rider


@app.post("/riders/{rider_id}/location", response_model=RiderResponse, tags=["Riders"])
def update_rider_location(rider_id: int, data: RiderLocationUpdate, db: Session = Depends(get_db)):
    """Called by the rider app to push GPS coordinates (heartbeat ~every 5s)."""
    rider = rider_service.update_location(db, rider_id, data)
    if not rider:
        raise HTTPException(404, "Rider not found")
    return rider


@app.get("/riders/{rider_id}/active-delivery", response_model=OrderResponse | None, tags=["Riders"])
def rider_active_delivery(rider_id: int, db: Session = Depends(get_db)):
    return rider_service.get_active_order_for_rider(db, rider_id)


@app.get("/riders/{rider_id}/location-history", tags=["Riders"])
def rider_location_history(rider_id: int, limit: int = 50, db: Session = Depends(get_db)):
    return rider_service.get_location_history(db, rider_id, limit)


# ── Orders ────────────────────────────────────────────────────────────────────

@app.post("/orders", response_model=OrderResponse, status_code=201, tags=["Orders"])
def place_order(data: OrderCreate, db: Session = Depends(get_db)):
    """
    Place a new order and immediately attempt rider dispatch.
    The response will already contain the assigned rider and ETA if dispatch succeeds.
    """
    order = Order(**data.model_dump())
    db.add(order)
    db.commit()
    db.refresh(order)

    # Auto-dispatch — non-blocking; status will reflect outcome
    dispatch_engine.dispatch_order(db, order.id)
    db.refresh(order)
    return order


@app.get("/orders", response_model=list[OrderResponse], tags=["Orders"])
def list_orders(
    customer_id: str | None = Query(None),
    status: OrderStatus | None = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Order)
    if customer_id:
        q = q.filter(Order.customer_id == customer_id)
    if status:
        q = q.filter(Order.status == status)
    return q.order_by(Order.placed_at.desc()).all()


@app.get("/orders/{order_id}", response_model=OrderResponse, tags=["Orders"])
def get_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(404, "Order not found")
    return order


@app.patch("/orders/{order_id}/status", response_model=OrderResponse, tags=["Orders"])
def update_order_status(order_id: int, data: OrderStatusUpdate, db: Session = Depends(get_db)):
    """
    Advance an order through the state machine.
    Returns 409 if the requested transition is not allowed from the current state.
    """
    order = dispatch_engine.advance_order_status(db, order_id, data.status)
    if not order:
        existing = db.query(Order).filter(Order.id == order_id).first()
        if not existing:
            raise HTTPException(404, "Order not found")
        raise HTTPException(
            409,
            f"Transition from '{existing.status}' to '{data.status}' is not allowed",
        )
    if data.cancellation_reason and data.status == OrderStatus.CANCELLED:
        order.cancellation_reason = data.cancellation_reason
        db.commit()
        db.refresh(order)
    return order


@app.post("/orders/{order_id}/reassign", response_model=DispatchResult, tags=["Orders"])
def reassign_order(order_id: int, db: Session = Depends(get_db)):
    """Force re-dispatch — use when a rider rejects the job or goes offline."""
    return dispatch_engine.reassign_order(db, order_id)


@app.get("/orders/{order_id}/track", tags=["Orders"])
def track_order(order_id: int):
    """
    SSE stream — connect to receive real-time order and rider location updates.
    Emits a JSON snapshot every 3 seconds until the order reaches a terminal state.
    """
    return StreamingResponse(
        order_tracking_stream(order_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Dispatch ──────────────────────────────────────────────────────────────────

@app.post("/dispatch/nearby-riders", response_model=list[NearbyRiderResult], tags=["Dispatch"])
def nearby_riders(query: NearbyRiderQuery, db: Session = Depends(get_db)):
    """Find available riders within a radius of a given location."""
    return dispatch_engine.find_nearby_riders(
        db, query.lat, query.lng, query.radius_km, query.limit
    )


@app.post("/dispatch/assign/{order_id}", response_model=DispatchResult, tags=["Dispatch"])
def manual_dispatch(order_id: int, search_radius_km: float = 10.0, db: Session = Depends(get_db)):
    """Manually trigger dispatch for a specific order."""
    return dispatch_engine.dispatch_order(db, order_id, search_radius_km)


# ── Zones ─────────────────────────────────────────────────────────────────────

@app.post("/zones", response_model=ZoneResponse, status_code=201, tags=["Zones"])
def create_zone(data: ZoneCreate, db: Session = Depends(get_db)):
    return zone_service.create_zone(db, data)


@app.get("/zones", response_model=list[ZoneResponse], tags=["Zones"])
def list_zones(active_only: bool = False, db: Session = Depends(get_db)):
    return zone_service.list_zones(db, active_only)


@app.get("/zones/check", tags=["Zones"])
def check_zone_coverage(
    lat: float = Query(...),
    lng: float = Query(...),
    db: Session = Depends(get_db),
):
    """Check which delivery zones cover a coordinate, with surge multipliers."""
    covered = zone_service.check_coverage(db, lat, lng)
    return {
        "lat": lat,
        "lng": lng,
        "covered": len(covered) > 0,
        "zones": covered,
    }


@app.get("/zones/{zone_id}", response_model=ZoneResponse, tags=["Zones"])
def get_zone(zone_id: int, db: Session = Depends(get_db)):
    zone = zone_service.get_zone(db, zone_id)
    if not zone:
        raise HTTPException(404, "Zone not found")
    return zone


@app.patch("/zones/{zone_id}", response_model=ZoneResponse, tags=["Zones"])
def update_zone(zone_id: int, data: ZoneUpdate, db: Session = Depends(get_db)):
    zone = zone_service.update_zone(db, zone_id, data)
    if not zone:
        raise HTTPException(404, "Zone not found")
    return zone


@app.delete("/zones/{zone_id}", status_code=204, tags=["Zones"])
def delete_zone(zone_id: int, db: Session = Depends(get_db)):
    if not zone_service.delete_zone(db, zone_id):
        raise HTTPException(404, "Zone not found")
