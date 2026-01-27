#!/bin/bash
# Setup script for ReqPM development environment

set -e

echo "===== ReqPM Development Setup ====="
echo ""

# Check Python version
echo "Checking Python version..."
python3 --version || { echo "Python 3 not found!"; exit 1; }

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    echo "Please edit .env file with your configuration!"
fi

# Create necessary directories
echo "Creating necessary directories..."
mkdir -p data/git_cache
mkdir -p data/builds
mkdir -p data/repositories
mkdir -p logs

# Initialize database
echo "Initializing database..."
python manage.py makemigrations
python manage.py migrate

# Create superuser (optional)
echo ""
read -p "Create superuser? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    python manage.py createsuperuser
fi

echo ""
echo "===== Setup Complete! ====="
echo ""
echo "To start the development server:"
echo "  1. Activate virtual environment: source venv/bin/activate"
echo "  2. Start Redis: redis-server (in another terminal)"
echo "  3. Start Celery worker: celery -A backend.reqpm worker -l info (in another terminal)"
echo "  4. Start Django server: python manage.py runserver"
echo ""
echo "Default URLs:"
echo "  - API: http://localhost:8000/api/"
echo "  - Admin: http://localhost:8000/admin/"
echo ""
