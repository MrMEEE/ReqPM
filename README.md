# ReqPM - Python Requirements to RPM Package Manager

ReqPM is a comprehensive build system for creating RPM packages from Python projects with requirements files. It automates the process of building a Python project and all its dependencies as RPM packages for different RHEL versions.

## Features

- **Git Integration**: Pull Python projects directly from Git repositories
- **Dependency Resolution**: Automatically analyze requirements.txt and build dependency trees
- **Multi-Platform Builds**: Build for different RHEL versions simultaneously
- **Build Queue Management**: Intelligent build scheduling based on dependency order
- **Spec File Management**: Edit and version control spec files
- **Repository Publishing**: Automatic YUM/DNF repository creation and publishing
- **Web Interface**: Modern React UI for monitoring builds and managing projects
- **REST API**: Full API for automation and integration
- **JWT Authentication**: Secure API access with token-based auth

## Architecture

- **Backend**: Django 5.0 + Django REST Framework 3.14
- **Frontend**: React 18 + Vite + Tailwind CSS
- **Task Queue**: Celery with Redis
- **Database**: SQLite (dev) / MariaDB (production)
- **Build System**: Mock (pluggable architecture for other systems)
- **Repository Management**: createrepo_c

## Quick Start

### Prerequisites

- Python 3.9+
- Node.js 18+ (for frontend)
- Redis
- **Mock** (for building RPMs - see [Mock Setup Guide](docs/MOCK_SETUP.md))
- createrepo_c
- Git

### Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd ReqPM

# Backend Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create .env file from example
cp .env.example .env

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Frontend Setup
cd frontend
npm install
cp .env.example .env
cd ..
```

### Setting Up Mock (Required for Building RPMs)

Mock is required for building RPM packages.

**On RHEL/Fedora/CentOS:**
```bash
# Install Mock
sudo dnf install mock

# Add your user to the mock group
sudo usermod -a -G mock $USER

# Log out and log back in for group membership to take effect
```

**On Ubuntu/Debian:**
```bash
# Quick install from pre-built .deb package
./scripts/install-mock-deb.sh

# Or build the .deb package yourself
./scripts/build-mock-deb.sh
sudo dpkg -i build/mock-deb/output/mock_*.deb
sudo apt-get install -f
sudo usermod -a -G mock $USER

# Log out and log back in for group membership to take effect
```

**Important**: Builds will fail until Mock is properly installed and configured.

For detailed setup instructions, see:
- RHEL/Fedora: **[docs/MOCK_SETUP.md](docs/MOCK_SETUP.md)**
- Ubuntu/Debian: **[docs/MOCK_SETUP_UBUNTU.md](docs/MOCK_SETUP_UBUNTU.md)**

### Running the Application

Use the provided control script to manage all services:

```bash
# Start all services (Redis, Django, Celery worker, Celery beat, Frontend)
./reqpm.sh start-all

# Check status
./reqpm.sh status

# View logs
./reqpm.sh logs all          # All services
./reqpm.sh logs frontend     # Frontend only

# Stop all services
./reqpm.sh stop-all

# Restart all services
./reqpm.sh restart-all
```

Or start services individually:

```bash
# Backend services
./reqpm.sh start-redis
./reqpm.sh start-django
./reqpm.sh start-celery
./reqpm.sh start-beat

# Frontend
./reqpm.sh start-frontend
./reqpm.sh stop-frontend
```

The application will be available at:
- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000/api
- **API Documentation**: http://localhost:8000/api/docs/

# Create superuser
python manage.py createsuperuser

# Start development server
python manage.py runserver

# In another terminal, start Celery worker
celery -A reqpm worker -l info

# In another terminal, start Celery beat (for scheduled tasks)
celery -A reqpm beat -l info
```

## Project Structure

```
ReqPM/
├── backend/
│   ├── reqpm/              # Main Django project
│   ├── apps/
│   │   ├── users/          # User management
│   │   ├── projects/       # Project management
│   │   ├── packages/       # Package management
│   │   ├── builds/         # Build management
│   │   └── repositories/   # Repository management
│   ├── plugins/            # Plugin system
│   │   ├── builders/       # Build system plugins (Mock, etc.)
│   │   └── repositories/   # Repository plugins (createrepo_c, etc.)
│   └── core/               # Core utilities
├── frontend/               # React frontend (TBD)
├── docs/                   # Documentation
└── docker/                 # Docker configurations
```

## API Documentation

API documentation will be available at `/api/docs/` when running the server.

## Development

### Running Tests

```bash
python manage.py test
```

### Code Style

```bash
# Format code
black .

# Lint code
flake8 .
pylint backend/
```

## Production Deployment

See [docs/deployment.md](docs/deployment.md) for production deployment instructions.

## Contributing

Contributions are welcome! Please read our contributing guidelines (TBD).

## License

[To be determined]

## Inspired By

- [awx-rpm-v2](https://github.com/MrMEEE/awx-rpm-v2)
- [OpenSUSE Build Service](https://github.com/openSUSE/open-build-service)
- [Mock](https://github.com/rpm-software-management/mock)
