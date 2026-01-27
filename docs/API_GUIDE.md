# ReqPM API Quick Start Guide

## Overview

This guide shows how to use ReqPM through its API to build RPM packages from Python projects.

## Authentication

ReqPM supports two authentication methods:

### 1. JWT Token Authentication

```bash
# Login to get tokens
curl -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "your_username", "password": "your_password"}'

# Response:
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}

# Use the access token in requests
curl -H "Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc..." \
  http://localhost:8000/api/projects/
```

### 2. API Key Authentication

```bash
# Generate an API key in your user profile
# Then use it in requests:

curl -H "X-API-Key: your_api_key_here" \
  http://localhost:8000/api/projects/
```

## Workflow Example

### 1. Create a Project

```bash
curl -X POST http://localhost:8000/api/projects/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Python Project",
    "description": "A sample Python project",
    "git_url": "https://github.com/username/repo.git",
    "branch": "main",
    "requirements_path": "requirements.txt",
    "rhel_versions": ["8", "9"],
    "auto_sync": true
  }'

# Response:
{
  "id": 1,
  "name": "My Python Project",
  "status": "pending",
  ...
}
```

### 2. Clone and Analyze Project

The project will be automatically cloned when created. Monitor progress:

```bash
# Get project status
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/projects/1/

# Response shows status:
{
  "id": 1,
  "status": "ready",  # or "cloning", "analyzing", "failed"
  "repo_path": "/path/to/cached/repo",
  "commit_hash": "abc123...",
  ...
}
```

### 3. View Discovered Packages

```bash
# List packages discovered from requirements.txt
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/packages/?project=1

# Response:
{
  "count": 15,
  "results": [
    {
      "id": 1,
      "name": "requests",
      "version": "2.31.0",
      "package_type": "dependency",
      "build_order": 0,
      ...
    },
    ...
  ]
}
```

### 4. Generate Spec Files

```bash
# Generate spec file for a specific package
curl -X POST http://localhost:8000/api/packages/1/generate_spec/ \
  -H "Authorization: Bearer YOUR_TOKEN"

# Or generate for all packages in project
curl -X POST http://localhost:8000/api/projects/1/generate_all_specs/ \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 5. View/Edit Spec File

```bash
# Get latest spec file for a package
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/packages/1/spec_files/

# Edit spec file (creates new revision)
curl -X POST http://localhost:8000/api/packages/1/spec_files/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Name: python3-requests\nVersion: 2.31.0\n...",
    "changelog": "Updated dependencies"
  }'
```

### 6. Trigger Build

```bash
# Create a build job
curl -X POST http://localhost:8000/api/builds/create_build/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "project": 1,
    "rhel_versions": ["8", "9"]
  }'

# Response:
{
  "id": 1,
  "project": 1,
  "status": "pending",
  "total_packages": 15,
  "built_packages": 0,
  "failed_packages": 0,
  "progress": 0,
  ...
}
```

### 7. Monitor Build Progress

```bash
# Get build job status
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/builds/1/

# Get detailed build queue
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/builds/1/queue/

# Response shows individual package builds:
{
  "count": 30,
  "results": [
    {
      "id": 1,
      "package": {"id": 1, "name": "requests"},
      "rhel_version": "8",
      "status": "completed",
      "output_rpm": "/path/to/python3-requests-2.31.0-1.el8.noarch.rpm",
      ...
    },
    ...
  ]
}
```

### 8. Create Repository

```bash
# Create a YUM/DNF repository
curl -X POST http://localhost:8000/api/repositories/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "project": 1,
    "name": "my-python-packages",
    "description": "Python packages for RHEL 8/9",
    "rhel_version": "8",
    "repo_path": "/var/www/repos/my-packages-el8",
    "base_url": "https://repos.example.com/my-packages-el8"
  }'

# Response:
{
  "id": 1,
  "name": "my-python-packages",
  "repo_url": "https://repos.example.com/my-packages-el8",
  ...
}
```

### 9. Publish Build to Repository

```bash
# Publish successful builds to repository
curl -X POST http://localhost:8000/api/builds/1/publish/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "repository": 1
  }'
```

### 10. Get Repository .repo File

```bash
# Get the .repo file content for clients
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/repositories/1/repo_file/

# Response (plain text):
[my-python-packages]
name=Python packages for RHEL 8/9
baseurl=https://repos.example.com/my-packages-el8
enabled=1
gpgcheck=0
```

## Advanced Operations

### Check for Package Updates

```bash
curl -X POST http://localhost:8000/api/projects/1/check_updates/ \
  -H "Authorization: Bearer YOUR_TOKEN"

# Returns list of packages with updates available
```

### Resolve Dependencies

```bash
# Manually trigger dependency resolution
curl -X POST http://localhost:8000/api/projects/1/resolve_dependencies/ \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Sign Repository

```bash
curl -X POST http://localhost:8000/api/repositories/1/sign/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "gpg_key_id": "ABCD1234"
  }'
```

### List Available Build Targets

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8000/api/builds/available_targets/

# Response:
{
  "targets": [
    "rhel-7-x86_64",
    "rhel-8-x86_64",
    "rhel-9-x86_64"
  ]
}
```

## Filtering and Searching

### Filter Projects

```bash
# Active projects only
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "http://localhost:8000/api/projects/?is_active=true"

# By status
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "http://localhost:8000/api/projects/?status=ready"

# Search by name
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "http://localhost:8000/api/projects/?search=python"
```

### Filter Packages

```bash
# By project
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "http://localhost:8000/api/packages/?project=1"

# By type
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "http://localhost:8000/api/packages/?package_type=dependency"

# By build order
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "http://localhost:8000/api/packages/?build_order=0"
```

### Filter Builds

```bash
# By status
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "http://localhost:8000/api/builds/?status=completed"

# By project
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "http://localhost:8000/api/builds/?project=1"
```

## Webhooks (Future)

ReqPM can trigger webhooks on build completion:

```bash
curl -X POST http://localhost:8000/api/projects/1/webhooks/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/webhook",
    "events": ["build.completed", "build.failed"],
    "secret": "your_webhook_secret"
  }'
```

## Error Handling

All API endpoints return appropriate HTTP status codes:

- `200 OK` - Successful GET/PUT/PATCH
- `201 Created` - Successful POST
- `204 No Content` - Successful DELETE
- `400 Bad Request` - Invalid input
- `401 Unauthorized` - Authentication required
- `403 Forbidden` - Insufficient permissions
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server error

Error responses include details:

```json
{
  "detail": "Project not found.",
  "error_code": "project_not_found"
}
```

## Rate Limiting

API requests are rate limited:
- Authenticated users: 1000 requests/hour
- Anonymous users: 100 requests/hour

Rate limit headers:
```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 999
X-RateLimit-Reset: 1640000000
```

## Client Installation on RHEL

Once packages are built and published:

```bash
# Download .repo file
sudo curl -o /etc/yum.repos.d/my-packages.repo \
  https://repos.example.com/my-packages.repo

# Install packages
sudo dnf install python3-requests python3-flask

# Or install all packages from the project
sudo dnf install @my-python-project
```

## Python Client Library (Future)

```python
from reqpm_client import ReqPMClient

# Initialize client
client = ReqPMClient(
    base_url='http://localhost:8000',
    api_key='your_api_key'
)

# Create and build project
project = client.projects.create(
    name='My Project',
    git_url='https://github.com/user/repo.git',
    rhel_versions=['8', '9']
)

# Wait for analysis
project.wait_until_ready()

# Start build
build = project.create_build()

# Monitor progress
for update in build.watch():
    print(f"Progress: {update.progress}%")

# Publish to repository
build.publish(repository='my-repo')
```
