import os
import threading
import logging

import serial

logger = logging.getLogger(__name__)

_GPS_BAUD = 4800
_RECONNECT_INTERVAL = 5.0
_CANDIDATES = ['/dev/ttyACM0', '/dev/ttyUSB0', '/dev/ttyACM1', '/dev/ttyUSB1']


def _parse_nmea_coord(value: str, direction: str):
    """Parse NMEA DDDMM.MMMM + N/S/E/W into decimal degrees, or None on error."""
    if not value or not direction:
        return None
    try:
        dot = value.index('.')
        deg_digits = dot - 2
        degrees = float(value[:deg_digits])
        minutes = float(value[deg_digits:])
        result = degrees + minutes / 60.0
        if direction in ('S', 'W'):
            result = -result
        return result
    except (ValueError, IndexError):
        return None


def _process_sentence(sentence: str, transport) -> None:
    """Parse one NMEA RMC sentence and update transport state if valid fix."""
    if not sentence.startswith('$'):
        return
    # Strip checksum before splitting
    parts = sentence.split('*')[0].split(',')
    if len(parts) < 7:
        return
    # Accept $GPRMC and $GNRMC (multi-constellation)
    if not parts[0].endswith('RMC'):
        return
    if parts[2] != 'A':  # A=valid fix, V=void
        return
    lat = _parse_nmea_coord(parts[3], parts[4])
    lon = _parse_nmea_coord(parts[5], parts[6])
    if lat is None or lon is None:
        return
    with transport._lock:
        transport.gps_lat = lat
        transport.gps_lon = lon
        if transport.location_source == 'gps':
            transport.lat = lat
            transport.lon = lon


class GpsReceiver(threading.Thread):
    """Reads NMEA sentences from a USB GPS receiver and updates transport location."""

    def __init__(self, transport):
        super().__init__(name='GpsReceiver', daemon=True)
        self._transport = transport
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def _find_port(self):
        for path in _CANDIDATES:
            if os.path.exists(path):
                return path
        return None

    def run(self):
        while not self._stop_event.is_set():
            port_path = self._find_port()
            if not port_path:
                with self._transport._lock:
                    self._transport.gps_connected = False
                self._stop_event.wait(_RECONNECT_INTERVAL)
                continue

            try:
                with serial.Serial(port_path, _GPS_BAUD, timeout=2.0) as port:
                    logger.info("GPS receiver connected on %s", port_path)
                    with self._transport._lock:
                        self._transport.gps_connected = True

                    while not self._stop_event.is_set():
                        try:
                            raw = port.readline()
                        except serial.SerialException:
                            break
                        if not raw:
                            continue
                        try:
                            line = raw.decode('ascii', errors='replace').strip()
                        except Exception:
                            continue
                        _process_sentence(line, self._transport)

            except serial.SerialException as exc:
                logger.warning("GPS serial error on %s: %s", port_path, exc)
            except Exception:
                logger.exception("GPS receiver unexpected error")
            finally:
                with self._transport._lock:
                    self._transport.gps_connected = False
                logger.info("GPS receiver disconnected")

            self._stop_event.wait(_RECONNECT_INTERVAL)
