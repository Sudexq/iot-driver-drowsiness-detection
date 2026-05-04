import socket
import json
import random
import time
import threading
import requests
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────
UDP_IP        = "127.0.0.1"
UDP_PORT      = 9999
FLASK_API_URL = "http://127.0.0.1:5000/sensor-data"
DRIVER_ID     = "driver_001"

# ── Helpers ───────────────────────────────────────────────────────

def make_drowsy_reading():
    return {
        "driver_id": DRIVER_ID,
        "state": "drowsy",
        "blink_rate": round(random.uniform(4, 8), 2),
        "eye_closure_duration": round(random.uniform(0.5, 2.0), 3),
        "head_tilt_angle": round(random.uniform(20, 45), 1),
        "reaction_delay": round(random.uniform(500, 900), 1),
        "sent_at": datetime.now(timezone.utc).isoformat()
    }

def make_alert_reading():
    return {
        "driver_id": DRIVER_ID,
        "state": "alert",
        "blink_rate": round(random.uniform(15, 20), 2),
        "eye_closure_duration": round(random.uniform(0.1, 0.2), 3),
        "head_tilt_angle": round(random.uniform(0, 10), 1),
        "reaction_delay": round(random.uniform(150, 300), 1),
        "sent_at": datetime.now(timezone.utc).isoformat()
    }

def send_udp(sock, reading):
    payload = json.dumps(reading).encode("utf-8")
    sock.sendto(payload, (UDP_IP, UDP_PORT))
    return len(payload)

def print_header(title):
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)

def print_results(results: dict):
    print("\n📊 Results:")
    for k, v in results.items():
        print(f"   {k:<30}: {v}")

# ══════════════════════════════════════════════════════════════════
# EXPERIMENT 1 — Packet Loss
# ══════════════════════════════════════════════════════════════════

def experiment_packet_loss():
    print_header("EXPERIMENT 1: Packet Loss Simulation")
    print("Simulates unreliable IoT wireless channel.")
    print("Tests: how many drowsy alerts are MISSED due to loss?\n")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    loss_rates = [0.0, 0.1, 0.2, 0.3, 0.5]
    packets_per_test = 20

    all_results = []

    for loss_rate in loss_rates:
        sent = 0
        dropped = 0
        delivered = 0
        alerts_missed = 0

        print(f"  Testing loss_rate={int(loss_rate*100)}% ...", end=" ")

        for i in range(packets_per_test):
            reading = make_drowsy_reading()

            if random.random() < loss_rate:
                dropped += 1
                alerts_missed += 1
            else:
                send_udp(sock, reading)
                sent += 1
                delivered += 1
                time.sleep(0.1)

        delivery_rate = round(delivered / packets_per_test * 100, 1)
        miss_rate     = round(alerts_missed / packets_per_test * 100, 1)

        print(f"delivered={delivery_rate}%  missed_alerts={miss_rate}%")
        all_results.append({
            "loss_rate_%":      int(loss_rate * 100),
            "sent":             packets_per_test,
            "delivered":        delivered,
            "dropped":          dropped,
            "delivery_rate_%":  delivery_rate,
            "missed_alerts_%":  miss_rate
        })
        time.sleep(1)

    sock.close()
    print_results({"Summary": "See table above"})

    print("\n📋 Full Table (copy to your report):")
    print(f"  {'Loss%':<10} {'Delivered':<12} {'Dropped':<10} {'Delivery%':<12} {'MissedAlerts%'}")
    print("  " + "-"*58)
    for r in all_results:
        print(f"  {r['loss_rate_%']:<10} "
              f"{r['delivered']:<12} "
              f"{r['dropped']:<10} "
              f"{r['delivery_rate_%']:<12} "
              f"{r['missed_alerts_%']}")

    return all_results

# ══════════════════════════════════════════════════════════════════
# EXPERIMENT 2 — Network Delay / Latency
# ══════════════════════════════════════════════════════════════════

def experiment_latency():
    print_header("EXPERIMENT 2: Network Delay Simulation")
    print("Simulates delayed IoT sensor transmission.")
    print("Tests: how does delay affect alert response time?\n")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    delay_levels = [0, 50, 100, 200, 500]  # ms
    packets_per_test = 10
    all_results = []

    for delay_ms in delay_levels:
        latencies = []
        print(f"  Testing delay={delay_ms}ms ...", end=" ")

        for i in range(packets_per_test):
            reading = make_drowsy_reading()
            reading["sent_at"] = datetime.now(timezone.utc).isoformat()

            # Simulate network delay
            time.sleep(delay_ms / 1000.0)

            send_udp(sock, reading)

            # Measure end-to-end latency
            received_at = datetime.now(timezone.utc)
            sent_at     = datetime.fromisoformat(reading["sent_at"])
            latency_ms  = (received_at - sent_at).total_seconds() * 1000
            latencies.append(round(latency_ms, 2))

            time.sleep(0.1)

        avg_lat = round(sum(latencies) / len(latencies), 2)
        min_lat = round(min(latencies), 2)
        max_lat = round(max(latencies), 2)

        print(f"avg={avg_lat}ms  min={min_lat}ms  max={max_lat}ms")
        all_results.append({
            "injected_delay_ms": delay_ms,
            "avg_latency_ms":    avg_lat,
            "min_latency_ms":    min_lat,
            "max_latency_ms":    max_lat
        })
        time.sleep(0.5)

    sock.close()

    print("\n📋 Full Table (copy to your report):")
    print(f"  {'InjectedDelay':<16} {'AvgLatency':<14} {'MinLatency':<14} {'MaxLatency'}")
    print("  " + "-"*58)
    for r in all_results:
        print(f"  {r['injected_delay_ms']:<16} "
              f"{r['avg_latency_ms']:<14} "
              f"{r['min_latency_ms']:<14} "
              f"{r['max_latency_ms']}")

    return all_results

# ══════════════════════════════════════════════════════════════════
# EXPERIMENT 3 — Burst Traffic
# ══════════════════════════════════════════════════════════════════

def experiment_burst():
    print_header("EXPERIMENT 3: Burst Traffic Simulation")
    print("Simulates sudden surge of sensor readings.")
    print("Tests: can the backend handle rapid sensor bursts?\n")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    burst_sizes = [1, 5, 10, 20, 50]
    all_results = []

    for burst_size in burst_sizes:
        print(f"  Testing burst_size={burst_size} packets ...", end=" ")

        start_time = time.time()
        sent = 0

        for i in range(burst_size):
            reading = make_drowsy_reading()
            send_udp(sock, reading)
            sent += 1

        duration_ms = round((time.time() - start_time) * 1000, 2)
        rate = round(burst_size / (duration_ms / 1000), 1)

        print(f"duration={duration_ms}ms  rate={rate} pkt/s")
        all_results.append({
            "burst_size":    burst_size,
            "duration_ms":   duration_ms,
            "send_rate_pps": rate
        })
        time.sleep(2)  # let backend recover between bursts

    sock.close()

    print("\n📋 Full Table (copy to your report):")
    print(f"  {'BurstSize':<12} {'Duration(ms)':<16} {'Rate(pkt/s)'}")
    print("  " + "-"*42)
    for r in all_results:
        print(f"  {r['burst_size']:<12} "
              f"{r['duration_ms']:<16} "
              f"{r['send_rate_pps']}")

    return all_results

# ══════════════════════════════════════════════════════════════════
# MAIN — run all experiments
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n🔬 IoT Network Experiment Suite")
    print("   Smart Driver Drowsiness Detection System")
    print(f"   Target: {UDP_IP}:{UDP_PORT}\n")
    print("⚠️  Make sure these are running:")
    print("   Terminal 1: python api/app.py")
    print("   Terminal 2: python network/udp_bridge.py\n")

    input("Press ENTER to start experiments...\n")

    r1 = experiment_packet_loss()
    print("\n✅ Experiment 1 complete. Waiting 3s...\n")
    time.sleep(3)

    r2 = experiment_latency()
    print("\n✅ Experiment 2 complete. Waiting 3s...\n")
    time.sleep(3)

    r3 = experiment_burst()
    print("\n✅ Experiment 3 complete.")

    print("\n" + "="*60)
    print("  ALL EXPERIMENTS COMPLETE")
    print("  Copy the tables above into your report.")
    print("="*60)