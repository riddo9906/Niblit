---
name: niblit-maintenance
description: Diagnose and maintain Niblit's Core, GGUF Cloud, UI, MCP bridge, memory, runtime and packaging.
---
# Niblit maintenance

Use this skill for Niblit-specific diagnosis, upgrades and release work.

- Identify the exact Core, Cloud and UI versions, process paths, ports and model inventory.
- Inspect health endpoints and recent logs before restarting anything.
- Preserve active installations, worktrees, user data, model files, memory databases and configuration.
- Keep Core as the authority for tool registration, policy, permissions, audit and execution. GGUF models propose actions; they do not execute them.
- Verify MCP server connections, tool counts, availability and authorization metadata.
- Test actual inference and tool execution, not just imports or mocked calls.
- For packaging, build into a fresh candidate directory, record hashes and run packaged acceptance before promotion.
- Keep trading execution disabled unless the user explicitly authorizes a separate governed workflow.
