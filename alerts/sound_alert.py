import threading
import time

try:
    import winsound
    WINDOWS = True
except ImportError:
    WINDOWS = False

# Şu an hangi alarm çalıyor?
# None = sessiz, "drowsiness" = uyuşukluk, "distraction" = telefon/gaze
_active_alarm = None
_alarm_lock   = threading.Lock()
_alarm_thread = None


def _beep_loop(alarm_type):
    """Arka planda sürekli bip sesi çalar."""
    global _active_alarm
    while True:
        with _alarm_lock:
            if _active_alarm != alarm_type:
                break
        if WINDOWS:
            if alarm_type == "drowsiness":
                winsound.Beep(800, 400)   # 800 Hz, 0.4 sn — uzun tehlikeli ses
                time.sleep(0.3)
            else:
                winsound.Beep(1200, 200)  # 1200 Hz, 0.2 sn — kısa dikkat sesi
                time.sleep(0.5)
        else:
            print(f"\a")  # Mac/Linux terminal zili
            time.sleep(1)


def play_alarm(alarm_type):
    """
    alarm_type: "drowsiness" veya "distraction"

    Kural:
    - drowsiness alarmı aktifse distraction alarmı ÇALMA
    - drowsiness yoksa distraction çalabilir
    - aynı alarm zaten çalıyorsa tekrar başlatma
    """
    global _active_alarm, _alarm_thread

    with _alarm_lock:
        # Uyuşukluk çalıyorsa dikkat dağınıklığı alarmını engelle
        if _active_alarm == "drowsiness" and alarm_type == "distraction":
            return

        # Zaten aynı alarm çalıyorsa tekrar başlatma
        if _active_alarm == alarm_type:
            return

        _active_alarm = alarm_type

    # Eski thread bitene kadar bekle, yenisini başlat
    if _alarm_thread and _alarm_thread.is_alive():
        _alarm_thread.join(timeout=1)

    _alarm_thread = threading.Thread(
        target=_beep_loop, args=(alarm_type,), daemon=True
    )
    _alarm_thread.start()


def stop_alarm(alarm_type=None):
    """
    alarm_type verilirse sadece o alarm durdurulur.
    None verilirse her alarm durdurulur.
    """
    global _active_alarm
    with _alarm_lock:
        if alarm_type is None or _active_alarm == alarm_type:
            _active_alarm = None


def is_alarm_active(alarm_type=None):
    """Belirtilen alarm (veya herhangi bir alarm) çalıyor mu?"""
    with _alarm_lock:
        if alarm_type is None:
            return _active_alarm is not None
        return _active_alarm == alarm_type