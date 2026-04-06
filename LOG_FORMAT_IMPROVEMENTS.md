# Log Format Improvements

## Overview
Updated the build log display to show interleaved, time-sorted logs from multiple Mock log files with clear file name prefixes.

## Changes Made

### 1. New Log Merger Utility
**File:** `backend/core/log_merger.py`

- **Function:** `merge_log_files(log_files, sort_by_time=True)`
  - Merges multiple log files with filename prefixes
  - Parses timestamps from Mock log lines
  - Sorts lines chronologically when timestamps are available
  - Falls back to original order for lines without timestamps

- **Function:** `merge_log_file_paths(log_file_paths, sort_by_time=True)`
  - Convenience wrapper for merging log files from Path objects
  - Handles file I/O and error handling

### 2. Updated Mock Builder
**File:** `backend/plugins/builders/mock.py`

**Changes:**
- Added import: `from backend.core.log_merger import merge_log_file_paths`
- Added support for `state.log` in addition to `build.log` and `root.log`
- Replaced separate log file reading with unified merge function
- Logs now stored in database with filename prefixes and time-sorted

### 3. Updated WebSocket Consumer
**File:** `backend/apps/packages/consumers.py`

**Changes:**
- Live log streaming now prefixes each line with the source filename
- Both incremental streaming and final read use the same format
- Format: `<filename> - <log message>`

## New Log Format

### Before
```
=== build.log ===
Mock Version: unreleased_version
Building package...

=== root.log ===
INFO buildroot.py:667:  Mock Version: unreleased_version
DEBUG file_util.py:18:  ensuring that dir exists: /var/lib/mock/rhel-9-x86_64-pkg3084/root
```

### After (Time-sorted)
```
root.log - 2024-01-15 10:23:45,123 INFO buildroot.py:667:  Mock Version: unreleased_version
root.log - 2024-01-15 10:23:45,150 DEBUG file_util.py:18:  ensuring that dir exists: /var/lib/mock/rhel-9-x86_64-pkg3084/root
build.log - 2024-01-15 10:23:47,000 Mock Version: unreleased_version
build.log - 2024-01-15 10:23:48,500 Building package...
```

## Benefits

1. **Chronological Order**: Logs are sorted by timestamp, making it easier to follow the build timeline
2. **Clear Source**: Each line clearly shows which log file it came from
3. **Unified View**: All log files merged into a single stream instead of separate sections
4. **Efficient**: No duplication, each line appears exactly once with its context

## Implementation Details

### Timestamp Parsing
The log merger recognizes these timestamp formats:
- ISO format with milliseconds: `2024-01-15 10:23:45,123`
- ISO format: `2024-01-15 10:23:45`

Lines without recognized timestamps are placed after timestamped lines, preserving their original order.

### Live Streaming
For real-time build log streaming (WebSocket):
- Lines are prefixed with filename as they arrive
- Cannot be time-sorted during streaming (files grow at different times)
- Ordering is based on when Mock writes to each file

### Stored Logs
For completed/failed builds:
- All log files read completely
- Lines sorted by timestamp
- Stored in database with the new format

## Files Affected

1. ✅ `backend/core/log_merger.py` - New utility (151 lines)
2. ✅ `backend/plugins/builders/mock.py` - Updated log reading
3. ✅ `backend/apps/packages/consumers.py` - Updated WebSocket streaming
4. ✅ `test_log_merger.py` - Test suite (all tests passing)

## Testing

Run the test suite:
```bash
python test_log_merger.py
```

All tests pass:
- ✓ Basic merge with filename prefixes
- ✓ Time-sorted merge
- ✓ Mixed timestamps (some lines with, some without)
- ✓ Single file handling
- ✓ Empty content handling

## Rollout

Services have been restarted to apply changes:
- ✅ Django/Daphne server (WebSocket support)
- ✅ Celery worker (build processing)
- ✅ Redis

New builds will automatically use the new log format.
Existing builds in the database retain their old format (no migration needed).
