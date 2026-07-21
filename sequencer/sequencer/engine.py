import time
import threading
import queue
import logging
from collections import deque
from fractions import Fraction

import config
from tracks.state import TrackStateStore
from transport.state import TransportState
from sequencer.midi_output import MIDIOutput

logger = logging.getLogger(__name__)

DIVIDER_RATIOS = [
    Fraction(1, 32),
    Fraction(1, 24),
    Fraction(1, 16),
    Fraction(1, 12),
    Fraction(1, 8),
    Fraction(1, 6),
    Fraction(1, 4),
    Fraction(1, 3),
    Fraction(1, 2),
    Fraction(1, 1),
    Fraction(2, 1),
    Fraction(3, 1),
    Fraction(4, 1),
]


class _NoteOff:
    __slots__ = ("tick", "channel", "note")

    def __init__(self, tick: int, channel: int, note: int):
        self.tick = tick
        self.channel = channel
        self.note = note


def _ticks_per_step(divider_index: int) -> int:
    ratio = DIVIDER_RATIOS[min(divider_index, len(DIVIDER_RATIOS) - 1)]
    return max(1, int(config.PPQN * ratio))


class SequencerEngine(threading.Thread):
    """Real-time sequencer engine: advances steps, schedules MIDI notes."""

    def __init__(
        self,
        track_store: TrackStateStore,
        transport: TransportState,
        midi_out: MIDIOutput,
        ext_clock_queue: queue.Queue = None,
    ):
        super().__init__(name="SequencerEngine", daemon=True)
        self._track_store = track_store
        self._transport = transport
        self._midi_out = midi_out
        self._ext_clock_queue = ext_clock_queue or queue.Queue()
        self._stop_event = threading.Event()
        self._tick_count = 0
        self._note_offs: list = []  # sorted list of _NoteOff
        self._prev_modes = [0] * 8
        # Rolling window of perf_counter timestamps: 96 intervals = 4 quarter notes
        self._clock_times: deque = deque(maxlen=97)
        self._clock_pulse_count: int = 0  # cycles 0–23; BPM updated once per beat
        # Flash events: (star_hr, perf_counter_timestamp) for display
        self.flash_events: queue.Queue = queue.Queue(maxsize=200)

    def stop(self):
        self._stop_event.set()

    # ------------------------------------------------------------------ helpers

    def _fire_note_offs(self, tick: int):
        while self._note_offs and self._note_offs[0].tick <= tick:
            ev = self._note_offs.pop(0)
            self._midi_out.send_note_off(ev.channel, ev.note)

    def _schedule_note_off(self, at_tick: int, channel: int, note: int):
        ev = _NoteOff(at_tick, channel, note)
        lo, hi = 0, len(self._note_offs)
        while lo < hi:
            mid = (lo + hi) // 2
            if self._note_offs[mid].tick <= at_tick:
                lo = mid + 1
            else:
                hi = mid
        self._note_offs.insert(lo, ev)

    def _flush_channel_note_offs(self, channel: int):
        self._note_offs = [ev for ev in self._note_offs if ev.channel != channel]

    # ------------------------------------------------------------------ tick

    def _tick(self, tick: int, tick_interval: float = 0.0):
        self._fire_note_offs(tick)

        for i, track in enumerate(self._track_store.tracks):
            with track._lock:
                mode = track.mode

            # Detect mode transitions
            if self._prev_modes[i] != 0 and mode == 0:
                self._midi_out.send_all_notes_off(track.midi_channel)
                self._flush_channel_note_offs(track.midi_channel)
            elif self._prev_modes[i] == 0 and mode != 0:
                with track._lock:
                    track.step_index = 0
                    track.tick_accumulator = 0

            self._prev_modes[i] = mode

            if mode == 0:
                continue

            tps = _ticks_per_step(track.step_divider)

            with track._lock:
                track.tick_accumulator += 1
                if track.tick_accumulator < tps:
                    continue
                track.tick_accumulator = 0
                prev_step_index = track.step_index
                forward = track.play_direction != 0
                if forward:
                    track.step_index = (track.step_index + 1) % track.length
                else:
                    track.step_index = (track.step_index - 1) % track.length
                step_index = track.step_index

            # Loop boundary: forward crosses it on the wrap into step 0; reverse
            # crosses it on the wrap out of step 0.
            at_loop_boundary = step_index == 0 if forward else prev_step_index == 0

            # For loop-randomized tracks (random play mode or random-per-loop param
            # mode): apply any pre-built pending sequence exactly as we cross the loop
            # boundary — the step that's about to become highlighted and play — then
            # queue a rebuild so the next loop's sequence is ready in time.
            if (track.play_mode == 0 or track.param_mode == 2) and at_loop_boundary:
                track.apply_pending()
                with track._lock:
                    track.sequence_dirty = True

            sequence = track.get_sequence()
            if not sequence or step_index >= len(sequence):
                continue

            step = sequence[step_index]
            for note_ev in step.notes:
                self._midi_out.send_note_on(
                    track.midi_channel, note_ev.midi_note, note_ev.velocity
                )
                off_tick = tick + note_ev.duration * tps
                self._schedule_note_off(off_tick, track.midi_channel, note_ev.midi_note)
                hold_s = note_ev.duration * tps * tick_interval
                try:
                    self.flash_events.put_nowait(
                        (note_ev.star_hr, i, time.perf_counter(), hold_s)
                    )
                except queue.Full:
                    pass

    # ------------------------------------------------------------------ rt setup

    @staticmethod
    def _try_realtime():
        try:
            import os as _os

            if hasattr(_os, "sched_setscheduler"):
                param = _os.sched_param(_os.sched_get_priority_max(_os.SCHED_FIFO))
                _os.sched_setscheduler(0, _os.SCHED_FIFO, param)
                logger.info("Real-time scheduling enabled (SCHED_FIFO)")
        except (AttributeError, PermissionError, OSError):
            logger.debug("SCHED_FIFO unavailable; using normal thread priority")

    # ------------------------------------------------------------------ run

    def run(self):
        self._try_realtime()
        ppqn = config.PPQN
        _deadline = time.perf_counter()

        while not self._stop_event.is_set():
            with self._transport._lock:
                playing = self._transport.playing
                bpm = self._transport.bpm
                detected_bpm = self._transport.detected_bpm
                clock_source = self._transport.clock_source

            if clock_source == "external":
                # Process external clock regardless of play state so that a
                # MIDI Start can transition us from stopped → playing.
                try:
                    msg = self._ext_clock_queue.get(timeout=0.1)
                    if msg.type == "clock":
                        now = time.perf_counter()
                        self._clock_times.append(now)
                        self._clock_pulse_count = (self._clock_pulse_count + 1) % 24
                        if (
                            self._clock_pulse_count == 0
                            and len(self._clock_times) == 97
                        ):
                            # 96 intervals = 4 quarter notes; update display once per beat
                            span = self._clock_times[-1] - self._clock_times[0]
                            if span > 0:
                                bpm = 60.0 * 4 / span
                                with self._transport._lock:
                                    self._transport.detected_bpm = bpm
                        if playing:
                            ext_ti = (
                                60.0 / (detected_bpm * ppqn)
                                if detected_bpm > 0
                                else 0.0
                            )
                            self._tick(self._tick_count, ext_ti)
                            self._tick_count += 1
                    elif msg.type == "start":
                        self._tick_count = 0
                        for track in self._track_store.tracks:
                            with track._lock:
                                track.step_index = 0
                                track.tick_accumulator = 0
                        with self._transport._lock:
                            self._transport.playing = True
                    elif msg.type == "continue":
                        with self._transport._lock:
                            self._transport.playing = True
                    elif msg.type == "stop":
                        self._clock_times.clear()
                        self._clock_pulse_count = 0
                        with self._transport._lock:
                            self._transport.playing = False
                            self._transport.detected_bpm = 0.0
                except queue.Empty:
                    pass
                continue

            # Switching from external → internal: reset detected BPM
            if self._clock_times:
                self._clock_times.clear()
                self._clock_pulse_count = 0
                with self._transport._lock:
                    self._transport.detected_bpm = 0.0

            # Internal clock
            if not playing:
                _deadline = time.perf_counter()  # reset so we don't catch up on restart
                time.sleep(0.01)
                continue

            tick_interval = 60.0 / (bpm * ppqn)

            # Sleep to within ~0.5 ms of deadline, then busy-wait for accuracy.
            # Using an accumulating deadline prevents sleep overshoot from
            # compounding across ticks.
            sleep_s = _deadline - time.perf_counter() - 0.0005
            if sleep_s > 0.001:
                time.sleep(sleep_s)
            while time.perf_counter() < _deadline:
                pass

            self._midi_out.send_clock()
            self._tick(self._tick_count, tick_interval)
            self._tick_count += 1

            _deadline += tick_interval
            # If we've fallen more than one tick behind, resync rather than
            # firing a burst of catch-up ticks.
            if _deadline < time.perf_counter():
                _deadline = time.perf_counter()
