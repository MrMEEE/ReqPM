# ReqPM Workflow Automation - Implementation Complete

## Overview
This document describes the complete automated build pipeline that has been implemented in ReqPM.

## Automated Workflow

The system now automatically processes projects from requirements analysis through to build job creation:

```
1. Clone Repository
   ↓
2. Analyze Requirements Files
   ↓
3. Generate Spec Files (NEW - Automated)
   ↓
4. Resolve Dependencies
   ↓
5. Create Build Job (NEW - Automated)
   ↓
6. Build Packages in Dependency Order
```

## Changes Implemented

### 1. Fixed reqpm.sh Script

**File**: `reqpm.sh`

**Changes**:
- Added support for `restart <service>` syntax (previously only `restart` for all)
- Fixed function name inconsistency (`stop_celery_beat` → `stop_beat`)
- Added `start/stop/restart <service>` for individual service control

**Commands Now Available**:
```bash
./reqpm.sh start [service]      # Start all or specific service
./reqpm.sh stop [service]       # Stop all or specific service
./reqpm.sh restart [service]    # Restart all or specific service
./reqpm.sh status               # Show status of all services
./reqpm.sh logs <service>       # Tail logs

# Services: django, redis, celery, beat, frontend, all
```

### 2. Automatic Spec File Generation

**File**: `backend/apps/projects/tasks.py`

**Change in `analyze_requirements_task`**:
```python
# After creating Package records, automatically trigger spec generation
from backend.apps.packages.tasks import generate_all_spec_files_task
log_project(project_id, 'info', "Triggering spec file generation...")
generate_all_spec_files_task.delay(project_id)
```

**Result**: After requirements analysis completes, spec files are automatically generated for all detected packages.

### 3. Automatic Build Job Creation

**File**: `backend/apps/projects/tasks.py`

**Change in `resolve_dependencies_task`**:
```python
# After dependency resolution, automatically create a build job
from backend.apps.builds.models import BuildJob
from backend.apps.builds.tasks import start_build_job_task

build_job = BuildJob.objects.create(
    project=project,
    build_version=project.git_tag or project.git_branch or 'latest',
    git_ref=project.git_branch or project.git_tag or 'main',
    git_commit=project.git_commit or '',
    rhel_versions=['rhel8', 'rhel9'],  # Default to both
    status='preparing',
    total_packages=packages.count()
)

log_project(project_id, 'info', f"Build job #{build_job.id} created, starting build queue...")
start_build_job_task.delay(build_job.id)
```

**Result**: After dependencies are resolved, a build job is automatically created and the build queue is started.

### 4. Fixed Bug: is_active Field References

**Files**: 
- `backend/apps/projects/tasks.py` (resolve_dependencies_task)
- `backend/apps/packages/tasks.py` (generate_all_spec_files_task, check_package_updates_task)

**Problem**: Code was filtering `Package.objects.filter(is_active=True)` but the Package model doesn't have an `is_active` field.

**Fix**: Removed all `is_active=True` filters.

### 5. Fixed Bug: SpecFileRevision Arguments

**File**: `backend/apps/packages/tasks.py`

**Problem**: `SpecFileRevision.objects.create()` was passing invalid arguments:
- `version` (doesn't exist in model)
- `changelog` (should be `commit_message`)

**Fix**:
```python
SpecFileRevision.objects.create(
    package=package,
    content=spec_content,
    commit_message=f"Initial spec file generated from PyPI metadata for version {pkg_info.version}",
    created_by=None
)
```

## Testing the Workflow

### Manual Test
```bash
# Create a project in the UI or via API
# The system will automatically:
# 1. Clone the repository
# 2. Analyze requirements files
# 3. Generate spec files for all packages
# 4. Resolve dependencies
# 5. Create a build job
# 6. Start building packages

# Monitor progress in the UI or via logs:
./reqpm.sh logs celery

# Or check project logs:
python manage.py shell
>>> from backend.apps.projects.models import ProjectLog
>>> logs = ProjectLog.objects.filter(project_id=YOUR_PROJECT_ID).order_by('timestamp')
>>> for log in logs:
...     print(f"[{log.level}] {log.message}")
```

### Check Build Progress
```bash
python manage.py shell
>>> from backend.apps.builds.models import BuildJob, BuildQueue
>>> job = BuildJob.objects.latest('created_at')
>>> print(f"Status: {job.status}, Progress: {job.completed_packages}/{job.total_packages}")
>>> queue = BuildQueue.objects.filter(build_job=job)
>>> print(f"Queue items: {queue.count()}")
>>> for item in queue[:10]:
...     print(f"  - {item.package.name}: {item.status}")
```

## Architecture

### Task Chain
1. **clone_project_task** (projects/tasks.py)
   - Clones Git repository
   - Triggers → analyze_requirements_task

2. **analyze_requirements_task** (projects/tasks.py)
   - Parses requirements files
   - Creates Package records
   - Triggers → generate_all_spec_files_task
   - Triggers → resolve_dependencies_task

3. **generate_all_spec_files_task** (packages/tasks.py)
   - Iterates through all packages
   - Triggers → generate_spec_file_task for each

4. **generate_spec_file_task** (packages/tasks.py)
   - Fetches PyPI metadata
   - Generates RPM spec file
   - Creates SpecFileRevision record

5. **resolve_dependencies_task** (projects/tasks.py)
   - Fetches dependencies from PyPI
   - Creates PackageDependency records
   - Calculates build order
   - Triggers → Creates BuildJob and calls start_build_job_task

6. **start_build_job_task** (builds/tasks.py)
   - Creates BuildQueue entries in dependency order
   - Triggers → build_package_task for first batch

7. **build_package_task** (builds/tasks.py)
   - Builds SRPM using Mock
   - Builds RPM from SRPM
   - Creates PackageBuild record
   - Updates BuildQueue status
   - Triggers next package in queue

### Logging

All operations are logged to the `ProjectLog` model:
- **Level**: debug, info, warning, error
- **Message**: Human-readable progress updates
- **Timestamp**: When the log entry was created

Logs are visible in:
- UI: Project detail page with live log viewer (auto-refresh every 2s)
- Database: `project_logs` table
- Celery logs: `logs/celery.log`

### Resume System

**Celery Beat Task**: `resume_stuck_projects_task` (runs every 5 minutes)

Automatically resumes projects stuck in:
- **pending** > 5 minutes → triggers clone_project_task
- **cloning** > 30 minutes → triggers clone_project_task
- **analyzing** > 15 minutes → triggers analyze_requirements_task

## UI Features

### Project Detail Page
- **Live Logs**: Auto-refresh every 2 seconds when project is processing
- **Show/Hide Logs**: Toggle button to view/hide log viewer
- **Resume/Retry Button**: Manually trigger project re-processing
- **Auto-refresh**: Project status updates every 3 seconds during processing
- **Dark Theme**: All UI elements use dark theme (gray-800 backgrounds)

### Project Creation
- **Multiple Requirements Files**: Select multiple requirements.txt files
- **Auto-detection**: Automatically finds requirements files in repository
- **Branch/Tag Selection**: Choose specific Git ref to build from

## Build System

### Mock Integration
- **SRPM Building**: Builds source RPM from spec file
- **RPM Building**: Builds binary RPM from SRPM
- **RHEL Versions**: Supports RHEL 7, 8, 9
- **Build Roots**: Isolated build environments per RHEL version
- **Result Tracking**: PackageBuild records store build artifacts

### Dependency Management
- **Build Order**: Calculated from dependency tree
- **Parallel Builds**: Multiple packages can build simultaneously
- **Blocked States**: Packages wait for dependencies to complete
- **Retry Logic**: Failed builds can be retried

## Next Steps

### Recommended Enhancements
1. **Build Configuration UI**: Allow users to select RHEL versions before building
2. **Build Monitoring**: Real-time build progress UI with logs
3. **Repository Publishing**: Automatic createrepo_c after builds complete
4. **Notifications**: Email/webhook notifications for build completion/failures
5. **Build Artifacts**: Download built RPMs from UI
6. **Build History**: View previous builds and compare results

### Testing Checklist
- [ ] Create new project from Git repository
- [ ] Verify automatic spec file generation
- [ ] Check dependency resolution
- [ ] Confirm build job creation
- [ ] Monitor build queue processing
- [ ] Verify RPMs are built successfully
- [ ] Test resume functionality for stuck projects
- [ ] Validate live log viewer in UI
- [ ] Test retry/resume button

## Troubleshooting

### No Spec Files Generated
Check Celery logs: `./reqpm.sh logs celery`
Look for PyPI connection errors or spec generation failures.

### Build Job Not Created
Verify resolve_dependencies_task completed:
```python
from backend.apps.projects.models import ProjectLog
logs = ProjectLog.objects.filter(project_id=X, message__icontains='Build job')
```

### Builds Not Starting
Check BuildQueue status:
```python
from backend.apps.builds.models import BuildQueue
BuildQueue.objects.filter(status='blocked')  # Waiting for dependencies
BuildQueue.objects.filter(status='failed')   # Failed builds
```

### Services Not Running
Check status: `./reqpm.sh status`
Restart all: `./reqpm.sh restart`
View logs: `./reqpm.sh logs all`

## Configuration

### Celery Beat Schedule
Located in `backend/reqpm/celery.py`:
- **resume-stuck-projects**: Every 5 minutes
- **sync-all-projects**: Every 6 hours
- **cleanup-old-repos**: Daily at 2 AM
- **cleanup-old-builds**: Daily at 3 AM
- **sync-all-repositories**: Every 30 minutes

### Build Settings
Located in `backend/settings/base.py`:
- **MOCK_CONFIGS**: RHEL version configurations
- **BUILD_ROOT**: Base directory for builds
- **MAX_PARALLEL_BUILDS**: Maximum concurrent builds

## Summary

✅ **Complete automated workflow** from requirements analysis to build job creation
✅ **Fixed all bugs** (is_active references, SpecFileRevision arguments, reqpm.sh functions)
✅ **Enhanced reqpm.sh** with individual service restart support
✅ **Live logging** with real-time UI updates
✅ **Automatic resume** for stuck projects every 5 minutes
✅ **Dark theme UI** with responsive design
✅ **Build system** fully integrated with Mock

The system is now ready for end-to-end testing of the complete build pipeline!
