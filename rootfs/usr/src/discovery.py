"""
Discovery Module

Handles MQTT discovery payload generation for Home Assistant.
"""

import json
import logging
from typing import Final

import paho.mqtt.client as mqtt

from state import AppContext, MeterState
import utils

logger = logging.getLogger(__name__)

GLOBAL_DIAGNOSTICS: Final = [
    {"id": "version", "name": "App Version", "icon": "mdi:information-outline"},
    {"id": "firmware", "name": "S0PCM Firmware", "icon": "mdi:chip"},
    {"id": "startup_time", "name": "Startup Time"},
    {"id": "port", "name": "Serial Port", "icon": "mdi:serial-port"},
]


def send_global_discovery(mqttc: mqtt.Client, context: AppContext) -> None:
    """
    Send discovery for global entities (Status, Error, Version, etc.)

    Args:
        mqttc: The connected MQTT client.
        context: Application context.
    """
    if not context.config.mqtt.discovery:
        return

    base_topic = context.config.mqtt.base_topic
    discovery_prefix = context.config.mqtt.discovery_prefix

    device_info = {
        "identifiers": [base_topic],
        "name": "S0PCM Reader",
        "model": "S0PCM",
        "manufacturer": "SmartMeterDashboard",
        "sw_version": context.s0pcm_reader_version,
    }

    # Status Binary Sensor
    status_unique_id = f"s0pcm_{base_topic}_status"
    status_topic = f"{discovery_prefix}/binary_sensor/{base_topic}/{status_unique_id}/config"
    status_payload = {
        "name": "S0PCM Reader Status",
        "unique_id": status_unique_id,
        "device": device_info,
        "device_class": "connectivity",
        "entity_category": "diagnostic",
        "state_topic": base_topic + "/status",
        "payload_on": context.config.mqtt.online,
        "payload_off": context.config.mqtt.offline,
    }
    mqttc.publish(status_topic, json.dumps(status_payload), retain=True)

    # Cleanup legacy
    mqttc.publish(f"{discovery_prefix}/sensor/{base_topic}/s0pcm_{base_topic}_info/config", "", retain=True)
    mqttc.publish(f"{discovery_prefix}/sensor/{base_topic}/s0pcm_{base_topic}_uptime/config", "", retain=True)

    # Error Sensor
    error_unique_id = f"s0pcm_{base_topic}_error"
    error_topic = f"{discovery_prefix}/sensor/{base_topic}/{error_unique_id}/config"
    error_payload = {
        "name": "S0PCM Reader Error",
        "unique_id": error_unique_id,
        "device": device_info,
        "entity_category": "diagnostic",
        "state_topic": base_topic + "/error",
        "icon": "mdi:alert-circle",
        # Force the sensor to stay Available to prevent HA from inheriting device-level offline states
        "availability": [
            {"topic": base_topic + "/status", "value_template": "{{ 'online' }}", "payload_available": "online"}
        ],
    }
    mqttc.publish(error_topic, json.dumps(error_payload), retain=True)

    ha_version = utils.get_ha_core_version()
    ha_version_tuple = utils.parse_ha_version(ha_version)

    # Diagnostics
    for diag in GLOBAL_DIAGNOSTICS:
        diag_unique_id = f"s0pcm_{base_topic}_{diag['id']}"
        diag_topic = f"{discovery_prefix}/sensor/{base_topic}/{diag_unique_id}/config"

        diag_data = dict(diag)
        if diag_data["id"] == "startup_time":
            if ha_version_tuple >= (2025, 5, 0):
                diag_data["class"] = "uptime"
                diag_data["icon"] = "mdi:clock-start"
            else:
                diag_data["class"] = "timestamp"
                diag_data["icon"] = "mdi:clock-outline"

        diag_payload = {
            "name": f"S0PCM Reader {diag_data['name']}",
            "unique_id": diag_unique_id,
            "device": device_info,
            "entity_category": "diagnostic",
            "state_topic": base_topic + "/" + diag_data["id"],
            "value_template": "{{ value }}",
            "force_update": True,
            "icon": diag_data["icon"],
        }
        if "unit" in diag_data:
            diag_payload["unit_of_measurement"] = diag_data["unit"]
        if "class" in diag_data:
            diag_payload["device_class"] = diag_data["class"]
        mqttc.publish(diag_topic, json.dumps(diag_payload), retain=True)

    logger.info("Sent global MQTT discovery messages")


def send_meter_discovery(mqttc: mqtt.Client, context: AppContext, meter_id: int, meter_state: MeterState) -> str | None:
    """
    Send discovery for a specific meter.

    Args:
        mqttc: The connected MQTT client.
        context: Application context.
        meter_id: The unique ID of the meter.
        meter_state: The MeterState object for this meter.

    Returns:
        str | None: The instance name (for tracking), or None if discovery is disabled.
    """
    if not context.config.mqtt.discovery:
        return None

    base_topic = context.config.mqtt.base_topic
    discovery_prefix = context.config.mqtt.discovery_prefix

    device_info = {
        "identifiers": [base_topic],
        "name": "S0PCM Reader",
    }  # Link to global device
    raw_name = meter_state.name
    instancename = str(meter_id) if not raw_name or str(raw_name).lower() == "none" else str(raw_name)
    # Defensive: strip MQTT special characters from topic names
    for char in "/+#":
        instancename = instancename.replace(char, "")

    # Purge obsolete diagnostic sensors (PPS and Activity)
    for p_type, p_key in [("binary_sensor", "activity"), ("sensor", "pps")]:
        p_uid = f"s0pcm_{base_topic}_{meter_id}_{p_key}"
        p_topic = f"{discovery_prefix}/{p_type}/{base_topic}/{p_uid}/config"
        mqttc.publish(p_topic, "", retain=True)

    for subkey in ["total", "today", "yesterday"]:
        unique_id = f"s0pcm_{base_topic}_{meter_id}_{subkey}"
        topic = f"{discovery_prefix}/sensor/{base_topic}/{unique_id}/config"

        payload = {"name": f"{instancename} {subkey.capitalize()}", "unique_id": unique_id, "device": device_info}

        # Availability: sensors go "Unavailable" when addon is offline
        payload["availability_topic"] = base_topic + "/status"
        payload["payload_available"] = "online"
        payload["payload_not_available"] = "offline"

        if subkey in ("total", "today"):
            payload["state_class"] = "total_increasing"
        else:
            payload["state_class"] = "measurement"

        if context.config.mqtt.split_topic:
            payload["state_topic"] = f"{base_topic}/{instancename}/{subkey}"
        else:
            payload["state_topic"] = f"{base_topic}/{instancename}"
            payload["value_template"] = f"{{{{ value_json.{subkey} }}}}"

        # Force refresh
        mqttc.publish(topic, "", retain=True)
        mqttc.publish(topic, json.dumps(payload), retain=True)

        if subkey == "total":
            # Text Entity (Name)
            text_uid = f"s0pcm_{base_topic}_{meter_id}_name_config"
            text_topic = f"{discovery_prefix}/text/{base_topic}/{text_uid}/config"
            text_payload = {
                "name": f"{instancename} Name",
                "unique_id": text_uid,
                "device": device_info,
                "entity_category": "config",
                "command_topic": f"{base_topic}/{meter_id}/name/set",
                "state_topic": f"{base_topic}/{meter_id}/name",
                "icon": "mdi:tag-text-outline",
            }
            mqttc.publish(text_topic, "", retain=True)
            mqttc.publish(text_topic, json.dumps(text_payload), retain=True)

            # Number Entity (Total Correction)
            num_uid = f"s0pcm_{base_topic}_{meter_id}_total_config"
            num_topic = f"{discovery_prefix}/number/{base_topic}/{num_uid}/config"
            num_payload = {
                "name": f"{instancename} Total Correction",
                "unique_id": num_uid,
                "device": device_info,
                "entity_category": "config",
                "command_topic": f"{base_topic}/{meter_id}/total/set",
                "state_topic": f"{base_topic}/{meter_id}/total",
                "min": 0,
                "max": 2147483647,
                "step": 1,
                "mode": "box",
                "icon": "mdi:counter",
            }
            mqttc.publish(num_topic, "", retain=True)
            mqttc.publish(num_topic, json.dumps(num_payload), retain=True)

    logger.info(f"Sent discovery for Meter {meter_id} ({instancename})")
    return instancename


def cleanup_meter_discovery(mqttc: mqtt.Client, context: AppContext, meter_id: int) -> None:
    """
    Clear discovery for a specific meter ID (useful for purging ghost sensors).

    Args:
        mqttc: The connected MQTT client.
        context: Application context.
        meter_id: The ID of the meter to clear.
    """
    if not context.config.mqtt.discovery:
        return

    base_topic = context.config.mqtt.base_topic
    discovery_prefix = context.config.mqtt.discovery_prefix

    # Clear individual sensors
    for subkey in ["total", "today", "yesterday"]:
        unique_id = f"s0pcm_{base_topic}_{meter_id}_{subkey}"
        topic = f"{discovery_prefix}/sensor/{base_topic}/{unique_id}/config"
        mqttc.publish(topic, "", retain=True)

    # Clear configuration entities
    text_uid = f"s0pcm_{base_topic}_{meter_id}_name_config"
    text_topic = f"{discovery_prefix}/text/{base_topic}/{text_uid}/config"
    mqttc.publish(text_topic, "", retain=True)

    num_uid = f"s0pcm_{base_topic}_{meter_id}_total_config"
    num_topic = f"{discovery_prefix}/number/{base_topic}/{num_uid}/config"
    mqttc.publish(num_topic, "", retain=True)

    # Clear obsolete diagnostic sensors
    for p_type, p_key in [("binary_sensor", "activity"), ("sensor", "pps")]:
        p_uid = f"s0pcm_{base_topic}_{meter_id}_{p_key}"
        p_topic = f"{discovery_prefix}/{p_type}/{base_topic}/{p_uid}/config"
        mqttc.publish(p_topic, "", retain=True)

    logger.debug(f"Cleared MQTT discovery for Meter {meter_id}")
