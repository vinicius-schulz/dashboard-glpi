FROM python:3.10-slim

# Non-root, minimal python runtime for the GLPI dashboard
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV MPLBACKEND=Agg

# Create app user (distribution dependent - works on Debian based images)
RUN useradd --create-home --shell /bin/bash appuser || adduser --disabled-password --gecos "" appuser

WORKDIR /app

# Install OS-level deps that help with common Python packages (kept minimal)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates \
       gcc \
       libssl-dev \
       libffi-dev \
       build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps. Copy requirements first to leverage Docker cache.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy application sources
COPY . /app

# Ensure non-root ownership
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
ENV PORT=8000
ENV FLASK_ENV=production

# Default command: run the Flask server. Override at runtime if needed.
CMD ["python", "server.py"]
