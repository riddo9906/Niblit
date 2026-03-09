# membrane.py

import logging

log = logging.getLogger("Membrane")

class Membrane:
    def __init__(self):
        log.info("[Membrane] Device abstraction initialized")

if __name__ == "__main__":
    print('Running membrane_full.py')
