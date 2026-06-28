import os
import sys
from pathlib import Path

from modules.runtime_bootstrap import bootstrap_runtime_environment


def test_bootstrap_runtime_environment_is_idempotent(tmp_path):
    repo_root = Path(__file__).resolve().parent
    original_cwd = os.getcwd()

    try:
        os.chdir(tmp_path)
        resolved_root = bootstrap_runtime_environment(__file__)

        assert resolved_root == repo_root
        assert os.getcwd() == str(repo_root)
        assert str(repo_root) in sys.path
        assert str(repo_root.parent) in sys.path
    finally:
        os.chdir(original_cwd)
