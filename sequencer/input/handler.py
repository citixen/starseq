import threading
import queue
import logging

import config

logger = logging.getLogger(__name__)

# BCM pin assignments
_ENC_A = 17
_ENC_B = 18
_ENC_BTN = 27
_PLAY_STOP = 16

_LONG_HOLD_S = config.ENCODER_LONG_HOLD_MS / 1000.0

try:
    from gpiozero import Device, RotaryEncoder, Button
    from gpiozero.pins.lgpio import LGPIOFactory

    Device.pin_factory = LGPIOFactory()
    _HAS_GPIO = True
except ImportError:
    _HAS_GPIO = False
    logger.info("gpiozero/lgpio not available; input handler running in stub mode")


class InputEvent:
    __slots__ = ("type", "value")

    def __init__(self, event_type: str, value=None):
        self.type = event_type  # 'rotate' | 'press' | 'long_press' | 'play_stop'
        self.value = value  # ±1 for rotate; bool for play_stop


class InputHandler(threading.Thread):
    """Handles rotary encoder and SPDT switch via gpiozero/lgpio; emits InputEvent objects."""

    def __init__(self, event_queue: queue.Queue):
        super().__init__(name="InputHandler", daemon=True)
        self._queue = event_queue
        self._stop_event = threading.Event()
        self._long_fired = False

    def stop(self):
        self._stop_event.set()

    def _emit(self, event_type: str, value=None):
        try:
            self._queue.put_nowait(InputEvent(event_type, value))
        except queue.Full:
            pass

    def run(self):
        if not _HAS_GPIO:
            while not self._stop_event.is_set():
                self._stop_event.wait(0.1)
            return

        encoder = RotaryEncoder(_ENC_A, _ENC_B)
        btn = Button(_ENC_BTN, pull_up=True, hold_time=_LONG_HOLD_S, bounce_time=0.05)
        play_stop = Button(_PLAY_STOP, pull_up=True, bounce_time=0.05)

        encoder.when_rotated_clockwise = lambda: self._emit("rotate", 1)
        encoder.when_rotated_counter_clockwise = lambda: self._emit("rotate", -1)

        import time as _time

        _DOUBLE_PRESS_WINDOW_S = 0.35
        last_press_time = [None]  # mutable cell for closure
        suppress_release = [False]

        def on_btn_pressed():
            now = _time.perf_counter()
            if (
                last_press_time[0] is not None
                and (now - last_press_time[0]) < _DOUBLE_PRESS_WINDOW_S
            ):
                self._emit("double_press")
                suppress_release[0] = True
                last_press_time[0] = None
            else:
                self._long_fired = False
                last_press_time[0] = now
                suppress_release[0] = False

        def on_btn_held():
            self._long_fired = True
            last_press_time[0] = None  # prevent hold+release being mistaken for double
            self._emit("long_press")

        def on_btn_released():
            if suppress_release[0]:
                suppress_release[0] = False
                return
            if not self._long_fired:
                self._emit("press")
            self._long_fired = False

        btn.when_pressed = on_btn_pressed
        btn.when_held = on_btn_held
        btn.when_released = on_btn_released

        # The encoder button was causing sustained crosstalk on the play/stop line
        # # for as long as it was held. Primary fix: reject any play/stop signal that
        # arrives while the encoder button is pressed. Secondary fix: require the
        # signal to be held for 150 ms before confirming, catching any residual
        # noise after the encoder button releases.
        # Tertiary fix : Make better hardware than I did.
        _PLAY_MIN_HOLD_S = 0.15
        _ps_timer = [None]
        _ps_active = [False]

        def on_play_pressed():
            if btn.is_pressed:
                return  # crosstalk from encoder button

            def _confirm():
                _ps_timer[0] = None
                if play_stop.is_pressed and not btn.is_pressed:
                    _ps_active[0] = True
                    self._emit("play_stop", True)

            t = threading.Timer(_PLAY_MIN_HOLD_S, _confirm)
            _ps_timer[0] = t
            t.start()

        def on_play_released():
            if _ps_timer[0] is not None:
                _ps_timer[0].cancel()
                _ps_timer[0] = None
            if _ps_active[0]:
                _ps_active[0] = False
                self._emit("play_stop", False)

        play_stop.when_pressed = on_play_pressed
        play_stop.when_released = on_play_released

        self._stop_event.wait()

        encoder.close()
        btn.close()
        play_stop.close()
