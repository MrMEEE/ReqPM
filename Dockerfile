FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    git \
    libmariadb-dev \
    pkg-config \
    createrepo-c \
    rpm \
    rpmbuild \
    mock \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements
COPY requirements.txt requirements-dev.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p data/git_cache data/builds data/repositories logs

# Collect static files
RUN python manage.py collectstatic --noinput || true

# Create non-root user
RUN useradd -m -u 1000 reqpm && \
    chown -R reqpm:reqpm /app

USER reqpm

# Expose port
EXPOSE 8000

# Default command
CMD ["gunicorn", "backend.reqpm.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4"]
