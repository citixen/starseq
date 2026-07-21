import os

# Geographic location defaults - set as needed!
LOCATION_LAT = 51.75
LOCATION_LON = -0.22
LOCATION_ELEV = 80  # metres

# Data files (relative to project root)
CATALOGUE_PATH = os.path.join("data", "bsc5.json")
EPHEMERIS_PATH = os.path.join("data", "de421.bsp")
CONSTELLATION_LINES_PATH = os.path.join("data", "constellation-lines-hr.utf8")

# Star dome display
SHOW_OUT_OF_SCOPE_STARS = True

# Display
TARGET_FPS = 30
SHOW_MIDI_NOTE_LABELS = False
BAR_HEIGHT = 48  # height of the transport / parameter bar in pixels

# Sequencer
MAX_POLY_NOTES = 5
PPQN = 24

# Sky engine
SKY_RECALC_INTERVAL_MS = 250

# Track colours — one per track, RGB tuples
TRACK_COLOURS = [
    (255, 100, 100),  # track 1 — red
    (255, 180, 60),  # track 2 — amber
    (255, 255, 80),  # track 3 — yellow
    (80, 220, 80),  # track 4 — green
    (60, 200, 220),  # track 5 — cyan
    (80, 120, 255),  # track 6 — blue
    (180, 80, 255),  # track 7 — purple
    (255, 80, 180),  # track 8 — pink
]

# UI
ENCODER_LONG_HOLD_MS = 2000

# Serial
SERIAL_PORT = os.environ.get("SERIAL_PORT", "/dev/ttyAMA0")
SERIAL_BAUD = 57600
