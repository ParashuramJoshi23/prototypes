"""Worker process — polls the task queue and runs workflow + activity code.

Run this in one terminal (or via docker compose), then kick off a workflow with
``python -m app.starter``. The worker is what actually executes the Python
functions; the Temporal server only stores state and dispatches work.
"""

from __future__ import annotations

import asyncio
import logging
import os

from temporalio.client import Client
from temporalio.worker import Worker

from app.activities import (
    process_payment,
    reserve_inventory,
    send_order_confirmation,
)
from app.shared import TASK_QUEUE
from app.workflows import OrderWorkflow

TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    client = await Client.connect(TEMPORAL_ADDRESS)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[OrderWorkflow],
        activities=[reserve_inventory, process_payment, send_order_confirmation],
    )

    logging.info("Worker started, polling task queue %r at %s", TASK_QUEUE, TEMPORAL_ADDRESS)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
