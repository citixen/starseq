import threading
import struct
import logging

import serial

from tracks.state import TrackStateStore

logger = logging.getLogger(__name__)

PROTO_VERSION = 5  # payload[0] — protocol version - don't worry about 1-4. It's fine.
PKT_TYPE_FULL = 0x01  # payload[1] — 8-track snapshot
PKT_TYPE_DELTA = 0x02  # payload[1] — single-track delta

CONTROLLER_RECORD_SIZE = 21
HEADER_SIZE = 4
FULL_BODY_SIZE = 8 * CONTROLLER_RECORD_SIZE  # 168 bytes
DELTA_BODY_SIZE = CONTROLLER_RECORD_SIZE  # 21 bytes

# Expected decoded payload sizes (header + body + CRC; no COBS overhead, no 0x00 delimiter)
FULL_PAYLOAD_SIZE = HEADER_SIZE + FULL_BODY_SIZE + 1
DELTA_PAYLOAD_SIZE = HEADER_SIZE + DELTA_BODY_SIZE + 1

STATUS_LABELS = {0: "waiting", 1: "online", 2: "stale", 3: "offline"}


def crc8(data: bytes) -> int:
    """CRC-8 poly 0x31, init 0x00, non-reflected MSB-first — matches firmware crc8.cpp."""
    crc = 0x00
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x31) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def cobs_decode(encoded: bytes) -> bytes:
    """Decode COBS-encoded bytes (the trailing 0x00 delimiter must already be stripped)."""
    out = bytearray()
    i = 0
    while i < len(encoded):
        overhead = encoded[i]
        i += 1
        if overhead == 0:
            raise ValueError("Unexpected zero byte inside COBS frame")
        for _ in range(overhead - 1):
            if i >= len(encoded):
                raise ValueError("COBS: truncated frame")
            out.append(encoded[i])
            i += 1
        # Append the implicit zero that was replaced, except after the last group
        if i < len(encoded) and overhead < 0xFF:
            out.append(0x00)
    return bytes(out)


def _parse_record(data: bytes, offset: int) -> dict:
    b = data[offset : offset + CONTROLLER_RECORD_SIZE]
    return {
        "controller_id": b[0],
        "interface_status": b[1],
        "last_seq": b[2],
        "mode": b[3],
        "length": b[4],
        "play_mode": b[5],
        "step_divider": b[6],
        "param_mode": b[7],
        "play_direction": b[8],
        "base_note": b[9],
        "note_range": b[10],
        "vel_lo": b[11],
        "vel_hi": b[12],
        "dur_lo": b[13],
        "dur_hi": b[14],
        "slice_centre": struct.unpack_from("<H", b, 15)[0],
        "slice_width": struct.unpack_from("<H", b, 17)[0],
        "slice_brightness": b[19],
        "midi_channel": b[20],
    }


def _apply_record(record: dict, track_store: TrackStateStore, transport=None):
    cid = record["controller_id"]
    if not 1 <= cid <= 8:
        return
    track = track_store[cid - 1]
    ch = max(1, min(16, record["midi_channel"]))

    # Always cache the controller's reported channel; apply it to the track only
    # when the mode is 'custom' (all other modes manage channels independently).
    apply_ch = True
    if transport is not None:
        with transport._lock:
            transport.controller_channels[cid - 1] = ch
            apply_ch = transport.midi_ch_mode == "custom"

    with track._lock:
        new_status = record["interface_status"]
        if new_status != track.interface_status:
            level = logging.INFO if new_status in (0, 1) else logging.WARNING
            logger.log(
                level,
                "Controller %d interface status: %s -> %s",
                cid,
                STATUS_LABELS.get(track.interface_status, track.interface_status),
                STATUS_LABELS.get(new_status, new_status),
            )
        track.controller_id = cid
        track.interface_status = new_status
        track.mode = record["mode"]
        track.length = max(1, min(32, record["length"]))
        track.play_mode = record["play_mode"]
        track.step_divider = record["step_divider"]
        track.param_mode = record["param_mode"]
        track.play_direction = record["play_direction"]
        track.base_note = record["base_note"]
        track.note_range = record["note_range"]
        track.vel_lo = record["vel_lo"]
        track.vel_hi = record["vel_hi"]
        track.dur_lo = max(1, record["dur_lo"])
        track.dur_hi = max(1, record["dur_hi"])
        track.slice_centre = record["slice_centre"] % 360
        track.slice_width = max(1, min(360, record["slice_width"]))
        track.slice_brightness = min(100, record["slice_brightness"])
        if apply_ch:
            track.midi_channel = ch
        track.sequence_dirty = True


class SerialRXThread(threading.Thread):
    """Receives COBS-framed packets from the controller interface and updates track state."""

    def __init__(
        self, port: str, track_store: TrackStateStore, baud: int = 57600, transport=None
    ):
        super().__init__(name="SerialRX", daemon=True)
        self._port_name = port
        self._baud = baud
        self._track_store = track_store
        self._transport = transport
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def _process_frame(self, raw_frame: bytes):
        try:
            payload = cobs_decode(raw_frame)
        except ValueError as exc:
            logger.debug("COBS decode error: %s", exc)
            return

        if len(payload) < HEADER_SIZE + 1:
            return

        proto = payload[0]
        pkt_type = payload[1] if len(payload) > 1 else 0

        if proto != PROTO_VERSION:
            logger.debug("Unknown protocol version: %d", proto)
            return

        if pkt_type == PKT_TYPE_FULL and len(payload) == FULL_PAYLOAD_SIZE:
            is_full = True
        elif pkt_type == PKT_TYPE_DELTA and len(payload) == DELTA_PAYLOAD_SIZE:
            is_full = False
        else:
            logger.debug(
                "Unexpected type/size: type=0x%02x size=%d", pkt_type, len(payload)
            )
            return

        crc_rx = payload[-1]
        crc_calc = crc8(payload[:-1])
        if crc_rx != crc_calc:
            logger.debug("CRC mismatch: rx=0x%02x calc=0x%02x", crc_rx, crc_calc)
            return

        body_start = HEADER_SIZE
        if is_full:
            for i in range(8):
                record = _parse_record(payload, body_start + i * CONTROLLER_RECORD_SIZE)
                _apply_record(record, self._track_store, self._transport)
        else:
            record = _parse_record(payload, body_start)
            _apply_record(record, self._track_store, self._transport)

    def run(self):
        try:
            ser = serial.Serial(self._port_name, self._baud, timeout=0.1)
        except serial.SerialException as exc:
            logger.error("Cannot open serial port %s: %s", self._port_name, exc)
            return

        buf = bytearray()
        logger.info("SerialRX listening on %s at %d baud", self._port_name, self._baud)
        with ser:
            while not self._stop_event.is_set():
                try:
                    data = ser.read(256)
                except serial.SerialException as exc:
                    logger.error("Serial read error: %s", exc)
                    break
                for byte in data:
                    if byte == 0x00:
                        if buf:
                            self._process_frame(bytes(buf))
                            buf.clear()
                    else:
                        buf.append(byte)
