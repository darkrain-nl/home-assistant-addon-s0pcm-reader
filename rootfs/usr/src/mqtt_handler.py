"""
MQTT Handler

Manages MQTT connection, publishing sensor data, and handling discovery.
"""

import asyncio
from dataclasses import dataclass, field
import json
import logging
import ssl
from typing import Any

import aiomqtt
import paho.mqtt.client as paho_mqtt

from constants import ConnectionStatus, MqttTopicSuffix
import discovery
from recovery import StateRecoverer
import state as state_module

logger = logging.getLogger(__name__)

MAX_PAYLOAD_SIZE = 256

# Background task set to hold strong references (prevents GC of fire-and-forget tasks)
_background_tasks: set[asyncio.Task] = set()

# Map config version strings to paho-mqtt protocol constants (used by aiomqtt internally)
MQTT_VERSION_MAP: dict[str, int] = {
    "3.1": paho_mqtt.MQTTv31,
    "3.1.1": paho_mqtt.MQTTv311,
    "5.0": paho_mqtt.MQTTv5,
}


@dataclass
class MqttTaskState:
    """Internal state for MQTT task."""

    global_discovery_sent: bool = False
    discovered_meters: dict[int, str] = field(default_factory=dict)
    recovery_complete: bool = False
    last_diagnostics: dict[str, Any] = field(default_factory=dict)
    last_info_payload: str | None = None
    last_error_msg: str | None = None


def _resolve_meter_id(context: state_module.AppContext, identifier: str) -> int | None:
    """Resolve a meter identifier (ID or Name) to a numeric Meter ID."""
    try:
        return int(identifier)
    except ValueError:
        for mid, mstate in context.state.meters.items():
            if mstate.name and mstate.name.lower() == identifier.lower():
                return mid
    return None


async def _handle_set_command(context: state_module.AppContext, topic: str, payload: bytes) -> None:
    """Handle a total/set MQTT command."""
    if len(payload) > MAX_PAYLOAD_SIZE:
        context.set_error(f"Ignored oversized payload ({len(payload)} bytes) on {topic}", category="mqtt")
        return
    try:
        parts = topic.split("/")
        identifier = parts[-3]
        meter_id = _resolve_meter_id(context, identifier)

        if meter_id is None:
            context.set_error(f"Ignored set command for unknown meter: {identifier}", category="mqtt")
            return

        payload_str = payload.decode("utf-8")
        try:
            new_total = int(float(payload_str))
        except ValueError:
            context.set_error(
                f"Ignored invalid payload for set command on meter {meter_id}: {payload_str}", category="mqtt"
            )
            return

        logger.info(f"Received MQTT set command for meter {meter_id}. Setting total to {new_total}.")

        if meter_id not in context.state.meters:
            context.state.meters[meter_id] = state_module.MeterState()
        context.state.meters[meter_id].total = new_total
        context.trigger_event.set()

    except Exception as e:
        context.set_error(f"Failed to process MQTT set command: {e}", category="mqtt")


async def _handle_name_set(
    context: state_module.AppContext,
    client: aiomqtt.Client,
    task_state: MqttTaskState,
    topic: str,
    payload: bytes,
) -> None:
    """Handle a name/set MQTT command."""
    if len(payload) > MAX_PAYLOAD_SIZE:
        context.set_error(f"Ignored oversized payload ({len(payload)} bytes) on {topic}", category="mqtt")
        return
    try:
        parts = topic.split("/")
        identifier = parts[-3]
        meter_id = _resolve_meter_id(context, identifier)

        if meter_id is None:
            context.set_error(f"Ignored name/set command for unknown meter: {identifier}", category="mqtt")
            return

        new_name = payload.decode("utf-8").strip()
        # Sanitize MQTT special characters and non-printable characters from meter names
        for char in "/+#":
            new_name = new_name.replace(char, "")
        new_name = "".join(c for c in new_name if c.isprintable())
        if not new_name:
            new_name = None

        logger.info(f"Received MQTT name/set command for meter {meter_id}. Setting name to: {new_name or 'None'}")

        if meter_id not in context.state.meters:
            context.state.meters[meter_id] = state_module.MeterState()
        context.state.meters[meter_id].name = new_name

        # Re-trigger discovery
        await discovery.send_global_discovery(client, context)
        for mid, mstate in context.state.meters.items():
            instancename = await discovery.send_meter_discovery(client, context, mid, mstate)
            if instancename:
                task_state.discovered_meters[mid] = instancename
        task_state.global_discovery_sent = True
        context.trigger_event.set()

    except Exception as e:
        context.set_error(f"Failed to process MQTT name/set command: {e}", category="mqtt")


async def _message_listener(
    context: state_module.AppContext,
    client: aiomqtt.Client,
    task_state: MqttTaskState,
) -> None:
    """Listen for incoming MQTT messages (set commands, name changes)."""
    async for message in client.messages:
        topic = str(message.topic)
        logger.debug(f"MQTT on_message: {topic} {message.payload}")
        if topic.endswith("/total/set"):
            await _handle_set_command(context, topic, message.payload)
        elif topic.endswith("/name/set"):
            await _handle_name_set(context, client, task_state, topic, message.payload)


async def _publish_diagnostics(
    context: state_module.AppContext,
    client: aiomqtt.Client,
    task_state: MqttTaskState,
) -> None:
    """Publish diagnostic information to MQTT."""
    try:
        current_diagnostics = {
            "version": context.s0pcm_reader_version,
            "firmware": context.s0pcm_firmware,
            "startup_time": context.startup_time,
            "port": context.config.serial.port,
        }

        for key, val in current_diagnostics.items():
            if key not in task_state.last_diagnostics or task_state.last_diagnostics[key] != val:
                topic = context.config.mqtt.base_topic + "/" + key
                await client.publish(topic, str(val), retain=context.config.mqtt.retain)
                task_state.last_diagnostics[key] = val

        info_payload = json.dumps(current_diagnostics)
        if task_state.last_info_payload != info_payload:
            await client.publish(
                context.config.mqtt.base_topic + "/info",
                info_payload,
                retain=context.config.mqtt.retain,
            )
            task_state.last_info_payload = info_payload
    except Exception as e:
        logger.error(f"Failed to publish info state to MQTT: {e}")


async def _publish_measurements(
    context: state_module.AppContext,
    client: aiomqtt.Client,
    state_snapshot: state_module.AppState,
    previous_snapshot: state_module.AppState | None,
) -> None:
    """Publish meter measurements to MQTT."""
    # Date
    current_date_str = str(state_snapshot.date)
    previous_date_str = str(previous_snapshot.date) if previous_snapshot else ""
    if current_date_str != previous_date_str:
        await client.publish(context.config.mqtt.base_topic + "/date", current_date_str, retain=True)

    for mid, mstate in state_snapshot.meters.items():
        if not mstate.enabled:
            continue

        instancename = mstate.name if mstate.name else str(mid)
        prev_mstate = previous_snapshot.meters.get(mid) if previous_snapshot else None

        # Internal topics for recovery
        for topic_field in [
            MqttTopicSuffix.TOTAL,
            MqttTopicSuffix.TODAY,
            MqttTopicSuffix.YESTERDAY,
            MqttTopicSuffix.PULSECOUNT,
        ]:
            val = getattr(mstate, topic_field)
            old_val = getattr(prev_mstate, topic_field) if prev_mstate else None
            if val != old_val:
                topic = f"{context.config.mqtt.base_topic}/{mid}/{topic_field}"
                await client.publish(topic, val, retain=True)
                logger.debug(f"MQTT Publish: topic='{topic}', value='{val}'")

        # High-level topics
        jsondata = {}
        for topic_field in [MqttTopicSuffix.TOTAL, MqttTopicSuffix.TODAY, MqttTopicSuffix.YESTERDAY]:
            val = getattr(mstate, topic_field)
            old_val = getattr(prev_mstate, topic_field) if prev_mstate else -1

            if val != old_val or (prev_mstate and mstate.name != prev_mstate.name):
                if context.config.mqtt.split_topic:
                    topic = f"{context.config.mqtt.base_topic}/{instancename}/{topic_field}"
                    await client.publish(topic, val, retain=context.config.mqtt.retain)
                    logger.debug(f"MQTT Publish: topic='{topic}', value='{val}'")
                else:
                    jsondata[topic_field] = val

        # Name state
        if not prev_mstate or mstate.name != prev_mstate.name:
            topic = f"{context.config.mqtt.base_topic}/{mid}/name"
            val = mstate.name if mstate.name else ""
            await client.publish(topic, val, retain=True)
            logger.debug(f"MQTT Publish Name: topic='{topic}', value='{val}'")

        # JSON publish
        if not context.config.mqtt.split_topic and jsondata:
            topic = f"{context.config.mqtt.base_topic}/{instancename}"
            await client.publish(topic, json.dumps(jsondata), retain=context.config.mqtt.retain)
            logger.debug(f"MQTT Publish: topic='{topic}', value='{json.dumps(jsondata)}'")


async def _publish_loop(
    context: state_module.AppContext,
    client: aiomqtt.Client,
    task_state: MqttTaskState,
) -> None:
    """Main publish loop — waits for trigger events and publishes data."""
    previous_snapshot = None

    while True:
        # Take a snapshot of current state for diff-based publishing
        state_snapshot = context.state.model_copy(deep=True)
        error_msg = context.lasterror_share

        if not task_state.global_discovery_sent:
            await discovery.send_global_discovery(client, context)
            # Purge all potential meters first to clear ghosts
            for mid in range(1, 6):
                await discovery.cleanup_meter_discovery(client, context, mid)
            task_state.global_discovery_sent = True

        for mid, mstate in state_snapshot.meters.items():
            current_name = mstate.name if mstate.name else str(mid)
            if mid not in task_state.discovered_meters or task_state.discovered_meters[mid] != current_name:
                instancename = await discovery.send_meter_discovery(client, context, mid, mstate)
                if instancename:
                    task_state.discovered_meters[mid] = instancename

        await _publish_diagnostics(context, client, task_state)
        await _publish_measurements(context, client, state_snapshot, previous_snapshot)

        # Publish Error (only on change)
        try:
            error_to_publish = error_msg if error_msg else "No Error"
            if task_state.last_error_msg != error_to_publish:
                await client.publish(
                    context.config.mqtt.base_topic + "/error",
                    error_to_publish,
                    retain=context.config.mqtt.retain,
                )
                task_state.last_error_msg = error_to_publish

                # If we just successfully published a REAL connection failure, launch a robust
                # 15-second background timer to clear it later, bypassing any rapid serial events.
                # This completely avoids race conditions with HA's state ingestion.
                if error_to_publish != "No Error":

                    async def delayed_clear():
                        await asyncio.sleep(15.0)
                        context.set_error(None, category="mqtt")

                    task = asyncio.create_task(delayed_clear())
                    _background_tasks.add(task)
                    task.add_done_callback(_background_tasks.discard)
        except Exception as e:
            logger.error(f"MQTT Publish Failed for error: {e}")

        previous_snapshot = state_snapshot
        await context.trigger_event.wait()
        context.trigger_event.clear()


def _build_ssl_context(context: state_module.AppContext) -> ssl.SSLContext | None:
    """Build an SSL context from configuration, or None on failure."""
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if context.config.mqtt.tls_ca == "":
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
    else:
        if context.config.mqtt.tls_check_peer:
            ssl_context.verify_mode = ssl.CERT_REQUIRED
            ssl_context.check_hostname = True
        else:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        try:
            ssl_context.load_verify_locations(cafile=context.config.mqtt.tls_ca)
        except Exception as e:
            context.set_error(f"Failed to load TLS CA file '{context.config.mqtt.tls_ca}': {e}", category="mqtt")
            return None
    return ssl_context


async def mqtt_task(context: state_module.AppContext) -> None:
    """Main MQTT task coroutine."""
    task_state = MqttTaskState()

    try:
        while True:
            use_tls = context.config.mqtt.tls
            port = int(context.config.mqtt.tls_port if use_tls else context.config.mqtt.port)
            base_topic = context.config.mqtt.base_topic

            # Build TLS context if needed
            tls_context = None
            if use_tls:
                tls_context = _build_ssl_context(context)
                if tls_context is None:
                    await asyncio.sleep(context.config.mqtt.connect_retry)
                    continue

            # Resolve protocol version
            protocol = MQTT_VERSION_MAP.get(context.config.mqtt.version, paho_mqtt.MQTTv5)

            # Prepare credentials
            username = context.config.mqtt.username.get_secret_value() if context.config.mqtt.username else None
            password = context.config.mqtt.password.get_secret_value() if context.config.mqtt.password else None

            logger.debug(f"Connecting to MQTT Broker '{context.config.mqtt.host}:{port}' (TLS: {use_tls})")

            try:
                async with aiomqtt.Client(
                    hostname=context.config.mqtt.host,
                    port=port,
                    identifier=context.config.mqtt.client_id,
                    username=username,
                    password=password,
                    protocol=protocol,
                    tls_context=tls_context,
                    will=aiomqtt.Will(
                        topic=base_topic + "/status",
                        payload=ConnectionStatus.OFFLINE,
                        retain=True,
                    ),
                ) as client:
                    logger.info("MQTT successfully connected to broker")

                    # Publish online status and subscribe to command topics
                    await client.publish(base_topic + "/status", ConnectionStatus.ONLINE, retain=True)
                    await client.subscribe(base_topic + "/+/total/set")
                    await client.subscribe(base_topic + "/+/name/set")

                    # Recovery phase (only on first connect)
                    if not task_state.recovery_complete:
                        recoverer = StateRecoverer(context, client)
                        await recoverer.run()
                        task_state.recovery_complete = True
                        context.recovery_event.set()

                    # Run listener + publisher concurrently
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(_message_listener(context, client, task_state))
                        tg.create_task(_publish_loop(context, client, task_state))

            except Exception as e:
                err_str = f"MQTT connection failed: {e}"
                context.set_error(err_str, category="mqtt")
                logger.error(err_str)
                # Reset discovery state on disconnect so it re-sends on reconnect
                task_state.global_discovery_sent = False
                task_state.discovered_meters.clear()
                task_state.last_diagnostics.clear()
                task_state.last_info_payload = None
                task_state.last_error_msg = None
                await asyncio.sleep(context.config.mqtt.connect_retry)

    except asyncio.CancelledError:
        logger.info("MQTT Task: Cancelled, shutting down.")
    except Exception:
        logger.error("Fatal MQTT exception", exc_info=True)
