import threading
import time

try:
    import winsound
    WINDOWS = True
except ImportError:
    WINDOWS = False

# Currently active alarm.
# None = silent, "drowsiness" = drowsiness alarm, "distraction" = phone/gaze alarm
_active_alarm = None
_alarm_lock   = threading.Lock()
_alarm_thread = None


def _beep_loop(alarm_type):
    """Plays a continuous beep in the background."""
    global _active_alarm
    while True:
        with _alarm_lock:
            if _active_alarm != alarm_type:
                break
        if WINDOWS:
            if alarm_type == "drowsiness":
                winsound.Beep(800, 400)   # 800 Hz, 0.4s — long danger tone
                time.sleep(0.3)
            else:
                winsound.Beep(1200, 200)  # 1200 Hz, 0.2s — short attention tone
                time.sleep(0.5)
        else:
            print("\a")  # Mac/Linux terminal bell
            time.sleep(1)


def play_alarm(alarm_type):
    """
    alarm_type: "drowsiness" or "distraction"

    Rules:
    - If drowsiness alarm is active, distraction alarm is BLOCKED
    - If no drowsiness alarm, distraction alarm can play
    - If the same alarm is already playing, do not restart it
    """
    global _active_alarm, _alarm_thread

    with _alarm_lock:
        # Block distraction alarm if drowsiness is already playing
        if _active_alarm == "drowsiness" and alarm_type == "distraction":
            return

        # Same alarm already playing — do nothing
        if _active_alarm == alarm_type:
            return

        _active_alarm = alarm_type

    # Wait for old thread to finish, then start new one
    if _alarm_thread and _alarm_thread.is_alive():
        _alarm_thread.join(timeout=1)

    _alarm_thread = threading.Thread(
        target=_beep_loop, args=(alarm_type,), daemon=True
    )
    _alarm_thread.start()


def stop_alarm(alarm_type=None):
    """
    If alarm_type is given, only that alarm is stopped.
    If None, all alarms are stopped.
    """
    global _active_alarm
    with _alarm_lock:
        if alarm_type is None or _active_alarm == alarm_type:
            _active_alarm = None


def is_alarm_active(alarm_type=None):
    """Returns True if the specified alarm (or any alarm) is currently playing."""
    with _alarm_lock:
        if alarm_type is None:
            return _active_alarm is not None
        return _active_alarm == alarm_type
