"""Serial communication task reading and parsing S0PCM packets."""

import asyncio
from dataclasses import dataclass
import datetime
import logging

import serialx

from constants import SerialPacketType
from protocol import parse_s0pcm_packet
import state as state_module

logger = logging.getLogger(__name__)


@dataclass
class SerialTaskState:
    """Internal state tracking for serial connection retries."""

    serialerror: int = 0
    started: bool = False


async def _log_available_ports() -> None:
    """Log available serial ports on connection failure."""
    try:
        ports = await serialx.async_list_serial_ports()
        if ports:
            port_list = ", ".join(p.device for p in ports)
            logger.info(f"Available serial ports: {port_list}")
        else:
            logger.warning("No serial ports detected on system")
    except Exception:
        logger.debug("Unable to enumerate serial ports")


def _handle_header(context: state_module.AppContext, datastr: str) -> None:
    """Parse header packet to extract device firmware version."""
    logger.debug(f"Header Packet: '{datastr}'")
    try:
        if ":" in datastr:
            context.s0pcm_firmware = datastr.split(":", 1)[1].strip()
        else:
            context.s0pcm_firmware = datastr[1:].strip()
    except IndexError:
        context.s0pcm_firmware = datastr


def _update_meter(
    context: state_module.AppContext, meter_id: int, pulsecount: int, pulses_in_interval: int, interval: int
) -> None:
    """Update meter state, handle rollover, and track pulse delta."""
    # Ensure meter state object exists in context.
    if meter_id not in context.state.meters:
        context.state.meters[meter_id] = state_module.MeterState()

    meter = context.state.meters[meter_id]

    # Roll over daily counters when local date changes.
    today = datetime.date.today()
    if context.state.date != today:
        logger.info(f"Day changed from '{context.state.date}' to '{today}', rolling over all counters.")
        for _, m in context.state.meters.items():
            m.yesterday = m.today
            m.today = 0
        context.state.date = today

    # Add positive delta to total and today counters.
    if pulsecount > meter.pulsecount:
        logger.debug(f"Pulsecount changed from '{meter.pulsecount}' to '{pulsecount}' for meter {meter_id}")
        delta = pulsecount - meter.pulsecount
        meter.pulsecount = pulsecount
        meter.total += delta
        meter.today += delta

    elif pulsecount < meter.pulsecount:
        # Handle counter reset or MCU reboot without losing total.
        if pulsecount == 0:
            context.set_error(
                f"S0PCM Reset detected for meter {meter_id}: Pulsecounters cleared. Restoring from total {meter.total}.",
                category="serial",
                level=logging.WARNING,
            )
        else:
            context.set_error(
                f"Pulsecount anomaly detected for meter {meter_id}: Stored pulsecount '{meter.pulsecount}' is higher than read '{pulsecount}'.",
                category="serial",
            )

        delta = pulsecount
        meter.pulsecount = pulsecount
        meter.total += delta
        meter.today += delta

    # Clamp to 32-bit signed max matching HA number entity.
    meter.total = min(meter.total, 2_147_483_647)
    meter.today = min(meter.today, 2_147_483_647)


def _handle_data_packet(context: state_module.AppContext, datastr: str) -> None:
    """Parse serial data telegram and trigger MQTT update."""
    logger.debug(f"S0PCM Packet: '{datastr}'")

    try:
        parsed_data = parse_s0pcm_packet(datastr)
        interval = parsed_data["interval"]
        meters = parsed_data["meters"]
    except (ValueError, KeyError) as e:
        context.set_error(f"Invalid Packet: {e}. Packet: '{datastr}'", category="serial")
        return

    for meter_id, data in meters.items():
        _update_meter(context, meter_id, data["pulsecount"], data["pulses_in_interval"], interval)

    # Clear serial error state upon valid packet.
    context.set_error(None, category="serial")

    # Notify MQTT task of new measurement data.
    context.trigger_event.set()


async def _read_loop(context: state_module.AppContext, ser: serialx.BaseSerial) -> None:
    """Continuous read loop from open serial port."""
    while True:
        try:
            datain = await ser.readline()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            context.set_error(f"Serialport read error: {type(e).__name__}: '{e}'", category="serial")
            break

        if len(datain) == 0:
            # Empty read indicates timeout on serial stream.
            context.set_error("Serialport read timeout: Failed to read any data", category="serial")
            break

        try:
            datastr = datain.decode("ascii").rstrip("\r\n")
        except UnicodeDecodeError:
            context.set_error(f"Failed to decode serial data: '{datain}'", category="serial")
            continue

        match datastr:
            case str(s) if s.startswith(SerialPacketType.HEADER):
                _handle_header(context, datastr)
            case str(s) if s.startswith(SerialPacketType.DATA):
                _handle_data_packet(context, datastr)
            case "":
                logger.warning("Empty Packet received, this can happen during start-up")
            case _:
                context.set_error(f"Invalid Packet: '{datastr}'", category="serial")


async def serial_task(context: state_module.AppContext) -> None:
    """Run serial port reader task after state recovery."""
    task_state = SerialTaskState()

    try:
        # Await MQTT state recovery before accepting new serial pulses.
        logger.info("Serial Task: Waiting for MQTT/HA state recovery...")
        await context.recovery_event.wait()
        logger.info("Serial Task: Recovery complete, starting serial read loop.")

        while True:
            logger.debug(f"Opening serialport '{context.config.serial.port}'")
            try:
                ser = serialx.async_serial_for_url(
                    context.config.serial.port,
                    baudrate=context.config.serial.baudrate,
                    parity=context.config.serial.parity,
                    stopbits=context.config.serial.stopbits,
                    byte_size=context.config.serial.bytesize,
                    read_timeout=context.config.serial.timeout,
                    exclusive=True,
                )
                async with ser:
                    task_state.serialerror = 0
                    logger.info(f"Connected to serialport '{context.config.serial.port}'")
                    if not task_state.started:
                        task_state.started = True
                        logger.info(f"s0pcm-reader v{context.s0pcm_reader_version} started successfully")
                    await _read_loop(context, ser)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                task_state.serialerror += 1
                context.set_error(f"Serialport connection failed: {type(e).__name__}: '{e}'", category="serial")
                if task_state.serialerror == 1:
                    await _log_available_ports()
                logger.error(f"Retry in {context.config.serial.connect_retry} seconds")
                await asyncio.sleep(context.config.serial.connect_retry)
    except asyncio.CancelledError:
        logger.info("Serial Task: Cancelled, shutting down.")
    except Exception:
        logger.error("Fatal exception in Serial Task", exc_info=True)
