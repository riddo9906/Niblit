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
    print('Running niblit_voice_full.py')
