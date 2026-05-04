from flask import Flask, request, jsonify
from datetime import datetime, timezone
import json
import os

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from ai.detector import extract_features, train_model, predict, load_readings as ai_load
import numpy as np

from alerts.alert_manager import evaluate_reading, trigger_alert, load_alerts as load_alert_list

app = Flask(__name__)
DATA_FILE = "data/readings.json"

# ── Scoring logic ─────────────────────────────────────────────────

def score_blink_rate(blink_rate):
    """Normal is 15-20. Too low or too high is bad."""
    if 15 <= blink_rate <= 20:
        return 0.0
    elif blink_rate < 15:
        return min(1.0, (15 - blink_rate) / 10)
    else:
        return min(1.0, (blink_rate - 20) / 10)

def score_eye_closure(duration):
    """Normal is ~0.15s. Longer = worse."""
    normal = 0.15
    max_val = 2.0
    return min(1.0, max(0.0, (duration - normal) / (max_val - normal)))

def score_head_tilt(angle):
    """Normal is 0-10 degrees. Higher = worse."""
    if angle <= 10:
        return 0.0
    return min(1.0, (angle - 10) / 35)

def score_reaction_delay(delay_ms):
    """Normal is 150-300ms. Higher = worse."""
    if delay_ms <= 300:
        return 0.0
    return min(1.0, (delay_ms - 300) / 600)

def calculate_drowsiness_score(data):
    """Combine all sensor scores into a final 0-100 score."""
    s_blink   = score_blink_rate(data['blink_rate'])        * 0.25
    s_eye     = score_eye_closure(data['eye_closure_duration']) * 0.30
    s_tilt    = score_head_tilt(data['head_tilt_angle'])    * 0.25
    s_react   = score_reaction_delay(data['reaction_delay']) * 0.20

    total = (s_blink + s_eye + s_tilt + s_react) * 100
    return round(total, 1)

def get_risk_level(score):
    if score < 40:
        return "alert"
    elif score < 70:
        return "warning"
    else:
        return "danger"

# ── File helpers ──────────────────────────────────────────────────

def load_readings():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            content = f.read().strip()
            if content:
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    print("⚠️  readings.json corrupted, resetting...")
                    return []
    return []

def save_reading(data):
    readings = load_readings()
    readings.append(data)
    with open(DATA_FILE, "w") as f:
        json.dump(readings, f, indent=2)

# ── Endpoints ─────────────────────────────────────────────────────

@app.route('/health', methods=['GET'])
def health():
    readings = load_readings()
    return jsonify({
        "status": "ok",
        "total_readings": len(readings),
        "timestamp": datetime.now(timezone.utc).isoformat()
    }), 200

@app.route('/sensor-data', methods=['POST'])
@app.route('/sensor-data', methods=['POST'])
def receive_data():
    data = request.get_json()
    data['timestamp'] = datetime.now(timezone.utc).isoformat()
    data['drowsiness_score'] = calculate_drowsiness_score(data)
    data['risk_level']       = get_risk_level(data['drowsiness_score'])

    ICONS = {"alert": "🟢", "warning": "🟡", "danger": "🔴"}
    icon = ICONS[data['risk_level']]
    print(f"\n{icon} [{data['timestamp']}]  score={data['drowsiness_score']}  risk={data['risk_level'].upper()}")

    # Run AI if we have enough data
    ai_result = {"anomaly": False, "anomaly_score": 0.0}
    all_readings = load_readings()
    if len(all_readings) >= 10:
        X = extract_features(all_readings)
        model = train_model(X)
        ai_result = predict(model, data)

    # Check alert conditions
    alert = evaluate_reading(data, ai_result)
    if alert:
        trigger_alert(alert)

    save_reading(data)
    return jsonify({
        "status":           "ok",
        "drowsiness_score": data['drowsiness_score'],
        "risk_level":       data['risk_level'],
        "ai_anomaly":       bool(ai_result["anomaly"]),
        "alert_triggered":  alert is not None
    }), 200

@app.route('/readings', methods=['GET'])
def get_readings():
    readings = load_readings()
    limit = request.args.get('limit', default=None, type=int)
    if limit is not None:
        readings = readings[-limit:]
    return jsonify({"total": len(readings), "readings": readings}), 200

@app.route('/readings/summary', methods=['GET'])
def get_summary():
    readings = load_readings()
    if not readings:
        return jsonify({"message": "No data yet"}), 200

    scores = [r['drowsiness_score'] for r in readings if 'drowsiness_score' in r]
    risk_counts = {"alert": 0, "warning": 0, "danger": 0}
    for r in readings:
        level = r.get('risk_level')
        if level in risk_counts:
            risk_counts[level] += 1

    return jsonify({
        "total_readings": len(readings),
        "average_score": round(sum(scores) / len(scores), 1),
        "max_score": max(scores),
        "min_score": min(scores),
        "risk_distribution": risk_counts
    }), 200

# ── Grafana JSON datasource endpoints ────────────────────────────

@app.route('/', methods=['GET'])
def grafana_health():
    return '', 200

@app.route('/grafana/search', methods=['POST'])
def grafana_search():
    return jsonify([
        'drowsiness_score',
        'blink_rate',
        'eye_closure_duration',
        'head_tilt_angle',
        'reaction_delay'
    ]), 200
    
@app.route('/metrics', methods=['POST', 'GET'])
def grafana_metrics():
    return jsonify([
        'drowsiness_score',
        'blink_rate',
        'eye_closure_duration',
        'head_tilt_angle',
        'reaction_delay'
    ]), 200

@app.route('/grafana/query', methods=['POST'])
def grafana_query():
    readings = load_readings()
    if not readings:
        return jsonify([]), 200

    body = request.get_json()
    targets = [t['target'] for t in body.get('targets', [])]

    METRICS = {
        'drowsiness_score':     'drowsiness_score',
        'blink_rate':           'blink_rate',
        'eye_closure_duration': 'eye_closure_duration',
        'head_tilt_angle':      'head_tilt_angle',
        'reaction_delay':       'reaction_delay',
    }

    result = []
    for target in targets:
        field = METRICS.get(target)
        if not field:
            continue
        datapoints = []
        for r in readings:
            if field not in r or 'timestamp' not in r:
                continue
            from datetime import datetime
            ts = datetime.fromisoformat(r['timestamp'])
            epoch_ms = int(ts.timestamp() * 1000)
            datapoints.append([r[field], epoch_ms])
        result.append({"target": target, "datapoints": datapoints})

    return jsonify(result), 200

@app.route('/query', methods=['POST'])
def grafana_query_alias():
    return grafana_query()
    
@app.route('/ai/analyze', methods=['GET'])
def ai_analyze():
    """Train model on all data and return anomaly analysis."""
    readings = load_readings()

    if len(readings) < 10:
        return jsonify({
            "error": "Not enough data yet. Need at least 10 readings."
        }), 400

    X = extract_features(readings)
    model = train_model(X)

    results = []
    for r in readings[-20:]:  # analyze last 20 readings
        result = predict(model, r)
        results.append({
            "timestamp":        r.get("timestamp"),
            "state":            r.get("state"),
            "drowsiness_score": r.get("drowsiness_score"),
            "anomaly":          bool(result["anomaly"]),
            "anomaly_score":    result["anomaly_score"]
        })

    anomaly_count = sum(1 for r in results if r["anomaly"])

    return jsonify({
        "total_analyzed": len(results),
        "anomalies_found": anomaly_count,
        "anomaly_rate": f"{round(anomaly_count / len(results) * 100, 1)}%",
        "results": results
    }), 200
    
@app.route('/alerts', methods=['GET'])
def get_alerts():
    alerts = load_alert_list()
    limit = request.args.get('limit', default=None, type=int)
    if limit:
        alerts = alerts[-limit:]
    return jsonify({
        "total_alerts": len(alerts),
        "alerts": alerts
    }), 200

@app.route('/alerts/latest', methods=['GET'])
def latest_alert():
    alerts = load_alert_list()
    if not alerts:
        return jsonify({"message": "No alerts yet"}), 200
    return jsonify(alerts[-1]), 200

if __name__ == '__main__':
    app.run(debug=True, port=5000)