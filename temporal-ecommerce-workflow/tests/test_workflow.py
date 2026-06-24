"""Tests for the order workflow and its activities.

Two layers:

1. Activity-level tests (``ActivityEnvironment``) run fully offline — no Temporal
   server needed. They pin down the simulated payment failure-then-recovery.
2. A full workflow integration test (``WorkflowEnvironment.start_time_skipping``)
   exercises the real retry machinery end to end with backoff fast-forwarded. It
   needs Temporal's test-server binary, which is fetched on first run; the test
   skips automatically if that download is unavailable (e.g. offline CI).
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import Worker

from app.activities import (
    process_payment,
    reserve_inventory,
    send_order_confirmation,
)
from app.shared import Order
from app.workflows import OrderWorkflow

TASK_QUEUE = "test-tq"


# --------------------------------------------------------------------------- #
# Activity-level tests (offline)
# --------------------------------------------------------------------------- #
async def test_reserve_inventory_succeeds():
    env = ActivityEnvironment()
    assert await env.run(reserve_inventory, "ORD-1") == {"status": "reserved"}


async def test_payment_fails_on_first_attempt():
    env = ActivityEnvironment()  # default attempt == 1
    with pytest.raises(ApplicationError) as exc:
        await env.run(process_payment, "ORD-1", 9.99)
    assert exc.value.type == "PaymentServiceError"


async def test_payment_succeeds_on_retry():
    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, attempt=2)  # simulate the retry
    result = await env.run(process_payment, "ORD-1", 9.99)
    assert result == {"status": "paid", "attempts": 2}


async def test_send_confirmation_succeeds():
    env = ActivityEnvironment()
    assert await env.run(send_order_confirmation, "a@b.com") == {"status": "sent"}


# --------------------------------------------------------------------------- #
# Full workflow integration test (needs test-server binary)
# --------------------------------------------------------------------------- #
async def _run_order(env: WorkflowEnvironment, order: Order):
    async with Worker(
        env.client,
        task_queue=TASK_QUEUE,
        workflows=[OrderWorkflow],
        activities=[reserve_inventory, process_payment, send_order_confirmation],
    ):
        return await env.client.execute_workflow(
            OrderWorkflow.run,
            order,
            id=f"test-order-{uuid.uuid4()}",
            task_queue=TASK_QUEUE,
        )


async def test_workflow_recovers_from_payment_failure():
    try:
        env_cm = await WorkflowEnvironment.start_time_skipping()
    except RuntimeError as e:  # test-server binary couldn't be downloaded
        pytest.skip(f"Temporal test server unavailable: {e}")

    async with env_cm as env:
        order = Order(
            order_id="ORD-TEST",
            email="test@example.com",
            amount=42.50,
            items=["widget"],
        )
        result = await _run_order(env, order)

    assert result.order_id == "ORD-TEST"
    assert result.inventory_status == "reserved"
    assert result.payment_status == "paid"
    # First payment attempt fails, second succeeds -> Temporal recovered.
    assert result.payment_attempts == 2
    assert result.confirmation_status == "sent"
    assert result.workflow_status == "COMPLETED"
    assert "recovered" in result.summary
