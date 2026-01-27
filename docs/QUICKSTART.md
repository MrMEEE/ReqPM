# 🚀 Quick Start Guide - ReqPM

Get ReqPM up and running in 5 minutes!

## Prerequisites Check

```bash
# Check Python version (need 3.9+)
python3 --version

# Check Node.js version (need 18+)
node --version

# Check Redis
redis-cli ping  # Should return "PONG"

# Check required tools
which mock createrepo_c git
```

## Step 1: Start Backend Services (30 seconds)

```bash
cd /home/mj/Downloads/ReqPM

# Start everything at once!
./reqpm.sh start-all

# Check status
./reqpm.sh status
```

You should see:
- ✓ Redis running
- ✓ Django running on port 8000
- ✓ Celery worker running
- ✓ Celery beat running
- ✓ Frontend running on port 5173

## Step 2: Open Browser (10 seconds)

1. Open browser to http://localhost:5173
2. Login with:
   - **Username**: `admin`
   - **Password**: `admin123`

## Step 3: Create Your First Project (1 minute)

1. Click **"New Project"** button
2. Fill in:
   - **Name**: `test-project`
   - **Git URL**: `https://github.com/psf/requests.git`
   - **Branch**: `main`
   - **Description**: `Testing ReqPM`
3. Click **"Create Project"**

✨ ReqPM will automatically:
- Clone the repository
- Detect requirements.txt
- Set up package tracking

## Step 4: Explore the Dashboard

- **Dashboard**: See project stats
- **Projects**: List all projects
- **Packages**: View all Python packages
- **Builds**: Monitor build jobs
- **Repositories**: Manage RPM repositories

## Common Commands

### Service Management

```bash
# View logs (now includes frontend!)
./reqpm.sh logs all
./reqpm.sh logs frontend

# Restart all services (including frontend)
./reqpm.sh restart-all

# Stop everything
./reqpm.sh stop-all

# Start individual service
./reqpm.sh start-django
./reqpm.sh start-frontend
./reqpm.sh stop-celery
```

### API Testing

```bash
# Get JWT token
curl -X POST http://localhost:8000/api/token/ \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# Use token in requests
TOKEN="your-access-token"
curl http://localhost:8000/api/projects/ \
  -H "Authorization: Bearer $TOKEN"
```

### Check Logs

```bash
# All logs
./reqpm.sh logs

# Django only
tail -f logs/django.log

# Celery worker
tail -f logs/celery.log

# Celery beat
tail -f logs/beat.log
```

## Troubleshooting

### Services won't start?

```bash
# Check if ports are in use
lsof -i :8000  # Django
lsof -i :6379  # Redis

# Kill processes if needed
./reqpm.sh stop-all
pkill -f celery
```

### Redis not running?

```bash
# Start Redis
sudo systemctl start redis
# OR
redis-server &
```

### Frontend won't start?

```bash
cd frontend
# Reinstall dependencies
rm -rf node_modules package-lock.json
npm install
npm run dev
```

### Can't login?

```bash
# Create new superuser
source venv/bin/activate
python manage.py createsuperuser
```

## What's Next?

1. **Create a Project**: Import your Python project from Git
2. **Analyze Packages**: Let ReqPM detect requirements
3. **Generate Specs**: Auto-create RPM spec files
4. **Start Build**: Build RPMs for RHEL 8/9
5. **Publish**: Create YUM repository

See `API_TESTING.md` for complete workflow examples!

## URLs to Bookmark

- 🎨 **Frontend**: http://localhost:5173
- 🔌 **API**: http://localhost:8000/api/
- 📖 **API Docs**: http://localhost:8000/api/docs/
- 📚 **ReDoc**: http://localhost:8000/api/redoc/

## Need Help?

- Check `PROJECT_COMPLETE.md` for architecture details
- See `API_TESTING.md` for API examples
- Read `README.md` for full documentation

---

**All set! 🎉** You're now ready to build RPM packages from Python projects!
