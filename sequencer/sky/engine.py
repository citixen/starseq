import threading
import time
import queue
import logging
import os
import numpy as np

import config
from sky.catalogue import SkyStar, load_catalogue
from sky.planets import PLANETS, PlanetPosition
from sky.time_sim import SimulatedClock

logger = logging.getLogger(__name__)


class SkyEngine(threading.Thread):
    """Computes visible star positions at the simulated time and publishes snapshots.

    Planet positions are computed on the same cadence but published on a
    separate, independent channel (get_planet_snapshot())
    """

    def __init__(
        self,
        sim_clock: SimulatedClock,
        sky_queue: queue.Queue,
        catalogue_path: str,
        ephemeris_path: str,
        transport=None,
    ):
        super().__init__(name="SkyEngine", daemon=True)
        self._sim_clock = sim_clock
        self._sky_queue = sky_queue
        self._catalogue_path = catalogue_path
        self._ephemeris_path = ephemeris_path
        self._transport = transport
        self._snapshot: list = []
        self._snapshot_lock = threading.Lock()
        self._planet_snapshot: list = []
        self._planet_snapshot_lock = threading.Lock()
        self._stop_event = threading.Event()

    def get_snapshot(self) -> list:
        with self._snapshot_lock:
            return list(self._snapshot)

    def get_planet_snapshot(self) -> list:
        with self._planet_snapshot_lock:
            return list(self._planet_snapshot)

    def stop(self):
        self._stop_event.set()

    def run(self):
        from skyfield.api import Loader, wgs84, Star

        data_dir = os.path.dirname(self._ephemeris_path)
        load = Loader(data_dir, expire=False, verbose=False)
        ts = load.timescale(builtin=True)
        eph = load(os.path.basename(self._ephemeris_path))
        earth = eph["earth"]

        def _build_location(lat, lon):
            return earth + wgs84.latlon(lat, lon, elevation_m=config.LOCATION_ELEV)

        cur_lat = config.LOCATION_LAT
        cur_lon = config.LOCATION_LON
        location = _build_location(cur_lat, cur_lon)

        logger.info("Loading star catalogue from %s", self._catalogue_path)
        raw = load_catalogue(self._catalogue_path)
        hrs = np.array([s[0] for s in raw], dtype=np.int32)
        ra_hours = np.array([s[1] for s in raw], dtype=np.float64)
        dec_degrees = np.array([s[2] for s in raw], dtype=np.float64)
        mags = np.array([s[3] for s in raw], dtype=np.float32)
        bvs = np.array([s[4] for s in raw], dtype=np.float32)
        logger.info("Catalogue loaded: %d stars", len(raw))

        all_stars = Star(ra_hours=ra_hours, dec_degrees=dec_degrees)
        planet_bodies = [
            (name, eph[target], colour) for name, target, colour in PLANETS
        ]
        interval_s = config.SKY_RECALC_INTERVAL_MS / 1000.0

        while not self._stop_event.is_set():
            # Rebuild observer location if transport lat/lon has changed
            if self._transport is not None:
                with self._transport._lock:
                    new_lat = self._transport.lat
                    new_lon = self._transport.lon
                if new_lat != cur_lat or new_lon != cur_lon:
                    cur_lat, cur_lon = new_lat, new_lon
                    location = _build_location(cur_lat, cur_lon)
                    logger.info(
                        "Observer location updated: %.4f, %.4f", cur_lat, cur_lon
                    )

            t_start = time.perf_counter()
            try:
                sim_time = self._sim_clock.now()
                t = ts.from_datetime(sim_time)

                astrometric = location.at(t).observe(all_stars)
                alt_obj, az_obj, _ = astrometric.apparent().altaz()
                alts = np.asarray(alt_obj.degrees, dtype=np.float32)
                azs = np.asarray(az_obj.degrees, dtype=np.float32) % 360.0

                # Filter: above horizon and within naked-eye magnitude limit
                mask = (alts > 0.0) & (mags <= 6.5)
                idx = np.where(mask)[0]

                snapshot = [
                    SkyStar(
                        hr=int(hrs[i]),
                        alt=float(alts[i]),
                        az=float(azs[i]),
                        mag=float(mags[i]),
                        bv=float(bvs[i]),
                    )
                    for i in idx
                ]

                with self._snapshot_lock:
                    self._snapshot = snapshot

                planet_snapshot = []
                for name, body, colour in planet_bodies:
                    p_astrometric = location.at(t).observe(body)
                    p_alt, p_az, _ = p_astrometric.apparent().altaz()
                    if p_alt.degrees > 0.0:
                        planet_snapshot.append(
                            PlanetPosition(
                                name=name,
                                alt=p_alt.degrees,
                                az=p_az.degrees % 360.0,
                                colour=colour,
                            )
                        )
                with self._planet_snapshot_lock:
                    self._planet_snapshot = planet_snapshot

                # Replace queue contents with the latest snapshot
                while not self._sky_queue.empty():
                    try:
                        self._sky_queue.get_nowait()
                    except queue.Empty:
                        break
                try:
                    self._sky_queue.put_nowait(snapshot)
                except queue.Full:
                    pass

            except Exception as exc:
                from skyfield.errors import EphemerisRangeError

                if isinstance(exc, EphemerisRangeError):
                    logger.warning(
                        "Simulated time out of ephemeris range; resetting to now"
                    )
                    self._sim_clock.reset()
                else:
                    logger.exception("Sky engine recalculation error")

            elapsed = time.perf_counter() - t_start
            sleep_time = max(0.0, interval_s - elapsed)
            if sleep_time > 0:
                self._stop_event.wait(sleep_time)
