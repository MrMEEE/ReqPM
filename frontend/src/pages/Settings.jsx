import { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { Settings as SettingsIcon, Save, AlertCircle, CheckCircle, Activity, Bot, Download, Zap } from 'lucide-react';
import { settingsAPI } from '../lib/api';

export default function Settings() {
  const { user } = useAuth();
  const [settings, setSettings] = useState(null);
  const [buildStatus, setBuildStatus] = useState(null);
  const [aiStatus, setAiStatus] = useState(null);
  const [aiTesting, setAiTesting] = useState(false);
  const [aiTestResult, setAiTestResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);

  const isAdmin = user?.is_staff || user?.is_superuser;

  useEffect(() => {
    loadSettings();
    loadBuildStatus();
    loadAiStatus();
    
    // Refresh build status every 5 seconds
    const interval = setInterval(loadBuildStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  // Poll AI status more frequently while a download is in progress
  useEffect(() => {
    const downloading = aiStatus?.models?.some(
      (m) => m.download?.state === 'downloading'
    );
    if (!downloading) return;
    const interval = setInterval(loadAiStatus, 2000);
    return () => clearInterval(interval);
  }, [aiStatus]);

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

  const loadAiStatus = async () => {
    try {
      const response = await settingsAPI.aiStatus();
      setAiStatus(response.data);
    } catch (err) {
      console.error('Failed to load AI status:', err);
    }
  };

  const handleDownloadModel = async (modelKey) => {
    try {
      await settingsAPI.aiDownloadModel(modelKey);
      await loadAiStatus();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to start download');
    }
  };

  const handleAiTest = async () => {
    setAiTesting(true);
    setAiTestResult(null);
    try {
      const response = await settingsAPI.aiTest();
      setAiTestResult(response.data);
    } catch (err) {
      setAiTestResult({ ok: false, detail: err.response?.data?.detail || 'Test failed' });
    } finally {
      setAiTesting(false);
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

      {/* AI Fixer Settings */}
      <div className="bg-gray-800 rounded-lg shadow-lg p-6 border border-gray-700">
        <div className="flex items-center space-x-2 mb-6">
          <Bot className="text-purple-500" size={24} />
          <h2 className="text-xl font-semibold text-white">AI Build Fixer</h2>
        </div>

        <div className="space-y-6">
          {/* Enable toggle */}
          <div className="flex items-center justify-between">
            <div className="flex-1">
              <label className="block text-sm font-medium text-gray-300 mb-1">
                Enable AI Fixer
              </label>
              <p className="text-sm text-gray-400">
                Use a local LLM as a fallback when rule-based build fixers can't resolve an error
              </p>
            </div>
            <button
              onClick={() => handleChange('ai_fixer_enabled', !settings.ai_fixer_enabled)}
              disabled={!isAdmin}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2 focus:ring-offset-gray-800 disabled:opacity-50 disabled:cursor-not-allowed ${
                settings.ai_fixer_enabled ? 'bg-purple-500' : 'bg-gray-600'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  settings.ai_fixer_enabled ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>

          {/* Backend select */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Backend
            </label>
            <select
              value={settings.ai_fixer_backend}
              onChange={(e) => handleChange('ai_fixer_backend', e.target.value)}
              disabled={!isAdmin}
              className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white focus:outline-none focus:border-purple-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <option value="builtin">Built-in (llama.cpp — no external services)</option>
              <option value="ollama">Ollama</option>
              <option value="openai">OpenAI-compatible API</option>
            </select>
          </div>

          {/* Builtin backend: runtime status + model catalog */}
          {settings.ai_fixer_backend === 'builtin' && (
            <div className="space-y-4">
              {aiStatus && !aiStatus.builtin_runtime_available && (
                <div className="bg-yellow-900/50 border border-yellow-500 rounded-lg p-4">
                  <div className="flex items-center space-x-2 mb-1">
                    <AlertCircle className="text-yellow-500" size={18} />
                    <span className="text-yellow-200 font-medium">Runtime not installed</span>
                  </div>
                  <p className="text-sm text-yellow-200/80">
                    Install the inference runtime in the ReqPM virtualenv, then restart:
                  </p>
                  <code className="block mt-2 px-3 py-2 bg-gray-900 rounded text-sm text-yellow-100">
                    pip install llama-cpp-python && ./reqpm.sh restart
                  </code>
                </div>
              )}

              <label className="block text-sm font-medium text-gray-300">
                Model
              </label>
              <div className="space-y-2">
                {aiStatus?.models?.map((m) => (
                  <div
                    key={m.key}
                    onClick={() => isAdmin && handleChange('ai_fixer_model', m.key)}
                    className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                      settings.ai_fixer_model === m.key
                        ? 'border-purple-500 bg-purple-900/20'
                        : 'border-gray-600 bg-gray-900/30 hover:border-gray-500'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-3">
                        <input
                          type="radio"
                          checked={settings.ai_fixer_model === m.key}
                          onChange={() => handleChange('ai_fixer_model', m.key)}
                          disabled={!isAdmin}
                          className="accent-purple-500"
                        />
                        <div>
                          <div className="text-white text-sm">{m.label}</div>
                          {m.downloaded ? (
                            <div className="text-xs text-green-400 flex items-center mt-1">
                              <CheckCircle size={12} className="mr-1" /> Downloaded
                            </div>
                          ) : m.download?.state === 'downloading' ? (
                            <div className="mt-2 w-64">
                              <div className="flex justify-between text-xs text-gray-400 mb-1">
                                <span>Downloading…</span>
                                <span>
                                  {m.download.downloaded_mb} / {m.download.total_mb} MB
                                </span>
                              </div>
                              <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                                <div
                                  className="h-full bg-purple-500 transition-all"
                                  style={{ width: `${m.download.progress}%` }}
                                />
                              </div>
                            </div>
                          ) : m.download?.state === 'error' ? (
                            <div className="text-xs text-red-400 mt-1">
                              Download failed: {m.download.error}
                            </div>
                          ) : (
                            <div className="text-xs text-gray-500 mt-1">Not downloaded</div>
                          )}
                        </div>
                      </div>
                      {isAdmin && !m.downloaded && m.download?.state !== 'downloading' && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDownloadModel(m.key);
                          }}
                          className="flex items-center space-x-1 px-3 py-1.5 bg-purple-600 hover:bg-purple-700 text-white text-sm rounded-lg transition-colors"
                        >
                          <Download size={14} />
                          <span>Download</span>
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Ollama / OpenAI backend settings */}
          {settings.ai_fixer_backend !== 'builtin' && (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Model Name
                </label>
                <input
                  type="text"
                  value={settings.ai_fixer_model}
                  onChange={(e) => handleChange('ai_fixer_model', e.target.value)}
                  disabled={!isAdmin}
                  placeholder={settings.ai_fixer_backend === 'ollama' ? 'qwen2.5-coder:7b' : 'gpt-4o-mini'}
                  className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-purple-500 disabled:opacity-50 disabled:cursor-not-allowed"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Base URL
                </label>
                <input
                  type="text"
                  value={settings.ai_fixer_base_url}
                  onChange={(e) => handleChange('ai_fixer_base_url', e.target.value)}
                  disabled={!isAdmin}
                  placeholder={settings.ai_fixer_backend === 'ollama' ? 'http://localhost:11434' : 'https://api.openai.com'}
                  className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-purple-500 disabled:opacity-50 disabled:cursor-not-allowed"
                />
              </div>
              {settings.ai_fixer_backend === 'openai' && (
                <div>
                  <label className="block text-sm font-medium text-gray-300 mb-2">
                    API Key
                  </label>
                  <input
                    type="password"
                    value={settings.ai_fixer_api_key || ''}
                    onChange={(e) => handleChange('ai_fixer_api_key', e.target.value)}
                    disabled={!isAdmin}
                    placeholder="Leave empty to keep current key"
                    className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-purple-500 disabled:opacity-50 disabled:cursor-not-allowed"
                  />
                </div>
              )}
            </div>
          )}

          {/* Timeout */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Request Timeout (Seconds)
            </label>
            <input
              type="number"
              min="30"
              max="1800"
              value={settings.ai_fixer_timeout}
              onChange={(e) => handleChange('ai_fixer_timeout', parseInt(e.target.value))}
              disabled={!isAdmin}
              className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-purple-500 disabled:opacity-50 disabled:cursor-not-allowed"
            />
            <p className="text-sm text-gray-400 mt-2">
              CPU inference can be slow — 300s is a good default for 3-7B models (30-1800)
            </p>
          </div>

          {/* Max attempts */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Max Fix Attempts Per Package
            </label>
            <input
              type="number"
              min="1"
              max="10"
              value={settings.ai_fixer_max_attempts}
              onChange={(e) => handleChange('ai_fixer_max_attempts', parseInt(e.target.value))}
              disabled={!isAdmin}
              className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-purple-500 disabled:opacity-50 disabled:cursor-not-allowed"
            />
            <p className="text-sm text-gray-400 mt-2">
              How many times the AI fixer will retry a single package before giving up (1-10)
            </p>
          </div>

          {/* Max concurrent */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Max Concurrent AI Fixes
            </label>
            <input
              type="number"
              min="1"
              max="10"
              value={settings.ai_fixer_max_concurrent}
              onChange={(e) => handleChange('ai_fixer_max_concurrent', parseInt(e.target.value))}
              disabled={!isAdmin}
              className="w-full px-4 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:border-purple-500 disabled:opacity-50 disabled:cursor-not-allowed"
            />
            <p className="text-sm text-gray-400 mt-2">
              How many packages the AI fixer may work on at the same time. Others will wait until a slot is free (1-10). Keep at 1 on low-RAM machines.
            </p>
          </div>

          {/* Test button */}
          {isAdmin && (
            <div>
              <button
                onClick={handleAiTest}
                disabled={aiTesting}
                className="flex items-center space-x-2 px-4 py-2 bg-gray-700 hover:bg-gray-600 border border-gray-600 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Zap size={16} className={aiTesting ? 'animate-pulse text-yellow-400' : 'text-purple-400'} />
                <span>{aiTesting ? 'Testing… (may take a minute on CPU)' : 'Test AI Backend'}</span>
              </button>
              {aiTestResult && (
                <div className={`mt-3 p-3 rounded-lg text-sm ${
                  aiTestResult.ok
                    ? 'bg-green-900/50 border border-green-500 text-green-200'
                    : 'bg-red-900/50 border border-red-500 text-red-200'
                }`}>
                  {aiTestResult.detail}
                </div>
              )}
              <p className="text-sm text-gray-400 mt-2">
                Note: save settings before testing — the test uses the saved configuration
              </p>
            </div>
          )}
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
