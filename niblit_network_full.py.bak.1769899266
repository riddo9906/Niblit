# niblit_network.py

import random, logging

log = logging.getLogger("NiblitNetwork")

class NiblitNetwork:
    def __init__(self):
        log.info("Network module initialized")

    def get_weather(self):
        # Randomized placeholder weather
        data = {
            "temp": round(20 + random.uniform(-5,5),1),
            "humidity": random.randint(40,80),
            "condition": random.choice(["Sunny","Cloudy","Rainy","Windy"])
        }
        log.debug(f"[Weather Data] {data}")
        return data

    def shutdown(self):
        log.info("Network module shutdown")