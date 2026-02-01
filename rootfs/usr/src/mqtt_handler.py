"""
MQTT Handler

Manages MQTT connection, publishing sensor data, and handling discovery.
"""

from dataclasses import dataclass, field
import json
import logging
import ssl
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

from constants import ConnectionStatus, MqttTopicSuffix
import discovery
from recovery import StateRecoverer
import state as state_module

logger = logging.getLogger(__name__)


@dataclass
class MqttTaskState:
    """Internal state for MQTT task."""

    connected: bool = False
    global_discovery_sent: bool = False
    discovered_meters: dict[int, str] = field(default_factory=dict)
    recovery_complete: bool = False
    mqttc: mqtt.Client | None = None
    last_diagnostics: dict[str, Any] = field(default_factory=dict)
    last_info_payload: str | None = None
    last_error_msg: str | None = None


class TaskDoMQTT(threading.Thread):
    """
    Task to handle MQTT communications.

    Responsible for connecting to the broker, performing state recovery on startup,
    subscribing to commands, and publishing meter data and diagnostics.
    """

    def __init__(self, context: state_module.AppContext, trigger: threading.Event, stopper: threading.Event) -> None:
        """
        Initialize the MQTT task.

        Args:
            context: Application context.
            trigger: Event to signal when work (publishing) is needed.
            stopper: Event to signal when the task should stop.
        """
        super().__init__()
        self._trigger = trigger
        self._stopper = stopper
        self._state = MqttTaskState()
        self.app_context = context

    def _recover_state(self) -> None:
        """Startup phase: Use StateRecoverer to restore totals."""
        recoverer = StateRecoverer(self.app_context, self._state.mqttc)
        recoverer.run()
        self._state.recovery_complete = True
        self.app_context.recovery_event.set()

    def on_connect(self, mqttc, obj, flags, reason_code, properties):
        context = self.app_context
        if reason_code == 0:
            self._state.connected = True
            logger.info("MQTT successfully connected to broker")
            self._trigger.set()
            self._state.mqttc.publish(
                context.config["mqtt"]["base_topic"] + "/status",
                ConnectionStatus.ONLINE,
                retain=context.config["mqtt"]["retain"],
            )
            self._state.mqttc.subscribe(context.config["mqtt"]["base_topic"] + "/+/total/set")
            self._state.mqttc.subscribe(context.config["mqtt"]["base_topic"] + "/+/name/set")
        else:
            self._state.connected = False
            context.set_error(f"MQTT failed to connect to broker: {mqtt.connack_string(reason_code)}", category="mqtt")

    def on_disconnect(self, mqttc, obj, flags, reason_code, properties):
        context = self.app_context
        self._state.connected = False
        if reason_code != 0:
            context.set_error(
                f"MQTT failed to disconnect from broker: {mqtt.connack_string(reason_code)}", category="mqtt"
            )
            logger.error(f"MQTT disconnected unexpectedly. Reason: {reason_code}")

    def on_message(self, mqttc, obj, msg):
        logger.debug("MQTT on_message: " + msg.topic + " " + str(msg.qos) + " " + str(msg.payload))
        match msg.topic:
            case str(topic) if topic.endswith("/total/set"):
                self._handle_set_command(msg)
            case str(topic) if topic.endswith("/name/set"):
                self._handle_name_set(msg)

    def _handle_set_command(self, msg):
        context = self.app_context
        try:
            parts = msg.topic.split("/")
            identifier = parts[-3]
            meter_id = None

            try:
                meter_id = int(identifier)
            except ValueError:
                for mid, mstate in context.state.meters.items():
                    if mstate.name and mstate.name.lower() == identifier.lower():
                        meter_id = mid
                        break

            if meter_id is None:
                context.set_error(f"Ignored set command for unknown meter: {identifier}", category="mqtt")
                return

            payload_str = msg.payload.decode("utf-8")
            try:
                new_total = int(float(payload_str))
            except ValueError:
                context.set_error(
                    f"Ignored invalid payload for set command on meter {meter_id}: {payload_str}", category="mqtt"
                )
                return

            logger.info(f"Received MQTT set command for meter {meter_id}. Setting total to {new_total}.")

            with context.lock:
                if meter_id not in context.state.meters:
                    context.state.meters[meter_id] = state_module.MeterState()
                context.state.meters[meter_id].total = new_total
                context.state_share = context.state.model_copy(deep=True)
                self._trigger.set()

        except Exception as e:
            context.set_error(f"Failed to process MQTT set command: {e}", category="mqtt")

    def _handle_name_set(self, msg):
        context = self.app_context
        try:
            parts = msg.topic.split("/")
            identifier = parts[-3]
            meter_id = None

            try:
                meter_id = int(identifier)
            except ValueError:
                for mid, mstate in context.state.meters.items():
                    if mstate.name and mstate.name.lower() == identifier.lower():
                        meter_id = mid
                        break

            if meter_id is None:
                context.set_error(f"Ignored name/set command for unknown meter: {identifier}", category="mqtt")
                return

            new_name = msg.payload.decode("utf-8").strip()
            if not new_name:
                new_name = None

            logger.info(f"Received MQTT name/set command for meter {meter_id}. Setting name to: {new_name or 'None'}")

            with context.lock:
                if meter_id not in context.state.meters:
                    context.state.meters[meter_id] = state_module.MeterState()
                context.state.meters[meter_id].name = new_name
                context.state_share = context.state.model_copy(deep=True)

                # Re-trigger discovery
                discovery.send_global_discovery(self._state.mqttc)
                for mid, mstate in context.state.meters.items():
                    instancename = discovery.send_meter_discovery(self._state.mqttc, mid, mstate.model_dump())
                    if instancename:
                        self._state.discovered_meters[mid] = instancename
                self._state.global_discovery_sent = True
                self._trigger.set()

        except Exception as e:
            context.set_error(f"Failed to process MQTT name/set command: {e}", category="mqtt")

    def _setup_mqtt_client(self, use_tls):
        context = self.app_context
        self._state.mqttc = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=context.config["mqtt"]["client_id"],
            protocol=context.config["mqtt"]["version"],
        )
        self._state.mqttc.on_connect = self.on_connect
        self._state.mqttc.on_disconnect = self.on_disconnect
        self._state.mqttc.on_message = self.on_message

        if context.config["mqtt"]["username"] is not None:
            self._state.mqttc.username_pw_set(context.config["mqtt"]["username"], context.config["mqtt"]["password"])

        if use_tls:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            if context.config["mqtt"]["tls_ca"] == "":
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            else:
                if context.config["mqtt"]["tls_check_peer"]:
                    ssl_context.verify_mode = ssl.CERT_REQUIRED
                    ssl_context.check_hostname = True
                else:
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE

                try:
                    ssl_context.load_verify_locations(cafile=context.config["mqtt"]["tls_ca"])
                except Exception as e:
                    context.set_error(
                        f"Failed to load TLS CA file '{context.config['mqtt']['tls_ca']}': {e}", category="mqtt"
                    )
                    return False
            self._state.mqttc.tls_set_context(context=ssl_context)

        self._state.mqttc.will_set(
            context.config["mqtt"]["base_topic"] + "/status",
            ConnectionStatus.OFFLINE,
            retain=context.config["mqtt"]["retain"],
        )
        return True

    def _connect_loop(self):
        context = self.app_context
        use_tls = context.config["mqtt"]["tls"]
        fallback_happened = False

        while not self._stopper.is_set():
            if not self._state.mqttc and not self._setup_mqtt_client(use_tls):
                time.sleep(context.config["mqtt"]["connect_retry"])
                continue

            port = int(context.config["mqtt"]["tls_port"] if use_tls else context.config["mqtt"]["port"])
            logger.debug(f"Connecting to MQTT Broker '{context.config['mqtt']['host']}:{port}' (TLS: {use_tls})")

            try:
                self._state.mqttc.connect(context.config["mqtt"]["host"], port, 60)
                self._state.mqttc.loop_start()

                timeout = time.time() + 10
                while time.time() < timeout and not self._state.connected and not self._stopper.is_set():
                    time.sleep(0.5)

                if self._state.connected:
                    self._recover_state()
                    return
                else:
                    raise ConnectionError("Timeout waiting for MQTT CONNACK")

            except Exception as e:
                if self._state.mqttc:
                    self._state.mqttc.loop_stop()
                    self._state.mqttc = None
                if use_tls and not fallback_happened:
                    context.set_error(f"MQTT TLS failed: {e}. Falling back to plain.", category="mqtt")
                    use_tls = False
                    fallback_happened = True
                else:
                    context.set_error(f"MQTT connection failed: {e}", category="mqtt")
                    logger.error(f"MQTT connection failed with exception: {e}", exc_info=True)
                    time.sleep(context.config["mqtt"]["connect_retry"])

    def _publish_diagnostics(self):
        context = self.app_context
        try:
            current_diagnostics = {
                "version": context.s0pcm_reader_version,
                "firmware": context.s0pcm_firmware,
                "startup_time": context.startup_time,
                "port": context.config["serial"]["port"],
            }

            for key, val in current_diagnostics.items():
                if key not in self._state.last_diagnostics or self._state.last_diagnostics[key] != val:
                    topic = context.config["mqtt"]["base_topic"] + "/" + key
                    self._state.mqttc.publish(topic, str(val), retain=context.config["mqtt"]["retain"])
                    self._state.last_diagnostics[key] = val

            info_payload = json.dumps(current_diagnostics)
            if self._state.last_info_payload != info_payload:
                self._state.mqttc.publish(
                    context.config["mqtt"]["base_topic"] + "/info",
                    info_payload,
                    retain=context.config["mqtt"]["retain"],
                )
                self._state.last_info_payload = info_payload
        except Exception as e:
            logger.error(f"Failed to publish info state to MQTT: {e}")

    def _publish_measurements(
        self, state_snapshot: state_module.AppState, previous_snapshot: state_module.AppState | None
    ):
        context = self.app_context

        # Date
        current_date_str = str(state_snapshot.date)
        previous_date_str = str(previous_snapshot.date) if previous_snapshot else ""
        if current_date_str != previous_date_str:
            self._state.mqttc.publish(context.config["mqtt"]["base_topic"] + "/date", current_date_str, retain=True)

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
                    topic = f"{context.config['mqtt']['base_topic']}/{mid}/{topic_field}"
                    self._state.mqttc.publish(topic, val, retain=True)
                    logger.debug(f"MQTT Publish: topic='{topic}', value='{val}'")

            # High-level topics
            jsondata = {}
            for topic_field in [MqttTopicSuffix.TOTAL, MqttTopicSuffix.TODAY, MqttTopicSuffix.YESTERDAY]:
                val = getattr(mstate, topic_field)
                old_val = getattr(prev_mstate, topic_field) if prev_mstate else -1

                if val != old_val or (prev_mstate and mstate.name != prev_mstate.name):
                    if context.config["mqtt"]["split_topic"]:
                        topic = f"{context.config['mqtt']['base_topic']}/{instancename}/{field}"
                        self._state.mqttc.publish(topic, val, retain=context.config["mqtt"]["retain"])
                        logger.debug(f"MQTT Publish: topic='{topic}', value='{val}'")
                    else:
                        jsondata[field] = val

            # Name state
            if not prev_mstate or mstate.name != prev_mstate.name:
                topic = f"{context.config['mqtt']['base_topic']}/{mid}/name"
                val = mstate.name if mstate.name else ""
                self._state.mqttc.publish(topic, val, retain=True)
                logger.debug(f"MQTT Publish Name: topic='{topic}', value='{val}'")

            # JSON publish
            if not context.config["mqtt"]["split_topic"] and jsondata:
                topic = f"{context.config['mqtt']['base_topic']}/{instancename}"
                self._state.mqttc.publish(topic, json.dumps(jsondata), retain=context.config["mqtt"]["retain"])
                logger.debug(f"MQTT Publish: topic='{topic}', value='{json.dumps(jsondata)}'")

    def _main_loop(self):
        context = self.app_context
        previous_snapshot = None

        while not self._stopper.is_set():
            with context.lock:
                state_snapshot = context.state_share.model_copy(deep=True)
                error_msg = context.lasterror_share

            if not self._state.connected:
                return

            if not self._state.global_discovery_sent:
                discovery.send_global_discovery(self._state.mqttc)
                # Purge all potential meters first to clear ghosts
                for mid in range(1, 6):
                    discovery.cleanup_meter_discovery(self._state.mqttc, mid)
                self._state.global_discovery_sent = True

            for mid, mstate in state_snapshot.meters.items():
                current_name = mstate.name if mstate.name else str(mid)
                if mid not in self._state.discovered_meters or self._state.discovered_meters[mid] != current_name:
                    instancename = discovery.send_meter_discovery(self._state.mqttc, mid, mstate.model_dump())
                    if instancename:
                        self._state.discovered_meters[mid] = instancename

            self._publish_diagnostics()
            self._publish_measurements(state_snapshot, previous_snapshot)

            # Publish Error (only on change)
            try:
                error_to_publish = error_msg if error_msg else "No Error"
                if self._state.last_error_msg != error_to_publish:
                    self._state.mqttc.publish(
                        context.config["mqtt"]["base_topic"] + "/error",
                        error_to_publish,
                        retain=context.config["mqtt"]["retain"],
                    )
                    self._state.last_error_msg = error_to_publish

                if self._state.connected and error_msg is None:
                    context.set_error(None, category="mqtt", trigger_event=False)
            except Exception as e:
                logger.error(f"MQTT Publish Failed for error: {e}")

            previous_snapshot = state_snapshot
            self._trigger.wait()
            self._trigger.clear()

    def run(self):
        context = self.app_context
        try:
            while not self._stopper.is_set():
                self._connect_loop()
                self._main_loop()
                if self._state.mqttc:
                    if self._state.connected:
                        self._state.mqttc.publish(
                            context.config["mqtt"]["base_topic"] + "/status",
                            ConnectionStatus.OFFLINE,
                            retain=context.config["mqtt"]["retain"],
                        )
                    self._state.mqttc.loop_stop()
                    self._state.mqttc.disconnect()
                    self._state.mqttc = None
        except Exception:
            logger.error("Fatal MQTT exception", exc_info=True)
        finally:
            self._stopper.set()
