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

### Build-failure routing

AI fixes run on the dedicated `ai` Celery queue, not inside RPM build tasks.
After rule-based fixes are exhausted, the build saves its logs and retry state,
queues an AI fix, and releases its build slot. The AI worker queues a new build
only when it creates a new, untried spec revision. Retry limits, repeated-spec
guards, and automatic confirmation on successful rebuilds span this handoff.
Unsuccessful AI fixes leave the package failed with its original build logs.
Queued fixes are recovered by the pending-work monitor; cancelled or superseded
requests cannot queue another build.

The existing build worker concurrency and maximum simultaneous builds settings
are unchanged. **AI Fix Worker Concurrency** defaults to **2** and is independently
configurable in Settings (1-20 processes); reload workers to apply changes.
The AI maximum-concurrent-model-requests setting remains a separate limit.
General fetch/spec work and project orchestration keep their existing workers.
`./reqpm.sh start|stop|restart|logs celery-ai` manages the AI worker; normal
startup, shutdown, status, and Reload Workers include it. Compose deployments
also have a separate `celery_ai` service reading this setting on startup.

SRPM and RPM failures caused by unavailable repository dependencies are handled
before automatic spec fixes or AI fixes. ReqPM records the latest build and root
logs, resolves missing dependencies, and queues known unbuilt project dependencies.
The blocked package is marked `dep_build_pending` when its dependencies are known
in the project, or `missing_packages` when they cannot yet be resolved. Dependency
completion triggers a readiness check and rebuild of waiting packages.
Readiness honors RPM equality (`=`) as an exact version constraint: a completed
newer dependency does not satisfy an older exact pin. Before starting another
build, ReqPM rechecks known repository-dependency blockers for an unchanged spec
and defers the build if any remain unresolved, preserving its previous logs.
A newer spec revision may retry so corrected requirements can be discovered.
Every five minutes, dependency discovery revisits projects with missing or
dependency-pending packages. This also recovers older failures that never ran
automatic discovery: missing PyPI build backends are added as transitive packages,
linked to their consumers, and queued for spec generation/build. System packages
and incompatible versions of existing project packages still require separate
resolution; a completed package is not considered sufficient merely by name.

The pending-work monitor also revisits `waiting_for_deps` packages with specs
and fetched sources. Once all linked dependencies are completed or not required,
it moves the package to `pending` and queues its build. This recovers missed
dependency-completion wake-ups. Active, reserved, and scheduled retry tasks are
excluded to avoid duplicate dispatch while a build is waiting for a slot.
Pending builds with an existing spec are also recovered when their metadata
status remains pending. Before dispatch, known unresolved build requirements
restore the dependency-blocked state without starting Mock. Slot retries do not
overwrite a dependency-blocked state recorded by another task.

Package details show a dependency-blockers panel with required constraints,
current project versions and build states, and links to blocking packages.
The panel follows waiting dependencies to expose transitive version conflicts.
Project-list dependency tooltips retain version-conflicting requirements even
when the matching dependency is already marked completed.

When a discovered transitive dependency has an incompatible version, ReqPM
selects the highest stable PyPI release satisfying all recorded project build
requirements and linked consumer constraints. Direct dependencies and active
builds are not changed automatically. If there is no shared compatible release,
the blocker remains and a warning is recorded. A selected version invalidates
old artifacts and queues spec generation, source fetching, and a rebuild.

Enabled Python extras generate RPM extras subpackages. Dependency resolution
checks the spec declaration as well as the enabled setting; an older spec that
omits a required extras subpackage is repaired in a new revision and rebuilt
without replacing the rest of the spec.
Both package list status tooltips and the package detail Build status section
use the same current blocker summary, including transitive missing dependencies,
version conflicts, RHEL mismatches, missing RPM extras, and failed-build errors.
Current missing dependencies are also displayed inline beneath Build Status in
project package tables and package listings. Package details include the linked
requirements and current blocker versions inside the Build status section,
rather than a separate duplicate panel. Resolved dependencies are omitted.

The AI fixer can explicitly request `disable_shebang_check` with the fixed value
`brp-mangle-shebangs` when targeted shebang repair cannot address the failure.
This adds `%undefine __brp_mangle_shebangs` to that package's spec only and records
the bypass in the AI fix revision. It disables validation rather than repairing
script interpreters.

Two general AI actions are available as separate opt-in settings under Settings →
AI Build Fixer; both are disabled by default:

- `insert_lines` inserts up to 40 lines before or after one existing spec line.
  The anchor must match exactly one line, inserted lines cannot add Name, Version,
  Release or Epoch, and repeated insertions at the same position are rejected.
- `rewrite_spec` replaces the complete spec as a last resort. It must be the only
  action, include Name, Version, Release, `%description` and `%files`, keep the
  main package's Name, Version, Release and Epoch unchanged, and stay below 200 KB.

While either is enabled, the AI receives the complete spec instead of selected
sections. These actions can add arbitrary build/install commands and RPM macros,
which run in Mock. Every result must pass `rpmspec --parse` and is stored as an
auditable, revertible spec revision. With both disabled, arbitrary macro edits and
build/install commands remain unsupported.

This routing is checked again after each RPM retry. If an SRPM rebuild fails, its
logs replace the previous RPM failure for dependency analysis. Missing imports,
compilers, headers, and self-referential requirements remain eligible for targeted
spec corrections; packaging errors such as missing `%files` paths also continue
through the spec/AI fixer loop.

AI proposals that make no changes receive one automatic reconsideration with the
executor's rejection details. Both exchanges are saved in the AI conversation.
The follow-up is labeled as an automatic reconsideration of the original
exchange, not a separate simultaneous autofix. Self-dependency proposals include
an explicit rejection reason in the feedback sent to the model.
The model must propose a different supported action or explain why no supported
spec action can fix the cause; it cannot execute arbitrary build commands or edit
the build environment. Past proposals without outcome feedback are explicitly
identified as unverified in the prompt.

AI Conversations show the model saved for each exchange, not the model currently
selected in Settings. They refresh even when no exchange is active. Old running
exchanges on packages no longer in the fixing state are marked as interrupted
after a conservative response-time grace period (at least 30 minutes), so worker
interruptions do not leave historical conversations displaying "Thinking" forever.
The AI activity list and slot-counter recovery only use AI logs from the current
build. A slot-acquired message supersedes an earlier waiting message; packages
that are no longer building or fixing do not appear as waiting for AI.

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
