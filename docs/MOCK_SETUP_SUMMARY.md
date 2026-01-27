# Mock Builder Setup Summary

## What Was Done

### 1. Created Mock Setup Documentation
**File**: `docs/MOCK_SETUP.md`

Comprehensive guide covering:
- What Mock is and why it's needed
- Installation steps for RHEL/Fedora/CentOS
- User group configuration
- Mock configuration files
- Testing and verification
- Troubleshooting common issues
- Alternative Docker-based builds (future)

### 2. Improved Error Messages

**Backend Changes**:
- `backend/plugins/builders/mock.py`: Enhanced `is_available()` method with detailed error messages
  - Distinguishes between "not installed" vs "not accessible"
  - Provides installation commands in logs
  - References setup documentation

- `backend/apps/builds/tasks.py`: Improved build failure messages
  - Now includes installation instructions
  - References Mock Setup Guide
  - More actionable error messages

### 3. Added System Health Check

**New Backend Endpoint**: `/api/system-health/`
- `backend/apps/builds/health.py`: New health check view
- Returns Mock availability status
- Includes Mock version if available
- Lists available build targets
- Provides user-friendly setup messages

### 4. Frontend Health Monitoring

**New Component**: `frontend/src/components/SystemHealthBanner.jsx`
- `SystemHealthBanner`: Yellow warning banner when Mock is not available
- `MockStatus`: Inline status indicator showing Mock availability
- Auto-refreshes every minute
- Links to setup documentation

**Updated Pages**:
- `frontend/src/pages/Builds.jsx`: Shows health banner at top
- `frontend/src/pages/ProjectDetail.jsx`: Shows Mock status in build dialog

### 5. Updated Documentation

**Updated Files**:
- `README.md`: Added Mock setup section with link to detailed guide
- Emphasized that Mock is required for builds
- Added quick setup commands

## How It Works Now

### When Mock Is Not Installed

1. **User Interface**:
   - Yellow warning banner appears on Builds page
   - Mock status shows red "X" with "Mock not available" in build dialog
   - Error message provides installation instructions

2. **Build Attempts**:
   - Builds are queued normally
   - Each build task checks Mock availability
   - Fails immediately with helpful error message
   - Error message includes:
     ```
     Mock builder is not available.
     Mock is required for building RPM packages.
     Please install Mock: sudo dnf install mock && sudo usermod -a -G mock $USER
     See docs/MOCK_SETUP.md for complete setup instructions.
     ```

3. **Logs**:
   - Celery logs show detailed error messages
   - Includes installation instructions
   - References documentation

### When Mock Is Installed

1. **User Interface**:
   - No warning banner
   - Green checkmark with "Mock X.X ready" in build dialog
   - Shows number of available build targets

2. **Build Attempts**:
   - Builds proceed normally
   - Mock is used to build RPMs in clean chroot environments
   - Progress shown in real-time

## Files Modified

### New Files
1. `docs/MOCK_SETUP.md` - Complete Mock setup guide
2. `backend/apps/builds/health.py` - System health check endpoint
3. `frontend/src/components/SystemHealthBanner.jsx` - Health warning UI components

### Modified Files
1. `backend/plugins/builders/mock.py` - Enhanced error messages
2. `backend/apps/builds/tasks.py` - Improved build failure messages
3. `backend/apps/builds/urls.py` - Added health check endpoint
4. `frontend/src/pages/Builds.jsx` - Added health banner
5. `frontend/src/pages/ProjectDetail.jsx` - Added Mock status in dialog
6. `README.md` - Added Mock setup section

## User Actions Required

To enable RPM building, users must:

1. **Install Mock**:
   ```bash
   sudo dnf install mock
   ```

2. **Add user to mock group**:
   ```bash
   sudo usermod -a -G mock $USER
   ```

3. **Log out and log back in** (or reboot)

4. **Verify installation**:
   ```bash
   mock --version
   groups | grep mock
   ```

5. **Restart ReqPM services**:
   ```bash
   ./reqpm.sh restart all
   ```

## Benefits

1. **Clear Feedback**: Users immediately know if Mock is not available
2. **Actionable Errors**: Error messages include specific commands to fix the issue
3. **Documentation**: Comprehensive guide for all setup scenarios
4. **Proactive Warnings**: System warns before user attempts builds
5. **Better UX**: Users know system status without triggering failures
6. **Easier Debugging**: Logs and UI both provide helpful information

## Testing

To verify the implementation:

1. **Without Mock**:
   - Visit Builds page → See warning banner
   - Start a build → See clear error message in build details
   - Check Tasks page → See failed tasks with instructions

2. **With Mock**:
   - Install Mock and configure
   - Visit Builds page → No warning banner
   - Build dialog shows "Mock X.X ready"
   - Builds proceed successfully
