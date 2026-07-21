import pygame
import config
from tracks.state import TrackStateStore
from transport.state import SCALES
from display.colour import dim_colour

_GRID_BG = (12, 12, 22)
_CELL_PAD = 2
_STATUS_BG = {
    0: (45, 45, 60),    # waiting
    1: (18, 18, 28),    # online
    2: (70, 55, 18),    # stale
    3: (70, 18, 18),    # offline
}
_FONT_SIZE    = 9
_SEMI_IN      = (80, 80, 120)   # semitone in selected scale
_SEMI_OUT     = (32, 32, 50)    # semitone outside selected scale
_OCTAVE_LINE  = (110, 110, 150) # octave boundary (structural, always brightest)
_TRACK_OFF_COL = (95, 95, 120)  # neutral colour used for all tracks when brightness == 'off'


def _grayscale(col: tuple) -> tuple:
    """Desaturate a track colour to its luminance-equivalent grey, used for muted tracks."""
    gray = int(0.299 * col[0] + 0.587 * col[1] + 0.114 * col[2])
    return (gray, gray, gray)


class SequencerGrid:
    def __init__(self, rect: pygame.Rect, track_store: TrackStateStore,
                 flash_state: dict, transport=None):
        self._rect = rect
        self._track_store = track_store
        self._flash_state = flash_state
        self._transport = transport
        self._font = None

    def init(self):
        self._font = pygame.font.SysFont('monospace', _FONT_SIZE)

    def set_rect(self, rect: pygame.Rect) -> None:
        self._rect = rect

    def draw(self, surface: pygame.Surface):
        pygame.draw.rect(surface, _GRID_BG, self._rect)

        # Read key/scale/brightness once per frame
        if self._transport is not None:
            with self._transport._lock:
                _key = self._transport.key
                _scale = self._transport.scale
                _brightness = self._transport.track_brightness
            _in_scale = set(SCALES.get(_scale, SCALES['major']))
        else:
            _key, _in_scale, _brightness = 0, set(range(12)), 'bright'

        n = len(self._track_store.tracks)
        row_h = self._rect.height // n
        icon_w = 22

        for ti, track in enumerate(self._track_store.tracks):
            row_y = self._rect.y + ti * row_h
            if _brightness == 'off':
                col = _TRACK_OFF_COL
            else:
                base_col = config.TRACK_COLOURS[ti]
                if track.mode == 0:
                    base_col = _grayscale(base_col)   # muted — desaturate, keep showing content
                col = dim_colour(base_col) if _brightness == 'dim' else base_col
            status_bg = _STATUS_BG.get(track.interface_status, _STATUS_BG[0])
            row_rect = pygame.Rect(self._rect.x, row_y, self._rect.width - icon_w, row_h - 1)
            pygame.draw.rect(surface, status_bg, row_rect)

            # Play/stop icon column
            icon_x = self._rect.right - icon_w + 4
            icon_y = row_y + row_h // 2
            if track.mode > 0:
                pts = [(icon_x, icon_y - 6), (icon_x + 10, icon_y), (icon_x, icon_y + 6)]
                pygame.draw.polygon(surface, col, pts)
            else:
                pygame.draw.rect(surface, (130, 60, 60),
                                 pygame.Rect(icon_x, icon_y - 5, 10, 10))

            # Offline/stale hatch overlay
            if track.interface_status in (2, 3):
                for hx in range(0, row_rect.width, 10):
                    pygame.draw.line(surface, (90, 55, 25),
                                     (row_rect.x + hx, row_rect.y),
                                     (row_rect.x + hx + 5, row_rect.bottom), 1)

            if track.length == 0:
                continue

            # Normalisation anchor for this track's note range
            lo = track.base_note
            note_span = max(1, track.note_range)

            # Pitch reference lines spanning the full row (drawn before cell borders)
            cell_top_y = row_y + _CELL_PAD
            cell_h = row_h - _CELL_PAD * 2 - 1
            px_per_semi = cell_h / note_span
            if px_per_semi >= 1.5:
                for s in range(note_span + 1):
                    ny = int(cell_top_y + (1.0 - s / note_span) * cell_h)
                    if s % 12 == 0:
                        lc = _OCTAVE_LINE
                    elif (track.base_note + s - _key) % 12 in _in_scale:
                        lc = _SEMI_IN
                    else:
                        lc = _SEMI_OUT
                    pygame.draw.line(surface, lc,
                                     (row_rect.x, ny), (row_rect.right - 1, ny))
            else:
                # Only octave boundaries when space is very tight
                for s in range(0, note_span + 1, 12):
                    ny = int(cell_top_y + (1.0 - s / note_span) * cell_h)
                    pygame.draw.line(surface, _OCTAVE_LINE,
                                     (row_rect.x, ny), (row_rect.right - 1, ny))

            sequence = track.get_sequence()
            step_w = row_rect.width / track.length
            cur = track.step_index

            for si in range(track.length):
                x0 = self._rect.x + int(si * step_w)
                cw = max(1, int((si + 1) * step_w) - int(si * step_w) - _CELL_PAD)
                cell = pygame.Rect(x0 + _CELL_PAD, row_y + _CELL_PAD,
                                   cw, row_h - _CELL_PAD * 2 - 1)

                # Active step highlight
                if si == cur:
                    hl = tuple(min(255, c + 50) for c in status_bg)
                    pygame.draw.rect(surface, hl, cell)
                    pygame.draw.rect(surface, col, cell, 1)
                else:
                    pygame.draw.rect(surface, col, cell, 1)

                if not (sequence and si < len(sequence)):
                    continue

                step = sequence[si]
                if not step.notes:
                    continue

                # Note dots: y position normalised to this track's note window
                for note_ev in step.notes:
                    norm_y = 1.0 - (note_ev.midi_note - lo) / note_span
                    dy = int(cell.y + norm_y * cell.height)
                    dy = max(cell.y + 1, min(cell.bottom - 2, dy))
                    pygame.draw.circle(surface, col, (cell.centerx, dy), 2)

                    # Flash ring when this star's note is firing
                    if note_ev.star_hr in self._flash_state:
                        pygame.draw.circle(surface, (255, 255, 255),
                                           (cell.centerx, dy), 3, 1)

            if config.SHOW_MIDI_NOTE_LABELS and sequence and cur < len(sequence):
                step = sequence[cur]
                if step.notes:
                    NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F',
                                  'F#', 'G', 'G#', 'A', 'A#', 'B']
                    names = ', '.join(
                        f'{NOTE_NAMES[n.midi_note % 12]}{n.midi_note // 12 - 1}'
                        for n in step.notes
                    )
                    lbl = self._font.render(names, True, col)
                    surface.blit(lbl, (self._rect.x + 2, row_y + row_h - lbl.get_height() - 1))
