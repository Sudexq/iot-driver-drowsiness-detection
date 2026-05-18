# 🚗 AI-Driven IoT Driver Drowsiness Detection System

An end-to-end IoT system that detects driver drowsiness in real time using behavioral
sensor data, UDP networking, hybrid AI models, and live Grafana visualization.

---

## 🎯 Project Overview

Driver fatigue is responsible for a significant proportion of road accidents worldwide.
This system monitors driver behavior continuously and raises alerts when drowsiness is
detected — using either a live webcam or a simulated sensor as the data source.

The project covers the full IoT stack: data acquisition, network transport, backend
processing, machine learning, alerting, and dashboard visualization. Network reliability
experiments (packet loss, latency, burst traffic) are included and analyzed with Wireshark.

---

## 🧠 Key Features

- **Dual input modes** — live webcam (Dlib EAR) or synthetic simulator, plug-and-play interchangeable
- **UDP-based IoT transport** — real network datagrams, visible in Wireshark
- **HMAC-SHA256 security** — every packet is signed; replay attacks are blocked by nonce guard
- **Flask backend API** — receives, scores, and stores every reading
- **Rule-based drowsiness scoring** — transparent, explainable 0–100 score
- **Isolation Forest** — unsupervised anomaly detection (no labels required)
- **Real-time alert system** — triggers on score threshold or AI anomaly flag, with audio alarm
- **Grafana dashboard** — live visualization of all sensor metrics
- **Network experiments** — packet loss, latency, burst traffic with measured results
- **Wireshark traffic analysis** — UDP packet capture and protocol inspection

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────┐
│              INPUT LAYER                    │
│                                             │
│  [Webcam]  →  camera/camera_detector.py     │
│      OR                                     │
│  [Synthetic]  →  sensor/simulator.py        │
└─────────────────┬───────────────────────────┘
                  │ UDP port 9999
                  │ + HMAC-SHA256 signature
                  ▼
┌─────────────────────────────────────────────┐
│           network/udp_bridge.py             │
│   Verifies HMAC · blocks replay attacks     │
│   Measures latency · forwards via HTTP POST │
└─────────────────┬───────────────────────────┘
                  │ HTTP POST port 5000
                  │ + API Key header
                  ▼
┌─────────────────────────────────────────────┐
│              api/app.py                     │
│   • Timestamps each reading                 │
│   • Rule-based drowsiness score (0–100)     │
│   • Isolation Forest anomaly detection      │
│   • Saves to data/readings.json             │
└──────┬──────────────────────┬───────────────┘
       │                      │
       ▼                      ▼
┌─────────────┐     ┌──────────────────────────┐
│alert_manager│     │      Grafana             │
│alerts.json  │     │  Live dashboard (5s)     │
│sound_alert  │     └──────────────────────────┘
└─────────────┘
```

---

## 📷 Camera-Based Detection (Dlib EAR)

### `camera/camera_detector.py`

Opens the webcam and detects drowsiness using the **Eye Aspect Ratio (EAR)** algorithm
with Dlib's 68-point facial landmark model. EAR drops sharply when eyes close —
this is more reliable than Haar Cascade eye detection.

#### What it detects

| Signal | Method | Alert threshold |
|---|---|---|
| Eye closure | Dlib EAR (68 landmarks) | EAR < 0.15 for > 2s |
| Blink rate | Rolling 60s window | < 6 or > 30 /min |
| Head tilt (horizontal) | Eye corner angle | > 15° for > 4s |
| Head tilt (forward) | Nose–chin distance ratio | Normalised drop |
| Both hands raised | Skin contour detection | 2 contours UP > 1.5s |

#### Calibration

Run before first use to find your personal EAR threshold:

```bash
python camera/calibrate_ear.py
```

Default threshold: `EAR_THRESHOLD = 0.15`

#### UDP output — every 1 second

```json
{
  "driver_id":            "driver_camera_001",
  "state":                "alert",
  "blink_rate":           17.2,
  "eye_closure_duration": 0.142,
  "head_tilt_angle":      3.1,
  "head_tilt_duration":   0.0,
  "reaction_delay":       250.0,
  "source":               "camera",
  "nonce":                "a3f2c1d4-...",
  "sent_at":              "2026-05-18T14:33:54+00:00"
}
```

---

## 🔒 Security Layer

Every UDP packet is protected by three mechanisms:

| Mechanism | Implementation | Purpose |
|---|---|---|
| HMAC-SHA256 | `security/crypto.py` | Integrity + authenticity |
| Nonce | UUID4 per packet | Replay attack prevention |
| API Key | `security/auth.py` | Flask endpoint access control |

Secrets are stored in `.env` (never committed to git):

```
IOT_HMAC_SECRET=<strong-random-value>
IOT_API_KEY=<strong-random-value>
```

---

## 📊 Sensor Fields

| Field | Description | Alert range | Drowsy range |
|---|---|---|---|
| `blink_rate` | Blinks per minute | 15–20 | below 6 |
| `eye_closure_duration` | Eye closed duration in seconds | 0.10–0.40 s | above 2.0 s |
| `head_tilt_angle` | Head angle in degrees | 0–15° | above 25° |
| `head_tilt_duration` | Seconds head has been tilted | 0 s | above 4 s |
| `reaction_delay` | Response time in milliseconds | 150–300 ms | above 500 ms |

---

## 🤖 AI Detection — Two Layers

### Layer 1 — Rule-based Drowsiness Score

Each sensor value is normalised to a 0–1 danger scale and combined with weights:

```
score = blink × 0.20 + eye_closure × 0.24 + head_tilt × 0.20
      + reaction × 0.16 + phone_risk × 0.20
```

| Score | Risk level |
|---|---|
| 0–39 | 🟢 Alert |
| 40–69 | 🟡 Warning |
| 70–100 | 🔴 Danger |

### Layer 2 — Isolation Forest (Unsupervised)

Trained on the stream of incoming readings. Normal readings cluster together;
anomalous readings are isolated and flagged. No labels required — the model learns
what "normal" looks like and flags deviations automatically.

```python
IsolationForest(n_estimators=100, contamination=0.15, random_state=42)
```

---

## 🚨 Alert Logic

An alert is triggered when **any** of the following conditions are true:

- Drowsiness score ≥ 65
- Isolation Forest anomaly score < -0.08

Each alert is saved to `data/alerts.json` with full sensor snapshot, timestamp,
driver ID, score, risk level, and reasons. An audio alarm also sounds.

---

## 📡 Network Layer

### Protocol — UDP

UDP is used instead of TCP because:
- Real IoT vehicle systems prioritise low latency over guaranteed delivery
- UDP exposes packet loss and delay behaviour that TCP hides automatically
- Every datagram is individually visible in Wireshark
- Network impairment experiments require UDP to be meaningful

### Network Experiments

| Experiment | What is measured |
|---|---|
| Packet loss (0–50%) | Delivery rate, missed alert percentage |
| Injected delay (0–500 ms) | Average, min, max latency |
| Burst traffic (1–50 packets) | Burst duration, send rate |

Results are saved to `data/reports/`.

---

## 📁 Project Structure

```
drowsiness_detection/
│
├── sensor/
│   └── simulator.py              # Synthetic UDP sensor (3-state cycle)
│
├── camera/
│   ├── camera_detector.py        # Live webcam — Dlib EAR
│   ├── hand_detector.py          # Both-hands-raised detection
│   ├── calibrate_ear.py          # Personal EAR threshold calibration
│   └── shape_predictor_68_face_landmarks.dat  # Dlib model (not in git)
│
├── network/
│   ├── udp_bridge.py             # UDP listener → Flask forwarder
│   ├── experiments.py            # Packet loss / latency / burst tests
│   └── report_generator.py       # Auto-generates experiment report
│
├── api/
│   └── app.py                    # Flask API — all endpoints
│
├── ai/
│   └── detector.py               # Isolation Forest anomaly detection
│
├── alerts/
│   ├── alert_manager.py          # Alert evaluation and storage
│   └── sound_alert.py            # Audio alarm
│
├── security/
│   ├── crypto.py                 # HMAC-SHA256 sign / verify
│   ├── auth.py                   # API key decorator
│   ├── replay_guard.py           # Nonce-based replay protection
│   ├── validators.py             # Input validation
│   └── file_guard.py             # File permission guard
│
├── data/
│   ├── readings.json             # All sensor readings (persistent)
│   ├── alerts.json               # All triggered alerts (persistent)
│   └── reports/                  # Network experiment results
│
├── .env                          # Secrets (not committed)
└── requirements.txt
```

---

## 🌐 API Endpoints

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/health` | — | API status + reading count |
| POST | `/sensor-data` | API Key | Receive a sensor reading |
| GET | `/readings` | API Key | All saved readings |
| GET | `/readings?limit=N` | API Key | Last N readings |
| GET | `/readings/summary` | API Key | Average score, risk distribution |
| GET | `/ai/analyze` | API Key | AI analysis on last 20 readings |
| GET | `/alerts` | API Key | All alerts |
| GET | `/alerts/latest` | API Key | Most recent alert |
| POST | `/metrics` | — | Grafana metric list |
| POST | `/query` | API Key | Grafana time-series data |

---

## ▶️ How to Run

### Prerequisites

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in secrets:
```
IOT_HMAC_SECRET=your-secret-here
IOT_API_KEY=your-api-key-here
```

Download the Dlib landmark model (required for camera mode):
```bash
python -c "
import urllib.request, bz2, os
urllib.request.urlretrieve('http://dlib.net/files/shape_predictor_68_face_landmarks.dat.bz2', 'tmp.bz2')
open('camera/shape_predictor_68_face_landmarks.dat', 'wb').write(bz2.open('tmp.bz2').read())
os.remove('tmp.bz2')
print('Done')
"
```

### Option A — Simulated sensor

```bash
# Terminal 1
python api/app.py

# Terminal 2
python network/udp_bridge.py

# Terminal 3
python sensor/simulator.py
```

### Option B — Live camera (Python 3.12 venv required)

```bash
# Terminal 1
python api/app.py

# Terminal 2
python network/udp_bridge.py

# Terminal 3
venv312\Scripts\activate
python camera/camera_detector.py
```

### Network experiments

```bash
python network/experiments.py
python network/report_generator.py
```

---

## 📈 Grafana Dashboard

1. Start Grafana: `net start grafana`
2. Open `http://localhost:3000` (admin / admin)
3. Datasource: `simpod-json-datasource` → `http://localhost:5000`
4. Custom HTTP Header: `X-API-Key` → your `IOT_API_KEY`

Panels: Drowsiness Score · Blink Rate · Eye Closure Duration · Head Tilt Angle · Reaction Delay

Auto-refresh: 5s

---

## 🔬 Wireshark Analysis

```
udp.port == 9999
```

Each packet is one signed sensor reading. The HMAC signature, nonce, and JSON
payload are visible in the packet details pane.

---

## 📋 Requirements

```
flask
requests
scikit-learn
numpy
pandas
joblib
opencv-python
dlib
scipy
cvzone
```

> **Note:** Python 3.12 is required for the camera module.
> The simulator and API work with Python 3.13.

---

## 🔄 Simulated vs Camera-Based Input

| Dimension | Simulator | Camera detector |
|---|---|---|
| Data source | Python random module | Live webcam (real human face) |
| Algorithm | State machine | Dlib 68-point EAR |
| Realism | Controlled, predictable | Real biological variance |
| Setup | None | Webcam + good lighting |
| Reproducibility | Fully reproducible | Varies per session |
| Failure modes | None | Poor lighting, face occlusion |
| UDP format | Identical JSON port 9999 | Identical JSON port 9999 |
| Best used for | Experiments, AI training | Live demos, real-world validation |

---

## 👩‍💻 Author

**Sudenur Tilla**
Final Year IoT Project — AI-Driven Driver Drowsiness Detection
