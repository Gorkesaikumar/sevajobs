FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements/ requirements/
RUN pip install --upgrade pip && pip install -r requirements/production.txt

# Copy project
COPY . .

# Create necessary directories and non-root user
RUN mkdir -p /app/logs /app/media /app/staticfiles && \
    addgroup --system appgroup && \
    adduser --system --group appuser && \
    chown -R appuser:appgroup /app

# Ensure entrypoint script is executable
RUN chmod +x /app/entrypoint.sh

# Switch to non-root user
USER appuser

EXPOSE ${PORT}

# Run entrypoint script
ENTRYPOINT ["/app/entrypoint.sh"]