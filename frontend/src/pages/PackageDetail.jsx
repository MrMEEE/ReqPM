import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Package as PackageIcon, AlertCircle, GitBranch, FileCode, Box, Edit2, Save, X, RefreshCw, Puzzle, Hammer } from 'lucide-react';
import { packagesAPI } from '../lib/api';
import { useState } from 'react';

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
  const queryClient = useQueryClient();
  
  const [editingSpec, setEditingSpec] = useState(null);
  const [specContent, setSpecContent] = useState('');
  const [commitMessage, setCommitMessage] = useState('');
  const [regenerating, setRegenerating] = useState(false);

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
      alert('Spec content cannot be empty');
      return;
    }
    if (!commitMessage.trim()) {
      alert('Commit message is required');
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
        <StatusBadge status={pkg.status} />
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
                    </div>
                    <button
                      onClick={() => handleEditSpec(spec)}
                      className="text-indigo-400 hover:text-indigo-300 text-sm flex items-center gap-1"
                    >
                      <Edit2 className="h-3 w-3" />
                      Edit
                    </button>
                  </div>
                  <p className="text-sm text-gray-400 mb-2">{spec.commit_message}</p>
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
            Builds ({builds.length})
          </h2>
          <div className="space-y-3">
            {builds.map((build) => (
              <div
                key={build.id}
                className="p-4 bg-gray-700/50 rounded border border-gray-600 hover:border-gray-500 transition-colors"
              >
                <div className="flex items-start justify-between">
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
                          : build.status === 'running'
                          ? 'bg-blue-100 text-blue-800'
                          : 'bg-gray-600 text-gray-300'
                      }`}>
                        {build.status}
                      </span>
                      <span className="px-2 py-1 bg-gray-700 text-gray-300 text-xs rounded">
                        RHEL {build.rhel_version}
                      </span>
                    </div>
                    {build.rpm_file && (
                      <div className="text-sm text-gray-400 mb-1">
                        <span className="font-medium">RPM:</span> {build.rpm_file.split('/').pop()}
                      </div>
                    )}
                    {build.srpm_file && (
                      <div className="text-sm text-gray-400 mb-1">
                        <span className="font-medium">SRPM:</span> {build.srpm_file.split('/').pop()}
                      </div>
                    )}
                    {build.built_at && (
                      <div className="text-xs text-gray-500 mt-2">
                        Built: {new Date(build.built_at).toLocaleString()}
                      </div>
                    )}
                  </div>
                  <div className="flex gap-2">
                    {build.rpm_file && (
                      <a
                        href={build.rpm_file}
                        download
                        className="px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm rounded transition-colors"
                      >
                        Download RPM
                      </a>
                    )}
                    {build.srpm_file && (
                      <a
                        href={build.srpm_file}
                        download
                        className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded transition-colors"
                      >
                        Download SRPM
                      </a>
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
          <button
            onClick={handleRegenerateSpec}
            disabled={regenerating}
            className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white text-sm rounded-lg transition-colors"
          >
            {regenerating ? 'Regenerating...' : 'Regenerate Spec'}
          </button>
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
    </div>
  );
}
