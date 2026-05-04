import socket
import json
import requests
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────
UDP_LISTEN_IP   = "0.0.0.0"
UDP_LISTEN_PORT = 9999
FLASK_API_URL   = "http://127.0.0.1:5000/sensor-data"

# ── Stats ─────────────────────────────────────────────────────────
stats = {
    "received": 0,
    "forwarded": 0,
    "failed": 0,
    "latencies": []
}

def compute_latency(sent_at_iso):
    """Measure time from sensor send to bridge receive in ms."""
    try:
        sent_at = datetime.fromisoformat(sent_at_iso)
        now     = datetime.now(timezone.utc)
        return round((now - sent_at).total_seconds() * 1000, 2)
    except Exception:
        return None

# ── UDP socket ────────────────────────────────────────────────────
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_LISTEN_IP, UDP_LISTEN_PORT))

print(f"🌉 UDP Bridge listening on port {UDP_LISTEN_PORT}")
print(f"🔗 Forwarding to Flask API at {FLASK_API_URL}\n")

while True:
    try:
        data, addr = sock.recvfrom(4096)
        stats["received"] += 1

        # Decode JSON payload
        reading = json.loads(data.decode("utf-8"))

        # Measure latency
        latency = compute_latency(reading.get("sent_at", ""))
        if latency is not None:
            stats["latencies"].append(latency)
            avg_latency = round(
                sum(stats["latencies"]) / len(stats["latencies"]), 2
            )
        else:
            avg_latency = "N/A"

        # Forward to Flask API
        response = requests.post(FLASK_API_URL, json=reading, timeout=3)
        stats["forwarded"] += 1

        print(f"📦 [{stats['received']}] from {addr[0]}:{addr[1]} "
              f"| {len(data)}B "
              f"| latency={latency}ms "
              f"| avg={avg_latency}ms "
              f"| flask={response.status_code} "
              f"| risk={response.json().get('risk_level','?')}")

    except json.JSONDecodeError:
        stats["failed"] += 1
        print(f"⚠️  Invalid JSON received from {addr}")

    except requests.exceptions.RequestException as e:
        stats["failed"] += 1
        print(f"❌ Flask API unreachable: {e}")

    except Exception as e:
        stats["failed"] += 1
        print(f"❌ Unexpected error: {e}")