from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from .models import OrderStatus, RiderStatus, VehicleType


# ── Rider ─────────────────────────────────────────────────────────────────────

class RiderCreate(BaseModel):
    name: str
    phone: str
    vehicle_type: VehicleType = VehicleType.MOTORCYCLE


class RiderStatusUpdate(BaseModel):
    status: RiderStatus


class RiderLocationUpdate(BaseModel):
    lat: float
    lng: float
    order_id: Optional[int] = None

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not -90 <= v <= 90:
            raise ValueError("latitude must be between -90 and 90")
        return v

    @field_validator("lng")
    @classmethod
    def validate_lng(cls, v: float) -> float:
        if not -180 <= v <= 180:
            raise ValueError("longitude must be between -180 and 180")
        return v


class RiderResponse(BaseModel):
    id: int
    name: str
    phone: str
    vehicle_type: VehicleType
    status: RiderStatus
    current_lat: Optional[float]
    current_lng: Optional[float]
    last_location_update: Optional[datetime]
    total_deliveries: int
    rating: float
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Order ─────────────────────────────────────────────────────────────────────

class OrderCreate(BaseModel):
    customer_id: str
    pickup_address: str
    pickup_lat: float
    pickup_lng: float
    delivery_address: str
    delivery_lat: float
    delivery_lng: float
    notes: Optional[str] = None


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    cancellation_reason: Optional[str] = None


class OrderResponse(BaseModel):
    id: int
    customer_id: str
    status: OrderStatus
    pickup_address: str
    pickup_lat: float
    pickup_lng: float
    delivery_address: str
    delivery_lat: float
    delivery_lng: float
    rider_id: Optional[int]
    placed_at: datetime
    assigned_at: Optional[datetime]
    picked_up_at: Optional[datetime]
    delivered_at: Optional[datetime]
    estimated_distance_km: Optional[float]
    estimated_eta_minutes: Optional[int]
    actual_duration_minutes: Optional[int]
    notes: Optional[str]
    cancellation_reason: Optional[str]

    model_config = {"from_attributes": True}


# ── Zone ──────────────────────────────────────────────────────────────────────

class ZoneCreate(BaseModel):
    name: str
    center_lat: float
    center_lng: float
    radius_km: float
    surge_multiplier: float = 1.0


class ZoneUpdate(BaseModel):
    name: Optional[str] = None
    radius_km: Optional[float] = None
    is_active: Optional[bool] = None
    surge_multiplier: Optional[float] = None


class ZoneResponse(BaseModel):
    id: int
    name: str
    center_lat: float
    center_lng: float
    radius_km: float
    is_active: bool
    surge_multiplier: float
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Dispatch ──────────────────────────────────────────────────────────────────

class NearbyRiderQuery(BaseModel):
    lat: float
    lng: float
    radius_km: float = 5.0
    limit: int = 10


class NearbyRiderResult(BaseModel):
    rider: RiderResponse
    distance_km: float
    eta_minutes: int


class DispatchResult(BaseModel):
    order_id: int
    rider_id: Optional[int]
    success: bool
    message: str
    estimated_distance_km: Optional[float] = None
    estimated_eta_minutes: Optional[int] = None


# ── Tracking ──────────────────────────────────────────────────────────────────

class TrackingSnapshot(BaseModel):
    order_id: int
    status: OrderStatus
    rider_id: Optional[int]
    rider_lat: Optional[float]
    rider_lng: Optional[float]
    estimated_eta_minutes: Optional[int]
    last_update: datetime
