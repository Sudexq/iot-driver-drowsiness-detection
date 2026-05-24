"""
camera/calibrate_ear.py
=======================
Personal EAR threshold calibration tool.

Usage:
    python camera/calibrate_ear.py

Steps:
    Phase 1 (5s): Keep eyes OPEN
    Phase 2 (5s): Keep eyes CLOSED

Output:
    Recommended EAR_THRESHOLD for camera_detector.py
"""

import cv2
import dlib
import numpy as np
from scipy.spatial import distance as dist
import os
import time

# ── Dlib setup ────────────────────────────────────────────────────
LANDMARK_MODEL = os.path.join(
    os.path.dirname(__file__),
    "shape_predictor_68_face_landmarks.dat"
)

if not os.path.exists(LANDMARK_MODEL):
    print("❌ shape_predictor_68_face_landmarks.dat bulunamadı!")
    print("   Önce modeli indirin:")
    print("   python -c \"import urllib.request, bz2, os; urllib.request.urlretrieve('http://dlib.net/files/shape_predictor_68_face_landmarks.dat.bz2', 'tmp.bz2'); open('camera/shape_predictor_68_face_landmarks.dat', 'wb').write(bz2.open('tmp.bz2').read()); os.remove('tmp.bz2'); print('Done')\"")
    exit(1)

detector  = dlib.get_frontal_face_detector()
predictor = dlib.shape_predictor(LANDMARK_MODEL)

LEFT_EYE  = list(range(42, 48))
RIGHT_EYE = list(range(36, 42))


def ear(pts):
    A = dist.euclidean(pts[1], pts[5])
    B = dist.euclidean(pts[2], pts[4])
    C = dist.euclidean(pts[0], pts[3])
    return (A + B) / (2.0 * C)


def lm_to_arr(shape, idx):
    return np.array([(shape.part(i).x, shape.part(i).y) for i in idx])


def main():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ Kamera açılamadı.")
        return

    open_ears   = []
    closed_ears = []

    print("=" * 50)
    print("EAR Kalibrasyon")
    print("=" * 50)
    print("Adım 1: Gözlerini AÇIK tut (3 saniye hazırlık + 5 saniye ölçüm)")
    print("Adım 2: Gözlerini KAPAT  (3 saniye hazırlık + 5 saniye ölçüm)")
    print("'q' ile çık\n")

    # ── Faz 1: Hazırlık ──────────────────────────────────────────
    print(">> 3 saniye sonra AÇIK göz ölçümü başlıyor...")
    for i in range(3, 0, -1):
        print(f"   {i}...")
        ret, frame = cap.read()
        if ret:
            cv2.putText(frame, f"Hazirlaniyor: {i}",
                        (20, 50), cv2.FONT_HERSHEY_SIMPLEX,
                        1.2, (0, 255, 255), 3)
            cv2.putText(frame, "GOZLERINI ACIK TUT",
                        (20, 100), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (0, 255, 0), 2)
            cv2.imshow("EAR Calibration", frame)
        cv2.waitKey(1000)

    # ── Faz 2: Açık göz ölçümü ───────────────────────────────────
    print("\n>> ACIK goz olcuyor — gozlerini ACIK tut!")
    start = time.time()
    while time.time() - start < 5.0:
        ret, frame = cap.read()
        if not ret:
            break
        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = detector(gray, 0)
        avg   = 0.0
        if faces:
            shape = predictor(gray, faces[0])
            l     = lm_to_arr(shape, LEFT_EYE)
            r     = lm_to_arr(shape, RIGHT_EYE)
            avg   = round((ear(l) + ear(r)) / 2.0, 4)
            open_ears.append(avg)

        remaining = round(5.0 - (time.time() - start), 1)
        cv2.putText(frame, f"ACIK GOZ: {remaining}s",
                    (20, 50), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (0, 255, 0), 2)
        cv2.putText(frame, f"EAR = {avg:.3f}",
                    (20, 90), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, (255, 255, 255), 2)
        cv2.imshow("EAR Calibration", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    # ── Faz 3: Hazırlık ──────────────────────────────────────────
    print("\n>> 3 saniye sonra KAPALI göz ölçümü başlıyor...")
    for i in range(3, 0, -1):
        print(f"   {i}...")
        ret, frame = cap.read()
        if ret:
            cv2.putText(frame, f"Hazirlaniyor: {i}",
                        (20, 50), cv2.FONT_HERSHEY_SIMPLEX,
                        1.2, (0, 255, 255), 3)
            cv2.putText(frame, "GOZLERINI KAPATMAYA HAZIRLAN",
                        (20, 100), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (0, 165, 255), 2)
            cv2.imshow("EAR Calibration", frame)
        cv2.waitKey(1000)

    # ── Faz 4: Kapalı göz ölçümü ─────────────────────────────────
    print("\n>> KAPALI goz olcuyor — gozlerini KAPAT!")
    start = time.time()
    while time.time() - start < 5.0:
        ret, frame = cap.read()
        if not ret:
            break
        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = detector(gray, 0)
        avg   = 0.0
        if faces:
            shape = predictor(gray, faces[0])
            l     = lm_to_arr(shape, LEFT_EYE)
            r     = lm_to_arr(shape, RIGHT_EYE)
            avg   = round((ear(l) + ear(r)) / 2.0, 4)
            closed_ears.append(avg)

        remaining = round(5.0 - (time.time() - start), 1)
        cv2.putText(frame, f"KAPALI GOZ: {remaining}s",
                    (20, 50), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (0, 0, 255), 2)
        cv2.putText(frame, f"EAR = {avg:.3f}",
                    (20, 90), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, (255, 255, 255), 2)
        cv2.imshow("EAR Calibration", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

    # ── Sonuç ─────────────────────────────────────────────────────
    if open_ears and closed_ears:
        avg_open   = round(sum(open_ears)   / len(open_ears),   3)
        avg_closed = round(sum(closed_ears) / len(closed_ears), 3)

        print(f"\n{'='*50}")
        print(f"📊 Kalibrasyon Sonucu:")
        print(f"   Açık göz EAR    : {avg_open}")
        print(f"   Kapalı göz EAR  : {avg_closed}")

        if avg_open > avg_closed:
            threshold = round(avg_closed + (avg_open - avg_closed) * 0.35, 3)
            print(f"\n✅ Senin için EAR_THRESHOLD: {threshold}")
            print(f"\n   camera_detector.py içinde değiştir:")
            print(f"   EAR_THRESHOLD = {threshold}")
        else:
            print("\n⚠️  Açık göz EAR kapalıdan düşük çıktı!")
            print("   Kalibrasyon sırasında gözlerin tam kapalı olmamış olabilir.")
            print("   Tekrar dene.")
        print("=" * 50)
    else:
        print("❌ Yeterli veri toplanamadı — tekrar dene.")


if __name__ == "__main__":
    main()