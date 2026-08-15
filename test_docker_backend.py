import unittest
from unittest.mock import MagicMock, patch
import json
import os

class TestDockerBackendExists(unittest.TestCase):
    def test_module_importable(self):
        from modules.docker_backend import DockerBackend, DockerModelInfo, BackendFallbackCoordinator
        self.assertTrue(True)

if __name__ == '__main__':
    unittest.main()
