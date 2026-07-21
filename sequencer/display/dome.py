import math
import time

import pygame

import config
from tracks.state import TrackStateStore
from tracks.slice import _az_in_slice
from transport.state import VIEW_MODE_AXES
from display.colour import dim_colour as _dim_colour

_DOME_BG = (8, 8, 18)
_HORIZON = (55, 55, 75)
_STAR_FULL = (160, 165, 190)  # stardome colour (bright) — background stars in
# wedge modes and all stars in wedge-less modes
_FLASH_DURATION = 0.5  # seconds
_TIME_COL = (255, 255, 255)
_CONST_LINE = (110, 145, 195)  # constellation stick-figure line colour
_PLANET_RADIUS = 7  # fixed marker size — no magnitude/size data used
_PLANET_RING = (255, 255, 255)  # outline distinguishing planet markers from stars
_PLANET_ALPHA = 160  # slight transparency on planet markers (0-255)

_STAR_DIM = _dim_colour(_STAR_FULL)


def _hexagon_points(center, radius):
    cx, cy = center
    return [
        (
            cx + radius * math.cos(math.radians(60 * i - 90)),
            cy + radius * math.sin(math.radians(60 * i - 90)),
        )
        for i in range(6)
    ]


def _draw_hexagon(surface, col, center, radius, width=0, alpha=255):
    # Drawn on a small per-pixel-alpha surface and blitted, since
    # pygame.draw.polygon ignores alpha on the (opaque) display surface.
    size = radius * 2 + 4
    temp = pygame.Surface((size, size), pygame.SRCALPHA)
    local_points = _hexagon_points((size / 2, size / 2), radius)
    pygame.draw.polygon(temp, (*col, alpha), local_points, width)
    surface.blit(temp, (center[0] - size / 2, center[1] - size / 2))


class StarDome:
    def __init__(
        self,
        rect: pygame.Rect,
        sky_engine,
        track_store: TrackStateStore,
        flash_state: dict,
        sim_clock=None,
        transport=None,
        constellation_lines: dict | None = None,
    ):
        self._rect = rect
        self._sky_engine = sky_engine
        self._track_store = track_store
        self._flash_state = flash_state
        self._sim_clock = sim_clock
        self._transport = transport
        self._constellation_lines = constellation_lines or {}
        self._font = None  # compass labels (11px), lazily created
        self._font_time = None  # datetime label (17px), lazily created
        self._font_legend = None  # planet legend labels (11px), lazily created

    def set_rect(self, rect: pygame.Rect) -> None:
        self._rect = rect

    # ------------------------------------------------------------------ helpers

    def _dome_radius(self) -> int:
        return min(self._rect.width, self._rect.height) // 2 - 10

    def _to_screen(self, alt: float, az: float) -> tuple:
        r = self._dome_radius()
        cx, cy = self._rect.centerx, self._rect.centery
        dist = r * (1.0 - alt / 90.0)
        az_rad = math.radians(az)
        return (
            int(cx + dist * math.sin(az_rad)),
            int(cy - dist * math.cos(az_rad)),
        )

    @staticmethod
    def _star_radius(mag: float) -> int:
        norm = 1.0 - max(0.0, min(1.0, mag / 6.5))
        return max(1, int(1 + norm * 4))

    # ------------------------------------------------------------------ draw

    def draw(self, surface: pygame.Surface):
        if self._font is None:
            self._font = pygame.font.SysFont("monospace", 11)
        if self._font_time is None:
            self._font_time = pygame.font.SysFont("monospace", 17)
        if self._font_legend is None:
            self._font_legend = pygame.font.SysFont("monospace", 11)

        view_mode = "bright_1"
        flash_duration = _FLASH_DURATION
        if self._transport is not None:
            with self._transport._lock:
                view_mode = self._transport.view_mode
                flash_duration = self._transport.pulse_duration
        stardome_bright, inscope_bright, wedges, pulse_bright = VIEW_MODE_AXES.get(
            view_mode, VIEW_MODE_AXES["bright_1"]
        )

        now = time.perf_counter()
        r = self._dome_radius()
        cx, cy = self._rect.centerx, self._rect.centery

        # Background dome
        pygame.draw.circle(surface, _DOME_BG, (cx, cy), r)
        pygame.draw.circle(surface, _HORIZON, (cx, cy), r, 1)

        # Compass labels
        for label, dx, dy in [
            ("N", 0, -r - 13),
            ("S", 0, r + 3),
            ("E", r + 3, 0),
            ("W", -r - 13, 0),
        ]:
            s = self._font.render(label, True, (90, 90, 120))
            surface.blit(
                s, (cx + dx - s.get_width() // 2, cy + dy - s.get_height() // 2)
            )

        snapshot = self._sky_engine.get_snapshot()
        if not snapshot:
            return

        # Build per-star track membership map
        star_tracks: dict = {}
        for ti, track in enumerate(self._track_store.tracks):
            if track.mode == 0:
                continue
            sw = float(track.slice_width)
            sc = float(track.slice_centre)
            az_lo = (sc - sw / 2.0) % 360.0
            az_hi = (sc + sw / 2.0) % 360.0
            mag_cutoff = 6.5 - (track.slice_brightness / 100.0) * 6.5
            for star in snapshot:
                if star.mag <= mag_cutoff and _az_in_slice(star.az, az_lo, az_hi):
                    star_tracks.setdefault(star.hr, []).append(ti)

        # Draw slice wedge outlines — suppressed when wedges == 'none'
        if wedges != "none":
            for ti, track in enumerate(self._track_store.tracks):
                if track.mode == 0:
                    continue
                col = config.TRACK_COLOURS[ti]
                if wedges == "dim":
                    col = _dim_colour(col)
                sc = float(track.slice_centre)
                sw = float(track.slice_width)
                steps = max(2, int(sw / 2))
                pts = [(cx, cy)]
                for k in range(steps + 1):
                    az = (sc - sw / 2.0 + k * sw / steps) % 360.0
                    az_r = math.radians(az)
                    pts.append(
                        (int(cx + r * math.sin(az_r)), int(cy - r * math.cos(az_r)))
                    )
                if len(pts) > 2:
                    pygame.draw.polygon(surface, col, pts, 2)

        # Draw constellation stick-figure overlay — only segments whose both
        # endpoints are currently visible (above horizon, naked-eye magnitude)
        const_mode = "off"
        if self._transport is not None:
            with self._transport._lock:
                const_mode = self._transport.constellation_brightness
        if const_mode != "off" and self._constellation_lines:
            line_col = (
                _CONST_LINE if const_mode == "bright" else _dim_colour(_CONST_LINE)
            )
            star_pos = {star.hr: (star.alt, star.az) for star in snapshot}
            for polylines in self._constellation_lines.values():
                for hrs in polylines:
                    for hr_a, hr_b in zip(hrs, hrs[1:]):
                        pos_a = star_pos.get(hr_a)
                        pos_b = star_pos.get(hr_b)
                        if pos_a is None or pos_b is None:
                            continue
                        pygame.draw.line(
                            surface,
                            line_col,
                            self._to_screen(*pos_a),
                            self._to_screen(*pos_b),
                            1,
                        )

        # Draw stars
        for star in snapshot:
            x, y = self._to_screen(star.alt, star.az)
            if not self._rect.collidepoint(x, y):
                continue

            base_r = self._star_radius(star.mag)
            track_ids = star_tracks.get(star.hr, [])

            # Resolve flash state — the flashing track is taken from the note
            # event itself (recorded when the note fired), not inferred from
            # wedge overlap, so overlapping slices never show the wrong colour.
            in_flash = False
            flash_track_idx = None
            draw_r = base_r
            flash_entry = self._flash_state.get(star.hr)
            if flash_entry is not None:
                flash_start, hold_s, flash_track_idx = flash_entry
                age = now - flash_start
                if age < hold_s:
                    # Note still held — stay at full flash size
                    in_flash = True
                    draw_r = base_r + 6
                elif age < hold_s + flash_duration:
                    # Note released — fade out over flash_duration
                    in_flash = True
                    norm = 1.0 - (age - hold_s) / flash_duration
                    draw_r = base_r + int(norm * 6)
                elif age > hold_s + flash_duration + 0.5:
                    self._flash_state.pop(star.hr, None)

            # ---- Wedge-less modes: neutral star colour, flash pulses in track colour
            if wedges == "none":
                if in_flash:
                    assert flash_track_idx is not None
                    col = config.TRACK_COLOURS[flash_track_idx]
                    if not pulse_bright:
                        col = _dim_colour(col)
                else:
                    col = _STAR_FULL if stardome_bright else _STAR_DIM
                pygame.draw.circle(surface, col, (x, y), draw_r)

            # ---- Wedge modes: track-coloured in-scope stars, tinted background
            else:
                if in_flash:
                    assert flash_track_idx is not None
                    col = config.TRACK_COLOURS[flash_track_idx]
                    if not pulse_bright:
                        col = _dim_colour(col)
                    pygame.draw.circle(surface, col, (x, y), draw_r)
                elif not track_ids:
                    if config.SHOW_OUT_OF_SCOPE_STARS:
                        bg = _STAR_FULL if stardome_bright else _STAR_DIM
                        pygame.draw.circle(surface, bg, (x, y), draw_r)
                elif len(track_ids) == 1:
                    col = config.TRACK_COLOURS[track_ids[0]]
                    if not inscope_bright:
                        col = _dim_colour(col)
                    pygame.draw.circle(surface, col, (x, y), draw_r)
                else:
                    for off, ti in enumerate(track_ids[:4]):
                        ox2 = off * 3 - (len(track_ids) * 3) // 2
                        col = config.TRACK_COLOURS[ti]
                        if not inscope_bright:
                            col = _dim_colour(col)
                        pygame.draw.circle(
                            surface, col, (x + ox2, y), max(1, draw_r - 1)
                        )

        # Draw planets — independent of sequencer/track data, purely visual
        planet_mode = "off"
        if self._transport is not None:
            with self._transport._lock:
                planet_mode = self._transport.planet_brightness
        if planet_mode != "off":
            planet_snapshot = self._sky_engine.get_planet_snapshot()
            # Mirror the in-scope star dimming for this view mode (inscope_bright
            # is False only in the "_3" wedge modes; None in wedge-less "stars_*"
            # modes, where there's no in-scope distinction to mirror).
            inscope_dim = inscope_bright is False
            ring_col = (
                _PLANET_RING if planet_mode == "bright" else _dim_colour(_PLANET_RING)
            )
            if inscope_dim:
                ring_col = _dim_colour(ring_col)
            for planet in planet_snapshot:
                x, y = self._to_screen(planet.alt, planet.az)
                if not self._rect.collidepoint(x, y):
                    continue
                col = (
                    planet.colour
                    if planet_mode == "bright"
                    else _dim_colour(planet.colour)
                )
                if inscope_dim:
                    col = _dim_colour(col)
                _draw_hexagon(surface, col, (x, y), _PLANET_RADIUS, alpha=_PLANET_ALPHA)
                _draw_hexagon(
                    surface,
                    ring_col,
                    (x, y),
                    _PLANET_RADIUS + 1,
                    width=1,
                    alpha=_PLANET_ALPHA,
                )

            # Legend: colour swatch + name for each currently-visible planet,
            # top-left of the dome — lets the operator tell them apart.
            if planet_snapshot:
                lx = self._rect.x + 8
                ly = self._rect.y + 8
                for planet in planet_snapshot:
                    col = (
                        planet.colour
                        if planet_mode == "bright"
                        else _dim_colour(planet.colour)
                    )
                    _draw_hexagon(
                        surface, col, (lx + 5, ly + 6), 5, alpha=_PLANET_ALPHA
                    )
                    name_surf = self._font_legend.render(planet.name, True, col)
                    surface.blit(name_surf, (lx + 15, ly))
                    ly += 15

        # Simulated datetime label — bottom of dome rect
        if self._sim_clock is not None:
            dt = self._sim_clock.now()
            label = dt.strftime("%d %b %Y  %H:%M:%S UTC")
            lbl_surf = self._font_time.render(label, True, _TIME_COL)
            lx = self._rect.x + 6
            ly = self._rect.bottom - lbl_surf.get_height() - 4
            surface.blit(lbl_surf, (lx, ly))
