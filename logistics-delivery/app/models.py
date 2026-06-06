import enum
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    DateTime, Enum as SAEnum, ForeignKey, Text
)
from sqlalchemy.orm import relationship

from .db import Base


class RiderStatus(str, enum.Enum):
    OFFLINE = "offline"
    AVAILABLE = "available"
    BUSY = "busy"


class VehicleType(str, enum.Enum):
    BICYCLE = "bicycle"
    MOTORCYCLE = "motorcycle"
    CAR = "car"


class OrderStatus(str, enum.Enum):
    PLACED = "placed"
    FINDING_RIDER = "finding_rider"
    RIDER_ASSIGNED = "rider_assigned"
    PICKUP_IN_PROGRESS = "pickup_in_progress"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Valid status transitions for the order state machine
ORDER_TRANSITIONS: dict[OrderStatus, list[OrderStatus]] = {
    OrderStatus.PLACED: [OrderStatus.FINDING_RIDER, OrderStatus.CANCELLED],
    OrderStatus.FINDING_RIDER: [OrderStatus.RIDER_ASSIGNED, OrderStatus.FAILED, OrderStatus.CANCELLED],
    OrderStatus.RIDER_ASSIGNED: [OrderStatus.PICKUP_IN_PROGRESS, OrderStatus.FINDING_RIDER, OrderStatus.CANCELLED],
    OrderStatus.PICKUP_IN_PROGRESS: [OrderStatus.PICKED_UP, OrderStatus.FAILED],
    OrderStatus.PICKED_UP: [OrderStatus.IN_TRANSIT],
    OrderStatus.IN_TRANSIT: [OrderStatus.DELIVERED, OrderStatus.FAILED],
    OrderStatus.DELIVERED: [],
    OrderStatus.FAILED: [],
    OrderStatus.CANCELLED: [],
}


class Rider(Base):
    __tablename__ = "riders"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, unique=True, nullable=False)
    vehicle_type = Column(SAEnum(VehicleType), default=VehicleType.MOTORCYCLE)
    status = Column(SAEnum(RiderStatus), default=RiderStatus.OFFLINE, index=True)

    current_lat = Column(Float, nullable=True)
    current_lng = Column(Float, nullable=True)
    last_location_update = Column(DateTime, nullable=True)

    total_deliveries = Column(Integer, default=0)
    rating = Column(Float, default=5.0)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    orders = relationship("Order", back_populates="rider")
    location_history = relationship("LocationHistory", back_populates="rider")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(String, nullable=False, index=True)
    status = Column(SAEnum(OrderStatus), default=OrderStatus.PLACED, index=True)

    pickup_address = Column(Text, nullable=False)
    pickup_lat = Column(Float, nullable=False)
    pickup_lng = Column(Float, nullable=False)

    delivery_address = Column(Text, nullable=False)
    delivery_lat = Column(Float, nullable=False)
    delivery_lng = Column(Float, nullable=False)

    rider_id = Column(Integer, ForeignKey("riders.id"), nullable=True)

    placed_at = Column(DateTime, default=datetime.utcnow)
    assigned_at = Column(DateTime, nullable=True)
    picked_up_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)

    estimated_distance_km = Column(Float, nullable=True)
    estimated_eta_minutes = Column(Integer, nullable=True)
    actual_duration_minutes = Column(Integer, nullable=True)

    notes = Column(Text, nullable=True)
    cancellation_reason = Column(Text, nullable=True)

    rider = relationship("Rider", back_populates="orders")


class DeliveryZone(Base):
    __tablename__ = "delivery_zones"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    center_lat = Column(Float, nullable=False)
    center_lng = Column(Float, nullable=False)
    radius_km = Column(Float, nullable=False)

    is_active = Column(Boolean, default=True)
    surge_multiplier = Column(Float, default=1.0)

    created_at = Column(DateTime, default=datetime.utcnow)


class LocationHistory(Base):
    __tablename__ = "location_history"

    id = Column(Integer, primary_key=True, index=True)
    rider_id = Column(Integer, ForeignKey("riders.id"), nullable=False)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    recorded_at = Column(DateTime, default=datetime.utcnow)
    order_id = Column(Integer, nullable=True)

    rider = relationship("Rider", back_populates="location_history")
