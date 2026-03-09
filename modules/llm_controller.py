#!/usr/bin/env python3
import logging

log = logging.getLogger("LLMController")
logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(name)s][%(levelname)s] %(message)s')

class LLMController:
    """
    Central controller for HFBrain / LLM toggle.
    """
    def __init__(self, hf_brain=None):
        self.enabled = True
        self.hf_brain = hf_brain

    def toggle(self, state: bool):
        self.enabled = state
        if self.hf_brain:
            if state:
                safe_call(self.hf_brain.enable)
                log.info("[LLMController] HFBrain enabled")
            else:
                safe_call(self.hf_brain.disable)
                log.info("[LLMController] HFBrain disabled")
        log.info(f"[LLMController] LLM {'enabled' if state else 'disabled'}")

    def call(self, prompt, **kwargs):
        """
        Safe LLM call. Returns None if disabled.
        """
        if not self.enabled:
            log.info("[LLMController] LLM disabled, skipping inference call")
            return None
        if not self.hf_brain:
            log.warning("[LLMController] No HFBrain provider available")
            return None
        try:
            return self.hf_brain.ask_single(prompt)
        except Exception as e:
            log.error(f"[LLMController] LLM call failed: {e}")
            return None

# Helper to safely call functions
def safe_call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as e:
        log.debug(f"safe_call failure: {fn} -> {e}")
        return None
if __name__ == "__main__":
    print('Running llm_controller.py')
