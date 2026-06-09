FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/production.txt requirements/production.txt
RUN pip install -r requirements/production.txt

COPY . .

RUN mkdir -p /app/logs /app/media /app/staticfiles

EXPOSE 8000
