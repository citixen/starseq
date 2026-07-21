import sys
import os
import queue
import logging
import argparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(threadName)-18s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)

# Ensure the project root is on sys.path so all packages resolve correctly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    parser = argparse.ArgumentParser(
        description="starseq — star-position-driven MIDI step sequencer",
    )
    parser.add_argument(
        "--no-gpio",
        action="store_true",
        help="Disable GPIO input handler; use keyboard shortcuts instead",
    )
    parser.add_argument(
        "--no-serial",
        action="store_true",
        help="Disable serial RX; all tracks start in mono mode with built-in defaults",
    )
    parser.add_argument(
        "--resolution",
        metavar="WxH",
        help="Force a specific window size for testing, e.g. 800x480 or 1920x1080",
    )
    parser.add_argument(
        "--rotation",
        type=int,
        choices=[0, 90, 180, 270],
        default=0,
        help="Display rotation in degrees clockwise (90/270 use stacked portrait layout)",
    )
    parser.add_argument(
        "--midi-channels",
        default="1 2 3 4 5 6 7 8",
        metavar="'1 2 3 4 5 6 7 8'",
        help="MIDI output channel per track (space-separated, 8 values from 1–16)",
    )
    args = parser.parse_args()

    resolution = None
    if args.resolution:
        try:
            w_str, h_str = args.resolution.lower().split("x")
            resolution = (int(w_str), int(h_str))
        except (ValueError, AttributeError):
            print("Error: --resolution must be in WxH format, e.g. 1280x720")
            sys.exit(1)

    try:
        launch_channels = [int(x) for x in args.midi_channels.split()]
        if len(launch_channels) != 8 or not all(1 <= c <= 16 for c in launch_channels):
            raise ValueError
    except ValueError:
        print("Error: --midi-channels must be 8 values from 1–16, e.g. '1 2 3 4 5 6 7 8'")
        sys.exit(1)

    import config
    from transport.state import TransportState, SCALE_NAMES
    from tracks.state import TrackStateStore
    from sky.time_sim import SimulatedClock
    from sky.engine import SkyEngine
    from sky.constellations import load_constellation_lines
    from tracks.builder import SequenceBuilder
    from sequencer.midi_output import MIDIOutput
    from sequencer.engine import SequencerEngine
    from sequencer.midi_clock_input import MidiClockInput
    from serial_rx.receiver import SerialRXThread
    from display.renderer import DisplayRenderer
    from input.handler import InputHandler, InputEvent
    from menu_state import MenuState
    from gps.receiver import GpsReceiver

    base_dir = os.path.dirname(os.path.abspath(__file__))
    catalogue_path = os.path.join(base_dir, config.CATALOGUE_PATH)
    ephemeris_path = os.path.join(base_dir, config.EPHEMERIS_PATH)
    constellation_lines_path = os.path.join(base_dir, config.CONSTELLATION_LINES_PATH)
    try:
        constellation_lines = load_constellation_lines(constellation_lines_path)
        logger.info("Loaded constellation lines for %d constellations", len(constellation_lines))
    except OSError as exc:
        logger.warning("Could not load constellation lines (%s); overlay will be empty", exc)
        constellation_lines = {}

    # --- State ---
    transport = TransportState()
    transport.launch_channels = launch_channels
    track_store = TrackStateStore(8)
    for i, ch in enumerate(launch_channels):
        track_store[i].midi_channel = ch
    sim_clock = SimulatedClock()
    menu_state = MenuState()

    # --- Queues ---
    sky_queue = queue.Queue(maxsize=1)  # SkyEngine → SequenceBuilder
    flash_events = queue.Queue(maxsize=200)  # SequencerEngine → DisplayRenderer
    input_queue = queue.Queue(maxsize=50)  # InputHandler → main loop
    ext_clock_queue = queue.Queue(maxsize=10)  # external MIDI clock → SequencerEngine

    # --- MIDI ---
    midi_out = MIDIOutput()
    available = MIDIOutput.get_output_names()
    if available:
        transport.midi_device = available[0]
        midi_out.open(transport.midi_device)
    else:
        logger.warning("No MIDI output devices found; MIDI output disabled")
    menu_state.midi_devices = available

    # --- Apply defaults when serial is disabled ---
    if args.no_serial:
        _apply_demo_defaults(track_store)
        logger.info("Serial disabled — all tracks set to mono with built-in defaults")
    if args.no_gpio:
        logger.info(
            "GPIO disabled — keyboard shortcuts active "
            "(P=play/stop  R=reset clock  Space=menu  arrows=navigate/adjust)"
        )

    # --- Create threads ---
    input_handler = InputHandler(input_queue)
    serial_rx = SerialRXThread(config.SERIAL_PORT, track_store, config.SERIAL_BAUD, transport)
    sky_engine = SkyEngine(sim_clock, sky_queue, catalogue_path, ephemeris_path, transport=transport)
    seq_builder = SequenceBuilder(track_store, transport, sky_queue)
    input_callback = lambda ev: _handle_input(
        ev, transport, sim_clock, midi_out, track_store, menu_state
    )
    display = DisplayRenderer(
        transport,
        track_store,
        sky_engine,
        flash_events,
        menu_state=menu_state,
        input_queue=input_queue,
        resolution=resolution,
        sim_clock=sim_clock,
        input_callback=input_callback,
        rotation=args.rotation,
        constellation_lines=constellation_lines,
    )
    seq_engine = SequencerEngine(track_store, transport, midi_out, ext_clock_queue)
    seq_engine.flash_events = flash_events
    midi_clock_in = MidiClockInput(transport, ext_clock_queue)
    gps_receiver = GpsReceiver(transport)

    # --- Start background threads ---
    logger.info("Starting starseq...")
    started = []

    if not args.no_gpio:
        input_handler.start()
        started.append(input_handler)

    if not args.no_serial:
        serial_rx.start()
        started.append(serial_rx)

    for t in (sky_engine, seq_builder, seq_engine, midi_clock_in, gps_receiver):
        t.start()
        started.append(t)

    logger.info("Running. Press Ctrl-C to quit.")

    # pygame must run on the main thread on Linux/RPi — call run() directly
    try:
        display.run()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt — shutting down")

    _shutdown(started, midi_out)


def _handle_input(event, transport, sim_clock, midi_out, track_store, menu_state):
    """Dispatch input events to transport/menu state changes."""
    if event.type == "double_press":
        for track in track_store.tracks:
            with track._lock:
                track.step_index = 0
                track.tick_accumulator = 0
        logger.info("All sequences reset to step 1")

    elif event.type == "long_press":
        sim_clock.reset()
        logger.info("Simulated clock reset to current UTC")

    elif event.type == "play_stop":
        with transport._lock:
            transport.playing = event.value
        if event.value:
            midi_out.send_start()
        else:
            midi_out.send_stop()
            for i in range(1, 9):
                midi_out.send_all_notes_off(i)

    elif event.type == "toggle_play":
        with transport._lock:
            playing = not transport.playing
            transport.playing = playing
        if playing:
            midi_out.send_start()
        else:
            midi_out.send_stop()
            for i in range(1, 9):
                midi_out.send_all_notes_off(i)

    elif event.type == "press":
        menu_state.refresh_midi_devices(midi_out)
        menu_state.press(sim_clock)

    elif event.type == "nav":
        menu_state.navigate(event.value, transport)

    elif event.type == "rotate":
        if menu_state.in_edit_mode:
            menu_state.adjust(event.value, transport, sim_clock, midi_out, track_store)
        else:
            menu_state.navigate(event.value, transport)


def _apply_demo_defaults(track_store) -> None:
    """Set all tracks to playable mono mode for --no-serial operation."""
    for track in track_store.tracks:
        with track._lock:
            track.mode = 2  # mono
            track.play_mode = 6
            track.note_range = 12
            track.interface_status = 1  # online — no stale/offline indicator
            track.sequence_dirty = True


def _shutdown(started: list, midi_out) -> None:
    logger.info("Sending all-notes-off and shutting down threads...")
    for t in started:
        t.stop()
    for ch in range(1, 17):
        midi_out.send_all_notes_off(ch)
    midi_out.close()
    for t in started:
        t.join(timeout=2.0)
    logger.info("Goodbye.")


if __name__ == "__main__":
    main()
