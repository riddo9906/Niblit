---
name: docker-operations
description: Inspect and manage Docker Desktop containers, images and Compose projects using governed Docker tools.
---
# Docker operations

Use Docker Desktop tools for container and Compose work.

1. Inspect daemon health, containers, images and Compose projects before proposing changes.
2. Prefer safe metadata inspection. Container environment variables and secret mounts must not be printed.
3. Container creation, start/stop, log access and Compose up/down are approval-gated. Show the exact target and operation before approval.
4. For Compose, verify the project directory and Compose file. Compose down affects the whole project; do not imply it targets one service.
5. Never add privileged mode, host mounts, host networking or secret environment values unless the user specifically requests and approves them.
6. After an approved operation, inspect container state and report the actual result.
7. Do not delete volumes or images unless the user explicitly requests that destructive action.
