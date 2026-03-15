import logging

def slice_guard(value, context="UNKNOWN"):
    """
    Ensures no function unexpectedly returns a slice object.
    - value: Return value to check.
    - context: (optional) Where/why you're calling this.
    """
    if isinstance(value, slice):
        logging.error(f"SLICE GUARD TRIGGERED: received slice object in {context}: {value}")
        raise RuntimeError(f"Unexpected slice object returned in {context}: {value}")
    return value

