import logging

log = logging.getLogger("SafeLoader")

def safe_call(obj, *args, **kwargs):
    """
    Safely call a class or function.
    Returns None instead of crashing.
    """
    try:
        if obj is None:
            return None

        # if it's a class → instantiate it
        if isinstance(obj, type):
            return obj(*args, **kwargs)

        # if callable → call it
        if callable(obj):
            return obj(*args, **kwargs)

        # otherwise return object itself
        return obj

    except Exception as e:
        log.warning(f"[safe_call ERROR] {e}")
        return None
if __name__ == "__main__":
    print('Running safe_loader.py')
