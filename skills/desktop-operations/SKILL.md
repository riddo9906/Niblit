---
name: desktop-operations
description: Safely inspect and operate the local Windows desktop, filesystem, processes and terminal through Desktop Commander.
---
# Desktop operations

Use Desktop Commander when the task needs the user's actual PC rather than only the repository workspace.

- Start with read-only inspection: identify the exact path, process, session or service involved.
- Use file listing, file info, search and read tools before editing.
- For terminal work, prefer explicit PowerShell commands with bounded timeouts and clear working directories.
- Starting processes, writing files, editing blocks, moving files, terminating processes and changing settings require the tool's one-time operator approval.
- Do not stop unrelated processes or replace the active Niblit installation. Confirm process command lines and ownership before stopping anything.
- Do not read secret files or expose command-line credentials. Never print environment-variable values.
- Capture real output and verify the intended effect. If a process is asynchronous, poll its own process/session output rather than assuming completion.
