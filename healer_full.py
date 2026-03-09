# healer.py

import logging

log = logging.getLogger("Healer")

class Healer:
    def heal(self):
        log.debug("[Healer] Healing action performed")

if __name__ == "__main__":
    print('Running healer_full.py')
