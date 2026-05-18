"""
camera/hand_detector.py
=======================
Two-hands-raised detection.
If both hands are raised = no one is holding the steering wheel.
"""

import cv2
import numpy as np
import time


RAISE_Y_RATIO  = 0.65   # frame üst %65 = havada
BOTH_RAISE_SEC = 1.0    # kaç saniye sonra alert
MAX_RISK_SEC   = 3.0
MIN_HAND_AREA  = 3000
MAX_HAND_AREA  = 80000  # çok büyük = gövde, el değil


class HandRaiseDetector:
    def __init__(self):
        self._raise_start = None
        self._last_result = self._neutral()

    def _skin_mask(self, frame):
        hsv  = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        blur = cv2.GaussianBlur(hsv, (5, 5), 0)

        lower1 = np.array([0,  25,  70],  dtype=np.uint8)
        upper1 = np.array([20, 255, 255], dtype=np.uint8)
        lower2 = np.array([170, 25, 70],  dtype=np.uint8)
        upper2 = np.array([180, 255, 255], dtype=np.uint8)

        mask = cv2.bitwise_or(
            cv2.inRange(blur, lower1, upper1),
            cv2.inRange(blur, lower2, upper2)
        )
        k    = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k)
        mask = cv2.dilate(mask, k, iterations=1)
        return mask

    def update(self, frame, face_rect=None) -> dict:
        h, w = frame.shape[:2]
        now  = time.time()

        mask       = self._skin_mask(frame)
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        # Alan filtresi
        valid = sorted(
            [c for c in contours
             if MIN_HAND_AREA < cv2.contourArea(c) < MAX_HAND_AREA],
            key=cv2.contourArea, reverse=True
        )[:3]

        # Yüz bölgesini çıkar
        hands = []
        for cnt in valid:
            M = cv2.moments(cnt)
            if M["m00"] == 0:
                continue
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])

            # Yüz bölgesinde mi?
            if face_rect is not None:
                fx, fy, fw, fh = face_rect
                margin = 40
                if (fx - margin < cx < fx + fw + margin and
                        fy - margin < cy < fy + fh + int(fh * 0.5)):
                    continue  # yüz bölgesi — atla

            hands.append({"cx": cx, "cy": cy,
                          "area": cv2.contourArea(cnt),
                          "contour": cnt})

        hands_count  = len(hands)
        raised_count = 0

        for hand in hands:
            cx, cy = hand["cx"], hand["cy"]
            # Eller yüzün altındaysa ve frame'in üst yarısındaysa = havada
            raised = cy < h * 0.75
            if raised:
                raised_count += 1
            color = (0, 0, 255) if raised else (255, 100, 0)
            cv2.drawContours(frame, [hand["contour"]], -1, color, 2)
            cv2.circle(frame, (cx, cy), 8, color, -1)
            cv2.putText(frame,
                        f"{'UP' if raised else 'down'}",
                        (cx + 10, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            color = (0, 0, 255) if raised else (255, 100, 0)
            cv2.drawContours(frame, [hand["contour"]], -1, color, 2)
            cv2.circle(frame, (cx, cy), 8, color, -1)
            cv2.putText(frame,
                        f"{'UP' if raised else 'down'}",
                        (cx + 10, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        both_raised = raised_count >= 2

        if both_raised:
            if self._raise_start is None:
                self._raise_start = now
            elapsed = now - self._raise_start
        else:
            self._raise_start = None
            elapsed = 0.0

        risk        = 0.0
        if elapsed >= BOTH_RAISE_SEC:
            risk = min(1.0, (elapsed - BOTH_RAISE_SEC) /
                       (MAX_RISK_SEC - BOTH_RAISE_SEC))

        distraction = both_raised

        if both_raised:
            color = (0, 0, 255) if distraction else (0, 165, 255)
            label = (f"! HANDS OFF WHEEL {elapsed:.1f}s !"
                     if distraction else
                     f"Hands raising {elapsed:.1f}s")
            cv2.putText(frame, label,
                        (w // 2 - 210, h - 40),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.9, color, 2)

        detail = "normal"
        if both_raised:
            detail = (f"hands off wheel {elapsed:.1f}s"
                      if distraction else
                      f"raising {elapsed:.1f}s")

        return {
            "both_raised":  both_raised,
            "hands_count":  hands_count,
            "raised_count": raised_count,
            "risk_score":   round(risk, 3),
            "detail":       detail,
            "distraction":  distraction,
        }

    def draw_status(self, frame, result: dict):
        h, w  = frame.shape[:2]
        risk  = result["risk_score"]
        color = (0, 200, 0) if risk < 0.3 else \
                (0, 165, 255) if risk < 0.6 else \
                (0, 0, 255)

        cv2.putText(
            frame,
            f"Hands:{result['hands_count']} "
            f"Raised:{result['raised_count']} "
            f"[{result['detail']}]",
            (18, h - 20),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1
        )

        if result["distraction"]:
            cv2.rectangle(frame, (0, 0), (w, 38), (0, 0, 200), -1)
            cv2.putText(
                frame,
                "! HANDS OFF STEERING WHEEL !",
                (w // 2 - 200, 27),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8, (255, 255, 255), 2
            )

    @staticmethod
    def _neutral(detail="normal") -> dict:
        return {
            "both_raised":  False,
            "hands_count":  0,
            "raised_count": 0,
            "risk_score":   0.0,
            "detail":       detail,
            "distraction":  False,
        }