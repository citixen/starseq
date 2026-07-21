import threading
import queue
import logging
import mido

logger = logging.getLogger(__name__)


def _find_input_port(device_name: str) -> str | None:
    """Return a MIDI input port name that best matches the given output device name."""
    try:
        inputs = mido.get_input_names()
    except Exception:
        return None
    if not inputs:
        return None
    if device_name in inputs:
        return device_name
    # ALSA port names often share a common prefix before the port number —
    # match on the part before the first digit run at the end.
    base = device_name.split(':')[0].strip()
    for name in inputs:
        if name.startswith(base):
            return name
    # Last resort: first available input
    return inputs[0]


class MidiClockInput(threading.Thread):
    """Reads MIDI clock/start/stop/continue from an input port and forwards
    them to ext_clock_queue for the sequencer engine."""

    def __init__(self, transport, ext_clock_queue: queue.Queue):
        super().__init__(name='MidiClockIn', daemon=True)
        self._transport = transport
        self._queue = ext_clock_queue
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        port = None
        active_device = None

        while not self._stop_event.is_set():
            with self._transport._lock:
                source = self._transport.clock_source
                device = self._transport.midi_device

            # Close port if clock source switched to internal or device changed
            if port is not None and (source != 'external' or device != active_device):
                try:
                    port.close()
                except Exception:
                    pass
                port = None
                active_device = None
                logger.info("MIDI clock input closed")

            # Open port when switching to external clock
            if source == 'external' and port is None:
                port_name = _find_input_port(device)
                if port_name:
                    try:
                        port = mido.open_input(port_name)
                        active_device = device
                        logger.info("MIDI clock input opened: %s", port_name)
                    except Exception as exc:
                        logger.error("Cannot open MIDI input '%s': %s", port_name, exc)
                        self._stop_event.wait(1.0)
                        continue
                else:
                    logger.warning("No MIDI input ports found for clock source")
                    self._stop_event.wait(1.0)
                    continue

            if port is None:
                self._stop_event.wait(0.05)
                continue

            for msg in port.iter_pending():
                if msg.type in ('clock', 'start', 'stop', 'continue'):
                    try:
                        self._queue.put_nowait(msg)
                    except queue.Full:
                        pass

            self._stop_event.wait(0.001)
