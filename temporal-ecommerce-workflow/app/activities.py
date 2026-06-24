"""Activities — the side-effecting steps of the order workflow.

Activities are where real-world I/O happens (DB writes, payment API calls,
sending email). Temporal records each activity's result durably, so once an
activity succeeds it is never re-run, even if the workflow later replays.

If an activity raises, Temporal retries it according to the RetryPolicy set on
the call site in the workflow. We exploit this in ``process_payment`` to
simulate a flaky payment gateway that fails the *first* attempt and succeeds on
the retry — letting Temporal demonstrate automatic recovery.
"""

from __future__ import annotations

import asyncio

from temporalio import activity
from temporalio.exceptions import ApplicationError


@activity.defn
async def reserve_inventory(order_id: str) -> dict:
    """Reserve stock for the order. Always succeeds in this demo."""
    activity.logger.info("Reserving inventory for order %s", order_id)
    await asyncio.sleep(0.5)  # pretend to talk to the inventory service
    return {"status": "reserved"}


@activity.defn
async def process_payment(order_id: str, amount: float) -> dict:
    """Charge the customer.

    Simulates a *transient* payment-gateway outage: the first attempt always
    fails, so Temporal automatically retries per the workflow's RetryPolicy.
    ``activity.info().attempt`` is 1-based and survives across retries because
    Temporal tracks attempt count as part of durable activity state — this is
    what lets us deterministically fail once and then recover.
    """
    attempt = activity.info().attempt
    activity.logger.info(
        "Processing payment for order %s ($%.2f) — attempt %d", order_id, amount, attempt
    )
    await asyncio.sleep(0.5)  # pretend to talk to the payment gateway

    if attempt == 1:
        # Transient failure — raised as a retryable ApplicationError so Temporal
        # schedules another attempt instead of failing the workflow.
        activity.logger.warning(
            "Payment gateway timeout for order %s (simulated transient failure)", order_id
        )
        raise ApplicationError(
            "Payment gateway timeout (simulated transient failure)",
            type="PaymentServiceError",
        )

    activity.logger.info("Payment succeeded for order %s on attempt %d", order_id, attempt)
    return {"status": "paid", "attempts": attempt}


@activity.defn
async def send_order_confirmation(email: str) -> dict:
    """Send the order confirmation email. Always succeeds in this demo."""
    activity.logger.info("Sending order confirmation to %s", email)
    await asyncio.sleep(0.5)  # pretend to talk to the email service
    return {"status": "sent"}
