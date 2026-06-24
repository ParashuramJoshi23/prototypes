"""The order-fulfillment workflow.

Workflow code is *deterministic orchestration* — it must not do I/O directly.
Instead it schedules activities and awaits their durable results. Temporal
records every step in an event history; if the worker crashes mid-flight, the
workflow is replayed from history on another worker and resumes exactly where
it left off. That is the "state persistence" and "recovery" this prototype
demonstrates.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

# Activity/dataclass imports are passed through the workflow sandbox unchanged.
with workflow.unsafe.imports_passed_through():
    from app.activities import (
        process_payment,
        reserve_inventory,
        send_order_confirmation,
    )
    from app.shared import Order, OrderResult


@workflow.defn
class OrderWorkflow:
    @workflow.run
    async def run(self, order: Order) -> OrderResult:
        workflow.logger.info("Starting order workflow for %s", order.order_id)

        # Step 1 — reserve inventory.
        inventory = await workflow.execute_activity(
            reserve_inventory,
            order.order_id,
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # Step 2 — process payment. The retry policy is what gives us automatic
        # recovery: the activity fails on attempt 1 and Temporal reschedules it,
        # backing off before attempt 2 (which succeeds).
        payment = await workflow.execute_activity(
            process_payment,
            args=[order.order_id, order.amount],
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                backoff_coefficient=2.0,
                maximum_interval=timedelta(seconds=10),
                maximum_attempts=5,
            ),
        )

        # Step 3 — send the confirmation email.
        confirmation = await workflow.execute_activity(
            send_order_confirmation,
            order.email,
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        attempts = int(payment.get("attempts", 1))
        recovered = " (payment recovered after a transient failure)" if attempts > 1 else ""
        summary = (
            f"Order {order.order_id} fulfilled: inventory {inventory['status']}, "
            f"payment {payment['status']} in {attempts} attempt(s){recovered}, "
            f"confirmation {confirmation['status']}."
        )

        return OrderResult(
            order_id=order.order_id,
            inventory_status=inventory["status"],
            payment_status=payment["status"],
            payment_attempts=attempts,
            confirmation_status=confirmation["status"],
            workflow_status="COMPLETED",
            summary=summary,
        )
