---
name: software-engineering
description: Plan, inspect, implement, test and verify changes in Niblit or another local software repository.
---
# Software engineering

Use this skill when the user asks to build, debug, refactor, test or review software.

1. Identify the repository and active branch. Before editing, inspect Git status, the current diff and relevant files. Preserve all existing user changes.
2. Build a short implementation plan from the actual code paths. Prefer integrated changes over placeholder modules or isolated stubs.
3. Use Core workspace tools for scoped source edits and tests. Use Desktop Commander for broader desktop operations and Git MCP for status, history and safe diffs.
4. Do not run destructive Git commands, delete files, reset, clean, stash, commit or push unless the user explicitly requests that exact operation. Mutating tools still require one-time approval.
5. Keep secrets out of tool calls and output. Never inspect .env, credential stores, private keys or tokens.
6. Add or update focused tests for behavior changes. Run the narrow suite first, then relevant broader tests.
7. Verify the actual resulting files, runtime behavior and test output. Do not report a build or test as passing unless its exit status and result were observed.
8. At handoff, list changed components, tests, known failures and the next unfinished task.
