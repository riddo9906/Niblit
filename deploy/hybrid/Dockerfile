# The build script verifies this local immutable base image ID before building.
# It reuses the installed pinned portal dependencies; no GPU/model/download.
ARG SOURCE_DATE_EPOCH=1794441600
ARG BASE_IMAGE=niblit-client-cloud-portal:runtime-base-20261112
FROM ${BASE_IMAGE}
LABEL org.opencontainers.image.version="2026.11.12-hybrid1"
COPY modules/__init__.py modules/server_manager.py modules/portal_workspaces.py modules/portal_model.py modules/portal_tools.py modules/portal_learning.py modules/portal_remote.py modules/task_admission.py /app/modules/
COPY assets/client-portal/ /app/assets/client-portal/
COPY scripts/run-client-portal.py scripts/backup-client-portal.py /app/scripts/
COPY deploy/hybrid/contracts.json /app/contracts.json
USER niblit
CMD ["python","scripts/run-client-portal.py","--host","0.0.0.0"]
