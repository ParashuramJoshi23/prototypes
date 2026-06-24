"""Starter — kicks off the workflow with a hardcoded sample order and prints
the structured result.

There is no external input by design: the sample order below is fixed so the
demo is reproducible. Run the worker first, then run this.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict

from temporalio.client import Client

from app.shared import TASK_QUEUE, Order
from app.workflows import OrderWorkflow

TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")

# Hardcoded sample order — no external input.
SAMPLE_ORDER = Order(
    order_id="ORD-1001",
    email="customer@example.com",
    amount=149.99,
    items=["wireless-mouse", "mechanical-keyboard"],
)


async def main() -> None:
    client = await Client.connect(TEMPORAL_ADDRESS)

    print(f"Submitting order {SAMPLE_ORDER.order_id} to Temporal...")
    result = await client.execute_workflow(
        OrderWorkflow.run,
        SAMPLE_ORDER,
        id=f"order-{SAMPLE_ORDER.order_id}",
        task_queue=TASK_QUEUE,
    )

    print("\n=== Final structured result ===")
    print(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
