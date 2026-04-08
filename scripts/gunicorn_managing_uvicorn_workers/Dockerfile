# --------- Builder Stage ---------
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

# Set environment variables for uv
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies first (for better layer caching)
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

# Copy the project source code
COPY . /app

# Install the project in non-editable mode
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

# --------- Final Stage ---------
FROM python:3.11-slim-bookworm

# Add metadata labels
LABEL maintainer="Benav Labs <contact@benav.io>"
LABEL description="FastAPI application - Staging with Gunicorn managing Uvicorn workers"

# Create a non-root user for security
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --shell /bin/bash --create-home app

# Copy the virtual environment from the builder stage
COPY --from=builder --chown=app:app /app/.venv /app/.venv

# Copy only necessary application files
COPY --chown=app:app src /app/src
COPY --chown=app:app pyproject.toml uv.lock /app/
COPY --chown=app:app alembic.ini /app/

# Ensure the virtual environment is in the PATH
ENV PATH="/app/.venv/bin:$PATH"

# Switch to the non-root user
USER app

# Set the working directory
WORKDIR /app

# Expose the port
EXPOSE 8000

# Health check (uses python since curl is not installed in slim images)
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"]

# Signal handling for graceful shutdown
STOPSIGNAL SIGTERM

# Start the application with Gunicorn managing Uvicorn workers
CMD ["gunicorn", "src.app.main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000"]
