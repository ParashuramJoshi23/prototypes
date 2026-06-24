"""Shared types and constants passed across the workflow boundary.

These dataclasses cross the network between the starter, the Temporal server
and the worker, so the default JSON data converter (de)serializes them. Keep
them simple and explicitly typed so reconstruction on the worker side works.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Single task queue shared by the worker (which polls it) and the starter
# (which targets it when kicking off a workflow).
TASK_QUEUE = "ecommerce-order-tq"


@dataclass
class Order:
    """The input to the order workflow — a hardcoded sample is used in the demo."""

    order_id: str
    email: str
    amount: float
    items: list[str] = field(default_factory=list)


@dataclass
class OrderResult:
    """Structured result returned by the workflow once the order is fulfilled."""

    order_id: str
    inventory_status: str
    payment_status: str
    payment_attempts: int
    confirmation_status: str
    workflow_status: str
    summary: str
