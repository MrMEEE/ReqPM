import { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { Settings as SettingsIcon, Save, AlertCircle, CheckCircle, Activity } from 'lucide-react';
import { settingsAPI } from '../lib/api';

export default function Settings() {
  const { user } = useAuth();
  const [settings, setSettings] = useState(null);
  const [buildStatus, setBuildStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);

  const isAdmin = user?.is_staff || user?.is_superuser;

  useEffect(() => {
    loadSettings();
    loadBuildStatus();
    
    // Refresh build status every 5 seconds
    const interval = setInterval(loadBuildStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  const loadSettings = async () => {
    try {
      const response = await settingsAPI.get();
      setSettings(response.data.results?.[0] || response.data);
      setLoading(false);
    } catch (err) {
      setError('Failed to load settings');
      setLoading(false);
    }
  };

  const loadBuildStatus = async () => {
    try {
      const response = await settingsAPI.buildStatus();
      setBuildStatus(response.data);
    } catch (err) {
      console.error('Failed to load build status:', err);
    }
  };

  const handleChange = (field, value) => {
    setSettings({ ...settings, [field]: value });
  };

  const handleSave = async () => {
    if (!isAdmin) {
      setError('Only administrators can modify settings');
      return;
    }

    setSaving(true);
    setError(null);
    setMessage(null);

    try {
      const response = await settingsAPI.update(1, settings);
      setSettings(response.data);
      setMessage('Settings saved successfully');
      setTimeout(() => setMessage(null), 3000);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-400">Loading settings...</div>
      </div>
    );
  }

  if (!settings) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-red-400">Failed to load settings</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <SettingsIcon className="text-blue-500" size={32} />
          <div>
            <h1 className="text-3xl font-bold text-white">System Settings</h1>
            <p className="text-gray-400 mt-1">Configure system-wide options</p>
          </div>
        </div>
      </div>

      {/* Messages */}
      {message && (
        <div className="bg-green-900/50 border border-green-500 rounded-lg p-4 flex items-center space-x-2">
          <CheckCircle className="text-green-500" size={20} />
          <span className="text-green-200">{message}</span>
        </div>
      )}

      {error && (
        <div className="bg-red-900/50 border border-red-500 rounded-lg p-4 flex items-center space-x-2">
          <AlertCircle className="text-red-500" size={20} />
          <span className="text-red-200">{error}</span>
        </div>
      )}

      {!isAdmin && (
        <div className="bg-yellow-900/50 border border-yellow-500 rounded-lg p-4 flex items-center space-x-2">
          <AlertCircle className="text-yellow-500" size={20} />
          <span className="text-yellow-200">You can view settings but only administrators can modify them.</span>
        </div>
      )}

      {/* Build Status Card */}
      {buildStatus && (
        <div className="bg-gray-800 rounded-lg shadow-lg p-6 border border-gray-700">
          <div className="flex items-center space-x-2 mb-4">
            <Activity className="text-blue-500" size={24} />
            <h2 className="text-xl font-semibold text-white">Build Activity</h2>
          </div>
          
          <div className="grid grid-cols-3 gap-4">
            <div className="bg-gray-900/50 rounded-lg p-4">
              <div className="text-gray-400 text-sm mb-1">Active Builds</div>
              <div className="text-3xl font-bold text-blue-500">{buildStatus.active_count}</div>
            </div>
            <div className="bg-gray-900/50 rounded-lg p-4">
              <div className="text-gray-400 text-sm mb-1">Max Concurrent</div>
              <div className="text-3xl font-bold text-white">{buildStatus.max_concurrent}</div>
            </div>
            <div className="bg-gray-900/50 rounded-lg p-4">
              <div className="text-gray-400 text-sm mb-1">Available Slots</div>
              <div className="text-3xl font-bold text-green-500">{buildStatus.available_slots}</div>
            </div>
          </div>

          {buildStatus.active_build_ids && buildStatus.active_build_ids.length > 0 && (
            <div className="mt-4">
              <div className="text-sm text-gray-400 mb-2">Currently Building:</div>
              <div className="flex flex-wrap gap-2">
                {buildStatus.active_build_ids.map((buildId) => (
                  <span
                    key={buildId}
                    className="px-3 py-1 bg-blue-900/50 text-blue-300 rounded-full text-sm"
                  >
                    {buildId}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Build Settings */}
      <div className="bg-gray-800 rounded-lg shadow-lg p-6 border border-gray-700">
        <h2 className="text-xl font-semibold text-white mb-6">Build Settings</h2>
        
        <div className="space-y-6">
          {/* Max Concurrent Builds */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Maximum Concurrent Builds
            </label>
            <div className="flex items-center space-x-4">
              <input
                type="range"
                min="1"
                max="20"
                value={settings.max_concurrent_builds}
                onChange={(e) => handleChange('max_concurrent_builds', parseInt(e.target.value))}
                disabled={!isAdmin}
                className="flex-1 h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
              />
              <span className="text-2xl font-bold text-white w-12 text-center">
                {settings.max_concurrent_builds}
              </span>
            </div>
            <p className="text-sm text-gray-400 mt-2">
              Maximum number of package builds that can run simultaneously (1-20)
            </p>
          </div>

          {/* Cleanup Builds After Days */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Cleanup Builds After (Days)
            </label>
            <input
              type="number"
              min="1"
              max="365"
              value={settings.cleanup_builds_after_days}
              onChange={(e) => handleChange('cleanup_builds_after_days', parseInt(e.target.value))}
              disabled={!isAdmin}
              className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
            />
            <p className="text-sm text-gray-400 mt-2">
              Remove build artifacts older than this many days (1-365)
            </p>
          </div>
        </div>
      </div>

      {/* Sync Settings */}
      <div className="bg-gray-800 rounded-lg shadow-lg p-6 border border-gray-700">
        <h2 className="text-xl font-semibold text-white mb-6">Sync Settings</h2>
        
        <div className="space-y-6">
          {/* Auto Sync Projects */}
          <div className="flex items-center justify-between">
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-300 mb-1">
                Auto Sync Projects
              </label>
              <p className="text-sm text-gray-400">
                Automatically sync projects from git repositories
              </p>
            </div>
            <button
              onClick={() => handleChange('auto_sync_projects', !settings.auto_sync_projects)}
              disabled={!isAdmin}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-800 disabled:opacity-50 disabled:cursor-not-allowed ${
                settings.auto_sync_projects ? 'bg-blue-500' : 'bg-gray-600'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  settings.auto_sync_projects ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>

          {/* Sync Interval Hours */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Project Sync Interval (Hours)
            </label>
            <input
              type="number"
              min="1"
              max="24"
              value={settings.sync_interval_hours}
              onChange={(e) => handleChange('sync_interval_hours', parseInt(e.target.value))}
              disabled={!isAdmin}
              className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
            />
            <p className="text-sm text-gray-400 mt-2">
              Hours between automatic project syncs (1-24)
            </p>
          </div>

          {/* Cleanup Repos After Days */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Cleanup Git Repos After (Days)
            </label>
            <input
              type="number"
              min="1"
              max="90"
              value={settings.cleanup_repos_after_days}
              onChange={(e) => handleChange('cleanup_repos_after_days', parseInt(e.target.value))}
              disabled={!isAdmin}
              className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
            />
            <p className="text-sm text-gray-400 mt-2">
              Remove old git repository clones after this many days (1-90)
            </p>
          </div>
        </div>
      </div>

      {/* Repository Settings */}
      <div className="bg-gray-800 rounded-lg shadow-lg p-6 border border-gray-700">
        <h2 className="text-xl font-semibold text-white mb-6">Repository Settings</h2>
        
        <div className="space-y-6">
          {/* Repository Sync Interval */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Repository Sync Interval (Minutes)
            </label>
            <input
              type="number"
              min="5"
              max="1440"
              value={settings.repository_sync_interval_minutes}
              onChange={(e) => handleChange('repository_sync_interval_minutes', parseInt(e.target.value))}
              disabled={!isAdmin}
              className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
            />
            <p className="text-sm text-gray-400 mt-2">
              Minutes between repository metadata syncs (5-1440)
            </p>
          </div>
        </div>
      </div>

      {/* Save Button */}
      {isAdmin && (
        <div className="flex justify-end">
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center space-x-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Save size={20} />
            <span>{saving ? 'Saving...' : 'Save Settings'}</span>
          </button>
        </div>
      )}

      {/* Timestamps */}
      <div className="text-sm text-gray-500 text-center space-y-1">
        <div>Last updated: {new Date(settings.updated_at).toLocaleString()}</div>
        <div>Created: {new Date(settings.created_at).toLocaleString()}</div>
      </div>
    </div>
  );
}
