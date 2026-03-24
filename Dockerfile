# Dockerfile — NOBA Command Center
FROM python:3.13-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl jq lm-sensors iproute2 && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    fastapi 'uvicorn[standard]' psutil pyyaml httpx websocket-client cryptography

WORKDIR /app

# Copy application files (modular structure)
COPY share/noba-web/server.py /app/server.py
COPY share/noba-web/server/ /app/server/
COPY share/noba-web/static/ /app/static/

# Copy agent script (served via /api/agent/update endpoint)
COPY share/noba-agent/agent.py /app/noba-agent/agent.py

# Create data directories and symlink config/data paths into volumes.
# NOBA writes to ~/.config/noba-web/ (users, auth) and ~/.local/share/ (DB).
# With HOME=/app, these become /app/.config/noba-web/ and /app/.local/share/.
# We symlink them into /app/config and /app/data for volume persistence.
RUN mkdir -p /app/config /app/data \
             /app/.config /app/.local && \
    ln -s /app/config /app/.config/noba-web && \
    ln -s /app/config /app/.config/noba && \
    ln -s /app/data   /app/.local/share

# Declare volumes for persistence
VOLUME ["/app/config", "/app/data"]

# Environment
ENV PORT=8080
ENV HOST=0.0.0.0
ENV NOBA_CONFIG=/app/config/config.yaml
ENV HOME=/app

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -sf http://localhost:8080/api/status/public || exit 1

EXPOSE 8080

CMD ["python3", "-u", "/app/server.py"]
