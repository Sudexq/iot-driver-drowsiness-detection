import json
import os
from datetime import datetime, timezone

ALERTS_FILE = "data/alerts.json"

ALERT_THRESHOLDS = {
    "drowsiness_score": 65,        # 60 → 65
    "min_anomaly_score": -0.08     # sadece güçlü anomaliler
}

def load_alerts():
    if os.path.exists(ALERTS_FILE):
        with open(ALERTS_FILE, "r") as f:
            content = f.read().strip()
            return json.loads(content) if content else []
    return []

def save_alert(alert):
    alerts = load_alerts()
    alerts.append(alert)
    with open(ALERTS_FILE, "w") as f:
        json.dump(alerts, f, indent=2)

def evaluate_reading(reading, ai_result):
    reasons = []

    if reading.get("drowsiness_score", 0) >= ALERT_THRESHOLDS["drowsiness_score"]:
        reasons.append(
            f"High drowsiness score: {reading['drowsiness_score']}"
        )

    anomaly_score = ai_result.get("anomaly_score", 0)
    is_anomaly    = ai_result.get("anomaly", False)

    if is_anomaly and anomaly_score < ALERT_THRESHOLDS["min_anomaly_score"]:
        reasons.append(
            f"AI anomaly detected (score: {anomaly_score})"
        )

    if not reasons:
        return None

    alert = {
        "alert_id":         len(load_alerts()) + 1,
        "timestamp":        reading.get("timestamp"),
        "driver_id":        reading.get("driver_id", "unknown"),
        "drowsiness_score": reading.get("drowsiness_score"),
        "risk_level":       reading.get("risk_level"),
        "ai_anomaly":       bool(ai_result.get("anomaly")),
        "ai_score":         ai_result.get("anomaly_score"),
        "reasons":          reasons,
        "sensor_snapshot": {
            "blink_rate":           reading.get("blink_rate"),
            "eye_closure_duration": reading.get("eye_closure_duration"),
            "head_tilt_angle":      reading.get("head_tilt_angle"),
            "reaction_delay":       reading.get("reaction_delay")
        }
    }
    return alert

def trigger_alert(alert):
    print("\n" + "🚨" * 20)
    print(f"  ALERT #{alert['alert_id']} — {alert['driver_id'].upper()}")
    print(f"  Time     : {alert['timestamp']}")
    print(f"  Score    : {alert['drowsiness_score']}  |  Risk: {alert['risk_level'].upper()}")
    print(f"  AI flag  : {'YES ⚠️' if alert['ai_anomaly'] else 'no'}")
    print(f"  Reasons  :")
    for r in alert['reasons']:
        print(f"    → {r}")
    print("🚨" * 20 + "\n")
    save_alert(alert)
    return alert