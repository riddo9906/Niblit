# generator.py

import logging, random

log = logging.getLogger("Generator")

class Generator:
    def generate_text(self, prompt):
        result = f"Generated response for: {prompt}"
        log.debug(f"[Generator] {result}")
        return result

if __name__ == "__main__":
    print('Running generator_full.py')
