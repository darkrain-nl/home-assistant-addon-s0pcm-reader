"""Main entry point orchestrating serial and MQTT tasks."""

import asyncio
import logging
import signal
import sys
from pathlib import Path

from pydantic import ValidationError

# ruff: noqa: I001
import config as config_module
from mqtt_handler import mqtt_task
from serial_handler import serial_task
import state as state_module
from utils import get_version

logger = logging.getLogger(__name__)


async def main() -> None:
    """Run the main event loop and task lifecycle."""
    context = state_module.get_context()

    version = await get_version()
    context.s0pcm_reader_version = version

    config_path = Path("./")
    if __name__ == "__main__":
        config_path = config_module.init_args()  # pragma: no cover

    try:
        context.config = await config_module.read_config(version=context.s0pcm_reader_version, config_dir=config_path)
    except ValidationError, Exception:
        logger.error("Fatal exception during startup", exc_info=True)
        sys.exit(1)

    logger.info("Starting s0pcm-reader...")

    # Allow graceful shutdown on termination signals.
    loop = asyncio.get_running_loop()

    def signal_handler() -> None:
        logger.info("Signal received, stopping...")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(serial_task(context))
            tg.create_task(mqtt_task(context))
    except* asyncio.CancelledError:
        pass

    logger.info("Stop: s0pcm-reader")


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
