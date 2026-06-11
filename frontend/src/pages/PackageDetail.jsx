import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Package as PackageIcon, AlertCircle, GitBranch, FileCode, Box, Edit2, Save, X, RefreshCw, Puzzle, Hammer, Download, Terminal, Wrench } from 'lucide-react';
import { packagesAPI } from '../lib/api';
import { useState, useEffect } from 'react';
import { useToast } from '../contexts/ToastContext';
import LivePackageBuildLog from '../components/LivePackageBuildLog';

const StatusBadge = ({ status }) => {
  const statusConfig = {
    pending: { color: 'bg-gray-100 text-gray-800', label: 'Pending' },
    ready: { color: 'bg-green-100 text-green-800', label: 'Ready' },
    building: { color: 'bg-blue-100 text-blue-800', label: 'Building' },
    built: { color: 'bg-green-100 text-green-800', label: 'Built' },
    failed: { color: 'bg-red-100 text-red-800', label: 'Failed' },
  };

  const config = statusConfig[status] || statusConfig.pending;

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${config.color}`}>
      {config.label}
    </span>
  );
};

export default function PackageDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient()

  // Poll for live updates when package is in an active build state
  useEffect(() => {
    const interval = setInterval(() => {
      const pkg = queryClient.getQueryData(['package', id])
      if (['building', 'pending', 'waiting_for_deps', 'dep_build_pending'].includes(pkg?.build_status)) {
        queryClient.invalidateQueries({ queryKey: ['package', id] })
        queryClient.invalidateQueries({ queryKey: ['package-specs', id] })
      }
    }, 3000)
    return () => clearInterval(interval)
  }, [id]);
  const toast = useToast();
  
  const [editingSpec, setEditingSpec] = useState(null);
  const [specContent, setSpecContent] = useState('');
  const [commitMessage, setCommitMessage] = useState('');
  const [regenerating, setRegenerating] = useState(false);
  const [showBuildLog, setShowBuildLog] = useState(false);

  const { data: pkg, isLoading, error } = useQuery({
    queryKey: ['package', id],
    queryFn: async () => {
      const response = await packagesAPI.get(id);
      return response.data;
    },
  });

  const { data: dependencies } = useQuery({
    queryKey: ['package-dependencies', id],
    queryFn: async () => {
      const response = await packagesAPI.dependencies(id);
      return response.data;
    },
    enabled: !!pkg,
  });

  const { data: specFiles } = useQuery({
    queryKey: ['package-specs', id],
    queryFn: async () => {
      const response = await packagesAPI.specFiles(id);
      return response.data;
    },
    enabled: !!pkg,
  });

  const { data: logs } = useQuery({
    queryKey: ['package-logs', id],
    queryFn: async () => {
      const response = await packagesAPI.logs(id, { limit: 50 });
      return response.data;
    },
    enabled: !!pkg,
  });

  const { data: extras, isLoading: extrasLoading } = useQuery({
    queryKey: ['package-extras', id],
    queryFn: async () => {
      const response = await packagesAPI.extras(id);
      return response.data;
    },
    enabled: !!pkg,
  });

  const { data: builds } = useQuery({
    queryKey: ['package-builds', id],
    queryFn: async () => {
      const response = await packagesAPI.builds(id);
      return response.data;
    },
    enabled: !!pkg,
  });

  const syncExtrasMutation = useMutation({
    mutationFn: async () => {
      const response = await packagesAPI.syncExtras(id);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['package-extras', id]);
      queryClient.invalidateQueries(['package-logs', id]);
    },
  });

  const toggleExtraMutation = useMutation({
    mutationFn: async ({ extraId, enabled }) => {
      const response = await packagesAPI.updateExtra(id, extraId, { enabled });
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['package-extras', id]);
      queryClient.invalidateQueries(['package-specs', id]);
      queryClient.invalidateQueries(['package-logs', id]);
    },
  });

  const fetchSourceMutation = useMutation({
    mutationFn: async () => {
      const response = await packagesAPI.fetchSource(id);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['package-logs', id]);
    },
    onError: (error) => {
      toast.error(`Failed to fetch source: ${error.response?.data?.detail || error.message}`);
    },
  });

  const buildPackageMutation = useMutation({
    mutationFn: async () => {
      const response = await packagesAPI.buildPackage(id);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['package', id]);
      queryClient.invalidateQueries(['package-builds', id]);
      queryClient.invalidateQueries(['package-logs', id]);
      setShowBuildLog(true);
    },
    onError: (error) => {
      toast.error(`Failed to build package: ${error.response?.data?.detail || error.message}`);
    },
  });

  const rebuildPackageMutation = useMutation({
    mutationFn: async () => {
      const response = await packagesAPI.rebuildPackage(id);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['package', id]);
      queryClient.invalidateQueries(['package-builds', id]);
      queryClient.invalidateQueries(['package-logs', id]);
      setShowBuildLog(true);
    },
    onError: (error) => {
      toast.error(`Failed to rebuild package: ${error.response?.data?.detail || error.message}`);
    },
  });

  const cancelBuildMutation = useMutation({
    mutationFn: async () => {
      const response = await packagesAPI.cancelBuild(id);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['package', id]);
    },
    onError: (error) => {
      toast.error(`Failed to cancel build: ${error.response?.data?.detail || error.message}`);
    },
  });

  const fixAndRebuildMutation = useMutation({
    mutationFn: async () => {
      const response = await packagesAPI.fixAndRebuild(id);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['package', id]);
      queryClient.invalidateQueries(['package-builds', id]);
      queryClient.invalidateQueries(['package-logs', id]);
      setShowBuildLog(true);
    },
    onError: (error) => {
      toast.error(`Failed to fix & rebuild: ${error.response?.data?.detail || error.message}`);
    },
  });

  const saveSpecMutation = useMutation({
    mutationFn: async ({ content, commit_message }) => {
      const response = await packagesAPI.specFiles(id, {
        content,
        commit_message,
      });
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['package-specs', id]);
      queryClient.invalidateQueries(['package-logs', id]);
      setEditingSpec(null);
      setSpecContent('');
      setCommitMessage('');
    },
  });

  const handleEditSpec = (spec) => {
    setEditingSpec(spec.id);
    setSpecContent(spec.content);
    setCommitMessage('');
  };

  const handleSaveSpec = () => {
    if (!specContent.trim()) {
      toast.warning('Spec content cannot be empty');
      return;
    }
    if (!commitMessage.trim()) {
      toast.warning('Commit message is required');
      return;
    }
    saveSpecMutation.mutate({
      content: specContent,
      commit_message: commitMessage,
    });
  };

  const handleCancelEdit = () => {
    setEditingSpec(null);
    setSpecContent('');
    setCommitMessage('');
  };

  const handleRegenerateSpec = async () => {
    if (regenerating) return;
    
    setRegenerating(true);
    try {
      await packagesAPI.generateSpec(id, { force: true });
      // Wait a bit for the task to complete
      setTimeout(() => {
        queryClient.invalidateQueries(['package-logs', id]);
        queryClient.invalidateQueries(['package-specs', id]);
        queryClient.invalidateQueries(['package', id]);
        setRegenerating(false);
      }, 3000);
    } catch (error) {
      console.error('Failed to regenerate spec:', error);
      setRegenerating(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-900/50 border border-red-700 rounded-lg p-4">
        <div className="flex items-center gap-2">
          <AlertCircle className="h-5 w-5 text-red-400" />
          <span className="text-red-200">Failed to load package: {error.message}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate(-1)}
            className="p-2 hover:bg-gray-800 rounded-lg transition-colors"
          >
            <ArrowLeft className="h-5 w-5 text-gray-400" />
          </button>
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <PackageIcon className="h-7 w-7" />
              {pkg.name}
            </h1>
            {pkg.description && (
              <p className="text-gray-400 mt-1">{pkg.description}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap justify-end">
          <StatusBadge status={pkg.status} />

          {/* Live Log — only while building */}
          {pkg.build_status === 'building' && (
            <button
              onClick={() => setShowBuildLog(true)}
              className="px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center gap-1.5 text-sm animate-pulse"
              title="View live build log"
            >
              <Terminal className="h-3.5 w-3.5" />
              Live Log
            </button>
          )}

          {/* Log — when there is something to show and not actively building */}
          {!['building', 'pending', 'waiting_for_deps'].includes(pkg.build_status) &&
            (pkg.has_build_log || pkg.build_error_message ||
              ['completed', 'failed', 'missing_packages', 'dep_build_pending'].includes(pkg.build_status) ||
              ['built', 'failed'].includes(pkg.status) ||
              builds?.some(b => b.build_log)) && (
            <button
              onClick={() => setShowBuildLog(true)}
              className="px-3 py-1.5 bg-gray-700 text-white rounded-lg hover:bg-gray-600 flex items-center gap-1.5 text-sm"
              title="View build log"
            >
              <Terminal className="h-3.5 w-3.5" />
              Log
            </button>
          )}

          {/* Gen Spec */}
          <button
            onClick={handleRegenerateSpec}
            disabled={regenerating}
            className="px-3 py-1.5 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5 text-sm"
            title={regenerating ? 'Generating spec…' : 'Generate / refresh SPEC file'}
          >
            <FileCode className="h-3.5 w-3.5" />
            {regenerating ? 'Generating…' : 'Gen Spec'}
          </button>

          {/* Fetch Source */}
          <button
            onClick={() => fetchSourceMutation.mutate()}
            disabled={fetchSourceMutation.isPending || !specFiles || specFiles.length === 0}
            className="px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5 text-sm"
            title={!specFiles || specFiles.length === 0 ? 'Generate spec file first' : 'Fetch source files'}
          >
            <Download className="h-3.5 w-3.5" />
            {fetchSourceMutation.isPending ? 'Fetching…' : 'Fetch'}
          </button>

          {/* Cancel / Build / Rebuild */}
          {['waiting_for_deps', 'dep_build_pending', 'missing_packages', 'pending', 'building'].includes(pkg.build_status) ? (
            <button
              onClick={() => cancelBuildMutation.mutate()}
              disabled={cancelBuildMutation.isPending}
              className="px-3 py-1.5 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5 text-sm"
              title={pkg.build_status === 'building' ? 'Cancel running build' : 'Cancel waiting build'}
            >
              <X className="h-3.5 w-3.5" />
              Cancel
            </button>
          ) : pkg.build_status === 'not_built' ? (
            <button
              onClick={() => buildPackageMutation.mutate()}
              disabled={!pkg.source_fetched || !specFiles?.length || buildPackageMutation.isPending}
              className="px-3 py-1.5 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5 text-sm"
              title={!pkg.source_fetched ? 'Fetch source first' : !specFiles?.length ? 'Generate spec file first' : 'Build package'}
            >
              <Hammer className="h-3.5 w-3.5" />
              Build
            </button>
          ) : (
            <button
              onClick={() => rebuildPackageMutation.mutate()}
              disabled={!pkg.source_fetched || !specFiles?.length || rebuildPackageMutation.isPending || pkg.build_status === 'building'}
              className="px-3 py-1.5 bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5 text-sm"
              title="Rebuild package"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Rebuild
            </button>
          )}

          {/* Fix & Rebuild */}
          {['missing_packages', 'failed'].includes(pkg.build_status) && pkg.source_fetched && specFiles?.length > 0 && (
            <button
              onClick={() => fixAndRebuildMutation.mutate()}
              disabled={fixAndRebuildMutation.isPending}
              className="px-3 py-1.5 bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5 text-sm"
              title="Apply auto-fixes to spec and rebuild"
            >
              <Wrench className="h-3.5 w-3.5" />
              Fix &amp; Rebuild
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Package Information */}
        <div className="bg-gray-800 shadow rounded-lg p-6 border border-gray-700">
          <h2 className="text-lg font-semibold text-white mb-4">Package Information</h2>
          <div className="space-y-3">
            <div>
              <label className="text-sm font-medium text-gray-400">Version</label>
              <p className="text-gray-200">{pkg.version || 'Not specified'}</p>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-400">Type</label>
              <p className="text-gray-200">
                <span className="px-2 py-1 bg-gray-700 text-gray-300 text-xs rounded">
                  {pkg.package_type || 'dependency'}
                </span>
              </p>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-400">Build Order</label>
              <p className="text-gray-200">{pkg.build_order ?? 'Not set'}</p>
            </div>
            {pkg.project && (
              <div>
                <label className="text-sm font-medium text-gray-400">Project</label>
                <Link
                  to={`/projects/${pkg.project}`}
                  className="text-indigo-400 hover:text-indigo-300"
                >
                  View Project
                </Link>
              </div>
            )}
            {pkg.homepage && (
              <div>
                <label className="text-sm font-medium text-gray-400">Homepage</label>
                <a
                  href={pkg.homepage}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-indigo-400 hover:text-indigo-300"
                >
                  {pkg.homepage}
                </a>
              </div>
            )}
            {pkg.license && (
              <div>
                <label className="text-sm font-medium text-gray-400">License</label>
                <p className="text-gray-200">{pkg.license}</p>
              </div>
            )}
          </div>
        </div>

        {/* Spec Files */}
        <div className="bg-gray-800 shadow rounded-lg p-6 border border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <FileCode className="h-5 w-5" />
              Spec Files ({specFiles?.length || 0})
            </h2>
            {specFiles?.length > 0 && !editingSpec && (
              <button
                onClick={() => handleEditSpec(specFiles[0])}
                className="flex items-center gap-2 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-sm rounded-lg transition-colors"
              >
                <Edit2 className="h-4 w-4" />
                Edit Latest
              </button>
            )}
          </div>

          {editingSpec ? (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-2">
                  Spec File Content
                </label>
                <textarea
                  value={specContent}
                  onChange={(e) => setSpecContent(e.target.value)}
                  className="w-full h-96 px-3 py-2 bg-gray-900 border border-gray-600 rounded-lg text-gray-200 font-mono text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  placeholder="Enter spec file content..."
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-400 mb-2">
                  Commit Message
                </label>
                <input
                  type="text"
                  value={commitMessage}
                  onChange={(e) => setCommitMessage(e.target.value)}
                  className="w-full px-3 py-2 bg-gray-900 border border-gray-600 rounded-lg text-gray-200 text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  placeholder="Describe your changes..."
                />
              </div>
              <div className="flex gap-2">
                <button
                  onClick={handleSaveSpec}
                  disabled={saveSpecMutation.isPending}
                  className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 text-white rounded-lg transition-colors"
                >
                  <Save className="h-4 w-4" />
                  {saveSpecMutation.isPending ? 'Saving...' : 'Save Changes'}
                </button>
                <button
                  onClick={handleCancelEdit}
                  disabled={saveSpecMutation.isPending}
                  className="flex items-center gap-2 px-4 py-2 bg-gray-600 hover:bg-gray-700 disabled:bg-gray-500 text-white rounded-lg transition-colors"
                >
                  <X className="h-4 w-4" />
                  Cancel
                </button>
              </div>
            </div>
          ) : specFiles?.length > 0 ? (
            <div className="space-y-3">
              {specFiles.map((spec) => (
                <div
                  key={spec.id}
                  className="p-4 bg-gray-700/50 rounded border border-gray-600"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-3">
                      <span className="text-sm text-gray-300">
                        {new Date(spec.created_at).toLocaleString()}
                      </span>
                      {spec.git_commit_hash && (
                        <span className="text-xs font-mono text-gray-400 bg-gray-800 px-2 py-1 rounded">
                          {spec.git_commit_hash.substring(0, 7)}
                        </span>
                      )}
                      {spec.commit_message?.startsWith('AI-fixed:') && (
                        <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-purple-900/50 text-purple-300 border border-purple-700">
                          AI fixed
                        </span>
                      )}
                    </div>
                    <button
                      onClick={() => handleEditSpec(spec)}
                      className="text-indigo-400 hover:text-indigo-300 text-sm flex items-center gap-1"
                    >
                      <Edit2 className="h-3 w-3" />
                      Edit
                    </button>
                  </div>
                  {spec.commit_message?.startsWith('AI-fixed:') ? (() => {
                    const actions = spec.commit_message.slice('AI-fixed:'.length).split(';').map(s => s.trim()).filter(Boolean);
                    return (
                      <ul className="mt-1 mb-2 space-y-1">
                        {actions.map((action, i) => (
                          <li key={i} className="flex items-start gap-2 text-sm text-gray-300">
                            <span className="text-purple-400 mt-0.5 shrink-0">•</span>
                            {action}
                          </li>
                        ))}
                      </ul>
                    );
                  })() : (
                    <p className="text-sm text-gray-400 mb-2">{spec.commit_message}</p>
                  )}
                  {spec.content && (
                    <details className="mt-2">
                      <summary className="text-sm text-indigo-400 cursor-pointer hover:text-indigo-300">
                        View Content
                      </summary>
                      <pre className="mt-2 p-3 bg-gray-900 rounded text-xs text-gray-300 overflow-x-auto max-h-96 overflow-y-auto">
                        {spec.content}
                      </pre>
                    </details>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-400 text-sm">No spec files generated yet</p>
          )}
        </div>
      </div>

      {/* Package Extras */}
      <div className="bg-gray-800 shadow rounded-lg p-6 border border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Puzzle className="h-5 w-5" />
            Package Extras ({extras?.length || 0})
          </h2>
          <button
            onClick={() => syncExtrasMutation.mutate()}
            disabled={syncExtrasMutation.isPending}
            className="flex items-center gap-2 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-600 text-white text-sm rounded-lg transition-colors"
          >
            <RefreshCw className={`h-4 w-4 ${syncExtrasMutation.isPending ? 'animate-spin' : ''}`} />
            {syncExtrasMutation.isPending ? 'Syncing...' : 'Sync from PyPI'}
          </button>
        </div>

        {extrasLoading ? (
          <p className="text-gray-400 text-sm">Loading extras...</p>
        ) : extras && extras.length > 0 ? (
          <div className="space-y-2">
            {extras.map((extra) => (
              <div
                key={extra.id}
                className="flex items-start justify-between p-4 bg-gray-700/50 rounded border border-gray-600 hover:border-gray-500 transition-colors"
              >
                <div className="flex-1">
                  <div className="flex items-center gap-3">
                    <code className="text-sm font-semibold text-indigo-300">
                      {pkg.name}[{extra.name}]
                    </code>
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      extra.enabled 
                        ? 'bg-green-100 text-green-800' 
                        : 'bg-gray-600 text-gray-300'
                    }`}>
                      {extra.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                  </div>
                  {extra.dependencies && (
                    <p className="text-xs text-gray-400 mt-2">
                      Dependencies: {extra.dependencies}
                    </p>
                  )}
                  <p className="text-xs text-gray-500 mt-1">
                    Last updated: {new Date(extra.updated_at).toLocaleString()}
                  </p>
                </div>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={extra.enabled}
                    onChange={(e) => {
                      toggleExtraMutation.mutate({
                        extraId: extra.id,
                        enabled: e.target.checked,
                      });
                    }}
                    disabled={toggleExtraMutation.isPending}
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-gray-600 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-indigo-800 rounded-full peer peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-indigo-600"></div>
                </label>
              </div>
            ))}
            <div className="mt-4 p-3 bg-blue-900/20 border border-blue-700/50 rounded">
              <p className="text-xs text-blue-300">
                <strong>Note:</strong> Enabling or disabling extras will automatically regenerate the spec file to include or exclude the extra dependencies.
              </p>
            </div>
          </div>
        ) : (
          <div className="text-center py-8">
            <p className="text-gray-400 text-sm mb-3">No extras available for this package</p>
            <button
              onClick={() => syncExtrasMutation.mutate()}
              disabled={syncExtrasMutation.isPending}
              className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-600 text-white text-sm rounded-lg transition-colors"
            >
              <RefreshCw className={`h-4 w-4 ${syncExtrasMutation.isPending ? 'animate-spin' : ''}`} />
              {syncExtrasMutation.isPending ? 'Syncing...' : 'Sync from PyPI'}
            </button>
          </div>
        )}
      </div>

      {/* Package Builds */}
      {builds && builds.length > 0 && (
        <div className="bg-gray-800 shadow rounded-lg p-6 border border-gray-700">
          <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
            <Hammer className="h-5 w-5" />
            Build History ({builds.length})
          </h2>
          <div className="space-y-3">
            {builds.map((build) => (
              <div
                key={build.id}
                className="p-4 bg-gray-700/50 rounded border border-gray-600 hover:border-gray-500 transition-colors"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <Link
                        to={`/builds/${build.build_job}`}
                        className="text-indigo-400 hover:text-indigo-300 font-medium"
                      >
                        Build #{build.build_job}
                      </Link>
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        build.status === 'completed' 
                          ? 'bg-green-100 text-green-800' 
                          : build.status === 'failed'
                          ? 'bg-red-100 text-red-800'
                          : build.status === 'building'
                          ? 'bg-blue-100 text-blue-800'
                          : 'bg-gray-600 text-gray-300'
                      }`}>
                        {build.status}
                      </span>
                      <span className="px-2 py-1 bg-gray-700 text-gray-300 text-xs rounded">
                        RHEL {build.rhel_version}
                      </span>
                    </div>
                    
                    {/* Error Analysis */}
                    {build.analyzed_errors && build.analyzed_errors.length > 0 && (
                      <div className="mb-3 space-y-2">
                        {build.analyzed_errors.map((error, idx) => (
                          <div key={idx} className="bg-yellow-900/20 border border-yellow-700/50 rounded p-2">
                            <div className="text-xs font-medium text-yellow-300 mb-1">
                              ⚠️ {error.category}
                            </div>
                            {error.items && error.items.length > 0 && (
                              <div className="text-xs text-gray-400 mb-1">
                                {error.items.slice(0, 3).map((item, i) => (
                                  <div key={i} className="font-mono">• {item}</div>
                                ))}
                                {error.items.length > 3 && (
                                  <div className="text-gray-500">... and {error.items.length - 3} more</div>
                                )}
                              </div>
                            )}
                            {error.suggestion && (
                              <div className="text-xs text-indigo-300">
                                💡 {error.suggestion}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                    
                    {build.rpm_path && (
                      <div className="text-sm text-gray-400 mb-1">
                        <span className="font-medium">RPM:</span> {build.rpm_path.split('/').pop()}
                      </div>
                    )}
                    {build.srpm_path && (
                      <div className="text-sm text-gray-400 mb-1">
                        <span className="font-medium">SRPM:</span> {build.srpm_path.split('/').pop()}
                      </div>
                    )}
                    {build.completed_at && (
                      <div className="text-xs text-gray-500 mt-2">
                        Completed: {new Date(build.completed_at).toLocaleString()}
                      </div>
                    )}
                  </div>
                  <div className="flex gap-2">
                    {build.rpm_path && (
                      <button
                        onClick={async () => {
                          try {
                            const response = await packagesAPI.downloadRpm(pkg.id);
                            const url = window.URL.createObjectURL(response.data);
                            const link = document.createElement('a');
                            link.href = url;
                            link.download = build.rpm_path.split('/').pop();
                            document.body.appendChild(link);
                            link.click();
                            document.body.removeChild(link);
                            window.URL.revokeObjectURL(url);
                          } catch (error) {
                            console.error('Download failed:', error);
                          }
                        }}
                        className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm rounded transition-colors"
                      >
                        Download RPM
                      </button>
                    )}
                    {build.srpm_path && (
                      <button
                        onClick={async () => {
                          try {
                            const response = await packagesAPI.downloadSrpm(pkg.id);
                            const url = window.URL.createObjectURL(response.data);
                            const link = document.createElement('a');
                            link.href = url;
                            link.download = build.srpm_path.split('/').pop();
                            document.body.appendChild(link);
                            link.click();
                            document.body.removeChild(link);
                            window.URL.revokeObjectURL(url);
                          } catch (error) {
                            console.error('Download failed:', error);
                          }
                        }}
                        className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded transition-colors"
                      >
                        Download SRPM
                      </button>
                    )}
                  </div>
                </div>
                {build.build_log && (
                  <details className="mt-3">
                    <summary className="text-sm text-indigo-400 cursor-pointer hover:text-indigo-300">
                      View Build Log
                    </summary>
                    <pre className="mt-2 p-3 bg-gray-900 rounded text-xs text-gray-300 overflow-x-auto max-h-64 overflow-y-auto">
                      {build.build_log}
                    </pre>
                  </details>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Dependencies */}
      {dependencies && (dependencies.runtime?.length > 0 || dependencies.build?.length > 0) && (
        <div className="bg-gray-800 shadow rounded-lg p-6 border border-gray-700">
          <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
            <Box className="h-5 w-5" />
            Dependencies
          </h2>
          
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {dependencies.runtime?.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-gray-400 mb-3">Runtime Dependencies</h3>
                <div className="space-y-1">
                  {dependencies.runtime.map((dep) => (
                    <div
                      key={dep.id}
                      className="text-sm text-gray-300 py-1 px-2 bg-gray-700/30 rounded"
                    >
                      {dep.depends_on_name}
                    </div>
                  ))}
                </div>
              </div>
            )}
            
            {dependencies.build?.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-gray-400 mb-3">Build Dependencies</h3>
                <div className="space-y-1">
                  {dependencies.build.map((dep) => (
                    <div
                      key={dep.id}
                      className="text-sm text-gray-300 py-1 px-2 bg-gray-700/30 rounded"
                    >
                      {dep.depends_on_name}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Package Logs */}
      <div className="bg-gray-800 shadow rounded-lg p-6 border border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white">Package Logs</h2>
          <div className="flex items-center gap-2">
            <button
              onClick={() => fetchSourceMutation.mutate()}
              disabled={fetchSourceMutation.isPending || !specFiles || specFiles.length === 0}
              className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors flex items-center gap-1"
              title={!specFiles || specFiles.length === 0 ? "Generate spec file first" : "Fetch source files"}
            >
              <Download className="h-3 w-3" />
              {fetchSourceMutation.isPending ? 'Fetching...' : 'Fetch Source'}
            </button>
            <button
              onClick={handleRegenerateSpec}
              disabled={regenerating}
              className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors"
            >
              {regenerating ? 'Regenerating...' : 'Regenerate Spec'}
            </button>
          </div>
        </div>
        
        {logs && logs.length > 0 ? (
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {logs.map((log) => {
              const levelColors = {
                debug: 'text-gray-400',
                info: 'text-blue-400',
                warning: 'text-yellow-400',
                error: 'text-red-400',
              };
              
              return (
                <div key={log.id} className="text-sm font-mono bg-gray-700/30 rounded px-3 py-2">
                  <span className="text-gray-500">
                    {new Date(log.timestamp).toLocaleString()}
                  </span>
                  {' '}
                  <span className={`font-semibold ${levelColors[log.level] || 'text-gray-400'}`}>
                    [{log.level.toUpperCase()}]
                  </span>
                  {' '}
                  <span className="text-gray-300">{log.message}</span>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-center py-8">
            <p className="text-gray-400 text-sm mb-2">No logs available yet</p>
            <p className="text-gray-500 text-xs">
              Logs will be created when the spec file is regenerated. Click "Regenerate Spec" above to create logs.
            </p>
          </div>
        )}
      </div>

      {/* Build Log Modal */}
      {showBuildLog && (
        <LivePackageBuildLog
          packageId={parseInt(id)}
          packageName={pkg.name}
          onClose={() => setShowBuildLog(false)}
        />
      )}
    </div>
  );
}
