# WebSocket Real-Time Updates

## Overview

The build system now uses WebSocket connections to provide real-time updates without requiring page refreshes. This eliminates the need for polling and provides instant feedback on build status changes.

## Architecture

### Backend Components

1. **WebSocket Consumer** (`backend/apps/builds/consumers.py`)
   - `BuildJobConsumer`: Handles WebSocket connections for individual build jobs
   - Automatically joins room group based on build job ID
   - Sends initial build job data upon connection
   - Listens for `build_update` and `queue_update` events

2. **WebSocket Utilities** (`backend/apps/builds/websocket_utils.py`)
   - `send_build_job_update(build_job_id)`: Broadcasts build job updates to all connected clients
   - `send_queue_item_update(queue_item_id)`: Broadcasts queue item updates to all connected clients
   - Includes error handling to prevent task failures

3. **Routing** (`backend/apps/builds/routing.py`)
   - WebSocket URL: `ws://localhost:8000/ws/builds/<build_job_id>/`
   - Maps to `BuildJobConsumer`

4. **Task Integration** (`backend/apps/builds/tasks.py`)
   - WebSocket updates sent after every status change in `build_package_task`
   - Updates sent after progress calculations in `check_build_job_completion`
   - Ensures all clients receive immediate notifications

### Frontend Components

1. **WebSocket Hook** (`frontend/src/hooks/useWebSocket.js`)
   - Custom React hook for managing WebSocket connections
   - Automatically connects when build is active
   - Updates TanStack Query cache when messages received
   - Handles connection lifecycle (open, message, error, close)

2. **BuildDetail Page** (`frontend/src/pages/BuildDetail.jsx`)
   - Uses `useWebSocket` hook to connect to build job
   - Disables polling in favor of WebSocket updates
   - Query key changed to `buildJob` for consistency

## Message Types

### Build Update
Sent when build job status or progress changes:
```json
{
  "type": "build_update",
  "data": {
    "id": 1,
    "status": "building",
    "completed_packages": 10,
    "failed_packages": 2,
    "total_packages": 185,
    "progress": 6.5
  }
}
```

### Queue Update
Sent when individual package build status changes:
```json
{
  "type": "queue_update",
  "data": {
    "id": 123,
    "status": "completed",
    "package": {...},
    "build_log": "...",
    "started_at": "2026-02-11T08:00:00Z",
    "completed_at": "2026-02-11T08:05:00Z"
  }
}
```

## Usage

### Backend - Sending Updates

In any Celery task, import and use the utility functions:

```python
from backend.apps.builds.websocket_utils import send_build_job_update, send_queue_item_update

# After updating a build job
build_job.status = 'completed'
build_job.save()
send_build_job_update(build_job.id)

# After updating a queue item
queue_item.status = 'completed'
queue_item.save()
send_queue_item_update(queue_item.id)
send_build_job_update(queue_item.build_job_id)
```

### Frontend - Receiving Updates

Use the `useWebSocket` hook in any component:

```javascript
import { useWebSocket } from '../hooks/useWebSocket';

function MyComponent() {
  const { id } = useParams();
  
  // Enable WebSocket for active builds only
  const wsEnabled = build && !['completed', 'failed', 'cancelled'].includes(build.status);
  useWebSocket(id, wsEnabled);
  
  // Query cache will be automatically updated
  const { data: build } = useQuery({
    queryKey: ['buildJob', id],
    queryFn: fetchBuildJob,
    refetchInterval: false, // Disable polling
  });
}
```

## Benefits

1. **Real-Time Updates**: Changes appear instantly without waiting for polling intervals
2. **Reduced Server Load**: No continuous polling requests
3. **Better UX**: Users see progress updates immediately
4. **Efficient**: WebSocket connection is only active during builds

## Connection Behavior

- WebSocket connects when build status is `pending`, `preparing`, or `running`
- Connection closes when build reaches terminal state (`completed`, `failed`, `cancelled`)
- Automatic reconnection on page refresh
- Connection cleanup on component unmount

## Testing

1. Start a build and open the build detail page
2. Open browser DevTools → Network → WS filter
3. You should see WebSocket connection to `ws://localhost:8000/ws/builds/<id>/`
4. Watch for `build_update` and `queue_update` messages as packages build
5. Verify UI updates without page refresh

## Troubleshooting

### WebSocket Not Connecting
- Verify Daphne is running (check `./reqpm.sh status`)
- Check browser console for connection errors
- Ensure build is in active state (not completed/failed)

### Updates Not Appearing
- Check Django logs: `tail -f logs/django.log`
- Check Celery logs: `tail -f logs/celery_worker.log`
- Verify WebSocket messages in browser DevTools
- Check if query cache is being updated

### Connection Drops
- Check for firewall/proxy issues
- Verify Redis is running (channel layer backend)
- Check for network interruptions
