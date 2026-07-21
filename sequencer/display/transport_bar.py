import math

import pygame
import config
from menu_state import PARAMS
from display.colour import dim_colour

# Re-exported so renderer.py can import them
BAR_HEIGHT = config.BAR_HEIGHT
EXTREME_BAR_W = 160  # width of the vertical bar strip in extreme-ratio layout

_GLOBE_W = 46
_ICON_W = 46
_CLOCK_W = 46
_TOGGLE_W = 40  # CONST / PLANETS / TRACKS icon-toggle columns

_BG_NORMAL = (20, 20, 34)
_BG_FOCUSED = (38, 50, 100)
_BG_EDITING = (80, 55, 10)
_DIVIDER = (55, 55, 80)
_BORDER = (55, 55, 80)
_LABEL_COL = (100, 100, 135)
_VALUE_NORMAL = (200, 200, 220)
_VALUE_FOCUS = (255, 255, 255)
_VALUE_EDIT = (255, 200, 80)
_PLAY_COL = (80, 210, 80)
_STOP_COL = (210, 80, 80)
_GLOBE_NORMAL = (90, 90, 120)
_GLOBE_FOCUS = (255, 255, 255)
_GLOBE_GPS = (80, 210, 130)
_CLOCK_NORMAL = (90, 90, 120)
_CLOCK_FOCUS = (255, 255, 255)
# Shared by the Bright/Dim/Off icon toggles (CONST, PLANETS, TRACKS)
_ICON_NORMAL = (90, 90, 120)
_ICON_FOCUS = (255, 255, 255)
_ICON_EDIT = (255, 200, 80)

_LABEL_SIZE = 10
_VALUE_SIZE = 16
_VALUE_SIZES = (_VALUE_SIZE, 13, 11, 9)

# Vertical bar font sizes (compact rows)
_V_LABEL_SIZE = 9
_V_VALUE_SIZE = 11
_V_VALUE_MAX_W = 76  # max px for value text in a vertical row


def _draw_globe(surface: pygame.Surface, cx: int, cy: int, r: int, col: tuple) -> None:
    """Outline globe: circle + meridian ellipse + equator."""
    pygame.draw.circle(surface, col, (cx, cy), r, 2)
    pygame.draw.ellipse(surface, col, pygame.Rect(cx - r // 2, cy - r, r, r * 2), 2)
    pygame.draw.line(surface, col, (cx - r, cy), (cx + r, cy), 2)


def _draw_clock(surface: pygame.Surface, cx: int, cy: int, r: int, col: tuple) -> None:
    """Outline clock: circle + hour hand + minute hand."""
    pygame.draw.circle(surface, col, (cx, cy), r, 2)
    pygame.draw.line(surface, col, (cx, cy), (cx, cy - round(r * 0.55)), 2)
    pygame.draw.line(surface, col, (cx, cy), (cx + round(r * 0.75), cy), 2)


def _draw_brightness(
    surface: pygame.Surface, cx: int, cy: int, r: int, col: tuple, mode: str
) -> None:
    """Sun-style icon whose form itself encodes the level:
    bright = filled centre + rays, dim = small filled centre only,
    off = hollow ring only."""
    if mode == "off":
        pygame.draw.circle(surface, col, (cx, cy), r, 2)
        return
    if mode == "dim":
        pygame.draw.circle(surface, col, (cx, cy), max(2, r // 2))
        return
    pygame.draw.circle(surface, col, (cx, cy), max(2, r // 2))
    # Rays are drawn as filled quadrilaterals rather than pygame.draw.line
    # strokes. For reasons of getting annoyed.
    half_w = 1.0
    inner, outer = r * 0.65, float(r)
    for ang_deg in (0, 45, 90, 135, 180, 225, 270, 315):
        ang = math.radians(ang_deg)
        dx, dy = math.cos(ang), math.sin(ang)
        px, py = -dy, dx  # unit vector perpendicular to the ray
        pts = [
            (cx + dx * inner - px * half_w, cy + dy * inner - py * half_w),
            (cx + dx * outer - px * half_w, cy + dy * outer - py * half_w),
            (cx + dx * outer + px * half_w, cy + dy * outer + py * half_w),
            (cx + dx * inner + px * half_w, cy + dy * inner + py * half_w),
        ]
        pygame.draw.polygon(surface, col, pts)


def _draw_constellation(
    surface: pygame.Surface, cx: int, cy: int, r: int, col: tuple, mode: str
) -> None:
    """Three-star stick figure: connected when visible, disconnected dots when off."""
    p1 = (cx - r, cy + r // 2)
    p2 = (cx, cy - r // 2)
    p3 = (cx + r, cy + r // 3)
    if mode != "off":
        pygame.draw.line(surface, col, p1, p2, 2)
        pygame.draw.line(surface, col, p2, p3, 2)
    for p in (p1, p2, p3):
        pygame.draw.circle(surface, col, p, 2)


def _draw_planet(
    surface: pygame.Surface, cx: int, cy: int, r: int, col: tuple, mode: str
) -> None:
    """Ringed planet: filled body + ring when visible, hollow ring only when off."""
    if mode != "off":
        pygame.draw.circle(surface, col, (cx, cy), max(2, r // 2))
    ring_rect = pygame.Rect(cx - r, cy - r // 3, r * 2, r // 2 + 2)
    pygame.draw.ellipse(surface, col, ring_rect, 2)


class TransportBar:
    def __init__(self, rect: pygame.Rect, transport, menu_state):
        self._rect = rect
        self._transport = transport
        self._menu = menu_state
        self._font_label = None
        self._font_cache: dict = {}

    def init(self):
        self._font_label = pygame.font.SysFont("monospace", _LABEL_SIZE)
        self._get_font(_VALUE_SIZE)

    def _get_font(self, size: int) -> pygame.font.Font:
        if size not in self._font_cache:
            self._font_cache[size] = pygame.font.SysFont("monospace", size)
        return self._font_cache[size]

    @staticmethod
    def _icon_toggle_colour(focused: bool, editing: bool) -> tuple:
        if editing:
            return _ICON_EDIT
        if focused:
            return _ICON_FOCUS
        return _ICON_NORMAL

    def _blit_fitted_value(self, surface, text, colour, cx, cw):
        padding = 8
        max_w = cw - padding
        font = surf = None
        for size in _VALUE_SIZES:
            font = self._get_font(size)
            surf = font.render(text, True, colour)
            if surf.get_width() <= max_w:
                break
        if surf.get_width() > max_w:
            t = text
            while len(t) > 0 and font.size(t + "…")[0] > max_w:
                t = t[:-1]
            surf = font.render((t + "…") if t else "…", True, colour)
        vx = cx + (cw - surf.get_width()) // 2
        vy = self._rect.bottom - surf.get_height() - 6
        surface.blit(surf, (vx, vy))

    # ------------------------------------------------------------------ horizontal

    def draw(self, surface: pygame.Surface):
        pygame.draw.rect(surface, _BG_NORMAL, self._rect)
        pygame.draw.line(
            surface, _BORDER, self._rect.bottomleft, self._rect.bottomright
        )

        # Globe column
        globe_rect = pygame.Rect(
            self._rect.x, self._rect.y, _GLOBE_W, self._rect.height
        )
        if self._menu.globe_focused or self._menu.overlay_open:
            pygame.draw.rect(surface, _BG_FOCUSED, globe_rect)

        with self._transport._lock:
            gps_active = (
                self._transport.location_source == "gps"
                and self._transport.gps_connected
            )

        if self._menu.globe_focused or self._menu.overlay_open:
            globe_col = _GLOBE_FOCUS
        elif gps_active:
            globe_col = _GLOBE_GPS
        else:
            globe_col = _GLOBE_NORMAL

        globe_r = max(8, self._rect.height // 4)
        _draw_globe(
            surface,
            self._rect.x + _GLOBE_W // 2,
            self._rect.centery,
            globe_r,
            globe_col,
        )

        pygame.draw.line(
            surface,
            _DIVIDER,
            (self._rect.x + _GLOBE_W, self._rect.y + 5),
            (self._rect.x + _GLOBE_W, self._rect.bottom - 5),
        )

        # CONST / PLANETS icon-toggle columns (left of the params, next to VIEW)
        const_x = self._rect.x + _GLOBE_W
        planets_x = const_x + _TOGGLE_W
        for x, field, draw_fn in (
            (const_x, "constellation_brightness", _draw_constellation),
            (planets_x, "planet_brightness", _draw_planet),
        ):
            t_rect = pygame.Rect(x, self._rect.y, _TOGGLE_W, self._rect.height)
            focused, editing = self._menu.icon_toggle_state(field)
            if editing:
                pygame.draw.rect(surface, _BG_EDITING, t_rect)
            elif focused:
                pygame.draw.rect(surface, _BG_FOCUSED, t_rect)
            pygame.draw.line(
                surface, _DIVIDER, (x, self._rect.y + 5), (x, self._rect.bottom - 5)
            )
            with self._transport._lock:
                mode = getattr(self._transport, field)
            col = self._icon_toggle_colour(focused, editing)
            r = max(7, self._rect.height // 5)
            draw_fn(surface, x + _TOGGLE_W // 2, self._rect.centery, r, col, mode)

        pygame.draw.line(
            surface,
            _DIVIDER,
            (planets_x + _TOGGLE_W, self._rect.y + 5),
            (planets_x + _TOGGLE_W, self._rect.bottom - 5),
        )

        # Param columns
        rows = self._menu.all_values(self._transport)
        n = len(rows)
        param_area_x = planets_x + _TOGGLE_W
        param_area_w = (
            self._rect.width - _GLOBE_W - 2 * _TOGGLE_W - _CLOCK_W - _TOGGLE_W - _ICON_W
        )
        col_w = param_area_w // n
        last_col_w = param_area_w - col_w * (n - 1)

        for i, (label, value, focused, editing) in enumerate(rows):
            cw = last_col_w if i == n - 1 else col_w
            cx = param_area_x + i * col_w
            col_rect = pygame.Rect(cx, self._rect.y, cw, self._rect.height)
            if editing:
                pygame.draw.rect(surface, _BG_EDITING, col_rect)
            elif focused:
                pygame.draw.rect(surface, _BG_FOCUSED, col_rect)
            if i > 0:
                pygame.draw.line(
                    surface,
                    _DIVIDER,
                    (cx, self._rect.y + 5),
                    (cx, self._rect.bottom - 5),
                )
            lbl_surf = self._font_label.render(label, True, _LABEL_COL)
            surface.blit(
                lbl_surf, (cx + (cw - lbl_surf.get_width()) // 2, self._rect.y + 6)
            )
            val_col = (
                _VALUE_EDIT if editing else (_VALUE_FOCUS if focused else _VALUE_NORMAL)
            )
            self._blit_fitted_value(surface, value, val_col, cx, cw)

        # Clock ("set time") icon column
        clock_x = param_area_x + param_area_w
        clock_rect = pygame.Rect(clock_x, self._rect.y, _CLOCK_W, self._rect.height)
        clock_active = self._menu.clock_focused or self._menu.time_overlay_open
        if clock_active:
            pygame.draw.rect(surface, _BG_FOCUSED, clock_rect)
        pygame.draw.line(
            surface,
            _DIVIDER,
            (clock_x, self._rect.y + 5),
            (clock_x, self._rect.bottom - 5),
        )
        clock_col = _CLOCK_FOCUS if clock_active else _CLOCK_NORMAL
        clock_r = max(8, self._rect.height // 4)
        _draw_clock(
            surface, clock_x + _CLOCK_W // 2, self._rect.centery, clock_r, clock_col
        )

        # Tracks brightness icon column
        tracks_x = clock_x + _CLOCK_W
        tracks_rect = pygame.Rect(tracks_x, self._rect.y, _TOGGLE_W, self._rect.height)
        focused, editing = self._menu.icon_toggle_state("track_brightness")
        if editing:
            pygame.draw.rect(surface, _BG_EDITING, tracks_rect)
        elif focused:
            pygame.draw.rect(surface, _BG_FOCUSED, tracks_rect)
        pygame.draw.line(
            surface,
            _DIVIDER,
            (tracks_x, self._rect.y + 5),
            (tracks_x, self._rect.bottom - 5),
        )
        with self._transport._lock:
            track_brightness = self._transport.track_brightness
        tracks_col = self._icon_toggle_colour(focused, editing)
        tracks_r = max(7, self._rect.height // 5)
        _draw_brightness(
            surface,
            tracks_x + _TOGGLE_W // 2,
            self._rect.centery,
            tracks_r,
            tracks_col,
            track_brightness,
        )

        # Play/stop icon column
        icon_x = tracks_x + _TOGGLE_W
        pygame.draw.line(
            surface,
            _DIVIDER,
            (icon_x, self._rect.y + 5),
            (icon_x, self._rect.bottom - 5),
        )
        with self._transport._lock:
            playing = self._transport.playing
        icx = icon_x + _ICON_W // 2
        icy = self._rect.centery
        if playing:
            pygame.draw.polygon(
                surface,
                _PLAY_COL,
                [(icx - 7, icy - 9), (icx + 9, icy), (icx - 7, icy + 9)],
            )
        else:
            pygame.draw.rect(surface, _STOP_COL, pygame.Rect(icx - 6, icy - 8, 12, 16))

    # ------------------------------------------------------------------ vertical

    def draw_vertical(self, surface: pygame.Surface):
        """Stacked row layout for extreme-wide canvases (bar on the left side)."""
        rect = self._rect
        rows = self._menu.all_values(self._transport)
        n_rows = 6 + len(
            rows
        )  # globe + const + planets + params + clock + tracks + play/stop
        row_h = rect.height // n_rows

        font_lbl = self._get_font(_V_LABEL_SIZE)
        font_val = self._get_font(_V_VALUE_SIZE)

        pygame.draw.rect(surface, _BG_NORMAL, rect)
        # Right-side border acts as divider between bar and dome
        pygame.draw.line(surface, _BORDER, rect.topright, rect.bottomright, 1)

        def _blit_value(val_text, val_col, mid_y):
            s = font_val.render(val_text, True, val_col)
            if s.get_width() > _V_VALUE_MAX_W:
                t = val_text
                while t and font_val.size(t + "…")[0] > _V_VALUE_MAX_W:
                    t = t[:-1]
                s = font_val.render((t + "…") if t else "…", True, val_col)
            surface.blit(
                s, (rect.right - 4 - s.get_width(), mid_y - s.get_height() // 2)
            )

        # --- Globe row (index 0) ---
        ry = rect.y
        with self._transport._lock:
            loc_src = self._transport.location_source
            gps_on = self._transport.gps_connected
        globe_focused = self._menu.globe_focused or self._menu.overlay_open
        if globe_focused:
            pygame.draw.rect(
                surface, _BG_FOCUSED, pygame.Rect(rect.x, ry, rect.width, row_h)
            )
        globe_col = (
            _GLOBE_FOCUS
            if globe_focused
            else _GLOBE_GPS if (loc_src == "gps" and gps_on) else _GLOBE_NORMAL
        )
        globe_r = max(5, row_h // 3)
        gcx = rect.x + globe_r + 6
        gcy = ry + row_h // 2
        _draw_globe(surface, gcx, gcy, globe_r, globe_col)
        src_abbr = {
            "default": "DEF",
            "manual": "MAN",
            "gps": "GPS",
            "preset": "PRE",
        }.get(loc_src, "?")
        sa = font_lbl.render(src_abbr, True, globe_col)
        surface.blit(sa, (gcx + globe_r + 5, gcy - sa.get_height() // 2))

        # --- CONST / PLANETS icon-toggle rows ---
        for row_i, (field, label, draw_fn) in enumerate(
            (
                ("constellation_brightness", "CONST", _draw_constellation),
                ("planet_brightness", "PLANETS", _draw_planet),
            )
        ):
            ry = rect.y + (1 + row_i) * row_h
            mid_y = ry + row_h // 2
            focused, editing = self._menu.icon_toggle_state(field)
            if editing:
                pygame.draw.rect(
                    surface, _BG_EDITING, pygame.Rect(rect.x, ry, rect.width, row_h)
                )
            elif focused:
                pygame.draw.rect(
                    surface, _BG_FOCUSED, pygame.Rect(rect.x, ry, rect.width, row_h)
                )
            pygame.draw.line(surface, _DIVIDER, (rect.x + 4, ry), (rect.right - 4, ry))
            with self._transport._lock:
                mode = getattr(self._transport, field)
            col = self._icon_toggle_colour(focused, editing)
            r = max(5, row_h // 3)
            tcx = rect.x + r + 6
            draw_fn(surface, tcx, mid_y, r, col, mode)
            lbl = font_lbl.render(f"{label} {mode.upper()}", True, col)
            surface.blit(lbl, (tcx + r + 5, mid_y - lbl.get_height() // 2))

        # --- Param rows ---
        for i, (label, value, focused, editing) in enumerate(rows):
            ry = rect.y + (3 + i) * row_h
            mid_y = ry + row_h // 2
            row_rect = pygame.Rect(rect.x, ry, rect.width, row_h)
            if editing:
                pygame.draw.rect(surface, _BG_EDITING, row_rect)
            elif focused:
                pygame.draw.rect(surface, _BG_FOCUSED, row_rect)
            pygame.draw.line(surface, _DIVIDER, (rect.x + 4, ry), (rect.right - 4, ry))
            lbl = font_lbl.render(label, True, _LABEL_COL)
            surface.blit(lbl, (rect.x + 4, mid_y - lbl.get_height() // 2))
            val_col = (
                _VALUE_EDIT if editing else (_VALUE_FOCUS if focused else _VALUE_NORMAL)
            )
            _blit_value(value, val_col, mid_y)

        # --- Clock ("set time") row ---
        ry = rect.y + (3 + len(rows)) * row_h
        mid_y = ry + row_h // 2
        clock_active = self._menu.clock_focused or self._menu.time_overlay_open
        if clock_active:
            pygame.draw.rect(
                surface, _BG_FOCUSED, pygame.Rect(rect.x, ry, rect.width, row_h)
            )
        clock_col = _CLOCK_FOCUS if clock_active else _CLOCK_NORMAL
        pygame.draw.line(surface, _DIVIDER, (rect.x + 4, ry), (rect.right - 4, ry))
        clock_r = max(5, row_h // 3)
        ccx = rect.x + clock_r + 6
        ccy = mid_y
        _draw_clock(surface, ccx, ccy, clock_r, clock_col)
        ct = font_lbl.render("SET TIME", True, clock_col)
        surface.blit(ct, (ccx + clock_r + 5, ccy - ct.get_height() // 2))

        # --- Tracks brightness row ---
        ry = rect.y + (4 + len(rows)) * row_h
        mid_y = ry + row_h // 2
        focused, editing = self._menu.icon_toggle_state("track_brightness")
        with self._transport._lock:
            track_brightness = self._transport.track_brightness
        if editing:
            pygame.draw.rect(
                surface, _BG_EDITING, pygame.Rect(rect.x, ry, rect.width, row_h)
            )
        elif focused:
            pygame.draw.rect(
                surface, _BG_FOCUSED, pygame.Rect(rect.x, ry, rect.width, row_h)
            )
        tracks_col = self._icon_toggle_colour(focused, editing)
        pygame.draw.line(surface, _DIVIDER, (rect.x + 4, ry), (rect.right - 4, ry))
        tracks_r = max(5, row_h // 3)
        bcx = rect.x + tracks_r + 6
        bcy = mid_y
        _draw_brightness(surface, bcx, bcy, tracks_r, tracks_col, track_brightness)
        bt = font_lbl.render(f"TRACKS {track_brightness.upper()}", True, tracks_col)
        surface.blit(bt, (bcx + tracks_r + 5, bcy - bt.get_height() // 2))

        # --- Play/stop row (last) ---
        ry = rect.y + (5 + len(rows)) * row_h
        mid_y = ry + row_h // 2
        pygame.draw.line(surface, _DIVIDER, (rect.x + 4, ry), (rect.right - 4, ry))
        with self._transport._lock:
            playing = self._transport.playing
        icx = rect.x + 16
        if playing:
            pygame.draw.polygon(
                surface,
                _PLAY_COL,
                [(icx - 5, mid_y - 6), (icx + 7, mid_y), (icx - 5, mid_y + 6)],
            )
            st = font_lbl.render("PLAYING", True, _PLAY_COL)
        else:
            pygame.draw.rect(surface, _STOP_COL, pygame.Rect(icx - 4, mid_y - 5, 9, 11))
            st = font_lbl.render("STOPPED", True, _STOP_COL)
        surface.blit(st, (icx + 14, mid_y - st.get_height() // 2))
