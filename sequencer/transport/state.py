import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
import time

import config

SCALES = {
    'major':          [0, 2, 4, 5, 7, 9, 11],
    'minor':          [0, 2, 3, 5, 7, 8, 10],
    'dorian':         [0, 2, 3, 5, 7, 9, 10],
    'phrygian':       [0, 1, 3, 5, 7, 8, 10],
    'lydian':         [0, 2, 4, 6, 7, 9, 11],
    'mixolydian':     [0, 2, 4, 5, 7, 9, 10],
    'locrian':        [0, 1, 3, 5, 6, 8, 10],
    'whole_tone':     [0, 2, 4, 6, 8, 10],
    'pentatonic_maj': [0, 2, 4, 7, 9],
    'pentatonic_min': [0, 3, 5, 7, 10],
    'chromatic':      list(range(12)),
}

SCALE_NAMES = list(SCALES.keys())
KEY_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


VIEW_MODES = ['bright_1', 'bright_2', 'bright_3',
              'dim_1', 'dim_2', 'dim_3',
              'stars_1', 'stars_2', 'stars_3', 'stars_4']
VIEW_MODE_LABELS = {
    'bright_1': 'BRIGHT 1',
    'bright_2': 'BRIGHT 2',
    'bright_3': 'BRIGHT 3',
    'dim_1':    'DIM 1',
    'dim_2':    'DIM 2',
    'dim_3':    'DIM 3',
    'stars_1':  'STARS 1',
    'stars_2':  'STARS 2',
    'stars_3':  'STARS 3',
    'stars_4':  'STARS 4',
}

# Per-mode (stardome_bright, inscope_bright, wedges, pulse_bright) axes —
# see display/dome.py. wedges: 'bright' | 'dim' | 'none'.
# inscope_bright is None when wedges == 'none' (no separate in-scope
# treatment — in-scope and out-of-scope stars are drawn identically).
VIEW_MODE_AXES = {
    'bright_1': (True,  True,  'bright', True),
    'bright_2': (False, True,  'bright', True),
    'bright_3': (False, False, 'bright', True),
    'dim_1':    (True,  True,  'dim',    False),
    'dim_2':    (False, True,  'dim',    False),
    'dim_3':    (False, False, 'dim',    False),
    'stars_1':  (True,  None,  'none',   True),
    'stars_2':  (True,  None,  'none',   False),
    'stars_3':  (False, None,  'none',   True),
    'stars_4':  (False, None,  'none',   False),
}

CH_MODES = ['default', 'sequential', 'single_1', 'single_2', 'single_3', 'single_4', 'custom']

CH_MODE_LABELS = {
    'default':    'DFLT',
    'sequential': 'SEQ',
    'single_1':   'ALL 1',
    'single_2':   'ALL 2',
    'single_3':   'ALL 3',
    'single_4':   'ALL 4',
    'custom':     'CUST',
}

LOC_SOURCES = ['default', 'manual', 'gps', 'preset']
LOC_SOURCE_LABELS = {'default': 'DEFAULT', 'manual': 'MANUAL', 'gps': 'GPS', 'preset': 'PRESET'}

# Shared 3-state visibility scheme, reused by tracks/constellations/planets
BRIGHTNESS_MODES = ['bright', 'dim', 'off']
BRIGHTNESS_LABELS = {'bright': 'BRIGHT', 'dim': 'DIM', 'off': 'OFF'}


@dataclass
class TransportState:
    playing: bool = False
    bpm: float = 120.0
    detected_bpm: float = 0.0        # measured from external clock; 0 = no signal yet
    clock_source: str = 'internal'   # 'internal' | 'external'
    key: int = 0                     # 0=C … 11=B
    scale: str = 'major'
    max_poly_notes: int = 5
    midi_device: str = ''
    view_mode: str = 'bright_1'        # see VIEW_MODES
    constellation_brightness: str = 'off'   # see BRIGHTNESS_MODES
    planet_brightness: str = 'off'          # see BRIGHTNESS_MODES
    track_brightness: str = 'bright'        # see BRIGHTNESS_MODES
    pulse_duration: float = 0.5      # flash fade length in seconds (0.1–2.0)
    midi_ch_mode: str = 'default'    # see CH_MODES
    time_multiplier: float = 1.0
    sim_time_anchor: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    wall_anchor: float = field(default_factory=time.perf_counter)
    # Per-track channel lists (index 0 = track 1)
    launch_channels: list = field(default_factory=lambda: list(range(1, 9)))
    controller_channels: list = field(default_factory=lambda: list(range(1, 9)))
    # Location
    location_source: str = 'default'   # 'default' | 'manual' | 'gps' | 'preset'
    lat: float = field(default_factory=lambda: config.LOCATION_LAT)
    lon: float = field(default_factory=lambda: config.LOCATION_LON)
    gps_connected: bool = False
    gps_lat: float = 0.0
    gps_lon: float = 0.0
    preset_city_index: int = 0   # index into transport.cities.PRESET_CITIES

    def __post_init__(self):
        self._lock = threading.Lock()
