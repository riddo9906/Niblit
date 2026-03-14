# healer.py

import logging

log = logging.getLogger("Healer")

class Healer:
    def heal(self):
        log.debug("[Healer] Healing action performed")

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("=== Healer self-test ===")
    h = Healer()
    h.heal()
    print("Healer OK")
