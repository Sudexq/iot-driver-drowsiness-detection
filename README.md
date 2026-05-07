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

- **Dual input modes** — live webcam (OpenCV) or synthetic simulator, plug-and-play interchangeable
- **UDP-based IoT transport** — real network datagrams, visible in Wireshark
- **Flask backend API** — receives, scores, and stores every reading
- **Rule-based drowsiness scoring** — transparent, explainable 0–100 score
- **Isolation Forest** — unsupervised anomaly detection (no labels required)
- **Real-time alert system** — triggers on score threshold or AI anomaly flag
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
                  │ UDP  port 9999
                  ▼
┌─────────────────────────────────────────────┐
│           network/udp_bridge.py             │
│   Listens on UDP · decodes JSON · measures  │
│   latency · forwards via HTTP POST          │
└─────────────────┬───────────────────────────┘
                  │ HTTP POST  port 5000
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
│alerts.json  │     │  Live dashboard          │
└─────────────┘     └──────────────────────────┘
```

---

## 📷 Camera-Based Input Module

### `camera/camera_detector.py`

Opens the PC webcam, detects the driver's face and eyes using OpenCV Haar Cascade
classifiers, and computes three drowsiness indicators from live video frames.

#### What it measures

| Field | Method | Normal range |
|---|---|---|
| `blink_rate` | Eye disappearance events per minute (60 s rolling window) | 12–20 /min |
| `eye_closure_duration` | Time from eyes closing to reopening | 0.10–0.25 s |
| `head_tilt_angle` | Lateral deviation of face center from frame center | 0–10 degrees |
| `reaction_delay` | Fixed baseline reference value | 250 ms |

#### UDP output — every 1 second

```json
{
  "driver_id":            "driver_camera_001",
  "state":                "alert",
  "blink_rate":           17.2,
  "eye_closure_duration": 0.142,
  "head_tilt_angle":      3.1,
  "reaction_delay":       250.0,
  "source":               "camera",
  "sent_at":              "2026-05-07T14:33:54+00:00"
}
```

The JSON structure is identical to `sensor/simulator.py`. The existing UDP bridge,
Flask API, AI model, alert system, and Grafana dashboard require no changes.

#### Why OpenCV Haar Cascades instead of a custom-trained model

Our task is **feature extraction**, not image classification. The goal is to obtain
numerical behavioral metrics from video — not to label images. Haar Cascades are
purpose-built for locating facial regions efficiently on CPU at 30 fps, with no GPU
required. Training a custom CNN from scratch would require tens of thousands of labeled
images and significant compute — effort that would not improve the core IoT system.
In production IoT systems (Bosch DMS, Seeing Machines, Mobileye), pre-trained
perception models are always used for this layer. Our novelty is the end-to-end
pipeline and the dual-layer AI detection — not face detection itself.

---

## 📊 Sensor Fields

| Field | Description | Alert range | Drowsy range |
|---|---|---|---|
| `blink_rate` | Blinks per minute | 15–20 | below 8 |
| `eye_closure_duration` | Eye closed duration in seconds | 0.10–0.20 s | above 0.50 s |
| `head_tilt_angle` | Head angle in degrees | 0–10° | above 20° |
| `reaction_delay` | Response time in milliseconds | 150–300 ms | above 500 ms |

---

## 🤖 AI Detection — Two Layers

### Layer 1 — Rule-based Drowsiness Score

Each sensor value is normalized to a 0–1 danger scale and combined with weights:

```
score = blink × 0.25 + eye_closure × 0.30 + head_tilt × 0.25 + reaction × 0.20
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

---

## 🚨 Alert Logic

An alert is triggered when **any** of the following conditions are true:

- Drowsiness score ≥ 60
- Isolation Forest flags the reading as an anomaly

Each alert is saved to `data/alerts.json` with full sensor snapshot, timestamp,
driver ID, score, risk level, and reasons.

---

## 📡 Network Layer

### Protocol — UDP

UDP is used instead of TCP because:
- Real IoT vehicle systems prioritize low latency over guaranteed delivery
- UDP exposes packet loss and delay behavior that TCP hides automatically
- Every datagram is individually visible in Wireshark
- Network impairment experiments (loss, delay, burst) require UDP to be meaningful

### Network Experiments

| Experiment | What is measured |
|---|---|
| Packet loss (0–50%) | Delivery rate, missed alert percentage |
| Injected delay (0–500 ms) | Average, min, max latency |
| Burst traffic (1–50 packets) | Burst duration, send rate |

Results are saved to `data/reports/experiment_report.txt` and
`data/reports/experiment_results.json`.

---

## 📁 Project Structure

```
drowsiness_detection/
│
├── sensor/
│   └── simulator.py              # Synthetic UDP sensor (3-state cycle)
│
├── camera/
│   └── camera_detector.py        # Live webcam input via OpenCV
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
│   └── alert_manager.py          # Alert evaluation and storage
│
├── data/
│   ├── readings.json             # All sensor readings (persistent)
│   ├── alerts.json               # All triggered alerts (persistent)
│   └── reports/                  # Network experiment results
│
└── requirements.txt
```

---

## 🌐 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/sensor-data` | Receive a sensor reading |
| GET | `/health` | API status + total reading count |
| GET | `/readings` | All saved readings |
| GET | `/readings?limit=N` | Last N readings |
| GET | `/readings/summary` | Average score, risk distribution |
| GET | `/ai/analyze` | Run AI analysis on last 20 readings |
| GET | `/alerts` | All alerts |
| GET | `/alerts/latest` | Most recent alert |
| POST | `/metrics` | Grafana metric list |
| POST | `/query` | Grafana time-series data |

---

## ▶️ How to Run

### Option A — Simulated sensor

```bash
# Terminal 1
python api/app.py

# Terminal 2
python network/udp_bridge.py

# Terminal 3
python sensor/simulator.py
```

### Option B — Live camera

```bash
# Terminal 1
python api/app.py

# Terminal 2
python network/udp_bridge.py

# Terminal 3
python camera/camera_detector.py
```

### Network experiments

```bash
# (with API and bridge already running)
python network/experiments.py
```

### Auto-generate experiment report

```bash
python network/report_generator.py
```

---

## 📈 Grafana Dashboard

Open `http://localhost:3000` after starting Grafana.

Panels:
- Drowsiness Score (time series)
- Blink Rate
- Eye Closure Duration
- Head Tilt Angle
- Reaction Delay

Datasource: `simpod-json-datasource` pointed at `http://localhost:5000`

Auto-refresh: set to 5s for live updates.

---

## 🔬 Wireshark Analysis

Capture filter:
```
udp.port == 9999
```

Each packet corresponds to one sensor reading. The JSON payload is visible in
the packet details pane. Burst traffic experiments produce a visually distinct
density spike in the packet timeline.

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
```

Install:
```bash
pip install -r requirements.txt
```

---

## 🔄 Simulated vs Camera-Based Input

| Dimension | Simulator | Camera detector |
|---|---|---|
| Data source | Python random module | Live webcam (real human face) |
| Realism | Controlled, predictable | Real biological variance |
| Setup | None | Webcam + good lighting |
| Reproducibility | Fully reproducible | Varies per session |
| Failure modes | None | Poor lighting, face occlusion |
| UDP format | Identical JSON port 9999 | Identical JSON port 9999 |
| Best used for | Experiments, AI training | Live demos, real-world validation |

Both modes feed the same downstream pipeline without any code changes.

---

## 👩‍💻 Author

**Sudenur Tilla**
Final Year IoT Project — AI-Driven Driver Drowsiness Detection