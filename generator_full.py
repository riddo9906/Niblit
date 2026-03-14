# generator.py

import logging, random

log = logging.getLogger("Generator")

class Generator:
    def generate_text(self, prompt):
        result = f"Generated response for: {prompt}"
        log.debug(f"[Generator] {result}")
        return result

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("=== Generator self-test ===")
    g = Generator()
    out = g.generate_text("Tell me about Python")
    print(f"Output: {out}")
    print("Generator OK")
