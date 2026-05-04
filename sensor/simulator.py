import socket
import json
import random
import time
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────
UDP_IP   = "127.0.0.1"
UDP_PORT = 9999
DRIVER_ID = "driver_001"
SEND_INTERVAL = 2.0  # seconds

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# ── Reading generators ────────────────────────────────────────────

def generate_alert_reading():
    return {
        "driver_id": DRIVER_ID,
        "state": "alert",
        "blink_rate": round(random.uniform(15, 20), 2),
        "eye_closure_duration": round(random.uniform(0.1, 0.2), 3),
        "head_tilt_angle": round(random.uniform(0, 10), 1),
        "reaction_delay": round(random.uniform(150, 300), 1)
    }

def generate_drowsy_reading():
    return {
        "driver_id": DRIVER_ID,
        "state": "drowsy",
        "blink_rate": round(random.uniform(4, 8), 2),
        "eye_closure_duration": round(random.uniform(0.5, 2.0), 3),
        "head_tilt_angle": round(random.uniform(20, 45), 1),
        "reaction_delay": round(random.uniform(500, 900), 1)
    }

def generate_transition_reading():
    return {
        "driver_id": DRIVER_ID,
        "state": "transitioning",
        "blink_rate": round(random.uniform(8, 15), 2),
        "eye_closure_duration": round(random.uniform(0.2, 0.5), 3),
        "head_tilt_angle": round(random.uniform(10, 20), 1),
        "reaction_delay": round(random.uniform(300, 500), 1)
    }

SCENARIO = (
    [("alert",         generate_alert_reading)]      * 5 +
    [("transitioning", generate_transition_reading)] * 5 +
    [("drowsy",        generate_drowsy_reading)]      * 5
)

STATE_ICONS = {"alert": "🟢", "transitioning": "🟡", "drowsy": "🔴"}

# ── Main loop ─────────────────────────────────────────────────────

print(f"🚗 UDP Sensor Simulator started")
print(f"📡 Sending to {UDP_IP}:{UDP_PORT} every {SEND_INTERVAL}s\n")

cycle = 0
while True:
    state_label, generator = SCENARIO[cycle % len(SCENARIO)]
    reading = generator()

    # Add send timestamp for latency measurement
    reading["sent_at"] = datetime.now(timezone.utc).isoformat()

    payload = json.dumps(reading).encode("utf-8")

    try:
        sock.sendto(payload, (UDP_IP, UDP_PORT))
        icon = STATE_ICONS[state_label]
        print(f"{icon} [{state_label.upper()}] UDP sent "
              f"({len(payload)} bytes) | "
              f"blink={reading['blink_rate']} | "
              f"eye={reading['eye_closure_duration']}s | "
              f"tilt={reading['head_tilt_angle']}° | "
              f"react={reading['reaction_delay']}ms")
    except Exception as e:
        print(f"❌ UDP send error: {e}")

    cycle += 1
    time.sleep(SEND_INTERVAL)




# import requests
# import random
# import time

# API_URL = "http://127.0.0.1:5000/sensor-data"
# DRIVER_ID = "driver_001"

# def generate_alert_reading():
#     """Simulates a fully awake, attentive driver."""
#     return {
#         "driver_id": DRIVER_ID,
#         "state": "alert",
#         "blink_rate": round(random.uniform(15, 20), 2),
#         "eye_closure_duration": round(random.uniform(0.1, 0.2), 3),
#         "head_tilt_angle": round(random.uniform(0, 10), 1),
#         "reaction_delay": round(random.uniform(150, 300), 1)
#     }

# def generate_drowsy_reading():
#     """Simulates a tired, drowsy driver."""
#     return {
#         "driver_id": DRIVER_ID,
#         "state": "drowsy",
#         "blink_rate": round(random.uniform(4, 8), 2),
#         "eye_closure_duration": round(random.uniform(0.5, 2.0), 3),
#         "head_tilt_angle": round(random.uniform(20, 45), 1),
#         "reaction_delay": round(random.uniform(500, 900), 1)
#     }

# def generate_transition_reading():
#     """Simulates the grey zone — driver is getting sleepy."""
#     return {
#         "driver_id": DRIVER_ID,
#         "state": "transitioning",
#         "blink_rate": round(random.uniform(8, 15), 2),
#         "eye_closure_duration": round(random.uniform(0.2, 0.5), 3),
#         "head_tilt_angle": round(random.uniform(10, 20), 1),
#         "reaction_delay": round(random.uniform(300, 500), 1)
#     }

# # Simulate a realistic drive: alert → transitioning → drowsy → alert
# SCENARIO = (
#     [("alert", generate_alert_reading)] * 5 +
#     [("transitioning", generate_transition_reading)] * 5 +
#     [("drowsy", generate_drowsy_reading)] * 5
# )

# STATE_ICONS = {
#     "alert": "🟢",
#     "transitioning": "🟡",
#     "drowsy": "🔴"
# }

# print("🚗 Sensor simulator started (realistic mode)\n")
# print("Pattern: 5× alert → 5× transitioning → 5× drowsy (then repeats)\n")

# cycle = 0
# while True:
#     state_label, generator = SCENARIO[cycle % len(SCENARIO)]
#     reading = generator()

#     icon = STATE_ICONS[state_label]
#     print(f"{icon} [{state_label.upper()}] Sending reading...")

#     try:
#         response = requests.post(API_URL, json=reading)
#         print(f"   ✅ Saved | blink={reading['blink_rate']} | "
#               f"eye={reading['eye_closure_duration']}s | "
#               f"tilt={reading['head_tilt_angle']}° | "
#               f"react={reading['reaction_delay']}ms")
#     except Exception as e:
#         print(f"   ❌ Error: {e}")

#     cycle += 1
#     time.sleep(2)