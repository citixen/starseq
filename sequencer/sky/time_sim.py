import time
import threading
from datetime import datetime, timezone, timedelta


class SimulatedClock:
    """Simulated sky clock that can run faster, slower, frozen, or in reverse."""

    def __init__(self):
        self._lock = threading.Lock()
        self._sim_time_anchor: datetime = datetime.now(timezone.utc)
        self._wall_anchor: float = time.perf_counter()
        self._multiplier: float = 1.0

    @property
    def multiplier(self) -> float:
        with self._lock:
            return self._multiplier

    @multiplier.setter
    def multiplier(self, value: float):
        with self._lock:
            # Advance sim anchor to current moment before changing rate
            elapsed = time.perf_counter() - self._wall_anchor
            self._sim_time_anchor += timedelta(seconds=elapsed * self._multiplier)
            self._wall_anchor = time.perf_counter()
            self._multiplier = value

    def reset(self):
        """Snap simulated clock to current UTC; multiplier is unchanged."""
        with self._lock:
            self._sim_time_anchor = datetime.now(timezone.utc)
            self._wall_anchor = time.perf_counter()

    def set_time(self, dt: datetime):
        """Jump the simulated clock to an arbitrary UTC datetime; multiplier unchanged."""
        with self._lock:
            self._sim_time_anchor = dt
            self._wall_anchor = time.perf_counter()

    def now(self) -> datetime:
        with self._lock:
            elapsed = time.perf_counter() - self._wall_anchor
            return self._sim_time_anchor + timedelta(seconds=elapsed * self._multiplier)

    def get_state(self) -> tuple:
        """Return (sim_time_anchor, wall_anchor, multiplier) snapshot."""
        with self._lock:
            return self._sim_time_anchor, self._wall_anchor, self._multiplier
