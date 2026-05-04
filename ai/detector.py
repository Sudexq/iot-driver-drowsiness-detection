import json
import os
import numpy as np
from sklearn.ensemble import IsolationForest

DATA_FILE = "data/readings.json"

FEATURES = [
    'blink_rate',
    'eye_closure_duration',
    'head_tilt_angle',
    'reaction_delay'
]

def load_readings():
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r") as f:
        content = f.read().strip()
        return json.loads(content) if content else []

def extract_features(readings):
    """Pull only the 4 sensor columns into a numpy array."""
    rows = []
    for r in readings:
        if all(k in r for k in FEATURES):
            rows.append([r[k] for k in FEATURES])
    return np.array(rows)

def train_model(X):
    """
    contamination = expected proportion of anomalies.
    0.15 means we expect ~15% of readings to be anomalous.
    """
    model = IsolationForest(
        n_estimators=100,
        contamination=0.15,
        random_state=42
    )
    model.fit(X)
    return model

def predict(model, reading):
    """
    Returns:
      -1 = anomaly (dangerous)
       1 = normal
    """
    X = np.array([[reading[k] for k in FEATURES]])
    prediction = model.predict(X)[0]
    score = model.decision_function(X)[0]  # negative = more anomalous
    return {
        "prediction": int(prediction),
        "anomaly": prediction == -1,
        "anomaly_score": round(float(score), 4)
    }

if __name__ == "__main__":
    # Quick test — run this file directly to see results
    readings = load_readings()
    if len(readings) < 10:
        print("❌ Not enough data. Run the simulator first to collect readings.")
    else:
        print(f"📊 Loaded {len(readings)} readings")
        X = extract_features(readings)
        print(f"🏋️  Training Isolation Forest on {len(X)} samples...")
        model = train_model(X)

        print("\n🔍 Predictions on last 10 readings:\n")
        for r in readings[-10:]:
            result = predict(model, r)
            icon = "🔴 ANOMALY" if result["anomaly"] else "🟢 normal "
            print(f"  {icon} | score={result['anomaly_score']:+.4f} | "
                  f"state={r.get('state','?'):14s} | "
                  f"drowsiness={r.get('drowsiness_score', '?')}")