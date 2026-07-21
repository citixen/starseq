import re

_LINE_RE = re.compile(r'^([A-Za-z]+)\s*=\s*(.+)$')
_POLYLINE_RE = re.compile(r'\[([^\]]*)\]')


def load_constellation_lines(path: str) -> dict:
    """Parse a 'constellation-lines-hr' file into {abbr: [[hr, hr, ...], ...]}.

    Each source line looks like:
        Ori = [2061, 1790, 1852, 1713];[1948, 1903, 1852]
    where each bracketed group is a polyline of HR (Yale Bright Star
    Catalogue) numbers to be connected in order.
    """
    result = {}
    with open(path, 'r', encoding='utf-8') as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            m = _LINE_RE.match(line)
            if not m:
                continue
            abbr = m.group(1)
            polylines = []
            for group in _POLYLINE_RE.finditer(m.group(2)):
                hrs = [int(tok) for tok in group.group(1).split(',') if tok.strip()]
                if len(hrs) >= 2:
                    polylines.append(hrs)
            if polylines:
                result[abbr] = polylines
    return result
