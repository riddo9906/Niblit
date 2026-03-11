#!/usr/bin/env python3
"""
Workspace Initialization for Niblit

Initializes project workspace with directory structure, configuration,
and validation for the Niblit AI system.

Features:
- Creates project directory structure
- Initializes configuration files
- Sets up logging
- Validates environment
- Production-ready error handling
"""

import os
import sys
import logging
import json
from pathlib import Path
from typing import Optional, Dict, Any

log = logging.getLogger("WorkspaceInit")
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s][%(name)s][%(levelname)s] %(message)s'
)


class WorkspaceInitializer:
    """Initialize Niblit workspace with production structure."""

    # Default directory structure
    DIRECTORY_STRUCTURE = {
        "ProjectOne": {
            "data": ["memory.json", "learning_log.json"],
            "config": ["default.yaml", "production.yaml"],
            "logs": [],
            "cache": [],
            "modules": [],
        }
    }

    def __init__(self, base_path: Optional[str] = None):
        """
        Initialize workspace initializer.

        Args:
            base_path: Base path for workspace (default: current directory)
        """
        self.base_path = Path(base_path) if base_path else Path.cwd()
        self.workspace_path = self.base_path / "ProjectOne"
        self.config = {}
        self.created_dirs = []
        self.created_files = []

    def create_directory_structure(self) -> bool:
        """Create the complete directory structure."""
        try:
            log.info(f"Creating workspace at: {self.workspace_path}")

            # Create base workspace directory
            self.workspace_path.mkdir(parents=True, exist_ok=True)
            self.created_dirs.append(str(self.workspace_path))

            # Create subdirectories
            for subdir in ["data", "config", "logs", "cache", "modules"]:
                dir_path = self.workspace_path / subdir
                dir_path.mkdir(parents=True, exist_ok=True)
                self.created_dirs.append(str(dir_path))
                log.info(f"Created directory: {dir_path}")

            return True
        except Exception as e:
            log.error(f"Failed to create directory structure: {e}")
            return False

    def initialize_config_files(self) -> bool:
        """Initialize configuration files."""
        try:
            log.info("Initializing configuration files...")

            # Default configuration
            default_config = {
                "workspace": {
                    "name": "ProjectOne",
                    "version": "1.0.0",
                    "created_at": str(Path.cwd()),
                },
                "system": {
                    "debug_mode": True,
                    "log_level": "INFO",
                    "enable_orchestrator": True,
                    "enable_background_loops": True,
                },
                "database": {
                    "type": "json",
                    "path": "data/memory.json",
                    "auto_save_interval": 60,
                },
                "improvements": {
                    "enable_all": True,
                    "circuit_breaker": True,
                    "telemetry": True,
                    "rate_limiting": True,
                    "caching": True,
                    "batch_processing": True,
                    "event_sourcing": True,
                },
            }

            # Save to config file
            config_file = self.workspace_path / "config" / "default.yaml"
            with open(config_file, "w") as f:
                json.dump(default_config, f, indent=4)

            self.created_files.append(str(config_file))
            log.info(f"Created configuration: {config_file}")

            # Production config
            prod_config = {**default_config}
            prod_config["system"]["debug_mode"] = False
            prod_config["system"]["log_level"] = "WARNING"

            prod_config_file = self.workspace_path / "config" / "production.yaml"
            with open(prod_config_file, "w") as f:
                json.dump(prod_config, f, indent=4)

            self.created_files.append(str(prod_config_file))
            log.info(f"Created production config: {prod_config_file}")

            self.config = default_config
            return True
        except Exception as e:
            log.error(f"Failed to initialize config files: {e}")
            return False

    def initialize_data_files(self) -> bool:
        """Initialize data files."""
        try:
            log.info("Initializing data files...")

            # Initialize memory.json
            memory_file = self.workspace_path / "data" / "memory.json"
            initial_memory = {
                "facts": [],
                "interactions": [],
                "learning_log": [],
                "preferences": {
                    "mood": "neutral",
                    "verbosity": "medium"
                },
                "events": [],
                "meta": {
                    "created_at": str(Path.cwd()),
                    "version": "1.0.0"
                }
            }

            with open(memory_file, "w") as f:
                json.dump(initial_memory, f, indent=4)

            self.created_files.append(str(memory_file))
            log.info(f"Initialized memory file: {memory_file}")

            # Initialize learning_log.json
            learning_file = self.workspace_path / "data" / "learning_log.json"
            initial_learning = {
                "entries": [],
                "meta": {
                    "created_at": str(Path.cwd()),
                    "version": "1.0.0"
                }
            }

            with open(learning_file, "w") as f:
                json.dump(initial_learning, f, indent=4)

            self.created_files.append(str(learning_file))
            log.info(f"Initialized learning file: {learning_file}")

            return True
        except Exception as e:
            log.error(f"Failed to initialize data files: {e}")
            return False

    def validate_environment(self) -> bool:
        """Validate the initialized environment."""
        try:
            log.info("Validating environment...")

            # Check workspace exists
            if not self.workspace_path.exists():
                log.error(f"Workspace not found: {self.workspace_path}")
                return False

            # Check required directories
            required_dirs = ["data", "config", "logs", "cache", "modules"]
            for req_dir in required_dirs:
                dir_path = self.workspace_path / req_dir
                if not dir_path.exists():
                    log.error(f"Required directory missing: {dir_path}")
                    return False

            # Check required files
            required_files = [
                "config/default.yaml",
                "data/memory.json",
                "data/learning_log.json",
            ]
            for req_file in required_files:
                file_path = self.workspace_path / req_file
                if not file_path.exists():
                    log.warning(f"Expected file not found: {file_path}")

            log.info("Environment validation successful ✓")
            return True
        except Exception as e:
            log.error(f"Environment validation failed: {e}")
            return False

    def print_summary(self):
        """Print initialization summary."""
        print("\n" + "=" * 60)
        print("WORKSPACE INITIALIZATION SUMMARY")
        print("=" * 60)
        print(f"\n✓ Workspace Path: {self.workspace_path}")
        print(f"✓ Base Path: {self.base_path}")
        print(f"\n✓ Created Directories ({len(self.created_dirs)}):")
        for d in self.created_dirs:
            print(f"  - {d}")
        print(f"\n✓ Created Files ({len(self.created_files)}):")
        for f in self.created_files:
            print(f"  - {f}")
        print(f"\n✓ Configuration:")
        for key, value in self.config.get("system", {}).items():
            print(f"  - {key}: {value}")
        print("\n" + "=" * 60)
        print("Workspace ready for Niblit AI system!")
        print("=" * 60 + "\n")

    def initialize(self) -> bool:
        """
        Run complete initialization.

        Returns:
            True if successful, False otherwise
        """
        try:
            steps = [
                ("Creating directory structure", self.create_directory_structure),
                ("Initializing configuration", self.initialize_config_files),
                ("Initializing data files", self.initialize_data_files),
                ("Validating environment", self.validate_environment),
            ]

            for step_name, step_func in steps:
                print(f"\n[→] {step_name}...")
                if not step_func():
                    print(f"[✗] {step_name} FAILED")
                    return False
                print(f"[✓] {step_name} successful")

            self.print_summary()
            return True
        except Exception as e:
            log.error(f"Initialization failed: {e}", exc_info=True)
            return False


def init_workspace(base_path: Optional[str] = None) -> bool:
    """
    Initialize workspace for Niblit.

    Args:
        base_path: Base path for workspace (default: current directory)

    Returns:
        True if successful
    """
    initializer = WorkspaceInitializer(base_path)
    return initializer.initialize()


if __name__ == "__main__":
    # Support command-line argument for custom base path
    base_path = sys.argv[1] if len(sys.argv) > 1 else None

    success = init_workspace(base_path)
    sys.exit(0 if success else 1)
