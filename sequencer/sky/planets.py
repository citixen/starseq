from dataclasses import dataclass

# (display_name, Skyfield/JPL ephemeris target key, marker colour)
# Targets resolve against the existing de421.bsp — no additional data file
# needed. Earth (the observer) and the Moon/Sun are intentionally excluded;
# this is a "where are the planets" overlay, not a full almanac. for now...
PLANETS = [
    ("Mercury", "MERCURY BARYCENTER", (180, 180, 180)),
    ("Venus", "VENUS", (255, 235, 190)),
    ("Mars", "MARS BARYCENTER", (255, 110, 80)),
    ("Jupiter", "JUPITER BARYCENTER", (255, 205, 130)),
    ("Saturn", "SATURN BARYCENTER", (230, 215, 165)),
    ("Uranus", "URANUS BARYCENTER", (150, 210, 225)),
    ("Neptune", "NEPTUNE BARYCENTER", (95, 130, 220)),
]


@dataclass
class PlanetPosition:
    name: str
    alt: float  # degrees above horizon
    az: float  # degrees, 0=N, 90=E, 180=S, 270=W
    colour: tuple
