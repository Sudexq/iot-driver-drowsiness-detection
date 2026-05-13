"""
camera/gaze_detector.py
=======================
Gaze direction detection using MediaPipe Face Mesh.

Computed values:
  gaze_down      : bool  — is the driver looking down?
  gaze_score     : float — risk level from 0.0 to 1.0
  gaze_down_secs : float — how many seconds looking down
"""

import time
import cv2
import numpy as np

try:
    import mediapipe as mp
    MP_AVAILABLE = True
except ImportError:
    MP_AVAILABLE = False

# ── Eye landmark indices (MediaPipe Face Mesh) ────────────────────
# Left eye
LEFT_EYE_TOP    = 159
LEFT_EYE_BOTTOM = 145
LEFT_EYE_LEFT   = 33
LEFT_EYE_RIGHT  = 133

# Right eye
RIGHT_EYE_TOP    = 386
RIGHT_EYE_BOTTOM = 374
RIGHT_EYE_LEFT   = 362
RIGHT_EYE_RIGHT  = 263

# Iris center (pupil)
LEFT_IRIS  = 468
RIGHT_IRIS = 473

# Nose tip + chin + forehead (for head tilt)
NOSE_TIP = 4
CHIN     = 152
FOREHEAD = 10

# ── Thresholds ────────────────────────────────────────────────────
GAZE_DOWN_RATIO = 0.58  # iris below this ratio of eye height = looking down
GAZE_RISK_SEC   = 1.5   # risk starts building after this many seconds
GAZE_MAX_SEC    = 4.0   # risk reaches maximum at this many seconds
GAZE_ALERT_SEC  = 2.0   # audio alarm triggers after this many seconds


class GazeDetector:
    """
    Call update(frame) every frame, returns a dict:
      gaze_down      : bool
      gaze_score     : float  0.0-1.0
      gaze_down_secs : float
      head_down      : bool
      detail         : str
    """

    def __init__(self):
        if not MP_AVAILABLE:
            self._face_mesh = None
            return

        self._mp = mp.solutions.face_mesh
        self._face_mesh = self._mp.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.5,
        )

        self._gaze_down_start = None
        self._last_result = self._neutral()

    # ── Public API ────────────────────────────────────────────────

    def update(self, frame) -> dict:
        if self._face_mesh is None:
            return self._neutral("mediapipe not available")

        h, w = frame.shape[:2]
        rgb  = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res  = self._face_mesh.process(rgb)

        if not res.multi_face_landmarks:
            # Face not visible — reset timer
            self._gaze_down_start = None
            self._last_result = self._neutral("face not visible")
            return self._last_result

        lm = res.multi_face_landmarks[0].landmark

        # ── Head position ─────────────────────────────────────────
        head_down = self._calc_head_down(lm)

        # ── Iris position ─────────────────────────────────────────
        iris_down = self._calc_iris_down(lm)

        # ── Decision: looking down? ───────────────────────────────
        # head_down alone is enough — more reliable than iris
        looking_down = head_down or iris_down

        now = time.time()
        if looking_down:
            if self._gaze_down_start is None:
                self._gaze_down_start = now
            elapsed = now - self._gaze_down_start
        else:
            self._gaze_down_start = None
            elapsed = 0.0

        # ── Risk score ────────────────────────────────────────────
        if elapsed < GAZE_RISK_SEC:
            score = 0.0
        else:
            score = min(1.0, (elapsed - GAZE_RISK_SEC) /
                        (GAZE_MAX_SEC - GAZE_RISK_SEC))

        # ── Draw on frame ─────────────────────────────────────────
        self._draw(frame, lm, w, h, looking_down, elapsed, score)

        detail = "normal"
        if looking_down:
            if elapsed < GAZE_RISK_SEC:
                detail = f"looking down ({elapsed:.1f}s)"
            else:
                detail = f"looking down too long ({elapsed:.1f}s) !"

        result = {
            "gaze_down":      looking_down,
            "gaze_score":     round(score, 3),
            "gaze_down_secs": round(elapsed, 1),
            "head_down":      head_down,
            "detail":         detail,
        }
        self._last_result = result
        return result

    # ── Calculations ──────────────────────────────────────────────

    def _calc_head_down(self, lm) -> bool:
        """
        Check if the head is tilted down by measuring
        the nose position relative to the face height.
        When looking down, the nose moves upward in frame
        relative to forehead-chin distance.
        """
        nose     = lm[NOSE_TIP]
        chin     = lm[CHIN]
        forehead = lm[FOREHEAD]

        face_height = chin.y - forehead.y
        if face_height < 0.001:
            return False

        # Where is the nose vertically within the face?
        # 0.0 = at forehead, 1.0 = at chin
        # Normal forward gaze: nose sits around 0.47-0.55
        # Looking down: nose appears higher -> ratio drops below 0.45
        nose_pos = (nose.y - forehead.y) / face_height
        return nose_pos < 0.45

    def _calc_iris_down(self, lm) -> bool:
        """
        Check iris position within the eye vertically.
        0.0 = top of eye, 1.0 = bottom of eye.
        Above threshold = looking down.
        """
        left_ratio = self._iris_ratio(
            lm, LEFT_IRIS,
            LEFT_EYE_TOP, LEFT_EYE_BOTTOM
        )
        right_ratio = self._iris_ratio(
            lm, RIGHT_IRIS,
            RIGHT_EYE_TOP, RIGHT_EYE_BOTTOM
        )
        avg = (left_ratio + right_ratio) / 2
        return avg > GAZE_DOWN_RATIO

    @staticmethod
    def _iris_ratio(lm, iris_idx, top_idx, bottom_idx) -> float:
        iris   = lm[iris_idx].y
        top    = lm[top_idx].y
        bottom = lm[bottom_idx].y
        eye_h  = bottom - top
        if eye_h < 0.001:
            return 0.5
        return (iris - top) / eye_h

    # ── Visualization ─────────────────────────────────────────────

    def _draw(self, frame, lm, w, h, looking_down, elapsed, score):
        color = (0, 0, 220) if looking_down else (0, 200, 0)

        # Left eye box
        lx1 = int(lm[LEFT_EYE_LEFT].x  * w) - 5
        lx2 = int(lm[LEFT_EYE_RIGHT].x * w) + 5
        ly1 = int(lm[LEFT_EYE_TOP].y   * h) - 5
        ly2 = int(lm[LEFT_EYE_BOTTOM].y * h) + 5
        cv2.rectangle(frame, (lx1, ly1), (lx2, ly2), color, 1)

        # Right eye box
        rx1 = int(lm[RIGHT_EYE_LEFT].x  * w) - 5
        rx2 = int(lm[RIGHT_EYE_RIGHT].x * w) + 5
        ry1 = int(lm[RIGHT_EYE_TOP].y   * h) - 5
        ry2 = int(lm[RIGHT_EYE_BOTTOM].y * h) + 5
        cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), color, 1)

        # Status text
        label = f"Gaze: {'DOWN!' if looking_down else 'normal'}"
        if elapsed > 0:
            label += f" {elapsed:.1f}s"
        cv2.putText(frame, label, (18, h - 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1)

    @staticmethod
    def _neutral(detail="normal") -> dict:
        return {
            "gaze_down":      False,
            "gaze_score":     0.0,
            "gaze_down_secs": 0.0,
            "head_down":      False,
            "detail":         detail,
        }