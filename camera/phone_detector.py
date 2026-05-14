"""
camera/phone_detector.py
========================
Phone usage detection using MediaPipe Hands.

Three signals are combined to distinguish phone use from face touching:

  1. POSITION  — If wrist landmark (0) is in the top 55% of the frame,
                 it is the face zone. Below that is the steering zone.
  2. DURATION  — Slow contact in face zone for over 2 seconds raises risk.
  3. MOVEMENT  — Fast hand movement (> FAST_MOVE_PX px/frame) = scratching
                 or waving. Slow + sustained = holding phone.

Output fields added to UDP packet:
  "phone_distraction": bool
  "phone_risk_score":  float
  "phone_detail":      str
"""

import time
from collections import deque
import numpy as np

try:
    import mediapipe as mp
    if not hasattr(mp, "solutions"):
        raise ImportError("This mediapipe version does not support mp.solutions (0.10+ incompatible)")
    MP_AVAILABLE = True
except ImportError as _mp_err:
    MP_AVAILABLE = False
    print(f"Warning: mediapipe unavailable: {_mp_err}")
    print("  Phone detection disabled. Camera will continue with other features.")
    print("  Compatible version: pip install mediapipe==0.10.9")


# ── Thresholds ────────────────────────────────────────────────────
FACE_ZONE_Y_RATIO   = 0.55   # Top 55% of frame = face zone
FACE_TOUCH_RISK_SEC = 2.0    # Seconds: slow contact longer than this = suspicious
PHONE_HOLD_SEC      = 3.0    # Seconds: still hand in steering zone = phone
FAST_MOVE_PX        = 20     # Pixels/frame: faster than this = scratch/wave

WRIST_LM             = 0     # MediaPipe wrist landmark index
PHONE_RISK_THRESHOLD = 0.55  # Above this = phone_distraction = True


class PhoneDetector:
    """
    Call update(frame) every frame, returns a dict:
      distraction : bool   — alert?
      risk_score  : float  — 0.0 to 1.0
      detail      : str    — human-readable status
      hands_count : int    — number of hands detected
    """

    def __init__(self):
        if not MP_AVAILABLE:
            self._mp_hands = None
            return

        self._mp   = mp.solutions.hands
        self._draw = mp.solutions.drawing_utils
        self._mp_hands = self._mp.Hands(
            static_image_mode=False,
            max_num_hands=2,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.5,
        )

        self._face_zone_start:  float | None = None
        self._direk_zone_start: float | None = None
        self._prev_wrist: tuple[float, float] | None = None
        self._speed_buf: deque[float] = deque(maxlen=4)
        self._last_result: dict = self._neutral()

    # ── Public API ────────────────────────────────────────────────

    def update(self, frame) -> dict:
        """Process BGR frame, assess risk, return result dict."""
        if self._mp_hands is None:
            return self._neutral("mediapipe not available")

        import cv2
        h, w = frame.shape[:2]
        rgb  = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res  = self._mp_hands.process(rgb)

        if not res.multi_hand_landmarks:
            # No hand detected — reset timers
            self._face_zone_start  = None
            self._direk_zone_start = None
            self._prev_wrist       = None
            self._speed_buf.clear()
            self._last_result = self._neutral("no hand detected")
            return self._last_result

        best_risk   = 0.0
        best_detail = "normal"
        hands_count = len(res.multi_hand_landmarks)

        for hand_lms in res.multi_hand_landmarks:
            self._draw.draw_landmarks(
                frame, hand_lms, self._mp.HAND_CONNECTIONS
            )

            wrist  = hand_lms.landmark[WRIST_LM]
            wx, wy = int(wrist.x * w), int(wrist.y * h)

            # Movement speed (pixels/frame)
            speed = 0.0
            if self._prev_wrist is not None:
                dx    = wx - self._prev_wrist[0]
                dy    = wy - self._prev_wrist[1]
                speed = float(np.sqrt(dx * dx + dy * dy))
            self._speed_buf.append(speed)
            self._prev_wrist = (wx, wy)
            avg_speed = float(np.mean(self._speed_buf)) if self._speed_buf else 0.0

            in_face_zone  = wy < h * FACE_ZONE_Y_RATIO
            in_direk_zone = not in_face_zone

            now = time.time()
            risk, detail = self._evaluate(
                in_face_zone, in_direk_zone, avg_speed, now
            )

            # Draw wrist marker with risk color
            color = self._risk_color(risk)
            import cv2 as _cv2
            _cv2.circle(frame, (wx, wy), 10, color, 2)
            _cv2.putText(
                frame,
                f"risk={risk:.2f}",
                (wx + 12, wy),
                _cv2.FONT_HERSHEY_SIMPLEX,
                0.45, color, 1
            )

            if risk > best_risk:
                best_risk   = risk
                best_detail = detail

        distraction = best_risk >= PHONE_RISK_THRESHOLD
        result = {
            "distraction": distraction,
            "risk_score":  round(best_risk, 3),
            "detail":      best_detail,
            "hands_count": hands_count,
        }
        self._last_result = result
        return result

    def draw_status(self, frame, result: dict):
        """Draw a short status overlay on the frame."""
        import cv2
        h, w = frame.shape[:2]
        risk  = result["risk_score"]
        color = self._risk_color(risk)

        label = f"Phone risk: {risk:.2f}  [{result['detail']}]"
        cv2.putText(
            frame, label,
            (18, h - 95),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48, color, 1
        )
        if result["distraction"]:
            cv2.rectangle(frame, (0, h - 85), (w, h - 65), (0, 0, 200), -1)
            cv2.putText(
                frame, "! PHONE USE DETECTED !",
                (w // 2 - 160, h - 70),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7, (255, 255, 255), 2
            )

    # ── Internal logic ────────────────────────────────────────────

    def _evaluate(
        self,
        in_face_zone: bool,
        in_direk_zone: bool,
        avg_speed: float,
        now: float,
    ) -> tuple[float, str]:
        """
        Produce a risk score from zone + duration + speed.

        Key rule: fast movement ALWAYS returns near-zero risk,
        regardless of zone or duration. Only slow, sustained
        contact raises risk — this prevents false positives
        from scratching, waving, or adjusting glasses.
        """
        # Fast movement anywhere = scratching / waving — reset and ignore
        if avg_speed > FAST_MOVE_PX:
            self._face_zone_start  = None
            self._direk_zone_start = None
            return 0.05, "fast movement (scratch/wave)"

        if in_face_zone:
            if self._face_zone_start is None:
                self._face_zone_start = now
            self._direk_zone_start = None
            elapsed = now - self._face_zone_start

            # Short slow contact — probably normal (e.g. resting chin on hand)
            if elapsed < FACE_TOUCH_RISK_SEC:
                risk = min(0.25, elapsed / FACE_TOUCH_RISK_SEC * 0.25)
                return risk, f"face touch ({elapsed:.1f}s)"

            # Long slow contact — risk rises steadily
            excess  = elapsed - FACE_TOUCH_RISK_SEC
            max_add = 3.0
            extra   = min(0.40, excess / max_add * 0.40)
            risk    = 0.25 + extra
            return risk, f"prolonged face contact ({elapsed:.1f}s)"

        else:
            # Steering zone — direct risk (hand below face = likely phone)
            if self._direk_zone_start is None:
                self._direk_zone_start = now
            self._face_zone_start = None
            elapsed = now - self._direk_zone_start

            if elapsed < PHONE_HOLD_SEC:
                risk = min(0.55, elapsed / PHONE_HOLD_SEC * 0.55)
                return risk, f"steering zone ({elapsed:.1f}s)"
            else:
                excess  = elapsed - PHONE_HOLD_SEC
                max_add = 5.0
                extra   = min(0.35, excess / max_add * 0.35)
                risk    = 0.55 + extra
                return risk, f"phone holding ({elapsed:.1f}s)"

    @staticmethod
    def _neutral(detail: str = "normal") -> dict:
        return {
            "distraction": False,
            "risk_score":  0.0,
            "detail":      detail,
            "hands_count": 0,
        }

    @staticmethod
    def _risk_color(risk: float) -> tuple[int, int, int]:
        """BGR color based on risk level."""
        if risk < 0.25:
            return (0, 200, 0)    # Green
        elif risk < 0.55:
            return (0, 165, 255)  # Orange
        else:
            return (0, 0, 220)    # Red
