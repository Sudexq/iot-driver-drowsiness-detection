# 🚍 AI-Driven IoT Driver Drowsiness Detection System

This project is an end-to-end IoT system designed to detect driver drowsiness using real-time behavioral data, network transmission, and hybrid AI models.

---

## 🎯 Project Overview

Driver fatigue is a major cause of road accidents. This system monitors driver behavior and detects potential drowsiness in real time using IoT architecture and machine learning.

---

## 🧠 Key Features

- Real-time driver behavior simulation
- UDP-based IoT communication (Netualizer)
- Flask backend API
- Rule-based drowsiness scoring
- Isolation Forest (unsupervised anomaly detection)
- Random Forest (supervised classification) *(coming soon)*
- Real-time alert system
- Grafana dashboard visualization
- Network experiments (latency, packet loss, burst traffic)
- Wireshark traffic analysis

---

## 🏗️ System Architecture
Sensor (Netualizer)

↓ UDP

UDP Bridge

↓ HTTP

Flask API

↓

Drowsiness Score (Rule-based)

↓

Isolation Forest

↓

Random Forest

↓

Alert System

↓

Grafana Dashboard


---

## 📡 Technologies Used

- Python (Flask, Scikit-learn)
- Netualizer (IoT simulation)
- UDP Networking
- Grafana (Visualization)
- Wireshark (Network analysis)

---

## 📊 Experiments

- Packet loss simulation
- Network delay analysis
- Burst traffic testing
- Impact on alert accuracy

---

## 🚨 Alert Logic

Alerts are triggered when:

- Drowsiness score ≥ 60
- OR anomaly detected (Isolation Forest)
- OR predicted as drowsy (Random Forest)

---

## ▶️ How to Run

### 1. Start Flask API
```bash
python api/app.py

### 2. Start UDP Bridge
```bash
python network/udp_bridge.py

### 3. Start Simulator
```bash
python sensor/simulator.py

# 📈 Dashboard

Grafana is used for real-time visualization of:

-Drowsiness score
-Blink rate
-Eye closure duration
-Head tilt angle
-Reaction delay

# 🧪 Future Improvements

-Camera-based detection (OpenCV)
-Model optimization
-Deployment on embedded systems (Raspberry Pi)
-Cloud integration

#👨‍💻 Author

Sudenur Tilla
