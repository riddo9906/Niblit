"""
Root-level wrapper for SelfResearcher.
Allows `import SelfResearcher` and `importlib.import_module('SelfResearcher')` to work,
which is required by live_updater and other dynamic import paths.
"""
from modules.self_researcher import SelfResearcher  # noqa: F401

__all__ = ["SelfResearcher"]

if __name__ == "__main__":
    print("SelfResearcher module loaded OK")
