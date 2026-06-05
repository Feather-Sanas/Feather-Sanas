# The Sanas Remote SDK ships as an Ubuntu 22.04 x86-64 native package.
# On Apple Silicon, Docker runs this under emulation (platform pinned below).
# Build context is the project root (san-consultant/). See docker-compose.yml.
FROM --platform=linux/amd64 ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 python3-pip python3.10-venv \
        ffmpeg ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app/server

# Python deps for the orchestrator
COPY server/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# --- Install the Sanas Remote SDK from the tarball you provide ---------------
# Drop your tarball into server/vendor/ before building, e.g.:
#   server/vendor/sanas_remote_sdk_linux_x86-64_<version>.tar.gz
COPY server/vendor/ /tmp/vendor/
RUN set -e; \
    TARBALL="$(ls /tmp/vendor/sanas_remote_sdk_*.tar.gz 2>/dev/null | head -n1 || true)"; \
    if [ -n "$TARBALL" ]; then \
        echo "Installing Sanas SDK from $TARBALL"; \
        mkdir -p /tmp/sdk && tar -zxvf "$TARBALL" -C /tmp/sdk; \
        SDKDIR="$(find /tmp/sdk -maxdepth 1 -mindepth 1 -type d | head -n1)"; \
        cd "$SDKDIR" && chmod +x install.sh && ./install.sh; \
        pip3 install --no-cache-dir ./sanas_remote_sdk 2>/dev/null || true; \
    else \
        echo "No SDK tarball in server/vendor/ — running in MOCK mode."; \
    fi

# Backend source (kept OUT of the web root so it isn't served over HTTP)
COPY server/main.py server/sanas_client.py ./

# Front-end into a dedicated, publicly-served directory
COPY index.html styles.css app.js /app/web/
ENV WEB_DIR=/app/web

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
