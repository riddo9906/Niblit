# membrane.py

import logging

log = logging.getLogger("Membrane")

class Membrane:
    def __init__(self):
        log.info("[Membrane] Device abstraction initialized")

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("=== Membrane self-test ===")
    m = Membrane()
    print(f"Membrane instance: {m}")
    print("Membrane OK")
