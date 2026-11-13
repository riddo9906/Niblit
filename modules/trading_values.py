"""Finite risk values shared by Core and its lightweight broker translator."""
import math


def number(value, name, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or (positive and value <= 0):
        raise ValueError('Unverified numeric ' + name)
    return float(value)
