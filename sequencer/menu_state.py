"""
MenuState

The parameter bar is always visible; there is no open/close concept.
One parameter is always focused. The encoder (or keyboard) adjusts it.
Pressing the encoder (or Space) advances focus to the next parameter.

Keyboard shortcuts (posted by DisplayRenderer):
  SPACE / ENTER → advance focus (same as press)
  UP / DOWN     → navigate params without changing value (InputEvent 'nav')
  LEFT / RIGHT  → adjust focused param (InputEvent 'rotate')
  P             → toggle play/stop
  R             → reset simulated clock (same as long press)
  ESC           → quit

Globe icon (left side of transport bar):
  Navigate left past the last icon (wrap) → land on globe
  Press while globe focused → open/close location overlay
  In overlay: rotate navigates items, press toggles edit, adjust changes value

Clock icon (right side of transport bar, before the brightness icons):
  Navigate right past TIME → land on clock icon
  Press while clock focused → open/close the "set time" overlay
  In overlay: rotate navigates year/month/day/hour/minute, press toggles
  edit, adjust changes the field and immediately jumps the simulated clock

Icon toggles (CONST/PLANETS to the left of VIEW, TRACKS to the right of the
clock icon) — no overlay, behave like a normal param:
  Press while focused → toggle edit mode
  While editing, rotate cycles Bright → Dim → Off

The full navigation ring, left to right:
  globe → [left icon toggles] → params → clock → [right icon toggles] → (wraps to globe)
"""

import calendar
from datetime import datetime, timezone

import config
from transport.state import (
    SCALE_NAMES,
    KEY_NAMES,
    VIEW_MODES,
    VIEW_MODE_LABELS,
    CH_MODES,
    CH_MODE_LABELS,
    LOC_SOURCES,
    LOC_SOURCE_LABELS,
    BRIGHTNESS_MODES,
)
from transport.cities import PRESET_CITIES
from transport.time_presets import TIME_PRESETS

PARAMS = [
    ("view_mode", "VIEW"),
    ("pulse_duration", "PULSE"),
    ("bpm", "BPM"),
    ("clock_source", "CLOCK"),
    ("key", "KEY"),
    ("scale", "SCALE"),
    ("max_poly_notes", "POLY"),
    ("midi_device", "MIDI DEVICE"),
    ("midi_ch_mode", "CH MODE"),
    ("time_multiplier", "TIME"),
]

# Simple tri-state icon toggles — no overlay, just Bright/Dim/Off cycling.
# 'zone' places them left of the params (near VIEW) or right of the clock
# icon (near play/stop).
ICON_TOGGLES = [
    ("constellation_brightness", "CONST", "left"),
    ("planet_brightness", "PLANETS", "left"),
    ("track_brightness", "TRACKS", "right"),
]

# Flat, ordered list of navigable "stops" around the transport bar:
# ('globe', None) | ('icon', idx-into-ICON_TOGGLES) | ('param', idx-into-PARAMS) | ('clock', None)
NAV_STOPS = (
    [("globe", None)]
    + [("icon", i) for i, t in enumerate(ICON_TOGGLES) if t[2] == "left"]
    + [("param", i) for i in range(len(PARAMS))]
    + [("clock", None)]
    + [("icon", i) for i, t in enumerate(ICON_TOGGLES) if t[2] == "right"]
)
_DEFAULT_STOP_INDEX = NAV_STOPS.index(("param", 0))
_GLOBE_STOP_INDEX = NAV_STOPS.index(("globe", None))

# Items shown inside the location overlay. 'city' is only present when
# location_source == 'preset' — see _overlay_items().
OVERLAY_ITEMS = [
    ("source", "SOURCE"),
    ("city", "CITY"),
    ("lat", "LATITUDE"),
    ("lon", "LONGITUDE"),
]


def _overlay_items(transport) -> list:
    """Overlay rows for the current location_source (called while holding transport._lock)."""
    if transport.location_source == "preset":
        return OVERLAY_ITEMS
    return [item for item in OVERLAY_ITEMS if item[0] != "city"]


# Items shown inside the "set time" overlay opened from the clock icon.
# 'event' is a scrollable picker over TIME_PRESETS — rotating it jumps the
# sim clock immediately and seeds year/month/day/hour/minute above it, the
# same way CITY seeds lat/lon in the location overlay. It's placed last,
# below MINUTE, so opening the overlay always focuses YEAR first — the
# preset picker is a deliberate scroll away, not the default landing spot.
# A 'Now' sentinel is appended after the fixed presets within EVENT itself
# (jumps to the current real UTC time rather than a fixed date) and kept
# last in that sub-list for the same reason.
# Note : Rpi5 doesn't have a battery = so now will only work when able to
# access NTP services. Otherwise it will be the last known-good date/time
_NOW_EVENT_INDEX = len(TIME_PRESETS)
_EVENT_COUNT = len(TIME_PRESETS) + 1

TIME_OVERLAY_ITEMS = [
    ("year", "YEAR"),
    ("month", "MONTH"),
    ("day", "DAY"),
    ("hour", "HOUR"),
    ("minute", "MINUTE"),
    ("event", "EVENT"),
]

_MULT_STEPS = [
    -64.0,
    -32.0,
    -16.0,
    -8.0,
    -4.0,
    -2.0,
    -1.0,
    0.0,
    1.0,
    2.0,
    4.0,
    8.0,
    16.0,
    32.0,
    64.0,
]

_LOC_STEP = 0.01  # degrees per encoder click when editing lat/lon


def _mult_label(m: float) -> str:
    if m == 0.0:
        return "FROZEN"
    sign = "-" if m < 0 else ""
    return f"{sign}x{abs(m):g}"


def _render_value(field: str, transport) -> str:
    """Return display string for a parameter (called while holding transport._lock)."""
    if field == "view_mode":
        return VIEW_MODE_LABELS.get(transport.view_mode, transport.view_mode)
    if field == "pulse_duration":
        return f"{transport.pulse_duration:.1f}s"
    if field == "bpm":
        if transport.clock_source == "external":
            if transport.detected_bpm > 0:
                return f"{transport.detected_bpm:.1f}"
            return "---"
        return f"{transport.bpm:.1f}"
    if field == "clock_source":
        return "INT" if transport.clock_source == "internal" else "EXT"
    if field == "key":
        return KEY_NAMES[transport.key % 12]
    if field == "scale":
        return transport.scale.replace("_", " ").upper()
    if field == "max_poly_notes":
        return str(transport.max_poly_notes)
    if field == "midi_device":
        d = transport.midi_device
        return (d[:20] + "..") if len(d) > 22 else (d or "—")
    if field == "midi_ch_mode":
        return CH_MODE_LABELS.get(transport.midi_ch_mode, transport.midi_ch_mode)
    if field == "time_multiplier":
        return _mult_label(transport.time_multiplier)
    return ""


def _render_overlay_value(field: str, transport) -> str:
    """Display string for a location overlay item (called while holding transport._lock)."""
    if field == "source":
        return LOC_SOURCE_LABELS.get(transport.location_source, "?")
    if field == "city":
        idx = transport.preset_city_index % len(PRESET_CITIES)
        return PRESET_CITIES[idx][0]
    if field == "lat":
        return f"{transport.lat:+.4f}°"
    if field == "lon":
        return f"{transport.lon:+.4f}°"
    return ""


class MenuState:
    def __init__(self):
        self.stop_index: int = _DEFAULT_STOP_INDEX  # position in NAV_STOPS
        self.editing: bool = False  # edit state for 'param' and 'icon' stops
        self.midi_devices: list = []
        # Globe / location overlay
        self.overlay_open: bool = False
        self.overlay_focused_index: int = 0  # index into OVERLAY_ITEMS
        self.overlay_editing: bool = False
        # Clock / set-time overlay
        self.time_overlay_open: bool = False
        self.time_overlay_focused_index: int = 0  # index into TIME_OVERLAY_ITEMS
        self.time_overlay_editing: bool = False
        self._pending_year: int = 2000
        self._pending_month: int = 1
        self._pending_day: int = 1
        self._pending_hour: int = 0
        self._pending_minute: int = 0
        self._event_index: int = 0  # position in TIME_PRESETS

    @property
    def in_edit_mode(self) -> bool:
        """True when encoder turns should adjust a value rather than navigate."""
        if self.overlay_open:
            return self.overlay_editing
        if self.time_overlay_open:
            return self.time_overlay_editing
        return self.editing

    @property
    def globe_focused(self) -> bool:
        return NAV_STOPS[self.stop_index][0] == "globe"

    @property
    def clock_focused(self) -> bool:
        return NAV_STOPS[self.stop_index][0] == "clock"

    @property
    def focused_param(self) -> str:
        kind, idx = NAV_STOPS[self.stop_index]
        return PARAMS[idx][0] if kind == "param" else ""

    def icon_toggle_state(self, field: str) -> tuple:
        """Return (focused, editing) for the ICON_TOGGLES entry with this transport field."""
        kind, idx = NAV_STOPS[self.stop_index]
        if kind != "icon" or ICON_TOGGLES[idx][0] != field:
            return False, False
        focused = not self.overlay_open and not self.time_overlay_open
        return focused, focused and self.editing

    def press(self, sim_clock=None):
        """Toggle edit mode; opens/closes the overlay when globe/clock is focused."""
        kind, _ = NAV_STOPS[self.stop_index]
        if self.overlay_open:
            self.overlay_editing = not self.overlay_editing
        elif self.time_overlay_open:
            self.time_overlay_editing = not self.time_overlay_editing
        elif kind == "globe":
            self.overlay_open = True
            self.overlay_focused_index = 0
            self.overlay_editing = False
        elif kind == "clock":
            self.time_overlay_open = True
            self.time_overlay_focused_index = 0
            self.time_overlay_editing = False
            self._seed_pending_time(sim_clock)
        else:
            self.editing = not self.editing

    def _seed_pending_time(self, sim_clock) -> None:
        """Initialise the pending year/month/day/hour/minute from the current sim time."""
        dt = sim_clock.now() if sim_clock is not None else datetime.now(timezone.utc)
        self._pending_year = dt.year
        self._pending_month = dt.month
        self._pending_day = dt.day
        self._pending_hour = dt.hour
        self._pending_minute = dt.minute

    def navigate(self, direction: int, transport):
        """Move focus; handles overlay navigation and the flat NAV_STOPS ring otherwise."""
        self.editing = False

        if self.overlay_open:
            self.overlay_editing = False
            with transport._lock:
                n_items = len(_overlay_items(transport))
            new_idx = self.overlay_focused_index + direction
            if new_idx < 0:
                # Navigate left past SOURCE → close overlay, stay on globe
                self.overlay_open = False
            elif new_idx >= n_items:
                # Navigate right past the last item → close overlay, move into params
                self.overlay_open = False
                self.stop_index = _DEFAULT_STOP_INDEX
            else:
                self.overlay_focused_index = new_idx
            return

        if self.time_overlay_open:
            self.time_overlay_editing = False
            new_idx = self.time_overlay_focused_index + direction
            if new_idx < 0:
                # Navigate left past YEAR → close overlay, stay on clock icon
                self.time_overlay_open = False
            elif new_idx >= len(TIME_OVERLAY_ITEMS):
                # Navigate right past MINUTE → close overlay, move on to globe (wrap)
                self.time_overlay_open = False
                self.stop_index = _GLOBE_STOP_INDEX
            else:
                self.time_overlay_focused_index = new_idx
            return

        self.stop_index = (self.stop_index + direction) % len(NAV_STOPS)

    def refresh_midi_devices(self, midi_out) -> None:
        self.midi_devices = midi_out.get_output_names()

    def value_str(self, transport) -> str:
        with transport._lock:
            return _render_value(self.focused_param, transport)

    def all_values(self, transport) -> list:
        """Return [(label, value_str, is_focused, is_editing)] for every parameter."""
        kind, idx = NAV_STOPS[self.stop_index]
        param_focused = (
            kind == "param" and not self.overlay_open and not self.time_overlay_open
        )
        with transport._lock:
            return [
                (
                    label,
                    _render_value(field, transport),
                    param_focused and idx == i,
                    param_focused and idx == i and self.editing,
                )
                for i, (field, label) in enumerate(PARAMS)
            ]

    def overlay_values(self, transport) -> list:
        """Return [(label, value_str, is_focused, is_editing, is_available)] for overlay items."""
        with transport._lock:
            gps_ok = transport.gps_connected
            rows = []
            for i, (field, label) in enumerate(_overlay_items(transport)):
                val = _render_overlay_value(field, transport)
                focused = i == self.overlay_focused_index
                editing = focused and self.overlay_editing
                # GPS source option unavailable when receiver not connected
                available = True
                if (
                    field == "source"
                    and transport.location_source == "gps"
                    and not gps_ok
                ):
                    available = (
                        False  # currently on GPS but disconnected — show as unavailable
                    )
                # LAT/LON are read-only unless manual mode is active; CITY is
                # always editable (it's only shown while source == 'preset')
                editable = True
                if field in ("lat", "lon") and transport.location_source != "manual":
                    editable = False
                rows.append((label, val, focused, editing, available, editable))
            return rows

    def time_overlay_values(self) -> list:
        """Return [(label, value_str, is_focused, is_editing, hint_str)] for the set-time overlay."""
        pending = {
            "year": self._pending_year,
            "month": self._pending_month,
            "day": self._pending_day,
            "hour": self._pending_hour,
            "minute": self._pending_minute,
        }
        rows = []
        for i, (field, label) in enumerate(TIME_OVERLAY_ITEMS):
            focused = i == self.time_overlay_focused_index
            editing = focused and self.time_overlay_editing
            if field == "event":
                idx = self._event_index % _EVENT_COUNT
                text = "Now" if idx == _NOW_EVENT_INDEX else TIME_PRESETS[idx][0]
                hint = f"{idx + 1}/{_EVENT_COUNT}"
            else:
                val = pending[field]
                text = f"{val:04d}" if field == "year" else f"{val:02d}"
                hint = ""
            rows.append((label, text, focused, editing, hint))
        return rows

    def adjust(
        self, direction: int, transport, sim_clock, midi_out, track_store
    ) -> None:
        """Apply direction (±1) to the focused parameter, including side effects."""
        if self.overlay_open:
            self._adjust_overlay(direction, transport)
            return

        if self.time_overlay_open:
            self._adjust_time_overlay(direction, sim_clock)
            return

        kind, idx = NAV_STOPS[self.stop_index]

        if kind == "icon":
            field = ICON_TOGGLES[idx][0]
            self._adjust_icon_toggle(field, direction, transport)
            return

        if kind != "param":
            return

        p = PARAMS[idx][0]

        if p == "view_mode":
            with transport._lock:
                cur = transport.view_mode
                idx = VIEW_MODES.index(cur) if cur in VIEW_MODES else 0
                transport.view_mode = VIEW_MODES[(idx + direction) % len(VIEW_MODES)]

        elif p == "pulse_duration":
            with transport._lock:
                transport.pulse_duration = round(
                    max(0.1, min(2.0, transport.pulse_duration + direction * 0.1)), 1
                )

        elif p == "bpm":
            with transport._lock:
                transport.bpm = max(20.0, min(300.0, transport.bpm + direction * 1.0))

        elif p == "clock_source":
            with transport._lock:
                transport.clock_source = (
                    "external" if transport.clock_source == "internal" else "internal"
                )

        elif p == "key":
            with transport._lock:
                transport.key = (transport.key + direction) % 12
            _mark_dirty(track_store)

        elif p == "scale":
            with transport._lock:
                idx = (
                    SCALE_NAMES.index(transport.scale)
                    if transport.scale in SCALE_NAMES
                    else 0
                )
                transport.scale = SCALE_NAMES[(idx + direction) % len(SCALE_NAMES)]
            _mark_dirty(track_store)

        elif p == "max_poly_notes":
            with transport._lock:
                transport.max_poly_notes = max(
                    1, min(8, transport.max_poly_notes + direction)
                )
            _mark_dirty(track_store)

        elif p == "midi_device":
            devices = self.midi_devices
            if not devices:
                return
            with transport._lock:
                try:
                    idx = devices.index(transport.midi_device)
                except ValueError:
                    idx = 0
                new_device = devices[(idx + direction) % len(devices)]
                transport.midi_device = new_device
            midi_out.open(new_device)

        elif p == "midi_ch_mode":
            with transport._lock:
                cur_idx = (
                    CH_MODES.index(transport.midi_ch_mode)
                    if transport.midi_ch_mode in CH_MODES
                    else 0
                )
                new_mode = CH_MODES[(cur_idx + direction) % len(CH_MODES)]
                transport.midi_ch_mode = new_mode
                launch = list(transport.launch_channels)
                ctrl = list(transport.controller_channels)
            _apply_ch_mode(new_mode, track_store, launch, ctrl, midi_out)

        elif p == "time_multiplier":
            with transport._lock:
                cur = transport.time_multiplier
            distances = [abs(s - cur) for s in _MULT_STEPS]
            best = distances.index(min(distances))
            new_idx = max(0, min(len(_MULT_STEPS) - 1, best + direction))
            new_mult = _MULT_STEPS[new_idx]
            with transport._lock:
                transport.time_multiplier = new_mult
            sim_clock.multiplier = new_mult

    def _adjust_overlay(self, direction: int, transport) -> None:
        """Adjust the currently focused overlay item by direction (±1)."""
        with transport._lock:
            field = _overlay_items(transport)[self.overlay_focused_index][0]

        if field == "source":
            with transport._lock:
                gps_ok = transport.gps_connected
                cur = transport.location_source
                available = [s for s in LOC_SOURCES if s != "gps" or gps_ok]
                try:
                    idx = available.index(cur)
                except ValueError:
                    idx = 0
                new_src = available[(idx + direction) % len(available)]
                transport.location_source = new_src
                if new_src == "default":
                    transport.lat = config.LOCATION_LAT
                    transport.lon = config.LOCATION_LON
                elif new_src == "gps" and gps_ok:
                    transport.lat = transport.gps_lat
                    transport.lon = transport.gps_lon
                elif new_src == "preset":
                    city_idx = transport.preset_city_index % len(PRESET_CITIES)
                    transport.lat = PRESET_CITIES[city_idx][1]
                    transport.lon = PRESET_CITIES[city_idx][2]

        elif field == "city":
            with transport._lock:
                if transport.location_source != "preset":
                    return
                new_idx = (transport.preset_city_index + direction) % len(PRESET_CITIES)
                transport.preset_city_index = new_idx
                transport.lat = PRESET_CITIES[new_idx][1]
                transport.lon = PRESET_CITIES[new_idx][2]

        elif field == "lat":
            with transport._lock:
                if transport.location_source != "manual":
                    return
                transport.lat = round(
                    max(-90.0, min(90.0, transport.lat + direction * _LOC_STEP)), 4
                )

        elif field == "lon":
            with transport._lock:
                if transport.location_source != "manual":
                    return
                transport.lon = round(
                    max(-180.0, min(180.0, transport.lon + direction * _LOC_STEP)), 4
                )

    def _adjust_time_overlay(self, direction: int, sim_clock) -> None:
        """Adjust the currently focused year/month/day/hour/minute field, then jump
        the simulated clock to the resulting UTC datetime."""
        field = TIME_OVERLAY_ITEMS[self.time_overlay_focused_index][0]

        if field == "event":
            self._event_index = (self._event_index + direction) % _EVENT_COUNT
            if self._event_index == _NOW_EVENT_INDEX:
                dt = datetime.now(timezone.utc)
            else:
                _, dt, _ = TIME_PRESETS[self._event_index]
            self._pending_year = dt.year
            self._pending_month = dt.month
            self._pending_day = dt.day
            self._pending_hour = dt.hour
            self._pending_minute = dt.minute
        elif field == "year":
            self._pending_year = max(1, min(9999, self._pending_year + direction))
        elif field == "month":
            self._pending_month = (self._pending_month - 1 + direction) % 12 + 1
        elif field == "day":
            days = calendar.monthrange(self._pending_year, self._pending_month)[1]
            self._pending_day = (self._pending_day - 1 + direction) % days + 1
        elif field == "hour":
            self._pending_hour = (self._pending_hour + direction) % 24
        elif field == "minute":
            self._pending_minute = (self._pending_minute + direction) % 60

        # A month/year change can leave the day out of range (e.g. Jan 31 → Feb).
        days = calendar.monthrange(self._pending_year, self._pending_month)[1]
        self._pending_day = min(self._pending_day, days)

        dt = datetime(
            self._pending_year,
            self._pending_month,
            self._pending_day,
            self._pending_hour,
            self._pending_minute,
            tzinfo=timezone.utc,
        )
        sim_clock.set_time(dt)

    def _adjust_icon_toggle(self, field: str, direction: int, transport) -> None:
        """Cycle the given transport field through Bright → Dim → Off."""
        with transport._lock:
            cur = getattr(transport, field)
            idx = BRIGHTNESS_MODES.index(cur) if cur in BRIGHTNESS_MODES else 0
            setattr(
                transport,
                field,
                BRIGHTNESS_MODES[(idx + direction) % len(BRIGHTNESS_MODES)],
            )


def _mark_dirty(track_store) -> None:
    for track in track_store.tracks:
        with track._lock:
            track.sequence_dirty = True


def _apply_ch_mode(
    mode: str, track_store, launch_channels: list, controller_channels: list, midi_out
) -> None:
    """Update every track's MIDI channel to match the selected mode."""
    for i, track in enumerate(track_store.tracks):
        if mode == "default":
            new_ch = launch_channels[i]
        elif mode == "sequential":
            new_ch = i + 1
        elif mode.startswith("single_"):
            new_ch = int(mode.split("_")[1])
        elif mode == "custom":
            new_ch = controller_channels[i]
        else:
            continue
        new_ch = max(1, min(16, new_ch))
        with track._lock:
            old_ch = track.midi_channel
            track.midi_channel = new_ch
        if old_ch != new_ch:
            midi_out.send_all_notes_off(old_ch)
