from typing import Tuple

def parse_intent(text: str) -> Tuple[str, dict]:
    t = text.strip().lower()

    if t.startswith("remember "):
        payload = t[len("remember "):].strip()
        if ":" in payload:
            k, v = payload.split(":", 1)
            return "remember", {"key": k.strip(), "value": v.strip()}
        return "bad_remember", {}

    if t in ("time", "what time is it", "current time"):
        return "time", {}

    if "weather" in t:
        return "weather", {}

    if t in ("help", "commands"):
        return "help", {}

    if t in ("status", "health"):
        return "status", {}

    if t in ("shutdown", "exit", "quit"):
        return "shutdown", {}

    if t.startswith("learn about "):
        return "learn", {"topic": t[len("learn about "):].strip()}

    if t.startswith("ideas about "):
        return "ideas", {"topic": t[len("ideas about "):].strip()}

    if t.startswith("toggle-llm "):
        return "toggle_llm", {"state": t[len("toggle-llm "):].strip()}

    if t.startswith("/slsa "):
        return "slsa", {"topic": t[len("/slsa "):].strip()}

    return "chat", {}
if __name__ == "__main__":
    print('Running intent_parser.py')
