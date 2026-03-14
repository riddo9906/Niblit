"""
Root-level wrapper for SLSAGenerator.
Allows `import SLSAGenerator` and `importlib.import_module('SLSAGenerator')` to work,
which is required by live_updater and other dynamic import paths.
"""
try:
    from slsa_generator_full import SLSAGenerator  # noqa: F401
except Exception:
    from modules.slsa_generator import SLSAGenerator  # noqa: F401

__all__ = ["SLSAGenerator"]

if __name__ == "__main__":
    print("SLSAGenerator module loaded OK")
