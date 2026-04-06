# Tasks View Enhancements

## Overview
Enhanced the Tasks view to show what each task is working on and provide quick access to build logs for package-related tasks.

## Changes Made

### 1. Backend - Enhanced Task Serializer
**File:** `backend/apps/tasks/serializers.py`

Added two new computed fields to the `TaskResultSerializer`:

#### `task_context` field
Parses task arguments to extract context about what the task is doing:
- **Type detection**: `build`, `package`, `project`, `repository`, `gpg`, etc.
- **Description**: Human-readable description (e.g., "Building package", "Generating spec file")
- **Related IDs**: Extracts package_id, build_queue_id, project_id, etc.

Supports these task types:
- `build_package_task` → "Building package" + build_queue_id
- `generate_spec_file_task` → "Generating spec file" + package_id
- `fetch_package_source` → "Fetching source files" + package_id
- `process_build_job` → "Processing build job" + build_job_id
- `analyze_project` → "Analyzing project dependencies" + project_id
- `sync_repository` → "Syncing repository" + repository_id
- And more...

#### `related_package` field
Links task to package information when applicable:
- For direct package tasks: Looks up by `package_id`
- For build tasks: Looks up via `BuildQueue` → `Package`

Returns:
```json
{
  "id": 123,
  "name": "django",
  "version": "5.0.0",
  "build_queue_id": 456,  // if build task
  "rhel_version": "10"     // if build task
}
```

### 2. Frontend - Enhanced Tasks Display
**File:** `frontend/src/pages/Tasks.jsx`

#### New Features

1. **"Working On" Column**
   - Shows task context with an icon indicating the task type
   - Displays package name and RHEL version for build tasks
   - Examples:
     - 🏗️ Building package: django (RHEL 10)
     - 📦 Generating spec file: requests
     - 📁 Fetching source files: numpy

2. **Build Log Button**
   - Green `FileCode` icon button next to task log button
   - Only appears for tasks with `related_package`
   - Opens build log modal for the associated package
   - Quick access without navigating to Packages view

3. **Improved Task Context**
   - Helper function `formatTaskContext()` formats the display text
   - Helper function `getTaskTypeIcon()` returns appropriate icon
   - Icons: `FileCode` for builds, `Package` for packages, `List` for projects

#### Visual Layout

```
┌─────────────────────────────────────────────────────────────┐
│ Task Name                        [Status] [Duration]         │
│ 🏗️ Building package: django (RHEL 10)                       │
│ Task ID: abc123... │ Started: ...                            │
│                                          [📄] [💻] [▼]       │
└─────────────────────────────────────────────────────────────┘
```

Buttons:
- 📄 (Green) - Build Log (only for build tasks)
- 💻 (Blue) - Task Log
- ▼ - Expand/Collapse

## Use Cases

### 1. Monitor Active Builds
Users can now see at a glance:
- Which packages are currently building
- What RHEL version they're targeting
- Quick access to build logs without leaving the Tasks view

### 2. Troubleshoot Failures
- Identify failed build tasks by package name
- Click build log button to see detailed error output
- Compare task log (Celery execution) vs build log (Mock output)

### 3. Track Progress
- See all spec file generation tasks
- Monitor source fetching operations
- Track repository sync status

## Implementation Details

### Task Context Detection Logic

The serializer parses `task_args` and `task_kwargs` (JSON strings) to extract:
1. Function positional arguments (e.g., `[123]` → package_id=123)
2. Keyword arguments (e.g., `{"package_id": 123}`)

Task name patterns matched:
- `*package*` + `build_package_task` → Build task
- `*package*` + `generate_spec_file` → Spec generation
- `*build*` + `build_job_task` → Build job processing
- `*project*` + `analyze_project` → Project analysis
- `*repository*` + `sync_repository` → Repository sync

### Database Queries

The `related_package` field performs:
- Direct lookup: `Package.objects.get(id=package_id)`
- Build queue lookup: `BuildQueue.objects.select_related('package').get(id=build_queue_id)`

Uses `select_related` to avoid N+1 queries when displaying task lists.

### Frontend Integration

The `LiveBuildLog` component (already exists) is reused:
```jsx
{buildLogPackage && (
  <LiveBuildLog
    packageId={buildLogPackage.id}
    packageName={buildLogPackage.name}
    onClose={() => setBuildLogPackage(null)}
  />
)}
```

## Testing

### Verify Task Context
1. Navigate to Tasks view (http://localhost:5173/tasks)
2. Look for running/completed build tasks
3. Verify "Working on" section shows package name
4. Check RHEL version is displayed for build tasks

### Verify Build Log Access
1. Find a build task with the green 📄 icon
2. Click the build log button
3. Verify modal opens with package build log
4. Check log shows mock output with new format (filename prefixes)

### Verify Different Task Types
1. Trigger spec generation: See "Generating spec file: {package}"
2. Trigger build: See "Building package: {package} (RHEL {version})"
3. Trigger repository sync: See "Syncing repository"

## Benefits

1. **Better Visibility**: Immediately see what each background task is doing
2. **Quick Troubleshooting**: One-click access to build logs from tasks view
3. **Context Awareness**: No need to cross-reference task IDs with packages
4. **Improved UX**: Less navigation between views to diagnose issues

## Files Changed

1. ✅ `backend/apps/tasks/serializers.py` - Added task_context and related_package fields
2. ✅ `frontend/src/pages/Tasks.jsx` - Enhanced UI with context display and build log button
3. ✅ Frontend built and deployed
4. ✅ Django server restarted

## Performance Impact

- **Minimal**: Only adds 1-2 DB queries per task when `related_package` is populated
- Uses `select_related` to optimize queries
- JSON parsing is fast (task_args/kwargs are small)
- No N+1 query issues (optimized with select_related)

## Future Enhancements

Potential improvements:
1. Add project context to show project name for all project-related tasks
2. Add repository context to show repository name
3. Color-code task types (builds=blue, spec gen=green, etc.)
4. Add task progress percentage for long-running builds
5. Add estimated time remaining based on historical data
