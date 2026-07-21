"""
Location overlay panel — drawn on top of the main display when the user
opens the globe icon menu.  Shows location source selection and current
lat/lon coordinates.
"""

import pygame

from transport.cities import PRESET_CITIES

_BG           = (18, 18, 38)
_BORDER       = (80, 90, 140)
_LABEL_COL    = (100, 100, 135)
_VALUE_NORMAL = (200, 200, 220)
_VALUE_FOCUS  = (255, 255, 255)
_VALUE_EDIT   = (255, 200, 80)
_VALUE_DIMMED = (70, 70, 95)     # read-only or unavailable
_BG_FOCUSED   = (38, 50, 100)
_BG_EDITING   = (80, 55, 10)
_GPS_AVAIL    = (80, 210, 130)   # GPS option when receiver is connected
_GPS_UNAVAIL  = (70, 70, 95)     # GPS option when no receiver
_HINT_COL     = (70, 70, 95)

_PANEL_W    = 260
_ROW_H      = 48
_PADDING    = 10
_LABEL_SIZE = 10
_VALUE_SIZE = 16
_HINT_SIZE  = 9


class LocationOverlay:
    """Draws the location source/coordinates overlay panel."""

    def __init__(self):
        self._font_label = None
        self._font_value = None
        self._font_hint  = None

    def _init_fonts(self):
        self._font_label = pygame.font.SysFont('monospace', _LABEL_SIZE)
        self._font_value = pygame.font.SysFont('monospace', _VALUE_SIZE)
        self._font_hint  = pygame.font.SysFont('monospace', _HINT_SIZE)

    def draw(self, surface: pygame.Surface, menu_state, transport,
             panel_x: int = 0, panel_y: int = 0) -> None:
        if self._font_label is None:
            self._init_fonts()

        rows = menu_state.overlay_values(transport)
        n = len(rows)
        panel_h = n * _ROW_H + _PADDING * 2
        panel_rect = pygame.Rect(panel_x, panel_y, _PANEL_W, panel_h)

        # Background
        pygame.draw.rect(surface, _BG, panel_rect)
        pygame.draw.rect(surface, _BORDER, panel_rect, 2)

        with transport._lock:
            gps_connected = transport.gps_connected
            city_index = transport.preset_city_index % len(PRESET_CITIES)

        for i, (label, value, focused, editing, available, editable) in enumerate(rows):
            row_y = panel_y + _PADDING + i * _ROW_H
            row_rect = pygame.Rect(panel_x + 2, row_y, _PANEL_W - 4, _ROW_H - 2)

            # Row highlight
            if editing:
                pygame.draw.rect(surface, _BG_EDITING, row_rect)
            elif focused:
                pygame.draw.rect(surface, _BG_FOCUSED, row_rect)

            # Row divider
            if i > 0:
                pygame.draw.line(surface, _BORDER,
                                 (panel_x + 8, row_y),
                                 (panel_x + _PANEL_W - 8, row_y))

            lx = panel_x + _PADDING + 4
            ly_label = row_y + 5
            ly_value = row_y + _ROW_H - _VALUE_SIZE - 8

            # Label
            lbl_surf = self._font_label.render(label, True, _LABEL_COL)
            surface.blit(lbl_surf, (lx, ly_label))

            # GPS source: show connected/disconnected status hint
            if label == 'SOURCE':
                status_text = 'GPS READY' if gps_connected else 'NO GPS'
                status_col = _GPS_AVAIL if gps_connected else _GPS_UNAVAIL
                status_surf = self._font_hint.render(status_text, True, status_col)
                sx = panel_x + _PANEL_W - status_surf.get_width() - _PADDING
                surface.blit(status_surf, (sx, ly_label + 1))

            # Value colour: dim when not available (GPS selected but disconnected)
            # or when field is read-only in the current source mode
            if not available:
                val_col = _GPS_UNAVAIL
            elif not editable:
                val_col = _VALUE_DIMMED
            elif editing:
                val_col = _VALUE_EDIT
            elif focused:
                val_col = _VALUE_FOCUS
            else:
                val_col = _VALUE_NORMAL

            max_val_w = _PANEL_W - (lx - panel_x) - _PADDING
            val_surf = self._font_value.render(value, True, val_col)
            if val_surf.get_width() > max_val_w:
                t = value
                while t and self._font_value.size(t + '…')[0] > max_val_w:
                    t = t[:-1]
                val_surf = self._font_value.render((t + '…') if t else '…', True, val_col)
            surface.blit(val_surf, (lx, ly_value))

            # Hint when editing lat/lon: show step size
            if editing and label in ('LATITUDE', 'LONGITUDE'):
                hint = '±0.01° per click'
                hint_surf = self._font_hint.render(hint, True, _HINT_COL)
                hx = panel_x + _PANEL_W - hint_surf.get_width() - _PADDING
                surface.blit(hint_surf, (hx, ly_value + (_VALUE_SIZE - _HINT_SIZE) // 2 + 2))

            # Hint when editing CITY: show position within the preset list
            if editing and label == 'CITY':
                hint = f'{city_index + 1}/{len(PRESET_CITIES)}'
                hint_surf = self._font_hint.render(hint, True, _HINT_COL)
                hx = panel_x + _PANEL_W - hint_surf.get_width() - _PADDING
                surface.blit(hint_surf, (hx, ly_value + (_VALUE_SIZE - _HINT_SIZE) // 2 + 2))
