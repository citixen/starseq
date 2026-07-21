import os
import sys
import threading
import queue
import logging

import pygame

import config
from display.transport_bar import TransportBar, BAR_HEIGHT, EXTREME_BAR_W
from display.dome import StarDome
from display.grid import SequencerGrid
from display.location_overlay import LocationOverlay
from display.time_overlay import TimeOverlay, PANEL_W as TIME_PANEL_W
from transport.state import TransportState
from tracks.state import TrackStateStore
from input.handler import InputEvent

logger = logging.getLogger(__name__)


class DisplayRenderer(threading.Thread):
    """pygame render loop — runs at TARGET_FPS, reads from sky/track state."""

    def __init__(self, transport: TransportState, track_store: TrackStateStore,
                 sky_engine, flash_events: queue.Queue,
                 menu_state=None, input_queue: queue.Queue = None,
                 resolution: tuple = None, sim_clock=None,
                 input_callback=None, rotation: int = 0,
                 constellation_lines: dict = None):
        super().__init__(name='Display', daemon=True)
        self._transport = transport
        self._track_store = track_store
        self._sky_engine = sky_engine
        self._flash_events = flash_events
        self._menu_state = menu_state
        self._input_queue = input_queue
        self._resolution = resolution
        self._sim_clock = sim_clock
        self._input_callback = input_callback
        self._rotation = rotation  # clockwise degrees: 0 | 90 | 180 | 270
        self._constellation_lines = constellation_lines or {}
        self._stop_event = threading.Event()
        # Shared dict polled by dome and grid: {star_hr: flash_start_perf_counter}
        self._flash_state: dict = {}

    def stop(self):
        self._stop_event.set()

    def _drain_flash_events(self):
        while True:
            try:
                hr, track_idx, ts, hold_s = self._flash_events.get_nowait()
                self._flash_state[hr] = (ts, hold_s, track_idx)
            except queue.Empty:
                break

    def _drain_input_queue(self):
        if self._input_queue is None or self._input_callback is None:
            return
        while True:
            try:
                self._input_callback(self._input_queue.get_nowait())
            except queue.Empty:
                break

    @staticmethod
    def _configure_sdl():
        """Detect and configure the SDL video driver on Linux."""
        if sys.platform != 'linux' or 'SDL_VIDEODRIVER' in os.environ:
            logger.info("SDL_VIDEODRIVER=%s", os.environ.get('SDL_VIDEODRIVER', 'auto'))
            return

        uid = os.getuid()
        runtime_dir = os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{uid}')

        # Prefer Wayland — find the compositor socket even when SSH'd in
        wayland_display = os.environ.get('WAYLAND_DISPLAY')
        if not wayland_display:
            for candidate in ('wayland-1', 'wayland-0'):
                if os.path.exists(os.path.join(runtime_dir, candidate)):
                    wayland_display = candidate
                    break

        if wayland_display:
            os.environ.setdefault('XDG_RUNTIME_DIR', runtime_dir)
            os.environ['WAYLAND_DISPLAY'] = wayland_display
            os.environ['SDL_VIDEODRIVER'] = 'wayland'
        elif os.environ.get('DISPLAY'):
            os.environ['SDL_VIDEODRIVER'] = 'x11'
        else:
            # Headless / Bookworm Lite: use KMS/DRM directly.
            # Pi 5 exposes the display output on card1, not card0.
            os.environ['SDL_VIDEODRIVER'] = 'kmsdrm'
            os.environ.setdefault('SDL_VIDEO_KMSDRM_DEVICE_INDEX', '1')

        logger.info("SDL_VIDEODRIVER=%s WAYLAND_DISPLAY=%s XDG_RUNTIME_DIR=%s",
                    os.environ['SDL_VIDEODRIVER'],
                    os.environ.get('WAYLAND_DISPLAY', ''),
                    os.environ.get('XDG_RUNTIME_DIR', ''))

    def run(self):
        self._configure_sdl()

        init_pass, init_fail = pygame.init()
        logger.info("pygame.init(): %d passed, %d failed", init_pass, init_fail)

        if self._resolution:
            W, H = self._resolution
            flags = 0
        elif sys.platform == 'linux':
            W, H = 0, 0
            flags = pygame.FULLSCREEN
        else:
            info = pygame.display.Info()
            W = info.current_w if info.current_w >= 800 else 1280
            H = info.current_h if info.current_h >= 480 else 720
            flags = 0

        logger.info("Opening display at %s flags=0x%x",
                    f"{W}x{H}" if W and H else "native", flags)
        screen = pygame.display.set_mode((W, H), flags)
        W, H = screen.get_size()
        logger.info("Display surface: %dx%d  rotation=%d°", W, H, self._rotation)
        pygame.display.set_caption('starseq')

        # --- Rotation ---
        # Auto-rotate portrait screens to landscape when no rotation was specified.
        rotation = self._rotation
        if rotation == 0 and W < H:
            rotation = 270
            logger.info("Auto-rotating portrait screen %dx%d → landscape", W, H)

        # Always swap canvas dimensions for 90/270 so the canvas is transposed
        # relative to the physical screen regardless of which axis is longer.
        if rotation in (90, 270):
            CW, CH = H, W
            _do_rotate = True
        elif rotation == 180:
            CW, CH = W, H
            _do_rotate = True
        else:
            CW, CH = W, H
            _do_rotate = False

        canvas = pygame.Surface((CW, CH)) if _do_rotate else screen

        # --- Layout selection ---
        # Extreme: very wide/short canvas → vertical bar left, dome centre, grid right.
        # Portrait: taller than wide → bar top, dome above, grid below.
        # Landscape: normal side-by-side.
        _EXTREME_RATIO = 3.5
        is_extreme  = CH > 0 and (CW / CH) >= _EXTREME_RATIO
        is_portrait = not is_extreme and CW < CH

        if is_extreme:
            bar_rect    = pygame.Rect(0, 0, EXTREME_BAR_W, CH)
            overlay_x   = EXTREME_BAR_W
            overlay_y   = 0
            bar_h       = CH   # sentinel — bar occupies full height on left
        else:
            bar_h     = max(BAR_HEIGHT, round(CH * BAR_HEIGHT / 1080))
            bar_rect  = pygame.Rect(0, 0, CW, bar_h)
            overlay_x = 0
            overlay_y = bar_h

        def _content_rects(hide_grid: bool):
            """Dome/grid rects for the current layout. When hide_grid is True the
            grid is collapsed out of the page and the dome expands to fill the
            freed space."""
            if is_extreme:
                if hide_grid:
                    dome_rect = pygame.Rect(EXTREME_BAR_W, 0, max(CH, CW - EXTREME_BAR_W), CH)
                    grid_rect = pygame.Rect(CW, 0, 0, CH)
                else:
                    dome_size = CH   # largest square that fits full height
                    grid_x    = EXTREME_BAR_W + dome_size
                    dome_rect = pygame.Rect(EXTREME_BAR_W, 0, dome_size, CH)
                    grid_rect = pygame.Rect(grid_x, 0, max(0, CW - grid_x), CH)
            else:
                content_h = CH - bar_h
                if is_portrait:
                    if hide_grid:
                        dome_rect = pygame.Rect(0, bar_h, CW, content_h)
                        grid_rect = pygame.Rect(0, CH, CW, 0)
                    else:
                        dome_h    = min(CW, content_h)
                        dome_rect = pygame.Rect(0, bar_h, CW, dome_h)
                        grid_rect = pygame.Rect(0, bar_h + dome_h, CW, max(0, content_h - dome_h))
                else:
                    if hide_grid:
                        dome_rect = pygame.Rect(0, bar_h, CW, content_h)
                        grid_rect = pygame.Rect(CW, bar_h, 0, content_h)
                    else:
                        dome_size = min(content_h, CW // 2)
                        dome_rect = pygame.Rect(0, bar_h, dome_size, content_h)
                        grid_rect = pygame.Rect(dome_size, bar_h, CW - dome_size, content_h)
            return dome_rect, grid_rect

        dome_rect, grid_rect = _content_rects(hide_grid=False)
        logger.info("Layout: extreme=%s portrait=%s canvas=%dx%d",
                    is_extreme, is_portrait, CW, CH)

        bar  = TransportBar(bar_rect, self._transport, self._menu_state)
        dome = StarDome(dome_rect, self._sky_engine, self._track_store, self._flash_state,
                        sim_clock=self._sim_clock, transport=self._transport,
                        constellation_lines=self._constellation_lines)
        grid = SequencerGrid(grid_rect, self._track_store, self._flash_state, self._transport)
        loc_overlay = LocationOverlay()
        time_overlay = TimeOverlay()

        bar.init()
        grid.init()

        clock = pygame.time.Clock()

        while not self._stop_event.is_set():
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._stop_event.set()
                    break
                if event.type == pygame.KEYDOWN:
                    self._handle_key(event.key)

            self._drain_flash_events()
            self._drain_input_queue()

            with self._transport._lock:
                hide_grid = (self._transport.track_brightness == 'off')
            dome_rect, grid_rect = _content_rects(hide_grid)
            dome.set_rect(dome_rect)
            grid.set_rect(grid_rect)

            canvas.fill((8, 8, 16))
            if is_extreme:
                bar.draw_vertical(canvas)
            else:
                bar.draw(canvas)
            dome.draw(canvas)
            if not hide_grid:
                grid.draw(canvas)

            if self._menu_state is not None and self._menu_state.overlay_open:
                loc_overlay.draw(canvas, self._menu_state, self._transport,
                                 panel_x=overlay_x, panel_y=overlay_y)

            if self._menu_state is not None and self._menu_state.time_overlay_open:
                if is_extreme:
                    time_panel_x, time_panel_y = overlay_x, overlay_y
                else:
                    time_panel_x, time_panel_y = max(0, CW - TIME_PANEL_W), overlay_y
                time_overlay.draw(canvas, self._menu_state,
                                  panel_x=time_panel_x, panel_y=time_panel_y)

            if _do_rotate:
                # pygame.transform.rotate is counterclockwise; negate for clockwise.
                rotated = pygame.transform.rotate(canvas, -rotation)
                screen.fill((0, 0, 0))
                rx = (W - rotated.get_width()) // 2
                ry = (H - rotated.get_height()) // 2
                screen.blit(rotated, (rx, ry))

            pygame.display.flip()
            clock.tick(config.TARGET_FPS)

        pygame.quit()

    def _post(self, event_type: str, value=None):
        """Post a synthetic InputEvent to the main-thread input queue."""
        if self._input_queue is not None:
            try:
                self._input_queue.put_nowait(InputEvent(event_type, value))
            except queue.Full:
                pass

    def _handle_key(self, key: int):
        if key == pygame.K_ESCAPE:
            self._stop_event.set()
        elif key in (pygame.K_RETURN, pygame.K_SPACE):
            self._post('press')
        elif key == pygame.K_UP:
            self._post('nav', -1)
        elif key == pygame.K_DOWN:
            self._post('nav', 1)
        elif key in (pygame.K_RIGHT, pygame.K_EQUALS, pygame.K_PLUS):
            self._post('rotate', 1)
        elif key in (pygame.K_LEFT, pygame.K_MINUS):
            self._post('rotate', -1)
        elif key == pygame.K_p:
            self._post('toggle_play')
        elif key == pygame.K_r:
            self._post('long_press')
        elif key == pygame.K_HOME:
            self._post('double_press')
