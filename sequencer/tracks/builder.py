import threading
import queue
import logging

from tracks.state import TrackStateStore
from tracks.slice import build_sequence
from transport.state import TransportState

logger = logging.getLogger(__name__)


def _is_loop_random(track) -> bool:
    """True when this track's output should be re-rolled once per loop, not per sky update."""
    return track.play_mode == 0 or track.param_mode == 2


class SequenceBuilder(threading.Thread):
    """Listens for sky snapshots and rebuilds sequences for dirty tracks."""

    def __init__(self, track_store: TrackStateStore, transport: TransportState,
                 sky_queue: queue.Queue):
        super().__init__(name='SequenceBuilder', daemon=True)
        self._track_store = track_store
        self._transport = transport
        self._sky_queue = sky_queue
        self._stop_event = threading.Event()
        self._last_snapshot: list = []

    def stop(self):
        self._stop_event.set()

    def trigger_rebuild_all(self):
        for track in self._track_store.tracks:
            with track._lock:
                track.sequence_dirty = True

    def _rebuild_dirty(self, snapshot: list):
        with self._transport._lock:
            key = self._transport.key
            scale = self._transport.scale
            max_poly = self._transport.max_poly_notes

        for track in self._track_store.tracks:
            with track._lock:
                dirty = track.sequence_dirty
                if dirty:
                    track.sequence_dirty = False

            if not dirty:
                continue

            try:
                new_seq = build_sequence(track, snapshot, key, scale, max_poly)
                # Tracks whose output is loop-randomized must not swap mid-loop.
                # Stage to pending so the engine applies it cleanly at step 0.
                if _is_loop_random(track) and track.has_sequence:
                    track.queue_sequence(new_seq)
                else:
                    track.swap_sequence(new_seq)
            except Exception:
                logger.exception("Sequence build error for track %d", track.controller_id)

    def run(self):
        while not self._stop_event.is_set():
            try:
                snapshot = self._sky_queue.get(timeout=0.05)
            except queue.Empty:
                # No new sky data — still check for dirty tracks from param changes
                if self._last_snapshot:
                    self._rebuild_dirty(self._last_snapshot)
                continue

            self._last_snapshot = snapshot

            # Mark tracks dirty on new sky data, but skip loop-randomized tracks:
            # their star selection is driven by the engine's per-loop trigger, not
            # by sky position updates, so a snapshot alone should never re-roll them.
            for track in self._track_store.tracks:
                if not _is_loop_random(track):
                    with track._lock:
                        track.sequence_dirty = True

            self._rebuild_dirty(snapshot)
