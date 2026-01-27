# ReqPM API Testing Guide

## Create a Superuser

First, create a user to test the API:

```bash
source venv/bin/activate
python manage.py createsuperuser
```

## Test the API

### 1. Login to Get JWT Token

```bash
curl -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "your_password"}'
```

Response:
```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGc..."
}
```

Save the `access` token for subsequent requests.

### 2. Browse API Root

```bash
# Set your token
export TOKEN="your_access_token_here"

# Browse API
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/
```

## Available Endpoints

### Users API
- `GET /api/users/` - List users
- `POST /api/users/` - Create user
- `GET /api/users/{id}/` - Get user details
- `POST /api/users/{id}/generate_api_key/` - Generate API key

### Projects API
- `GET /api/projects/` - List projects
- `POST /api/projects/` - Create project (triggers git clone)
- `GET /api/projects/{id}/` - Get project details
- `PUT /api/projects/{id}/` - Update project
- `DELETE /api/projects/{id}/` - Delete project
- `POST /api/projects/{id}/sync/` - Trigger git sync
- `POST /api/projects/{id}/analyze/` - Analyze requirements.txt
- `POST /api/projects/{id}/resolve_dependencies/` - Resolve dependencies
- `POST /api/projects/{id}/generate_specs/` - Generate all spec files
- `POST /api/projects/{id}/check_updates/` - Check for package updates
- `GET /api/projects/{id}/branches/` - List git branches
- `GET /api/projects/{id}/collaborators/` - List collaborators
- `POST /api/projects/{id}/collaborators/` - Add collaborator

### Packages API
- `GET /api/packages/` - List packages
- `GET /api/packages/{id}/` - Get package details
- `POST /api/packages/{id}/generate_spec/` - Generate spec file
- `POST /api/packages/{id}/update_metadata/` - Update from PyPI
- `GET /api/packages/{id}/dependencies/` - Get dependencies
- `GET /api/packages/{id}/builds/` - Get build history
- `GET /api/packages/{id}/spec_files/` - List spec file revisions
- `POST /api/packages/{id}/spec_files/` - Create spec revision
- `GET /api/packages/{id}/spec_files/latest/` - Get latest spec

### Builds API
- `GET /api/build-jobs/` - List build jobs
- `POST /api/build-jobs/` - Create build job
- `GET /api/build-jobs/{id}/` - Get build details
- `DELETE /api/build-jobs/{id}/` - Cancel/delete build
- `GET /api/build-jobs/{id}/queue/` - Get build queue
- `POST /api/build-jobs/{id}/publish/` - Publish to repository
- `POST /api/build-jobs/{id}/cancel/` - Cancel build
- `POST /api/build-jobs/{id}/retry/` - Retry failed builds
- `GET /api/build-queue/` - List queue items
- `GET /api/build-workers/` - List build workers
- `GET /api/available-targets/` - List available build targets

### Repositories API
- `GET /api/repositories/` - List repositories
- `POST /api/repositories/` - Create repository
- `GET /api/repositories/{id}/` - Get repository details
- `PUT /api/repositories/{id}/` - Update repository
- `DELETE /api/repositories/{id}/` - Delete repository
- `GET /api/repositories/{id}/packages/` - List packages
- `POST /api/repositories/{id}/add_package/` - Add package
- `POST /api/repositories/{id}/remove_package/` - Remove package
- `POST /api/repositories/{id}/update_metadata/` - Update metadata
- `POST /api/repositories/{id}/sign/` - Sign with GPG
- `GET /api/repositories/{id}/repo_file/` - Get .repo file (public)
- `GET /api/repositories/{id}/metadata/` - Get metadata

## Complete Workflow Example

### 1. Create a Project

```bash
curl -X POST http://localhost:8000/api/projects/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Flask App",
    "description": "My Flask application",
    "git_url": "https://github.com/pallets/flask.git",
    "branch": "main",
    "requirements_path": "requirements/dev.txt",
    "rhel_versions": ["8", "9"],
    "auto_sync": true
  }'
```

This will:
- Create the project
- Trigger git clone (async task)
- Analyze requirements.txt
- Discover packages

### 2. Check Project Status

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/projects/1/
```

Wait until `status` becomes `"ready"`.

### 3. List Discovered Packages

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/packages/?project=1"
```

### 4. Generate Spec Files

```bash
curl -X POST http://localhost:8000/api/projects/1/generate_specs/ \
  -H "Authorization: Bearer $TOKEN"
```

### 5. Create a Build Job

```bash
curl -X POST http://localhost:8000/api/build-jobs/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "project": 1,
    "rhel_versions": ["8", "9"]
  }'
```

### 6. Monitor Build Progress

```bash
# Get build job status
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/build-jobs/1/

# Get detailed queue
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/build-jobs/1/queue/
```

### 7. Create a Repository

```bash
curl -X POST http://localhost:8000/api/repositories/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "flask-packages-el8",
    "description": "Flask and dependencies for RHEL 8",
    "project": 1,
    "rhel_version": "8",
    "repo_path": "./data/repositories/flask-el8",
    "base_url": "http://localhost:8000/repos/flask-el8",
    "gpg_check": false
  }'
```

### 8. Publish Build to Repository

```bash
curl -X POST http://localhost:8000/api/build-jobs/1/publish/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"repository": 1}'
```

### 9. Get Repository .repo File

```bash
# This endpoint is public (no auth required)
curl http://localhost:8000/api/repositories/1/repo_file/
```

Save to `/etc/yum.repos.d/flask-el8.repo` on RHEL systems.

## Filtering and Searching

### Filter Projects by Status
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/projects/?status=ready"
```

### Search Projects
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/projects/?search=flask"
```

### Filter Packages by Type
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/packages/?package_type=dependency&project=1"
```

### Filter Builds by Status
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/build-jobs/?status=completed"
```

## Using API Key Instead of JWT

Generate an API key:

```bash
curl -X POST http://localhost:8000/api/users/1/generate_api_key/ \
  -H "Authorization: Bearer $TOKEN"
```

Then use it in requests:

```bash
curl -H "X-API-Key: your_api_key_here" \
  http://localhost:8000/api/projects/
```

## Check API Documentation

The API is documented with drf-spectacular:

- **Swagger UI**: http://localhost:8000/api/schema/swagger-ui/
- **ReDoc**: http://localhost:8000/api/schema/redoc/
- **OpenAPI Schema**: http://localhost:8000/api/schema/

## Common Status Codes

- `200 OK` - Successful GET/PUT/PATCH
- `201 Created` - Successful POST
- `202 Accepted` - Async task triggered
- `204 No Content` - Successful DELETE
- `400 Bad Request` - Invalid input
- `401 Unauthorized` - Authentication required
- `403 Forbidden` - Insufficient permissions
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server error

## Tips

1. **Use jq for pretty output**: `curl ... | jq`
2. **Set TOKEN variable**: `export TOKEN="your_token"` to avoid repeating it
3. **Check logs**: `./reqpm.sh logs django` or `./reqpm.sh logs celery`
4. **Monitor tasks**: Watch Celery logs to see background task execution
5. **Test with Postman**: Import the OpenAPI schema for easier testing
