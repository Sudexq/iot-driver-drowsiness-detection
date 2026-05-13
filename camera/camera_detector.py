import cv2
import numpy as np
import time
import socket
import json
import sys
import os
from collections import deque
from datetime import datetime, timezone

# Add project root to PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from security.crypto import sign_payload, get_secret
from camera.phone_detector import PhoneDetector
from camera.gaze_detector import GazeDetector
from alerts.sound_alert import play_alarm, stop_alarm

# Load HMAC secret once
HMAC_SECRET = get_secret()

print("Camera Drowsiness Detector — Final Version")
print("=" * 50)

# ── OpenCV cascades ───────────────────────────────────────────────
face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
)
eye_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + 'haarcascade_eye.xml'
)

# ── UDP Config ────────────────────────────────────────────────────
UDP_IP       = "127.0.0.1"
UDP_PORT     = 9999
DRIVER_ID    = "driver_camera_001"
UDP_INTERVAL = 1.0   # send every 1 second

# ── Detector constants ────────────────────────────────────────────
BLINK_RATE_WINDOW    = 60.0   # blink rate window (seconds)
EYE_CLOSE_THRESHOLD  = 0.5    # longer than this = drowsy
MIN_BLINK_INTERVAL   = 0.25   # min time between blinks
MIN_EYE_CLOSE_FRAMES = 3      # frames closed before counting as blink

# ── UDP socket ────────────────────────────────────────────────────
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# ── State estimation ──────────────────────────────────────────────

def estimate_state(blink_rate, eye_closure_duration, head_tilt_angle):
    """Estimate driver state from sensor values."""
    drowsy_score = 0

    if blink_rate < 8:
        drowsy_score += 2
    elif blink_rate < 12:
        drowsy_score += 1

    if eye_closure_duration > 0.5:
        drowsy_score += 2
    elif eye_closure_duration > 0.3:
        drowsy_score += 1

    if head_tilt_angle > 20:
        drowsy_score += 2
    elif head_tilt_angle > 10:
        drowsy_score += 1

    if drowsy_score >= 4:
        return "drowsy"
    elif drowsy_score >= 2:
        return "transitioning"
    else:
        return "alert"

# ── UDP sender ────────────────────────────────────────────────────

def send_udp_packet(blink_rate, eye_closure_duration,
                    head_tilt_angle, reaction_delay=250.0,
                    phone_result=None, gaze_result=None):
    """Send JSON packet compatible with existing pipeline."""
    if phone_result is None:
        phone_result = {"distraction": False, "risk_score": 0.0, "detail": ""}
    if gaze_result is None:
        gaze_result = {"gaze_down": False, "gaze_score": 0.0, "gaze_down_secs": 0.0}

    state = estimate_state(
        blink_rate, eye_closure_duration, head_tilt_angle
    )

    payload = {
        "driver_id":            DRIVER_ID,
        "state":                state,
        "blink_rate":           round(float(blink_rate), 2),
        "eye_closure_duration": round(float(eye_closure_duration), 3),
        "head_tilt_angle":      round(float(head_tilt_angle), 1),
        "reaction_delay":       round(float(reaction_delay), 1),
        "phone_distraction":    phone_result.get("distraction", False),
        "phone_risk_score":     phone_result.get("risk_score", 0.0),
        "phone_detail":         phone_result.get("detail", ""),
        "gaze_down":            gaze_result.get("gaze_down", False),
        "gaze_score":           gaze_result.get("gaze_score", 0.0),
        "gaze_down_secs":       gaze_result.get("gaze_down_secs", 0.0),
        "source":               "camera",
        "sent_at":              datetime.now(timezone.utc).isoformat()
    }

    # Sign with HMAC — udp_bridge will verify
    envelope = sign_payload(payload, secret=HMAC_SECRET)
    data = json.dumps(envelope).encode("utf-8")
    udp_sock.sendto(data, (UDP_IP, UDP_PORT))
    return payload

# ── Drowsiness Detector class ─────────────────────────────────────

class DrowsinessDetector:
    def __init__(self):
        self.blink_count       = 0
        self.blink_times       = deque()
        self.start_time        = time.time()

        self.eyes_visible_last = True
        self.eye_close_start   = None
        self.last_closure_dur  = 0.0

        self.no_eye_frames     = 0
        self.eye_frames        = 0
        self.last_blink_time   = 0.0

    def update(self, eyes_detected, frame_h, eye_rects):
        now = time.time()

        if eyes_detected:
            self.eye_frames += 1

            # Eyes reappeared — did a blink complete?
            if (not self.eyes_visible_last
                    and self.no_eye_frames >= MIN_EYE_CLOSE_FRAMES
                    and (now - self.last_blink_time) >= MIN_BLINK_INTERVAL):
                self.blink_count += 1
                self.blink_times.append(now)
                self.last_blink_time = now
                if self.eye_close_start is not None:
                    self.last_closure_dur = round(
                        now - self.eye_close_start, 3
                    )
                self.eye_close_start = None

            self.no_eye_frames     = 0
            self.eyes_visible_last = True

        else:
            self.no_eye_frames += 1
            if self.eye_close_start is None:
                self.eye_close_start = now
            self.last_closure_dur = round(
                now - self.eye_close_start, 3
            )
            self.eyes_visible_last = False

        # Blink rate — last 60 seconds
        cutoff = now - BLINK_RATE_WINDOW
        while self.blink_times and self.blink_times[0] < cutoff:
            self.blink_times.popleft()

        elapsed    = min(now - self.start_time, BLINK_RATE_WINDOW)
        blink_rate = round(
            len(self.blink_times) / max(elapsed, 1) * 60.0, 1
        )

        return self.blink_count, blink_rate, self.last_closure_dur


# ── Head tilt ─────────────────────────────────────────────────────

def get_head_tilt(face_rect, frame_shape):
    x, y, w, h       = face_rect
    frame_h, frame_w = frame_shape[:2]
    face_center_x    = x + w // 2
    frame_center_x   = frame_w // 2
    offset           = face_center_x - frame_center_x
    tilt             = round(abs(offset) / frame_w * 90, 1)
    return min(tilt, 45.0)


# ── Visualization ─────────────────────────────────────────────────

STATE_COLORS = {
    "alert":        (0, 255, 0),
    "transitioning":(0, 165, 255),
    "drowsy":       (0, 0, 255)
}

def draw_info(frame, blink_count, blink_rate, closure_dur,
              head_tilt, eyes_detected, udp_count,
              last_state, last_risk):
    h, w = frame.shape[:2]

    # Panel background
    overlay = frame.copy()
    cv2.rectangle(overlay, (10, 10), (330, 260), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)

    eye_color = (0, 255, 0) if eyes_detected else (0, 0, 255)
    eye_text  = "open" if eyes_detected else "CLOSED"

    state_color = STATE_COLORS.get(last_state, (255, 255, 255))

    def put(text, y, color=(255, 255, 255), scale=0.55, bold=False):
        thickness = 2 if bold else 1
        cv2.putText(frame, text, (18, y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    scale, color, thickness)

    put("Driver Drowsiness Monitor", 35, (255, 255, 0), 0.6, bold=True)
    put(f"Eye state    : {eye_text}",          62, eye_color)
    put(f"Closure dur  : {closure_dur:.3f} s", 87)
    put(f"Blink count  : {blink_count}",        112)
    put(f"Blink rate   : {blink_rate:.1f} /min",137)
    put(f"Head tilt    : {head_tilt:.1f} deg",  162)
    put(f"State        : {last_state.upper()}", 187, state_color)
    put(f"Risk level   : {last_risk.upper()}",  212, state_color)
    put(f"UDP sent     : #{udp_count}",         237, (0, 255, 150))

    # Drowsy warning band
    if not eyes_detected and closure_dur > EYE_CLOSE_THRESHOLD:
        cv2.rectangle(frame, (0, h - 60), (w, h), (0, 0, 180), -1)
        cv2.putText(frame, "! DROWSY WARNING !",
                    (w // 2 - 150, h - 18),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (255, 255, 255), 3)


def draw_closure_bar(frame, closure_dur):
    h, w    = frame.shape[:2]
    bar_x   = w - 30
    bar_top = 50
    bar_bot = h - 50
    bar_h   = bar_bot - bar_top
    max_dur = 3.0

    cv2.rectangle(frame, (bar_x, bar_top),
                  (bar_x + 20, bar_bot), (50, 50, 50), -1)

    fill  = int(bar_h * min(closure_dur / max_dur, 1.0))
    ratio = closure_dur / max_dur
    color = (0, 255, 0)   if ratio < 0.3 else \
            (0, 165, 255) if ratio < 0.6 else \
            (0, 0, 255)

    cv2.rectangle(frame,
                  (bar_x, bar_bot - fill),
                  (bar_x + 20, bar_bot), color, -1)

    thresh_y = bar_bot - int(bar_h * EYE_CLOSE_THRESHOLD / max_dur)
    cv2.line(frame,
             (bar_x - 5, thresh_y),
             (bar_x + 25, thresh_y),
             (0, 255, 255), 2)

    cv2.putText(frame, "CLS",
                (bar_x - 2, bar_top - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.38, (200, 200, 200), 1)


# ── Main ──────────────────────────────────────────────────────────

def main():
    cap       = cv2.VideoCapture(0)
    detector  = DrowsinessDetector()
    phone_det = PhoneDetector()
    gaze_det  = GazeDetector()

    last_phone_result = {"distraction": False, "risk_score": 0.0, "detail": "starting"}
    last_gaze_result  = {"gaze_down": False, "gaze_score": 0.0, "gaze_down_secs": 0.0, "detail": "starting"}

    print(f"\n UDP Target     : {UDP_IP}:{UDP_PORT}")
    print(f"   UDP Interval  : {UDP_INTERVAL}s")
    print(f"   Driver ID     : {DRIVER_ID}")
    print(f"\n   Make sure these are running:")
    print(f"   Terminal 1: python api/app.py")
    print(f"   Terminal 2: python network/udp_bridge.py")
    print(f"\n   Starting camera... press 'q' to quit.\n")

    last_udp_time = time.time()
    udp_count     = 0
    last_state    = "alert"
    last_risk     = "alert"
    frame_count   = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        frame_count += 1
        h, w  = frame.shape[:2]
        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # ── Face detection ────────────────────────────────────────
        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(120, 120)
        )

        head_tilt     = 0.0
        eyes_detected = False
        eye_rects     = []

        if len(faces) > 0:
            faces = sorted(faces,
                           key=lambda f: f[2] * f[3],
                           reverse=True)
            fx, fy, fw, fh = faces[0]

            cv2.rectangle(frame,
                          (fx, fy), (fx + fw, fy + fh),
                          (0, 255, 0), 2)

            head_tilt = get_head_tilt(faces[0], frame.shape)

            # Search eyes in top 55% of face
            roi_y2    = fy + int(fh * 0.55)
            roi_gray  = gray[fy:roi_y2, fx:fx + fw]
            roi_color = frame[fy:roi_y2, fx:fx + fw]

            eyes = eye_cascade.detectMultiScale(
                roi_gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(25, 25)
            )

            if len(eyes) >= 1:
                eyes_detected = True
                for (ex, ey, ew, eh) in eyes:
                    eye_rects.append((ex, ey, ew, eh))
                    cv2.rectangle(roi_color,
                                  (ex, ey),
                                  (ex + ew, ey + eh),
                                  (255, 100, 0), 2)
        else:
            cv2.putText(frame, "Face not found",
                        (20, 50),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (0, 0, 255), 2)

        # ── Update detectors ──────────────────────────────────────
        blink_count, blink_rate, closure_dur = \
            detector.update(eyes_detected, h, eye_rects)

        last_phone_result = phone_det.update(frame)
        phone_det.draw_status(frame, last_phone_result)

        last_gaze_result = gaze_det.update(frame)

        # ── Alarm logic ───────────────────────────────────────────
        # Only alarm if hand is NOT moving fast (not scratching/waving)
        phone_moving = last_phone_result.get("detail", "").startswith("kasima")

        gaze_alert  = last_gaze_result.get("gaze_down_secs", 0) > 1.5
        phone_alert = last_phone_result.get("distraction", False) and not phone_moving

        if gaze_alert:
            play_alarm("drowsiness")
        elif phone_alert:
            play_alarm("distraction")
        else:
            stop_alarm()

        # ── Send UDP every 1 second ───────────────────────────────
        now = time.time()
        if now - last_udp_time >= UDP_INTERVAL:
            try:
                pkt = send_udp_packet(
                    blink_rate=blink_rate,
                    eye_closure_duration=closure_dur,
                    head_tilt_angle=head_tilt,
                    reaction_delay=250.0,
                    phone_result=last_phone_result,
                    gaze_result=last_gaze_result
                )
                udp_count    += 1
                last_state    = pkt["state"]
                last_udp_time = now

                ICONS = {
                    "alert":         "[OK]",
                    "transitioning": "[!!]",
                    "drowsy":        "[!!]"
                }
                icon = ICONS.get(last_state, "[?]")

                print(
                    f"{icon} UDP #{udp_count:>3} | "
                    f"state={last_state:<13} | "
                    f"blink={pkt['blink_rate']:>5}/min | "
                    f"eye={pkt['eye_closure_duration']:.3f}s | "
                    f"tilt={pkt['head_tilt_angle']:>4}deg | "
                    f"react={pkt['reaction_delay']}ms | "
                    f"gaze_down={pkt['gaze_down']} | "
                    f"phone={pkt['phone_distraction']}"
                )

            except Exception as e:
                print(f"UDP error: {e}")

        # ── Visualize ─────────────────────────────────────────────
        draw_info(frame, blink_count, blink_rate,
                  closure_dur, head_tilt, eyes_detected,
                  udp_count, last_state, last_risk)
        draw_closure_bar(frame, closure_dur)

        cv2.imshow("Driver Drowsiness Detector", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    udp_sock.close()

    elapsed = time.time() - detector.start_time
    print(f"\n{'='*50}")
    print(f"Session summary:")
    print(f"   Duration        : {round(elapsed, 1)}s")
    print(f"   Total blinks    : {detector.blink_count}")
    print(f"   UDP sent        : {udp_count}")
    print(f"{'='*50}")
    print("Detector closed.")


if __name__ == "__main__":
    main()