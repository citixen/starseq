import threading
import logging
import mido

logger = logging.getLogger(__name__)


class MIDIOutput:
    def __init__(self):
        self._port = None
        self._lock = threading.Lock()

    def open(self, device_name: str = "") -> bool:
        with self._lock:
            try:
                if self._port:
                    self._port.close()
                    self._port = None
                if device_name:
                    self._port = mido.open_output(device_name)
                    logger.info("Opened MIDI output: %s", device_name)
                else:
                    names = mido.get_output_names()
                    if names:
                        self._port = mido.open_output(names[0])
                        logger.info("Opened MIDI output: %s", names[0])
                    else:
                        logger.warning("No MIDI output devices found")
                        return False
                return True
            except Exception as e:
                logger.error("Failed to open MIDI output '%s': %s", device_name, e)
                self._port = None
                return False

    def send(self, msg: mido.Message):
        with self._lock:
            if self._port:
                try:
                    self._port.send(msg)
                except Exception as e:
                    logger.error("MIDI send error: %s", e)

    def send_note_on(self, channel: int, note: int, velocity: int):
        self.send(
            mido.Message("note_on", channel=channel - 1, note=note, velocity=velocity)
        )

    def send_note_off(self, channel: int, note: int):
        self.send(mido.Message("note_off", channel=channel - 1, note=note, velocity=0))

    def send_all_notes_off(self, channel: int):
        self.send(
            mido.Message("control_change", channel=channel - 1, control=123, value=0)
        )

    def send_clock(self):
        self.send(mido.Message("clock"))

    def send_start(self):
        self.send(mido.Message("start"))

    def send_stop(self):
        self.send(mido.Message("stop"))

    @staticmethod
    def get_output_names() -> list:
        try:
            return mido.get_output_names()
        except Exception:
            return []

    def close(self):
        with self._lock:
            if self._port:
                self._port.close()
                self._port = None
