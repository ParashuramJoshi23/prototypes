"""
Real-time order tracking via Server-Sent Events (SSE).

Each SSE connection polls DB state and streams a TrackingSnapshot every 3s.
In production this would be backed by a Redis pub/sub channel; here SQLite
serves as the shared state store so it works without extra infrastructure.
"""

import asyncio
import json
from datetime import datetime

from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Order, OrderStatus


def _serialize(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, OrderStatus):
        return obj.value
    raise TypeError(f"not serializable: {type(obj)}")


async def order_tracking_stream(order_id: int):
    """
    Async generator that yields SSE-formatted lines with the latest
    tracking snapshot for the given order.  Stops when the order reaches
    a terminal state or the client disconnects.
    """
    terminal = {OrderStatus.DELIVERED, OrderStatus.FAILED, OrderStatus.CANCELLED}

    while True:
        db: Session = SessionLocal()
        try:
            order: Order | None = db.query(Order).filter(Order.id == order_id).first()

            if order is None:
                payload = json.dumps({"error": "order not found"})
                yield f"event: error\ndata: {payload}\n\n"
                return

            rider_lat = None
            rider_lng = None
            if order.rider:
                rider_lat = order.rider.current_lat
                rider_lng = order.rider.current_lng

            snapshot = {
                "order_id": order.id,
                "status": order.status.value,
                "rider_id": order.rider_id,
                "rider_lat": rider_lat,
                "rider_lng": rider_lng,
                "estimated_eta_minutes": order.estimated_eta_minutes,
                "last_update": datetime.utcnow().isoformat(),
            }
            yield f"data: {json.dumps(snapshot)}\n\n"

            if order.status in terminal:
                yield "event: done\ndata: {}\n\n"
                return
        finally:
            db.close()

        await asyncio.sleep(3)
