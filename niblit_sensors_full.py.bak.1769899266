# niblit_sensors.py – fully updated, silent logging

import threading, time, random, logging

log = logging.getLogger("NiblitSensors")

SENSOR_STATUS = {'gps': None, 'camera': False, 'microphone': False, 'last_update': None}

class NiblitSensors:
    def __init__(self):
        log.info("Initializing sensors...")
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def read_sensors(self):
        """Simulate reading sensors."""
        lat = -33.93 + random.uniform(-0.01, 0.01)
        lon = 18.42 + random.uniform(-0.01, 0.01)
        with self._lock:
            SENSOR_STATUS['gps'] = {'lat': round(lat,4), 'lon': round(lon,4)}
            SENSOR_STATUS['camera'] = False
            SENSOR_STATUS['microphone'] = False
            SENSOR_STATUS['last_update'] = time.strftime('%Y-%m-%d %H:%M:%S')
        log.debug(f"[Sensors Updated] {SENSOR_STATUS}")

    def update(self):
        """Public update cycle."""
        try:
            self.read_sensors()
        except Exception as e:
            log.debug(f"[Sensor Update Error] {e}")

    def _monitor_loop(self):
        """Background automatic update loop."""
        while True:
            self.update()
            time.sleep(30)