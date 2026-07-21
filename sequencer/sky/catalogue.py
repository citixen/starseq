import json
import re
from dataclasses import dataclass


@dataclass
class SkyStar:
    hr: int
    alt: float   # degrees above horizon
    az: float    # degrees, 0=N, 90=E, 180=S, 270=W
    mag: float   # visual magnitude
    bv: float    # B-V colour index (derived from K temperature)


def _parse_ra(ra_str: str) -> float:
    """Parse RA string like '00h 05m 09.9s' to decimal hours."""
    m = re.match(r'(\d+)h\s*(\d+)m\s*([\d.]+)s', ra_str.strip())
    if not m:
        return 0.0
    h, mn, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
    return h + mn / 60.0 + s / 3600.0


def _parse_dec(dec_str: str) -> float:
    """Parse Dec string like '+45° 13′ 45″' to decimal degrees."""
    # Unicode prime (′ U+2032) and double-prime (″ U+2033) used as arcmin/arcsec markers
    m = re.match(r'([+-]?)(\d+)[°º]\s*(\d+)[′\']\s*([\d.]+)', dec_str.strip())
    if not m:
        return 0.0
    sign = -1.0 if m.group(1) == '-' else 1.0
    d, mn, s = float(m.group(2)), float(m.group(3)), float(m.group(4))
    return sign * (d + mn / 60.0 + s / 3600.0)


def _k_to_bv(k: int) -> float:
    """Convert colour temperature in Kelvin to approximate B-V index.

    Derived from empirical stellar data:
        T=3000K → BV≈1.98, T=5000K → BV≈0.84, T=10000K → BV≈-0.01
    """
    if k <= 0:
        return 0.0
    bv = 8540.0 / k - 0.865
    return max(-0.4, min(2.0, bv))


def load_catalogue(path: str) -> list:
    """Load BSC5 JSON and return list of (hr, ra_hours, dec_degrees, mag, bv) tuples."""
    with open(path, 'r', encoding='utf-8') as f:
        entries = json.load(f)

    stars = []
    for entry in entries:
        try:
            hr = int(entry['HR'])
            ra_hours = _parse_ra(entry['RA'])
            dec_degrees = _parse_dec(entry['Dec'])
            mag = float(entry['V'])
            k = int(entry.get('K', 0))
            bv = _k_to_bv(k) if k > 0 else 0.0
            stars.append((hr, ra_hours, dec_degrees, mag, bv))
        except (KeyError, ValueError):
            continue

    return stars
