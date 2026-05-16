# ============================================================
# RabAiAgent Backend - Multi-stage Dockerfile
# Stage 1: Builder (compiles dependencies)
# Stage 2: Runner (production runtime)
# ============================================================

# ── Stage 1: Builder ────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /app

# Install build dependencies for native libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python deps in a venv
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install build-time only deps (not needed at runtime)
RUN pip install --no-cache-dir build

# Copy application source
COPY app/ ./app/

# ── Stage 2: Runner ─────────────────────────────────────────
FROM python:3.13-slim AS runner

WORKDIR /app

# Create non-root user for security
RUN groupadd --gid 1000 rabai && \
    useradd --uid 1000 --gid rabai --shell /bin/bash --create-home rabai

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi8 \
    libjpeg62-turbo \
    zlib1g \
    tini \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv

# Copy app source
COPY --from=builder /app /app

# Set up environment
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    ENV_FILE=/app/.env

# Create data directories with correct ownership
RUN mkdir -p /app/data /app/data/logs /app/data/user && \
    chown -R rabai:rabai /app

# Switch to non-root user
USER rabai

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python3 -c "
import urllib.request, urllib.error, sys
try:
    r = urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)
    if r.status == 200: sys.exit(0)
except:
    pass
sys.exit(1)"

# Expose port
EXPOSE 8000

# Use tini as init system to reap zombie processes
ENTRYPOINT ["/usr/bin/tini", "--"]

# Default command (override via docker-compose or CLI)
CMD ["python3", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--log-level", "info"]
