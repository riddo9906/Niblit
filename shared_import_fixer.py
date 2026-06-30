from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


class _RepoSharedFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'shared':
            candidate = REPO_ROOT / 'shared' / '__init__.py'
            if not candidate.exists():
                return None
            return importlib.util.spec_from_file_location(
                fullname,
                candidate,
                submodule_search_locations=[str(candidate.parent)],
            )
        if fullname.startswith('shared.'):
            module_name = fullname.split('.', 1)[1]
            candidate = REPO_ROOT / 'shared' / f'{module_name}.py'
            package_candidate = REPO_ROOT / 'shared' / module_name / '__init__.py'
            if candidate.exists():
                return importlib.util.spec_from_file_location(fullname, candidate)
            if package_candidate.exists():
                return importlib.util.spec_from_file_location(
                    fullname,
                    package_candidate,
                    submodule_search_locations=[str(package_candidate.parent)],
                )
        return None


sys.meta_path.insert(0, _RepoSharedFinder())
