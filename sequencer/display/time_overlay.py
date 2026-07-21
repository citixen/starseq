"""
Time overlay panel — drawn on top of the main display when the user opens
the clock icon menu. Lets the operator jump the simulated sky clock to a
specific UTC date/time by editing year/month/day/hour/minute; each field
change applies immediately.
"""

import pygame

_BG           = (18, 18, 38)
_BORDER       = (80, 90, 140)
_LABEL_COL    = (100, 100, 135)
_VALUE_NORMAL = (200, 200, 220)
_VALUE_FOCUS  = (255, 255, 255)
_VALUE_EDIT   = (255, 200, 80)
_BG_FOCUSED   = (38, 50, 100)
_BG_EDITING   = (80, 55, 10)
_HINT_COL     = (90, 150, 200)

PANEL_W     = 280
_ROW_H      = 48
_PADDING    = 10
_LABEL_SIZE = 10
_VALUE_SIZE = 16
_HINT_SIZE  = 9


class TimeOverlay:
    """Draws the "set time" (year/month/day/hour/minute) overlay panel."""

    def __init__(self):
        self._font_label = None
        self._font_value = None
        self._font_hint  = None

    def _init_fonts(self):
        self._font_label = pygame.font.SysFont('monospace', _LABEL_SIZE)
        self._font_value = pygame.font.SysFont('monospace', _VALUE_SIZE)
        self._font_hint  = pygame.font.SysFont('monospace', _HINT_SIZE)

    def draw(self, surface: pygame.Surface, menu_state,
             panel_x: int = 0, panel_y: int = 0) -> None:
        if self._font_label is None:
            self._init_fonts()

        rows = menu_state.time_overlay_values()
        n = len(rows)
        panel_h = n * _ROW_H + _PADDING * 2
        panel_rect = pygame.Rect(panel_x, panel_y, PANEL_W, panel_h)

        # Background
        pygame.draw.rect(surface, _BG, panel_rect)
        pygame.draw.rect(surface, _BORDER, panel_rect, 2)

        for i, (label, value, focused, editing, hint) in enumerate(rows):
            row_y = panel_y + _PADDING + i * _ROW_H
            row_rect = pygame.Rect(panel_x + 2, row_y, PANEL_W - 4, _ROW_H - 2)

            # Row highlight
            if editing:
                pygame.draw.rect(surface, _BG_EDITING, row_rect)
            elif focused:
                pygame.draw.rect(surface, _BG_FOCUSED, row_rect)

            # Row divider
            if i > 0:
                pygame.draw.line(surface, _BORDER,
                                 (panel_x + 8, row_y),
                                 (panel_x + PANEL_W - 8, row_y))

            lx = panel_x + _PADDING + 4
            ly_label = row_y + 5
            ly_value = row_y + _ROW_H - _VALUE_SIZE - 8

            # Label
            lbl_surf = self._font_label.render(label, True, _LABEL_COL)
            surface.blit(lbl_surf, (lx, ly_label))

            # UTC hint on the YEAR row (first fixed field, right after EVENT)
            if label == 'YEAR':
                hint_surf = self._font_hint.render('UTC', True, _HINT_COL)
                hx = panel_x + PANEL_W - hint_surf.get_width() - _PADDING
                surface.blit(hint_surf, (hx, ly_label + 1))

            # Position hint while scrolling the EVENT picker (e.g. "3/21")
            if editing and hint:
                hint_surf = self._font_hint.render(hint, True, _HINT_COL)
                hx = panel_x + PANEL_W - hint_surf.get_width() - _PADDING
                surface.blit(hint_surf, (hx, ly_label + 1))

            val_col = _VALUE_EDIT if editing else (_VALUE_FOCUS if focused else _VALUE_NORMAL)
            max_val_w = PANEL_W - (lx - panel_x) - _PADDING
            val_surf = self._font_value.render(value, True, val_col)
            if val_surf.get_width() > max_val_w:
                t = value
                while t and self._font_value.size(t + '…')[0] > max_val_w:
                    t = t[:-1]
                val_surf = self._font_value.render((t + '…') if t else '…', True, val_col)
            surface.blit(val_surf, (lx, ly_value))
