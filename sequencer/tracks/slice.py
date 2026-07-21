import random
from sky.catalogue import SkyStar
from tracks.state import TrackState, SequenceNote, SequenceStep
from transport.state import SCALES


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _az_in_slice(az: float, az_lo: float, az_hi: float) -> bool:
    """True if az falls within the arc [az_lo, az_hi) with 360° wrap-around."""
    if az_lo <= az_hi:
        return az_lo <= az < az_hi
    # Wraps around 0°
    return az >= az_lo or az < az_hi


def build_valid_notes(base_note: int, note_range: int, key: int, scale: str) -> list:
    """Return sorted list of MIDI note numbers within note_range semitones of base_note
    that belong to the selected scale/key."""
    intervals = set(SCALES.get(scale, SCALES['major']))
    valid = []
    for semitone in range(note_range + 1):
        note = base_note + semitone
        if note > 127:
            break
        if (note - key) % 12 in intervals:
            valid.append(note)
    return valid


def _note_for_star(star: SkyStar, valid_notes: list) -> int:
    n = len(valid_notes)
    idx = int(star.alt / 90.0 * n)
    return valid_notes[min(idx, n - 1)]


def _velocity_for_star(star: SkyStar, vel_lo: int, vel_hi: int) -> int:
    norm = 1.0 - _clamp(star.mag / 6.5, 0.0, 1.0)
    return int(vel_lo + norm * (vel_hi - vel_lo))


def _duration_for_star(star: SkyStar, dur_lo: int, dur_hi: int) -> int:
    # B-V range for naked-eye stars: -0.4 (blue) to +2.0 (red)
    norm = _clamp((star.bv + 0.4) / 2.4, 0.0, 1.0)
    return int(dur_lo + norm * (dur_hi - dur_lo))


def _select_stars(candidates: list, play_mode: int, n: int) -> list:
    """Select up to n stars from candidates per the play_mode rule."""
    if not candidates:
        return []
    if play_mode == 0:  # random
        k = random.randint(1, min(len(candidates), n))
        return random.sample(candidates, k)
    elif play_mode == 1:  # highest alt
        return sorted(candidates, key=lambda s: s.alt, reverse=True)[:n]
    elif play_mode == 2:  # lowest alt
        return sorted(candidates, key=lambda s: s.alt)[:n]
    elif play_mode == 3:  # middle (nearest median alt)
        mid = sorted(candidates, key=lambda s: s.alt)[len(candidates) // 2].alt
        return sorted(candidates, key=lambda s: abs(s.alt - mid))[:n]
    elif play_mode == 4:  # first (lowest az in step bucket)
        return sorted(candidates, key=lambda s: s.az)[:n]
    elif play_mode == 5:  # last (highest az in step bucket)
        return sorted(candidates, key=lambda s: s.az, reverse=True)[:n]
    elif play_mode == 6:  # brightest (lowest magnitude)
        return sorted(candidates, key=lambda s: s.mag)[:n]
    elif play_mode == 7:  # dimmest (highest magnitude)
        return sorted(candidates, key=lambda s: s.mag, reverse=True)[:n]
    return candidates[:n]


def build_sequence(track: TrackState, sky_snapshot: list,
                   key: int, scale: str, max_poly: int) -> list:
    """Build a list[SequenceStep] for the given track from the current sky snapshot."""
    if track.mode == 0:
        return [SequenceStep(notes=[]) for _ in range(track.length)]

    # Derive magnitude cutoff from slice_brightness (0=all, 100=brightest only)
    mag_cutoff = 6.5 - (track.slice_brightness / 100.0) * 6.5

    sw = float(track.slice_width)
    sc = float(track.slice_centre)
    az_lo = (sc - sw / 2.0) % 360.0
    az_hi = (sc + sw / 2.0) % 360.0

    # Stars inside this track's slice that pass the brightness filter
    in_slice = [
        s for s in sky_snapshot
        if s.mag <= mag_cutoff and _az_in_slice(s.az, az_lo, az_hi)
    ]

    valid_notes = build_valid_notes(track.base_note, track.note_range, key, scale)
    if not valid_notes:
        return [SequenceStep(notes=[]) for _ in range(track.length)]

    # Bucket stars into steps by their azimuth position within the slice
    step_width = sw / track.length
    buckets: list = [[] for _ in range(track.length)]
    for star in in_slice:
        rel_az = (star.az - az_lo) % 360.0
        step_n = min(int(rel_az / step_width), track.length - 1)
        buckets[step_n].append(star)

    n_select = 1 if track.mode == 1 else max_poly  # mono vs poly

    steps = []
    for bucket in buckets:
        selected = _select_stars(bucket, track.play_mode, n_select)
        notes = []
        for star in selected:
            midi_note = _note_for_star(star, valid_notes)
            if track.param_mode == 0:
                velocity = _velocity_for_star(star, track.vel_lo, track.vel_hi)
                duration = _duration_for_star(star, track.dur_lo, track.dur_hi)
            else:
                velocity = random.randint(track.vel_lo, track.vel_hi)
                duration = random.randint(track.dur_lo, track.dur_hi)
            notes.append(SequenceNote(
                midi_note=midi_note,
                velocity=velocity,
                duration=max(1, duration),
                star_hr=star.hr,
            ))
        steps.append(SequenceStep(notes=notes))

    return steps
