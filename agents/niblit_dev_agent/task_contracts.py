#!/usr/bin/env python3
"""Task contracts for NiblitDevAgent runtime integration."""

DEV_AGENT_TASK_TYPE = "dev_agent_inspect"

CLI_STATUS = "status"
CLI_RUNTIME = "runtime"
CLI_PROVIDERS = "providers"
CLI_ARCHITECTURE = "architecture"

VALID_CLI_ACTIONS = {
    CLI_STATUS,
    CLI_RUNTIME,
    CLI_PROVIDERS,
    CLI_ARCHITECTURE,
}
