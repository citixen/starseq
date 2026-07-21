"""Preset date/time list for the set-time overlay's EVENT picker.

Each entry is (label, datetime, is_exact) in UTC, kept in chronological
order so encoder navigation moves forward/backward through time. is_exact
is False where the source only establishes a date (not a time), and the
time field below that is a nominal placeholder.

All entries fall within the DE421 ephemeris's valid range
(1899-07-28 to 2053-10-08) — see SEQUENCER_DESIGN.md § Data Sources.
"""

from datetime import datetime, timezone


def _utc(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


TIME_PRESETS = [
    ("Wright Bros. First Flight", _utc(1903, 12, 17, 10, 35), True),
    ("Tunguska Event", _utc(1908, 6, 30, 7, 14), True),
    ("Pluto Discovered", _utc(1930, 2, 18, 16, 0), False),
    ("Sputnik 1 Launch", _utc(1957, 10, 4, 19, 28), True),
    ("Gagarin's First Spaceflight", _utc(1961, 4, 12, 6, 7), True),
    ("Apollo 11: First Step on Moon", _utc(1969, 7, 21, 2, 56), True),
    ("Voyager 1 Launch", _utc(1977, 9, 5, 12, 56), True),
    ("Halley's Comet Perihelion", _utc(1986, 2, 9, 12, 0), False),
    ("Y2K Midnight", _utc(2000, 1, 1, 0, 0), True),
    ("Last Shuttle Launch (STS-135)", _utc(2011, 7, 8, 15, 29), True),
    ("First Black Hole Image", _utc(2019, 4, 10, 13, 0), True),
]
