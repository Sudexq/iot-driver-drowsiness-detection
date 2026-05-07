import cv2

print("📷 Webcam test başlıyor...")
print("   Çıkmak için 'q' tuşuna bas.\n")

# 0 = varsayılan webcam
# Çalışmazsa 1 veya 2 dene
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("❌ Webcam açılamadı!")
    print("   Çözüm önerileri:")
    print("   1. Başka bir program webcam'i kullanıyor olabilir")
    print("   2. cv2.VideoCapture(1) veya (2) dene")
    print("   3. Windows'ta Kamera izinlerini kontrol et")
    exit(1)

# Webcam özellikleri
width  = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
fps    = cap.get(cv2.CAP_PROP_FPS)

print(f"✅ Webcam açıldı!")
print(f"   Çözünürlük : {int(width)}x{int(height)}")
print(f"   FPS        : {fps}\n")

frame_count = 0

while True:
    ret, frame = cap.read()

    if not ret:
        print("❌ Frame okunamadı!")
        break

    frame_count += 1

    # Ekrana bilgi yaz
    cv2.putText(
        frame,
        f"Webcam OK | Frame: {frame_count}",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (0, 255, 0),
        2
    )
    cv2.putText(
        frame,
        "Q = Cik",
        (20, 80),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 200, 255),
        2
    )

    cv2.imshow("Webcam Test", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()

print(f"\n✅ Test tamamlandı — {frame_count} frame okundu.")
print("   Webcam çalışıyor, Step 2'ye geçebiliriz!")