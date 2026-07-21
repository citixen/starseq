import threading
from dataclasses import dataclass, field


@dataclass
class SequenceNote:
    midi_note: int  # 0–127
    velocity: int  # 0–127
    duration: int  # steps; converted to ms at play time from BPM + divider
    star_hr: int  # HR number of source star (for display flash)


@dataclass
class SequenceStep:
    notes: list  # list[SequenceNote]; empty = rest


@dataclass
class TrackState:
    # From controller interface
    controller_id: int = 0
    interface_status: int = 0  # 0=waiting,1=online,2=stale,3=offline
    mode: int = 0  # 0=stopped,1=mono,2=poly
    length: int = 16
    play_mode: int = 0  # 0–7 index
    step_divider: int = 6  # 0–12 index (default = 1/4 note)
    param_mode: int = 0  # 0=parametric,1=random_static,2=random_per_loop
    play_direction: int = 1  # 0=reverse,1=forward
    base_note: int = 60  # MIDI note 60 = middle C
    note_range: int = 24  # semitones above base_note
    vel_lo: int = 64
    vel_hi: int = 100
    dur_lo: int = 1
    dur_hi: int = 4
    slice_centre: int = 180  # degrees
    slice_width: int = 60  # degrees
    slice_brightness: int = 60  # 0=all stars, 100=brightest only
    midi_channel: int = 1  # 1–16

    def __post_init__(self):
        self._lock = threading.Lock()
        self._sequence_lock = threading.Lock()
        # Double-buffered sequence store
        self._active_sequence: list = []
        self._inactive_sequence: list = []
        # Holds a freshly-built sequence waiting to go live at the next step-0
        self._pending_sequence: list = None
        self.sequence_dirty: bool = True
        # Sequencer engine runtime state
        self.step_index: int = 0
        self.tick_accumulator: int = 0

    def get_sequence(self) -> list:
        with self._sequence_lock:
            return self._active_sequence

    @property
    def has_sequence(self) -> bool:
        with self._sequence_lock:
            return bool(self._active_sequence)

    def swap_sequence(self, new_sequence: list):
        """Write new_sequence to inactive buffer then atomically swap."""
        with self._sequence_lock:
            self._inactive_sequence = new_sequence
            self._active_sequence, self._inactive_sequence = (
                self._inactive_sequence,
                self._active_sequence,
            )

    def queue_sequence(self, new_sequence: list):
        """Stage new_sequence to be applied at the next step-0 boundary."""
        with self._sequence_lock:
            self._pending_sequence = new_sequence

    def apply_pending(self):
        """Swap in any queued sequence. Called by the engine at step 0."""
        with self._sequence_lock:
            if self._pending_sequence is not None:
                self._inactive_sequence = self._pending_sequence
                self._active_sequence, self._inactive_sequence = (
                    self._inactive_sequence,
                    self._active_sequence,
                )
                self._pending_sequence = None


class TrackStateStore:
    def __init__(self, n_tracks: int = 8):
        self.tracks = []
        for i in range(n_tracks):
            t = TrackState(
                controller_id=i + 1,
                midi_channel=i + 1,
                slice_centre=(i * 45) % 360,
            )
            self.tracks.append(t)

    def __getitem__(self, i: int) -> TrackState:
        return self.tracks[i]

    def __len__(self) -> int:
        return len(self.tracks)
