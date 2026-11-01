FROM python:3.12-slim
WORKDIR /app
COPY deploy/client-portal/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home niblit && mkdir /data /backups && chown niblit /data /backups
# Explicit source allowlist excludes local keys, models, memory and build output.
COPY modules/__init__.py modules/server_manager.py modules/portal_workspaces.py modules/portal_model.py modules/portal_tools.py modules/portal_learning.py modules/portal_remote.py modules/task_admission.py /app/modules/
COPY docs/LOCAL_MODEL_TOOLS.md /app/docs/LOCAL_MODEL_TOOLS.md
COPY assets/client-portal/ /app/assets/client-portal/
COPY scripts/run-client-portal.py /app/scripts/run-client-portal.py
COPY scripts/backup-client-portal.py /app/scripts/backup-client-portal.py
ENV NIBLIT_PORTAL_DATA=/data PORT=8768
USER niblit
EXPOSE 8768
CMD ["python","scripts/run-client-portal.py","--host","0.0.0.0"]
