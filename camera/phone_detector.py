"""
camera/phone_detector.py
========================
MediaPipe Hands ile telefon kullanimi tespiti.

Yüze dokunma (kasima, vs.) ile telefon tutmayi ayirt etmek icin
3 sinyal birlesimi kullanilir:

  1. KONUM   — Bilek eklem noktasi (landmark 0) frame'in üst %55'indeyse
               yüz bölgesi, altindaysa direksiyon bölgesi.
  2. SÜRE    — Yüz bölgesinde 2 saniyeden uzun süreli temas → risk artar.
  3. HAREKET — El hareketi yavas ise (< FAST_MOVE_PX px/frame) tutma,
               hizli ise gecici dokunma (kasima, selam) olarak degerlendirile.

Elde edilen phone_risk_score (0.0–1.0) mevcut UDP paketine eklenir:
  "phone_distraction": bool
  "phone_risk_score":  float
  "phone_detail":      str   (debug icin)

Entegrasyon: camera_detector.py'nin main() dongusu icinde
  detector = PhoneDetector()
  ...
  phone_result = detector.update(frame)
  payload["phone_distraction"]  = phone_result["distraction"]
  payload["phone_risk_score"]   = phone_result["risk_score"]
  payload["phone_detail"]       = phone_result["detail"]
"""

import time
from collections import deque
import numpy as np

try:
    import mediapipe as mp
    MP_AVAILABLE = True
except ImportError:
    MP_AVAILABLE = False
    print("⚠️  mediapipe bulunamadi. pip install mediapipe --break-system-packages")


# ── Eslikleri ────────────────────────────────────────────────────
FACE_ZONE_Y_RATIO   = 0.55   # Frame yüksekliginin üst %55'i = yüz bölgesi
FACE_TOUCH_MAX_FAST = 2.0    # Saniye: bu kadar altinda hizli hareket → kasima
FACE_TOUCH_RISK_SEC = 2.0    # Saniye: bu kadar üzerinde yavas temas → süpheli
PHONE_HOLD_SEC      = 3.0    # Saniye: direksiyon altinda bu kadar → telefon
FAST_MOVE_PX        = 80     # Piksel/frame: bu kadar hizli → kasima/selam

WRIST_LM    = 0    # MediaPipe el bilegi landmark indeksi
FINGERTIP_LM = 8   # Isaret parmagi ucu (parmak kamera'ya yakin mi kontrolü)

PHONE_RISK_THRESHOLD = 0.55  # Bu deger ve üzeri = phone_distraction = True


class PhoneDetector:
    """
    Her frame'de update(frame) cagir, bir dict döner.

    Dönen dict:
      distraction : bool   — alert mi?
      risk_score  : float  — 0.0 ile 1.0 arasi risk
      detail      : str    — insan okunabilir durum aciklamasi
      hands_count : int    — tespit edilen el sayisi
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

        # Durum takibi
        self._face_zone_start: float | None = None   # Yüz bölgesine giris zamani
        self._direk_zone_start: float | None = None  # Direksiyon bölgesine giris zamani

        # Hareket hizi hesabi icin önceki bilek konumu
        self._prev_wrist: tuple[float, float] | None = None

        # Son N frame'deki hiz örnekleri (ortalama almak icin)
        self._speed_buf: deque[float] = deque(maxlen=8)

        self._last_result: dict = self._neutral()

    # ── Public API ────────────────────────────────────────────────

    def update(self, frame) -> dict:
        """
        BGR frame al, risk degerlendir, sonucu döndür.
        frame uzerine cizim de yapar (gorselleştirme icin).
        """
        if self._mp_hands is None:
            return self._neutral("mediapipe yuklu degil")

        import cv2
        h, w = frame.shape[:2]
        rgb   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res   = self._mp_hands.process(rgb)

        if not res.multi_hand_landmarks:
            # El yoksa her iki zamanlayici sifirla
            self._face_zone_start  = None
            self._direk_zone_start = None
            self._prev_wrist       = None
            self._speed_buf.clear()
            self._last_result = self._neutral("el tespit edilmedi")
            return self._last_result

        # Birden fazla el varsa hepsini degerlendir, en yüksek riski al
        best_risk  = 0.0
        best_detail = "normal"
        hands_count = len(res.multi_hand_landmarks)

        for hand_lms in res.multi_hand_landmarks:
            # Gorselleştir
            self._draw.draw_landmarks(
                frame, hand_lms, self._mp.HAND_CONNECTIONS
            )

            wrist  = hand_lms.landmark[WRIST_LM]
            wx, wy = int(wrist.x * w), int(wrist.y * h)

            # Hareket hizi (piksel/frame)
            speed = 0.0
            if self._prev_wrist is not None:
                dx    = wx - self._prev_wrist[0]
                dy    = wy - self._prev_wrist[1]
                speed = float(np.sqrt(dx*dx + dy*dy))
            self._speed_buf.append(speed)
            self._prev_wrist = (wx, wy)
            avg_speed = float(np.mean(self._speed_buf)) if self._speed_buf else 0.0

            # Bölge tespiti
            in_face_zone  = wy < h * FACE_ZONE_Y_RATIO
            in_direk_zone = not in_face_zone

            now = time.time()
            risk, detail = self._evaluate(
                in_face_zone, in_direk_zone,
                avg_speed, now
            )

            # El etrafina risk rengi ciz
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
        """Frame'e kisa durum ozeti yaz (camera_detector'daki draw_info'ya ek)."""
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
                frame, "! TELEFON KULLANIMI TESPIT EDILDI !",
                (w // 2 - 200, h - 70),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7, (255, 255, 255), 2
            )

    # ── Ic hesaplamalar ───────────────────────────────────────────

    def _evaluate(
        self,
        in_face_zone: bool,
        in_direk_zone: bool,
        avg_speed: float,
        now: float,
    ) -> tuple[float, str]:
        """
        Bölge + süre + hiz bilgisinden risk skoru üret.
        Döner: (risk_0_to_1, aciklama_str)
        """
        if in_face_zone:
            # Bölge: yüz/alın/kulak — zamanlayiciyi baslat
            if self._face_zone_start is None:
                self._face_zone_start = now
            self._direk_zone_start = None

            elapsed = now - self._face_zone_start

            # Hizli hareket → kasima, selam — düsük risk
            if avg_speed > FAST_MOVE_PX:
                return 0.05, "kasima/selam (hizli hareket)"

            # Kisa temas → büyük olasilikla normal
            if elapsed < FACE_TOUCH_RISK_SEC:
                # Risk elapsed'a göre lineer artar, maksimum 0.25
                risk = min(0.25, elapsed / FACE_TOUCH_RISK_SEC * 0.25)
                return risk, f"yüze dokunma ({elapsed:.1f}s)"

            # Uzun süreli yavas temas → giderek artan risk
            # 2–5 saniye arasi: 0.25 → 0.65
            excess  = elapsed - FACE_TOUCH_RISK_SEC
            max_add = 3.0   # bu kadar saniyede maksimum ek risk
            extra   = min(0.40, excess / max_add * 0.40)
            risk    = 0.25 + extra
            return risk, f"uzun yüz temasi ({elapsed:.1f}s)"

        else:
            # Bölge: direksiyon / alt — direkt risk
            if self._direk_zone_start is None:
                self._direk_zone_start = now
            self._face_zone_start = None

            elapsed = now - self._direk_zone_start

            if elapsed < PHONE_HOLD_SEC:
                # 0–3 sn: düsük-orta risk, 0.10 → 0.55
                risk = min(0.55, elapsed / PHONE_HOLD_SEC * 0.55)
                return risk, f"direksiyon alt bölge ({elapsed:.1f}s)"
            else:
                # 3+ sn: yüksek risk, 0.55 → 0.90
                excess  = elapsed - PHONE_HOLD_SEC
                max_add = 5.0
                extra   = min(0.35, excess / max_add * 0.35)
                risk    = 0.55 + extra
                return risk, f"telefon tutma ({elapsed:.1f}s)"

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
        """Risk degerine göre BGR renk."""
        if risk < 0.25:
            return (0, 200, 0)    # Yesil
        elif risk < 0.55:
            return (0, 165, 255)  # Turuncu
        else:
            return (0, 0, 220)    # Kirmizi


# ── Entegrasyon Ornegi ────────────────────────────────────────────

INTEGRATION_EXAMPLE = """
# camera/camera_detector.py icinde su degisiklikleri yap:

# 1. Import ekle (dosyanin basina):
from camera.phone_detector import PhoneDetector

# 2. main() icinde detector'la birlikte olustur:
phone_det = PhoneDetector()

# 3. Ana dongu icinde her frame'de cagir:
phone_result = phone_det.update(frame)
phone_det.draw_status(frame, phone_result)

# 4. send_udp_packet() cagrisi oncesinde payload'a ekle:
payload["phone_distraction"] = phone_result["distraction"]
payload["phone_risk_score"]  = phone_result["risk_score"]
payload["phone_detail"]      = phone_result["detail"]

# 5. api/app.py -> calculate_drowsiness_score() icinde score'a ekle:
# phone_score = 1.0 if data.get("phone_distraction") else data.get("phone_risk_score", 0.0)
# total = (s_blink + s_eye + s_tilt + s_react + phone_score * 0.30) * 100
# Not: diger agirliklari toplam 0.70 olacak sekilde yeniden dengele.
"""

if __name__ == "__main__":
    print("PhoneDetector — birim testi")
    print("=" * 50)
    det = PhoneDetector()

    if not MP_AVAILABLE:
        print("mediapipe yuklu degil, kütüphane testi atlanıyor.")
    else:
        print("MediaPipe Hands yuklu.")
        print("Webcam testi icin camera_detector.py'yi calistirin.")

    print(INTEGRATION_EXAMPLE)
