import cv2
import dlib
import numpy as np
import time
import socket
import json
import sys
import os
from collections import deque
from datetime import datetime, timezone
from scipy.spatial import distance as dist

# ── Path ──────────────────────────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# ── Proje modülleri ───────────────────────────────────────────────
from security.crypto import sign_payload, get_secret
from alerts.sound_alert import play_alarm, stop_alarm
from camera.hand_detector import HandRaiseDetector

HMAC_SECRET = get_secret()

print("Camera Drowsiness Detector — Dlib Version")
print("=" * 50)

# ── Dlib setup ────────────────────────────────────────────────────
LANDMARK_MODEL = os.path.join(
    os.path.dirname(__file__),
    "shape_predictor_68_face_landmarks.dat"
)
detector  = dlib.get_frontal_face_detector()
predictor = dlib.shape_predictor(LANDMARK_MODEL)

LEFT_EYE  = list(range(42, 48))
RIGHT_EYE = list(range(36, 42))

# ── UDP Config ────────────────────────────────────────────────────
UDP_IP       = "127.0.0.1"
UDP_PORT     = 9999
DRIVER_ID    = "driver_camera_001"
UDP_INTERVAL = 1.0
udp_sock     = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# ── Sabitler ──────────────────────────────────────────────────────
EAR_THRESHOLD     = 0.15
EAR_CONSEC_FRAMES = 3
MIN_BLINK_INTERVAL= 0.25
BLINK_RATE_WINDOW = 60.0
MAX_CLOSURE_DUR   = 4.0

# ── EAR ───────────────────────────────────────────────────────────

def eye_aspect_ratio(eye_pts):
    A = dist.euclidean(eye_pts[1], eye_pts[5])
    B = dist.euclidean(eye_pts[2], eye_pts[4])
    C = dist.euclidean(eye_pts[0], eye_pts[3])
    return (A + B) / (2.0 * C)

def landmarks_to_array(shape, indices):
    return np.array([(shape.part(i).x, shape.part(i).y)
                     for i in indices])

# ── Baş eğimi ─────────────────────────────────────────────────────

def head_tilt_from_landmarks(shape, frame_h):
    left_eye  = (shape.part(36).x, shape.part(36).y)
    right_eye = (shape.part(45).x, shape.part(45).y)
    dx = right_eye[0] - left_eye[0]
    dy = right_eye[1] - left_eye[1]
    horizontal_tilt = abs(np.degrees(np.arctan2(dy, dx)))

    nose_y = shape.part(30).y
    chin_y = shape.part(8).y
    vertical_dist = (chin_y - nose_y) / frame_h
    forward_tilt  = max(0.0, (0.13 - vertical_dist) / 0.13 * 45)

    return round(min(max(horizontal_tilt, forward_tilt), 45.0), 1)

# ── State tahmini ─────────────────────────────────────────────────

def estimate_state(blink_rate, eye_closure_duration,
                   head_tilt, tilt_duration, elapsed_secs=60):
    score = 0

    if elapsed_secs > 60:
        if blink_rate < 6:
            score += 2
        elif blink_rate < 10:
            score += 1

    if eye_closure_duration > 2.0:
        score += 3
    elif eye_closure_duration > 1.0:
        score += 2
    elif eye_closure_duration > 0.8:
        score += 1

    if tilt_duration > 4.0:
        score += 3
    elif tilt_duration > 2.0:
        score += 2
    elif tilt_duration > 1.0:
        score += 1

    if score >= 3:
        return "drowsy"
    elif score >= 1:
        return "transitioning"
    return "alert"

# ── UDP gönder ────────────────────────────────────────────────────

def send_udp_packet(blink_rate, eye_closure_duration,
                    head_tilt_angle, tilt_duration=0.0,
                    reaction_delay=250.0, elapsed_secs=60):
    state = estimate_state(
        blink_rate, eye_closure_duration,
        head_tilt_angle, tilt_duration, elapsed_secs
    )
    payload = {
        "driver_id":            DRIVER_ID,
        "state":                state,
        "blink_rate":           round(float(blink_rate), 2),
        "eye_closure_duration": round(float(eye_closure_duration), 3),
        "head_tilt_angle":      round(float(head_tilt_angle), 1),
        "head_tilt_duration":   round(float(tilt_duration), 1),
        "reaction_delay":       round(float(reaction_delay), 1),
        "source":               "camera",
        "sent_at":              datetime.now(timezone.utc).isoformat()
    }
    envelope = sign_payload(payload, secret=HMAC_SECRET)
    data     = json.dumps(envelope).encode("utf-8")
    udp_sock.sendto(data, (UDP_IP, UDP_PORT))
    return payload

# ── Drowsiness Detector ───────────────────────────────────────────

class DrowsinessDetector:
    def __init__(self):
        self.blink_count      = 0
        self.blink_times      = deque()
        self.start_time       = time.time()
        self.consec_closed    = 0
        self.eye_close_start  = None
        self.last_closure_dur = 0.0
        self.last_blink_time  = 0.0
        self.eye_was_closed   = False
        self.tilt_start       = None
        self.last_tilt_dur    = 0.0
        self.TILT_THRESHOLD   = 15.0

    def update(self, ear, head_tilt):
        now        = time.time()
        eye_closed = ear < EAR_THRESHOLD

        if eye_closed:
            self.consec_closed += 1
            if self.eye_close_start is None:
                self.eye_close_start = now
            self.last_closure_dur = min(
                round(now - self.eye_close_start, 3),
                MAX_CLOSURE_DUR
            )
        else:
            if (self.eye_was_closed
                    and self.consec_closed >= EAR_CONSEC_FRAMES
                    and (now - self.last_blink_time) >= MIN_BLINK_INTERVAL):
                self.blink_count += 1
                self.blink_times.append(now)
                self.last_blink_time = now
                if self.eye_close_start is not None:
                    self.last_closure_dur = min(
                        round(now - self.eye_close_start, 3),
                        MAX_CLOSURE_DUR
                    )
            self.consec_closed   = 0
            self.eye_close_start = None

        self.eye_was_closed = eye_closed

        cutoff = now - BLINK_RATE_WINDOW
        while self.blink_times and self.blink_times[0] < cutoff:
            self.blink_times.popleft()

        elapsed    = min(now - self.start_time, BLINK_RATE_WINDOW)
        blink_rate = round(
            len(self.blink_times) / max(elapsed, 1) * 60.0, 1
        )

        # Baş eğimi süresi
        if head_tilt > self.TILT_THRESHOLD:
            if self.tilt_start is None:
                self.tilt_start = now
            self.last_tilt_dur = round(now - self.tilt_start, 1)
        else:
            self.tilt_start    = None
            self.last_tilt_dur = 0.0

        return (self.blink_count, blink_rate,
                self.last_closure_dur, self.last_tilt_dur)

# ── Görselleştirme ────────────────────────────────────────────────

STATE_COLORS = {
    "alert":         (0, 255, 0),
    "transitioning": (0, 165, 255),
    "drowsy":        (0, 0, 255)
}

def draw_eye(frame, pts, color):
    hull = cv2.convexHull(pts)
    cv2.drawContours(frame, [hull], -1, color, 1)

def draw_info(frame, ear, blink_count, blink_rate,
              closure_dur, head_tilt, udp_count,
              last_state, hand_result):
    h, w = frame.shape[:2]

    overlay = frame.copy()
    cv2.rectangle(overlay, (10, 10), (340, 290), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)

    state_color = STATE_COLORS.get(last_state, (255, 255, 255))
    eye_color   = (0, 0, 255) if ear < EAR_THRESHOLD else (0, 255, 0)
    hand_color  = (0, 0, 255) if hand_result.get("distraction") \
                  else (0, 255, 0)

    def put(text, y, color=(255,255,255), scale=0.52, bold=False):
        cv2.putText(frame, text, (18, y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    scale, color, 2 if bold else 1)

    put("Driver Drowsiness Monitor", 30, (255,255,0), 0.58, True)
    put(f"EAR        : {ear:.3f}",                  54,  eye_color)
    put(f"Eye        : {'CLOSED' if ear < EAR_THRESHOLD else 'open'}",
        76,  eye_color)
    put(f"Closure    : {closure_dur:.2f}s",          98)
    put(f"Blink rate : {blink_rate:.1f}/min",        120)
    put(f"Head tilt  : {head_tilt:.1f}deg",          142)
    put(f"State      : {last_state.upper()}",        164, state_color)
    put(f"Hands      : {hand_result.get('hands_count',0)} "
        f"(raised={hand_result.get('raised_count',0)})",
        186, hand_color)
    put(f"UDP sent   : #{udp_count}",                208, (0,255,150))

    # Drowsy uyarı
    if ear < EAR_THRESHOLD and closure_dur > 1.0:
        cv2.rectangle(frame, (0, h-55), (w, h), (0,0,180), -1)
        cv2.putText(frame, "! DROWSY WARNING !",
                    (w//2-150, h-15),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (255,255,255), 3)

    # Baş eğimi uyarısı
    if head_tilt > 20:
        cv2.putText(frame, "! HEAD TILT !",
                    (w//2-100, 50),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (0,165,255), 2)

def draw_ear_bar(frame, ear):
    h, w   = frame.shape[:2]
    bx     = w - 30
    bt, bb = 50, h - 50
    bh     = bb - bt

    cv2.rectangle(frame, (bx, bt), (bx+20, bb), (50,50,50), -1)
    fill  = int(bh * min(ear / 0.40, 1.0))
    color = (0,255,0) if ear >= EAR_THRESHOLD else (0,0,255)
    cv2.rectangle(frame, (bx, bb-fill), (bx+20, bb), color, -1)
    ty = bb - int(bh * EAR_THRESHOLD / 0.40)
    cv2.line(frame, (bx-5, ty), (bx+25, ty), (0,255,255), 2)
    cv2.putText(frame, "EAR", (bx-2, bt-10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200,200,200), 1)

# ── Main ──────────────────────────────────────────────────────────

def main():
    cap = None
    for idx in [0, 1, 2]:
        c = cv2.VideoCapture(idx)
        if c.isOpened():
            ret, _ = c.read()
            if ret:
                cap = c
                print(f"✅ Kamera bulundu: index {idx}")
                break
            c.release()

    if cap is None:
        print("❌ Kamera açılamadı.")
        return

    det      = DrowsinessDetector()
    hand_det = HandRaiseDetector()

    print(f"\n   UDP: {UDP_IP}:{UDP_PORT}  |  interval: {UDP_INTERVAL}s")
    print(f"   EAR threshold: {EAR_THRESHOLD}")
    print("   Çıkmak için 'q' bas.\n")

    last_udp     = time.time()
    udp_count    = 0
    last_state   = "alert"
    ear          = 0.30
    last_hand    = {"both_raised": False, "hands_count": 0,
                    "raised_count": 0, "risk_score": 0.0,
                    "distraction": False, "detail": ""}

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = detector(gray, 0)
        head_tilt = 0.0

        if faces:
            shape     = predictor(gray, faces[0])
            left_pts  = landmarks_to_array(shape, LEFT_EYE)
            right_pts = landmarks_to_array(shape, RIGHT_EYE)
            ear       = round((eye_aspect_ratio(left_pts) +
                               eye_aspect_ratio(right_pts)) / 2.0, 4)
            head_tilt = head_tilt_from_landmarks(shape, frame.shape[0])

            eye_color = (0,0,255) if ear < EAR_THRESHOLD else (0,255,0)
            draw_eye(frame, left_pts,  eye_color)
            draw_eye(frame, right_pts, eye_color)
        else:
            cv2.putText(frame, "Yuz bulunamadi", (20, 50),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (0,0,255), 2)

        # ── Detectors ─────────────────────────────────────────────
        blink_count, blink_rate, closure_dur, tilt_dur = \
            det.update(ear, head_tilt)

        # Yüz koordinatlarını hand detector'a geç
        face_rect_cv = None
        if faces:
            fx = faces[0].left()
            fy = faces[0].top()
            fw = faces[0].right()  - faces[0].left()
            fh = faces[0].bottom() - faces[0].top()
            face_rect_cv = (fx, fy, fw, fh)

        last_hand = hand_det.update(frame, face_rect=face_rect_cv)
        hand_det.draw_status(frame, last_hand)

        # ── UDP gönder ────────────────────────────────────────────
        now = time.time()
        if now - last_udp >= UDP_INTERVAL:
            try:
                pkt = send_udp_packet(
                    blink_rate, closure_dur, head_tilt,
                    tilt_duration=tilt_dur,
                    elapsed_secs=now - det.start_time
                )
                udp_count += 1
                last_state = pkt["state"]
                last_udp   = now

                # Sesli uyarı
                if last_state == "drowsy":
                    play_alarm("drowsiness")
                elif last_hand.get("distraction"):
                    play_alarm("distraction")
                else:
                    stop_alarm()

                ICONS = {
                    "alert":         "[OK]",
                    "transitioning": "[!!]",
                    "drowsy":        "[!!]"
                }
                print(
                    f"{ICONS.get(last_state,'[?]')} "
                    f"UDP #{udp_count:>3} | "
                    f"EAR={ear:.3f} | "
                    f"state={last_state:<13} | "
                    f"blink={blink_rate:>5}/min | "
                    f"eye={closure_dur:.2f}s | "
                    f"tilt={head_tilt:.1f}deg | "
                    f"tilt_dur={tilt_dur:.1f}s | "
                    f"hands={last_hand.get('hands_count',0)} | "
                    f"both={last_hand.get('both_raised',False)}"
                )

            except Exception as e:
                print(f"UDP error: {e}")

        # ── Görselleştir ──────────────────────────────────────────
        draw_info(frame, ear, blink_count, blink_rate,
                  closure_dur, head_tilt, udp_count,
                  last_state, last_hand)
        draw_ear_bar(frame, ear)

        cv2.imshow("Driver Drowsiness Detector", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    udp_sock.close()

    elapsed = time.time() - det.start_time
    print(f"\n{'='*50}")
    print(f"   Süre   : {round(elapsed,1)}s")
    print(f"   Blink  : {det.blink_count}")
    print(f"   UDP    : {udp_count}")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()