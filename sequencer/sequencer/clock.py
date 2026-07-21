import threading


class InternalClock:
    """Provides the tick interval for the internal software clock."""

    def __init__(self, bpm: float = 120.0, ppqn: int = 24):
        self._bpm = bpm
        self._ppqn = ppqn
        self._lock = threading.Lock()

    @property
    def tick_interval(self) -> float:
        with self._lock:
            return 60.0 / (self._bpm * self._ppqn)

    def set_bpm(self, bpm: float):
        with self._lock:
            self._bpm = max(20.0, min(300.0, bpm))

    def set_ppqn(self, ppqn: int):
        with self._lock:
            self._ppqn = ppqn
