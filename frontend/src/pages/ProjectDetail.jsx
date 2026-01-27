import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, GitBranch, Package, AlertCircle, CheckCircle, Clock, XCircle, Edit2, RefreshCw, ChevronLeft, ChevronRight, Hammer } from 'lucide-react';
import { useState, useEffect, useRef } from 'react';
import { projectsAPI, buildsAPI } from '../lib/api';
import { MockStatus } from '../components/SystemHealthBanner';
import ConfirmDialog from '../components/ConfirmDialog';

const StatusBadge = ({ status }) => {
  const statusConfig = {
    pending: { icon: Clock, color: 'bg-gray-100 text-gray-800', label: 'Pending' },
    cloning: { icon: Clock, color: 'bg-blue-100 text-blue-800', label: 'Cloning' },
    analyzing: { icon: Clock, color: 'bg-yellow-100 text-yellow-800', label: 'Analyzing' },
    ready: { icon: CheckCircle, color: 'bg-green-100 text-green-800', label: 'Ready' },
    failed: { icon: XCircle, color: 'bg-red-100 text-red-800', label: 'Failed' },
  };

  const config = statusConfig[status] || statusConfig.pending;
  const Icon = config.icon;

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${config.color}`}>
      <Icon className="w-3.5 h-3.5" />
      {config.label}
    </span>
  );
};

export default function ProjectDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [showEditRequirements, setShowEditRequirements] = useState(false);
  const [showLogs, setShowLogs] = useState(false);
  const [showEditConfig, setShowEditConfig] = useState(false);
  const [showRegenerateConfirm, setShowRegenerateConfirm] = useState(false);
  const [packagesPage, setPackagesPage] = useState(1);
  const [packagesPageSize] = useState(10);

  const { data: project, isLoading, error } = useQuery({
    queryKey: ['project', id],
    queryFn: async () => {
      const response = await projectsAPI.get(id);
      return response.data;
    },
    refetchInterval: (data) => {
      // Auto-refresh every 3 seconds if project is processing
      const status = data?.status;
      return ['pending', 'cloning', 'analyzing'].includes(status) ? 3000 : false;
    },
  });

  const { data: packagesData } = useQuery({
    queryKey: ['project-packages', id, packagesPage, packagesPageSize],
    queryFn: async () => {
      const response = await projectsAPI.packages(id, packagesPage, packagesPageSize);
      return response.data;
    },
    enabled: !!project,
  });

  const retryMutation = useMutation({
    mutationFn: (id) => projectsAPI.sync(id),
    onSuccess: () => {
      queryClient.invalidateQueries(['project', id]);
    },
  });

  const createBuildMutation = useMutation({
    mutationFn: async () => {
      const response = await buildsAPI.create({
        project: parseInt(id),
      });
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries(['builds']);
      // Navigate to builds page filtered by this project
      navigate(`/builds?project=${id}`);
    },
    onError: (error) => {
      alert(`Failed to start build: ${error.response?.data?.detail || error.message}`);
    },
  });

  const regenerateSpecsMutation = useMutation({
    mutationFn: async () => {
      const response = await projectsAPI.generateSpecs(id);
      return response.data;
    },
    onSuccess: () => {
      setShowRegenerateConfirm(false);
      queryClient.invalidateQueries(['project', id]);
      queryClient.invalidateQueries(['project-packages', id]);
      // Show logs automatically so user can see progress
      setShowLogs(true);
    },
    onError: (error) => {
      setShowRegenerateConfirm(false);
      alert(`Failed to regenerate specs: ${error.response?.data?.detail || error.message}`);
    },
  });

  const handleRegenerateSpecs = () => {
    setShowRegenerateConfirm(false);
    regenerateSpecsMutation.mutate();
  };

  const handleStartBuild = () => {
    // Check if project has required configuration
    if (!project.rhel_versions || project.rhel_versions.length === 0) {
      alert('Please configure RHEL versions in project settings before building');
      return;
    }
    createBuildMutation.mutate();
  };

  // Auto-show logs when processing
  useEffect(() => {
    if (project && ['pending', 'cloning', 'analyzing'].includes(project.status)) {
      setShowLogs(true);
    }
  }, [project?.status]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <div className="flex items-center gap-2">
          <AlertCircle className="h-5 w-5 text-red-600" />
          <span className="text-red-800">Failed to load project: {error.message}</span>
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
            onClick={() => navigate('/projects')}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <ArrowLeft className="h-5 w-5 text-gray-600" />
          </button>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{project.name}</h1>
            {project.description && (
              <p className="text-gray-600 mt-1">{project.description}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3">
          {project.status === 'ready' && (
            <>
              <button
                onClick={handleStartBuild}
                disabled={createBuildMutation.isPending || !project.rhel_versions || project.rhel_versions.length === 0}
                className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 transition-colors"
                title="Start a new build"
              >
                {createBuildMutation.isPending ? (
                  <>
                    <RefreshCw className="h-4 w-4 animate-spin" />
                    Starting...
                  </>
                ) : (
                  <>
                    <Hammer className="h-4 w-4" />
                    Start Build
                  </>
                )}
              </button>
              <button
                onClick={() => setShowRegenerateConfirm(true)}
                disabled={regenerateSpecsMutation.isPending}
                className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 transition-colors"
                title="Regenerate all spec files for this project"
              >
                <RefreshCw className={`h-4 w-4 ${regenerateSpecsMutation.isPending ? 'animate-spin' : ''}`} />
                Regenerate Specs
              </button>
            </>
          )}
          {(['pending', 'failed', 'cloning', 'analyzing'].includes(project.status)) && (
            <button
              onClick={() => retryMutation.mutate(id)}
              disabled={retryMutation.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
              title="Retry/Resume processing"
            >
              <RefreshCw className={`h-4 w-4 ${retryMutation.isPending ? 'animate-spin' : ''}`} />
              {project.status === 'failed' ? 'Retry' : 'Resume'}
            </button>
          )}
          <button
            onClick={() => setShowLogs(!showLogs)}
            className="flex items-center gap-2 px-4 py-2 bg-gray-700 text-white rounded-lg hover:bg-gray-600 transition-colors"
            title="Toggle logs"
          >
            <Clock className="h-4 w-4" />
            {showLogs ? 'Hide Logs' : 'Show Logs'}
          </button>
          <StatusBadge status={project.status} />
        </div>
      </div>

      {/* Error Message */}
      {project.status === 'failed' && project.status_message && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-start gap-2">
            <AlertCircle className="h-5 w-5 text-red-600 mt-0.5" />
            <div>
              <h3 className="font-medium text-red-900">Error</h3>
              <p className="text-red-700 text-sm mt-1">{project.status_message}</p>
            </div>
          </div>
        </div>
      )}

      {/* Live Logs */}
      {showLogs && (
        <LogViewer projectId={id} />
      )}

      {/* Project Info */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Git Information */}
        <div className="bg-gray-800 shadow rounded-lg p-6 border border-gray-700">
          <h2 className="text-lg font-semibold text-white mb-4">Git Repository</h2>
          <div className="space-y-3">
            <div>
              <label className="text-sm font-medium text-gray-400">Repository URL</label>
              <p className="text-gray-200 break-all">{project.git_url}</p>
            </div>
            {project.branch && (
              <div>
                <label className="text-sm font-medium text-gray-400">Branch</label>
                <div className="flex items-center gap-2 text-gray-200">
                  <GitBranch className="h-4 w-4" />
                  <span>{project.branch}</span>
                </div>
              </div>
            )}
            {project.git_tag && (
              <div>
                <label className="text-sm font-medium text-gray-400">Tag</label>
                <p className="text-gray-200">{project.git_tag}</p>
              </div>
            )}
            {project.git_commit && (
              <div>
                <label className="text-sm font-medium text-gray-400">Commit</label>
                <p className="text-gray-200 font-mono text-sm">{project.git_commit.substring(0, 8)}</p>
              </div>
            )}
          </div>
        </div>

        {/* Build Information */}
        <div className="bg-gray-800 shadow rounded-lg p-6 border border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-white">Build Configuration</h2>
            <button
              onClick={() => setShowEditConfig(true)}
              className="text-blue-400 hover:text-blue-300 p-1"
              title="Edit build configuration"
            >
              <Edit2 className="h-4 w-4" />
            </button>
          </div>
          <div className="space-y-3">
            <div>
              <label className="text-sm font-medium text-gray-400">Build Version</label>
              <p className="text-gray-200">{project.build_version}</p>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-400">Python Version</label>
              <p className="text-gray-200">
                {project.python_version === 'default' 
                  ? 'Default (auto-detect)' 
                  : `Python ${project.python_version}`}
              </p>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-400">RHEL Versions</label>
              <div className="flex flex-wrap gap-2 mt-1">
                {project.rhel_versions?.length > 0 ? (
                  project.rhel_versions.map((version) => (
                    <span
                      key={version}
                      className="px-2 py-1 bg-gray-700 text-gray-200 text-xs rounded"
                    >
                      RHEL {version}
                    </span>
                  ))
                ) : (
                  <span className="text-gray-400 text-sm">No RHEL versions selected</span>
                )}
              </div>
            </div>
            {project.build_repositories && (
              <div>
                <label className="text-sm font-medium text-gray-400">Build Repositories</label>
                <pre className="text-xs text-gray-300 mt-1 p-2 bg-gray-900 rounded font-mono whitespace-pre-wrap">
                  {project.build_repositories}
                </pre>
              </div>
            )}
            {project.requirements_files && project.requirements_files.length > 0 && (
              <div>
                <div className="flex items-center justify-between">
                  <label className="text-sm font-medium text-gray-400">Requirements Files</label>
                  <button
                    onClick={() => setShowEditRequirements(true)}
                    className="text-blue-400 hover:text-blue-300 p-1"
                    title="Edit requirements files"
                  >
                    <Edit2 className="h-4 w-4" />
                  </button>
                </div>
                <div className="mt-1 space-y-1">
                  {project.requirements_files.map((file, index) => (
                    <p key={index} className="text-gray-200 font-mono text-sm">{file}</p>
                  ))}
                </div>
              </div>
            )}
            {(!project.requirements_files || project.requirements_files.length === 0) && (
              <div>
                <label className="text-sm font-medium text-gray-400">Requirements Files</label>
                <div className="flex items-center gap-2 mt-1">
                  <p className="text-gray-400 text-sm">No requirements files selected</p>
                  <button
                    onClick={() => setShowEditRequirements(true)}
                    className="text-blue-400 hover:text-blue-300 text-sm flex items-center gap-1"
                  >
                    <Edit2 className="h-3 w-3" />
                    Add files
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Packages */}
      <div className="bg-gray-800 shadow rounded-lg border border-gray-700">
        <div className="p-6 border-b border-gray-700">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <Package className="h-5 w-5" />
              Packages ({packagesData?.count || 0})
            </h2>
          </div>
        </div>
        
        {packagesData && packagesData.packages.length > 0 ? (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-700">
                <thead className="bg-gray-900">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                      Package Name
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                      Version
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                      Type
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                      Build Order
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                      Spec Files
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                      Status
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700">
                  {packagesData.packages.map((pkg) => (
                    <tr
                      key={pkg.id}
                      className="hover:bg-gray-700/50 cursor-pointer"
                      onClick={() => navigate(`/packages/${pkg.id}`)}
                    >
                      <td className="px-4 py-3 whitespace-nowrap text-sm font-medium text-gray-200">
                        {pkg.name}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-300">
                        {pkg.version || '-'}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-300">
                        <span className="px-2 py-1 bg-gray-700 text-gray-300 text-xs rounded">
                          {pkg.package_type}
                        </span>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-300">
                        {pkg.build_order ?? '-'}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-300">
                        {pkg.spec_files > 0 ? (
                          <span className="text-green-400">{pkg.spec_files}</span>
                        ) : (
                          <span className="text-gray-500">0</span>
                        )}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-300">
                        {pkg.status || 'pending'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            
            {/* Pagination */}
            {packagesData.total_pages > 1 && (
              <div className="px-6 py-4 bg-gray-900 border-t border-gray-700 flex items-center justify-between">
                <div className="text-sm text-gray-400">
                  Showing {((packagesData.page - 1) * packagesData.page_size) + 1} to{' '}
                  {Math.min(packagesData.page * packagesData.page_size, packagesData.count)} of{' '}
                  {packagesData.count} packages
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setPackagesPage(p => Math.max(1, p - 1))}
                    disabled={!packagesData.has_previous}
                    className="px-3 py-1 bg-gray-800 text-gray-300 rounded hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                  >
                    <ChevronLeft className="h-4 w-4" />
                    Previous
                  </button>
                  <span className="text-sm text-gray-400">
                    Page {packagesData.page} of {packagesData.total_pages}
                  </span>
                  <button
                    onClick={() => setPackagesPage(p => Math.min(packagesData.total_pages, p + 1))}
                    disabled={!packagesData.has_next}
                    className="px-3 py-1 bg-gray-800 text-gray-300 rounded hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                  >
                    Next
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="p-12 text-gray-400 text-center">
            No packages found yet. They will appear after the project is analyzed.
          </div>
        )}
      </div>

      {/* Timestamps */}
      <div className="bg-gray-800 shadow rounded-lg p-6 border border-gray-700">
        <h2 className="text-lg font-semibold text-white mb-4">Timeline</h2>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-gray-400">Created:</span>
            <span className="text-gray-200">{new Date(project.created_at).toLocaleString()}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-gray-400">Last Updated:</span>
            <span className="text-gray-200">{new Date(project.updated_at).toLocaleString()}</span>
          </div>
          {project.last_build_at && (
            <div className="flex justify-between">
              <span className="text-gray-400">Last Build:</span>
              <span className="text-gray-200">{new Date(project.last_build_at).toLocaleString()}</span>
            </div>
          )}
        </div>
      </div>
      
      {/* Edit Requirements Modal */}
      {showEditRequirements && (
        <EditRequirementsModal
          project={project}
          onClose={() => setShowEditRequirements(false)}
          onSuccess={() => {
            queryClient.invalidateQueries(['project', id]);
            setShowEditRequirements(false);
          }}
        />
      )}

      {/* Edit Build Configuration Modal */}
      {showEditConfig && (
        <EditConfigModal
          project={project}
          onClose={() => setShowEditConfig(false)}
          onSuccess={() => {
            queryClient.invalidateQueries(['project', id]);
            setShowEditConfig(false);
          }}
        />
      )}

      {/* Regenerate Specs Confirmation */}
      {showRegenerateConfirm && (
        <ConfirmDialog
          title="Regenerate Spec Files"
          message={`This will regenerate spec files for all ${packagesData?.count || 0} packages in this project. This action cannot be undone. Continue?`}
          confirmText="Regenerate"
          cancelText="Cancel"
          onConfirm={handleRegenerateSpecs}
          onCancel={() => setShowRegenerateConfirm(false)}
          variant="warning"
        />
      )}
    </div>
  );
}

function EditRequirementsModal({ project, onClose, onSuccess }) {
  const [availableFiles, setAvailableFiles] = useState([]);
  const [selectedFiles, setSelectedFiles] = useState(project.requirements_files || []);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [fetchingFiles, setFetchingFiles] = useState(false);

  const updateMutation = useMutation({
    mutationFn: (data) => projectsAPI.update(project.id, data),
    onSuccess: () => {
      onSuccess();
    },
    onError: (err) => {
      setError(err.response?.data?.detail || 'Failed to update requirements files');
    },
  });

  const handleFetchFiles = async () => {
    setFetchingFiles(true);
    setError('');
    try {
      const response = await projectsAPI.fetchRequirementsFiles(project.git_url, project.branch);
      const files = response.data.requirements_files || [];
      setAvailableFiles(files);
      
      if (files.length === 0) {
        setError('No requirements files found in the repository');
      }
    } catch (err) {
      setError('Failed to fetch requirements files from repository');
      console.error(err);
    } finally {
      setFetchingFiles(false);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    updateMutation.mutate({ requirements_files: selectedFiles });
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg p-6 max-w-2xl w-full max-h-[80vh] overflow-y-auto border border-gray-700">
        <h2 className="text-2xl font-bold text-white mb-4">Edit Requirements Files</h2>

        {error && (
          <div className="mb-4 p-3 bg-red-900 bg-opacity-50 border border-red-700 rounded text-red-200 text-sm">
            {error}
          </div>
        )}

        <div className="mb-4">
          <p className="text-sm text-gray-300 mb-2">
            Repository: <span className="font-mono text-xs text-gray-400">{project.git_url}</span>
          </p>
          <p className="text-sm text-gray-300 mb-4">
            Branch: <span className="font-semibold text-white">{project.branch}</span>
          </p>

          <button
            onClick={handleFetchFiles}
            disabled={fetchingFiles}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 ${fetchingFiles ? 'animate-spin' : ''}`} />
            {fetchingFiles ? 'Searching...' : 'Search for Requirements Files'}
          </button>
        </div>

        {availableFiles.length > 0 && (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Select Requirements Files to Process
              </label>
              <div className="space-y-2 max-h-64 overflow-y-auto p-3 bg-gray-900 rounded border border-gray-600">
                {availableFiles.map((file) => (
                  <label
                    key={file}
                    className="flex items-center space-x-2 text-sm text-gray-300 hover:bg-gray-800 p-2 rounded cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={selectedFiles.includes(file)}
                      onChange={(e) => {
                        const checked = e.target.checked;
                        setSelectedFiles(prev =>
                          checked
                            ? [...prev, file]
                            : prev.filter(f => f !== file)
                        );
                      }}
                      className="w-4 h-4 text-blue-600 border-gray-600 rounded focus:ring-blue-500 bg-gray-700"
                    />
                    <span className="flex-1 font-mono text-xs">{file}</span>
                  </label>
                ))}
              </div>
              <p className="mt-2 text-xs text-gray-400">
                {selectedFiles.length} file(s) selected
              </p>
            </div>

            <div className="flex space-x-3 pt-4 border-t border-gray-700">
              <button
                type="button"
                onClick={onClose}
                className="flex-1 px-4 py-2 bg-gray-700 text-gray-200 rounded hover:bg-gray-600"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={updateMutation.isPending || selectedFiles.length === 0}
                className="flex-1 px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
              >
                {updateMutation.isPending ? 'Updating...' : 'Update & Re-analyze'}
              </button>
            </div>
          </form>
        )}

        {availableFiles.length === 0 && !fetchingFiles && (
          <div className="text-center py-8 text-gray-400">
            Click "Search for Requirements Files" to find available files in the repository.
          </div>
        )}
      </div>
    </div>
  );
}

function EditConfigModal({ project, onClose, onSuccess }) {
  const [formData, setFormData] = useState({
    python_version: project.python_version || 'default',
    rhel_versions: project.rhel_versions || [],
  });
  const [error, setError] = useState('');

  const updateMutation = useMutation({
    mutationFn: async (data) => {
      const response = await projectsAPI.update(project.id, data);
      return response.data;
    },
    onSuccess: () => {
      onSuccess();
    },
    onError: (err) => {
      setError(err.response?.data?.detail || 'Failed to update configuration');
    },
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    updateMutation.mutate(formData);
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg p-6 max-w-md w-full mx-4 border border-gray-700">
        <h3 className="text-xl font-semibold text-white mb-4">Edit Build Configuration</h3>

        {error && (
          <div className="mb-4 p-3 bg-red-900 bg-opacity-50 border border-red-700 rounded text-red-200 text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Python Version *
            </label>
            <select
              required
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              value={formData.python_version}
              onChange={(e) => setFormData({ ...formData, python_version: e.target.value })}
            >
              <option value="default">Default (pyp2spec auto-detect)</option>
              <option value="3.9">Python 3.9</option>
              <option value="3.10">Python 3.10</option>
              <option value="3.11">Python 3.11</option>
              <option value="3.12">Python 3.12</option>
              <option value="3.13">Python 3.13</option>
            </select>
            <p className="mt-1 text-xs text-gray-400">
              Python version used for spec file generation with pyp2spec
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              RHEL Versions to Build *
            </label>
            <div className="space-y-2">
              {['8', '9', '10'].map((version) => (
                <label key={version} className="flex items-center space-x-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={formData.rhel_versions.includes(version)}
                    onChange={(e) => {
                      const checked = e.target.checked;
                      setFormData(prev => ({
                        ...prev,
                        rhel_versions: checked
                          ? [...prev.rhel_versions, version]
                          : prev.rhel_versions.filter(v => v !== version)
                      }));
                    }}
                    className="form-checkbox h-4 w-4 text-blue-600 bg-gray-700 border-gray-600 rounded focus:ring-blue-500"
                  />
                  <span className="text-gray-300">RHEL {version}</span>
                </label>
              ))}
            </div>
            <p className="mt-1 text-xs text-gray-400">
              Select RHEL versions to build packages for. One build job will be created per version selected.
            </p>
          </div>

          <div className="flex space-x-3 pt-4 border-t border-gray-700">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 bg-gray-700 text-gray-200 rounded hover:bg-gray-600"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={updateMutation.isPending}
              className="flex-1 px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {updateMutation.isPending ? 'Updating...' : 'Save Configuration'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function LiveLogs({ projectId }) {
  const [logs, setLogs] = useState([]);
  const [lastTimestamp, setLastTimestamp] = useState(null);
  const logsEndRef = useRef(null);

  useEffect(() => {
    // Initial fetch
    const fetchLogs = async () => {
      try {
        const response = await projectsAPI.logs(projectId, lastTimestamp);
        const newLogs = response.data.logs;
        
        if (newLogs.length > 0) {
          setLogs(prev => [...prev, ...newLogs]);
          setLastTimestamp(newLogs[newLogs.length - 1].timestamp);
        }
      } catch (err) {
        console.error('Failed to fetch logs:', err);
      }
    };

    fetchLogs();

    // Poll for new logs every 2 seconds
    const interval = setInterval(fetchLogs, 2000);

    return () => clearInterval(interval);
  }, [projectId, lastTimestamp]);

  useEffect(() => {
    // Auto-scroll to bottom when new logs arrive
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs]);

  const getLevelColor = (level) => {
    switch (level) {
      case 'error':
        return 'text-red-400';
      case 'warning':
        return 'text-yellow-400';
      case 'info':
        return 'text-blue-400';
      case 'debug':
        return 'text-gray-500';
      default:
        return 'text-gray-300';
    }
  };

  const getLevelIcon = (level) => {
    switch (level) {
      case 'error':
        return '✗';
      case 'warning':
        return '⚠';
      case 'info':
        return 'ℹ';
      case 'debug':
        return '⋯';
      default:
        return '·';
    }
  };

  return (
    <div className="bg-gray-800 shadow rounded-lg p-6 border border-gray-700">
      <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
        <Clock className="h-5 w-5 animate-pulse" />
        Live Logs
      </h2>
      <div className="bg-gray-900 rounded border border-gray-700 p-4 h-96 overflow-y-auto font-mono text-sm">
        {logs.length === 0 ? (
          <div className="text-gray-500 text-center py-8">
            Waiting for logs...
          </div>
        ) : (
          <>
            {logs.map((log, index) => (
              <div key={index} className="mb-1 flex gap-2">
                <span className="text-gray-600 text-xs">
                  {new Date(log.timestamp).toLocaleTimeString()}
                </span>
                <span className={`font-bold ${getLevelColor(log.level)}`}>
                  {getLevelIcon(log.level)}
                </span>
                <span className={getLevelColor(log.level)}>{log.message}</span>
              </div>
            ))}
            <div ref={logsEndRef} />
          </>
        )}
      </div>
    </div>
  );
}
