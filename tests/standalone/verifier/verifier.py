import logging
import os
import socket
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
    "connected": False,
    "app_online": False,
    "meter_total": None,
    "meter_pulsecount": None,
    "initial_total_seen": False,
    "updates_received": 0,
}


def on_connect(client, userdata, flags, rc):
    logging.info(f"Connected to MQTT broker with code {rc}")
    state["connected"] = True
    client.subscribe(f"{BASE_TOPIC}/#")


def on_message(client, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode()

    # logger.info(f"MSG: {topic} = {payload}")

    if topic == f"{BASE_TOPIC}/status":
        if payload == "online":
            logger.info("✅ App is ONLINE")
            state["app_online"] = True

    elif topic == f"{BASE_TOPIC}/{METER_ID}/total":
        try:
            val = int(float(payload))
            logger.info(f"Meter Total: {val}")

            if state["meter_total"] is None:
                state["meter_total"] = val
                # Verify recovery (must be >= what we seeded)
                if val >= INITIAL_TOTAL:
                    logger.info(f"✅ Recovery Verified: {val} >= {INITIAL_TOTAL}")
                    state["initial_total_seen"] = True
                else:
                    logger.error(f"❌ Recovery FAILED: {val} < {INITIAL_TOTAL}")
            else:
                if val > state["meter_total"]:
                    logger.info(f"✅ Counter incrementing: {state['meter_total']} -> {val}")
                    state["updates_received"] += 1
                state["meter_total"] = val

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
    # Use a temporary client to seed data
    client = mqtt.Client()
    client.connect(BROKER, PORT, 60)

    # Seed Total (Recovery Test)
    topic = f"{BASE_TOPIC}/{METER_ID}/total"
    client.publish(topic, str(INITIAL_TOTAL), retain=True)
    logger.info(f"Seeded {topic} = {INITIAL_TOTAL}")

    client.disconnect()


def run():
    if not wait_for_broker():
        logger.error("Broker unreachable")
        exit(1)

    seed_data()

    # Give app time to start AFTER seeding
    logger.info("Starting monitoring...")

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER, PORT, 60)
    client.loop_start()

    # Wait loop
    start_time = time.time()
    timeout = 45  # seconds

    while time.time() - start_time < timeout:
        if state["app_online"] and state["initial_total_seen"] and state["updates_received"] >= 3:
            logger.info("🎉 ALL CHECKS PASSED!")
            exit(0)
        time.sleep(1)

    logger.error("Timed out waiting for conditions.")
    logger.error(f"State: {state}")
    exit(1)


if __name__ == "__main__":
    run()
