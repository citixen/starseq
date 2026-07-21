import pygame
from menu_state import PARAMS

_BG          = (18, 18, 30, 210)    # RGBA — semi-transparent dark panel
_BORDER      = (90, 90, 130)
_TITLE       = (150, 150, 190)
_ROW_NORMAL  = (140, 140, 165)
_ROW_FOCUS   = (255, 255, 255)
_FOCUS_BAR   = (60, 80, 160)        # highlight bar behind focused row
_HINT        = (90, 90, 120)

_TITLE_SIZE  = 13
_ROW_SIZE    = 17
_HINT_SIZE   = 12
_PAD         = 16
_ROW_H       = 26
_VALUE_X     = 200    # x offset for value column inside panel


class MenuOverlay:
    """Semi-transparent parameter-editing overlay drawn on top of the main scene."""

    def __init__(self, menu_state, transport):
        self._menu = menu_state
        self._transport = transport
        self._font_title = None
        self._font_row = None
        self._font_hint = None

    def init(self):
        self._font_title = pygame.font.SysFont('monospace', _TITLE_SIZE)
        self._font_row   = pygame.font.SysFont('monospace', _ROW_SIZE)
        self._font_hint  = pygame.font.SysFont('monospace', _HINT_SIZE)

    def draw(self, surface: pygame.Surface):
        if not self._menu.active:
            return

        n_rows = len(PARAMS)
        panel_w = _VALUE_X + 160 + _PAD
        panel_h = _PAD + _TITLE_SIZE + 8 + n_rows * _ROW_H + _PAD + _HINT_SIZE + _PAD

        # Centre on screen
        sw, sh = surface.get_size()
        px = (sw - panel_w) // 2
        py = (sh - panel_h) // 2

        # Background
        panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        panel.fill(_BG)
        pygame.draw.rect(panel, _BORDER, panel.get_rect(), 1)

        y = _PAD

        # Title
        title_surf = self._font_title.render('PARAMETERS', True, _TITLE)
        panel.blit(title_surf, (_PAD, y))
        y += _TITLE_SIZE + 8

        # Parameter rows
        rows = self._menu.all_values(self._transport)
        for i, (label, value, focused) in enumerate(rows):
            row_y = y + i * _ROW_H

            if focused:
                bar = pygame.Rect(_PAD // 2, row_y - 3, panel_w - _PAD, _ROW_H)
                pygame.draw.rect(panel, _FOCUS_BAR, bar, border_radius=3)

            col = _ROW_FOCUS if focused else _ROW_NORMAL
            prefix = '▶ ' if focused else '  '

            label_surf = self._font_row.render(prefix + label, True, col)
            panel.blit(label_surf, (_PAD, row_y))

            val_surf = self._font_row.render(value, True, col)
            panel.blit(val_surf, (_PAD + _VALUE_X, row_y))

        # Hint bar
        hint_y = y + n_rows * _ROW_H + _PAD // 2
        pygame.draw.line(panel, _BORDER, (_PAD, hint_y - 4), (panel_w - _PAD, hint_y - 4))
        hint = self._font_hint.render('turn: adjust  ·  press: next  ·  hold: reset clock', True, _HINT)
        panel.blit(hint, (_PAD, hint_y))

        surface.blit(panel, (px, py))
