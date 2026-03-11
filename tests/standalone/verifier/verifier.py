import json
import logging
import os
import socket
import subprocess
import time

import paho.mqtt.client as mqtt

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Verifier")

BROKER = os.getenv("MQTT_HOST", "mqtt")
PORT = int(os.getenv("MQTT_PORT", 1883))
BASE_TOPIC = "s0pcmreader"
METER_ID = 1
INITIAL_TOTAL = 5000

# State tracking
state = {
    # Phase 1: Happy Path
    "phase": 1,
    "connected": False,
    "app_online": False,
    "meter_total": None,
    "initial_total_seen": False,
    "updates_received": 0,
    "discovery_received": False,
    "name_change_acknowledged": False,
    "today_tracked": False,
    # Phase 2: Unhappy Path (Broker restart)
    "broker_restarted": False,
    "app_reconnected": False,
    "error_reported": False,
    "error_cleared": False,
    "post_recovery_increments": 0,
}


def on_connect(client, userdata, flags, rc):
    logging.info(f"Connected to MQTT broker with code {rc}")
    state["connected"] = True
    client.subscribe(f"{BASE_TOPIC}/#")
    client.subscribe("homeassistant/sensor/#")


def on_message(client, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode()

    if topic == f"{BASE_TOPIC}/status":
        if payload == "online":
            if state["phase"] == 1:
                logger.info("✅ App is ONLINE")
                state["app_online"] = True
            elif state["phase"] == 2 and state["broker_restarted"] and not state["app_reconnected"]:
                logger.info("✅ App RECONNECTED after broker restart!")
                state["app_reconnected"] = True

    # Error Topic Checking
    elif topic == f"{BASE_TOPIC}/error":
        if state["phase"] == 2 and state["broker_restarted"]:
            if payload != "No Error" and not state["error_reported"]:
                logger.info(f"✅ App successfully reported error after connection drop: '{payload}'")
                state["error_reported"] = True
            if payload == "No Error" and state["error_reported"] and not state["error_cleared"]:
                logger.info("✅ App successfully cleared error state after 15s timer")
                state["error_cleared"] = True

    # Check for Discovery Config
    elif topic.startswith("homeassistant/sensor/s0pcmreader") and topic.endswith("/config") and state["phase"] == 1:
        try:
            config = json.loads(payload)
            if config.get("name") and config.get("state_topic"):
                if not state["discovery_received"]:
                    logger.info("✅ Home Assistant Discovery received")
                    state["discovery_received"] = True
                if config.get("name") == "TestMeter Total":
                    logger.info("✅ Discovery updated with new name")
        except json.JSONDecodeError:
            pass

    # Standard Topic Checks
    elif topic == f"{BASE_TOPIC}/{METER_ID}/total":
        try:
            val = int(float(payload))
            if state["phase"] == 1:
                if state["meter_total"] is None:
                    state["meter_total"] = val
                    if val >= INITIAL_TOTAL:
                        logger.info(f"✅ Recovery Verified: {val} >= {INITIAL_TOTAL}")
                        state["initial_total_seen"] = True
                    else:
                        logger.error(f"❌ Recovery FAILED: {val} < {INITIAL_TOTAL}")
                else:
                    if val > state["meter_total"]:
                        state["updates_received"] += 1
                    state["meter_total"] = val
            elif state["phase"] == 2 and state["app_reconnected"]:
                if val > state["meter_total"]:
                    logger.info(f"✅ Post-recovery counter incrementing: {state['meter_total']} -> {val}")
                    state["post_recovery_increments"] += 1
                state["meter_total"] = val

        except ValueError:
            pass

    elif topic == f"{BASE_TOPIC}/{METER_ID}/today" and state["phase"] == 1:
        try:
            val = int(float(payload))
            if val > 0 and not state["today_tracked"]:
                logger.info(f"✅ 'Today' tracker is working: {val}")
                state["today_tracked"] = True
        except ValueError:
            pass

    # Split topic checks for dynamic naming
    elif topic == f"{BASE_TOPIC}/TestMeter/total" and state["phase"] == 1:
        try:
            val = int(float(payload))
            if val > 0 and not state["name_change_acknowledged"]:
                logger.info(f"✅ Dynamic Split Topic detected: {val}")
                state["name_change_acknowledged"] = True
        except ValueError:
            pass


def wait_for_broker():
    logger.info("Waiting for MQTT broker...")
    for _ in range(30):
        try:
            with socket.create_connection((BROKER, PORT), timeout=1):
                return True
        except OSError, ConnectionRefusedError:
            time.sleep(1)
    return False


def seed_data():
    logger.info("Seeding retained data...")
    client = mqtt.Client()
    client.connect(BROKER, PORT, 60)
    topic = f"{BASE_TOPIC}/{METER_ID}/total"
    client.publish(topic, str(INITIAL_TOTAL), retain=True)
    logger.info(f"Seeded {topic} = {INITIAL_TOTAL}")
    client.disconnect()


def run():
    if not wait_for_broker():
        logger.error("Broker unreachable")
        exit(1)

    seed_data()

    logger.info("Starting monitoring...")
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER, PORT, 60)
    client.loop_start()

    start_time = time.time()
    # Need a relatively long timeout because Phase 2 clears the error after 15 seconds
    timeout = 90  # seconds

    name_change_sent = False

    while time.time() - start_time < timeout:
        # Phase 1 Operations
        if state["phase"] == 1:
            # Trigger name change
            if (
                not name_change_sent
                and state["app_online"]
                and state["initial_total_seen"]
                and state["updates_received"] >= 2
            ):
                logger.info("Sending dynamic name set command...")
                client.publish(f"{BASE_TOPIC}/{METER_ID}/name/set", "TestMeter", retain=False)
                name_change_sent = True

            # Transition to Phase 2
            if (
                state["app_online"]
                and state["initial_total_seen"]
                and state["updates_received"] >= 3
                and state["discovery_received"]
                and state["today_tracked"]
                and state["name_change_acknowledged"]
            ):
                logger.info("🎉 PHASE 1 PASSED! Transitioning to Phase 2: Unhappy Path")
                state["phase"] = 2
                logger.info("⚠️ Restarting standalone-mqtt-test container to simulate crash...")
                try:
                    subprocess.run(["docker", "restart", "standalone-mqtt-test"], check=True)
                    state["broker_restarted"] = True
                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to restart broker: {e}")
                    exit(1)

        # Phase 2 Operations
        elif state["phase"] == 2:
            if (
                state["broker_restarted"]
                and state["app_reconnected"]
                and state["error_reported"]
                and state["error_cleared"]
                and state["post_recovery_increments"] >= 2
            ):
                logger.info("🎉 PHASE 2 PASSED! ALL CHECKS PASSED!")
                exit(0)

        time.sleep(1)

    logger.error("Timed out waiting for conditions.")
    logger.error(f"State: {state}")
    exit(1)


if __name__ == "__main__":
    run()
