FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# tzdata so the scheduler's "local time" honours TZ (e.g. Africa/Nairobi)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root; uid 1000 matches a typical host user so the ./data bind mount is writable
RUN useradd -m -u 1000 app && mkdir -p /data && chown -R app /app /data
USER app

EXPOSE 5000

# Default command runs the web UI; the scheduler service overrides this.
CMD ["gunicorn", "--workers", "2", "--bind", "0.0.0.0:5000", "webapp:app"]
