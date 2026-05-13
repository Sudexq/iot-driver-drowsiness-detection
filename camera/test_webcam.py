import cv2

print("📷 Webcam test başlıyor...")
print("   0, 1, 2 indexleri deneniyor...\n")

# Çalışan kamera indexini otomatik bul
cap = None
found_index = -1
for idx in range(3):
    _c = cv2.VideoCapture(idx)
    if _c.isOpened():
        ret, _f = _c.read()
        if ret:
            cap = _c
            found_index = idx
            print(f"✅ Kamera bulundu: index {idx}")
            break
        _c.release()
    else:
        _c.release()
        print(f"   Index {idx}: açılamadı")

if cap is None:
    print("\n❌ Hiçbir kamera bulunamadı!")
    print("   Olası nedenler:")
    print("   1. Teams, Zoom veya başka bir uygulama kamerayı kullanıyor → kapat")
    print("   2. Windows Ayarları → Gizlilik → Kamera → Python'a izin ver")
    print("   3. Harici webcam takılı değil")
    print("\n   Kamera düzelince tekrar dene: python camera/test_webcam.py")
    exit(1)

# Webcam özellikleri
width  = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
fps    = cap.get(cv2.CAP_PROP_FPS)

print(f"   Çözünürlük : {int(width)}x{int(height)}")
print(f"   FPS        : {fps}")
print(f"\n   Pencereyi kapat veya 'q' tuşuna bas.\n")

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
print(f"   Webcam index {found_index} çalışıyor.")
print(f"   camera_detector.py'yi çalıştırabilirsin: python camera/camera_detector.py")