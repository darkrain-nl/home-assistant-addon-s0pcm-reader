"""
S0PCM Reader Main

This application reads pulse counters from S0PCM-2 or S0PCM-5 devices via serial port
and publishes the data (total, today, yesterday) to MQTT (Home Assistant compatible).
"""

import logging
import signal
import sys
import threading
from pathlib import Path
from typing import Any

from pydantic import ValidationError

# ruff: noqa: I001
import config as config_module
from mqtt_handler import TaskDoMQTT
from serial_handler import TaskReadSerial
import state as state_module
from utils import get_version

logger = logging.getLogger(__name__)


def init_args() -> Path:
    """Initialize command-line arguments and configuration paths."""
    return config_module.init_args()


# ------------------------------------------------------------------------------------
# Global Events (for signal handling and test access)
# ------------------------------------------------------------------------------------
trigger = threading.Event()
stopper = threading.Event()


def main() -> None:
    """Main application entry point."""
    global trigger, stopper

    # Initialize Context
    context = state_module.get_context()

    version = get_version()
    context.s0pcm_reader_version = version

    # Signal handling for graceful shutdown
    def signal_handler(signum: int, frame: Any) -> None:
        logger.info(f"Signal {signum} received, stopping...")
        stopper.set()
        trigger.set()  # Wake up threads waiting on trigger

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    config_path = Path(config_module.DEFAULT_CONFIG_DIR)
    if __name__ == "__main__":
        config_path = init_args()  # pragma: no cover

    try:
        # Load Configuration into context
        context.config = config_module.read_config(
            version=context.s0pcm_reader_version, config_dir=config_path
        ).model_dump()
    except ValidationError, Exception:
        logger.error("Fatal exception during startup", exc_info=True)
        sys.exit(1)

    # Register trigger with context
    context.register_trigger(trigger)

    logger.info("Starting s0pcm-reader...")

    # Start our SerialPort thread
    t1 = TaskReadSerial(context, trigger, stopper)
    t1.start()

    # Start our MQTT thread
    t2 = TaskDoMQTT(context, trigger, stopper)
    t2.start()

    # Wait for threads to finish
    while t1.is_alive() or t2.is_alive():
        t1.join(1)
        t2.join(1)

    logger.info("Stop: s0pcm-reader")


if __name__ == "__main__":  # pragma: no cover
    main()
