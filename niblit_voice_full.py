# niblit_voice.py

import logging

log = logging.getLogger("NiblitVoice")

class NiblitVoice:
    def __init__(self):
        self.plyer_enabled = False
        log.info(f"Niblit Voice initialized (plyer:{self.plyer_enabled})")

    def speak(self, text):
        try:
            # Placeholder: real TTS integration here
            log.debug(f"[Voice] {text}")
        except Exception as e:
            log.debug(f"[Voice Error] {e}")

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("=== NiblitVoice self-test ===")
    v = NiblitVoice()
    v.speak("Hello, I am Niblit.")
    v.speak("Voice module is operational.")
    print("NiblitVoice OK")
