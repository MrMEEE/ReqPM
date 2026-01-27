import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { projectsAPI } from '../lib/api';
import { Plus, GitBranch, RefreshCw, Trash2 } from 'lucide-react';
import { useState, useEffect, useRef } from 'react';

export default function Projects() {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();

  // Check if we should open the create modal from URL parameter
  useEffect(() => {
    if (searchParams.get('action') === 'create') {
      setShowCreateModal(true);
      // Remove the parameter from URL
      searchParams.delete('action');
      setSearchParams(searchParams);
    }
  }, [searchParams, setSearchParams]);

  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => projectsAPI.list().then(res => res.data),
  });

  const deleteMutation = useMutation({
    mutationFn: (id) => projectsAPI.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries(['projects']);
    },
  });

  const syncMutation = useMutation({
    mutationFn: (id) => projectsAPI.sync(id),
    onSuccess: () => {
      queryClient.invalidateQueries(['projects']);
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white">Projects</h1>
          <p className="mt-2 text-gray-400">Manage your Python package projects</p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center space-x-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus size={20} />
          <span>New Project</span>
        </button>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
        </div>
      ) : projects?.results?.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {projects.results.map((project) => (
            <div
              key={project.id}
              className="bg-gray-800 rounded-lg shadow-lg border border-gray-700 hover:border-gray-600 transition-colors"
            >
              <div className="p-6">
                <div className="flex items-start justify-between mb-4">
                  <div className="flex-1">
                    <Link
                      to={`/projects/${project.id}`}
                      className="block"
                    >
                      <h3 className="text-lg font-semibold text-white hover:text-blue-400">
                        {project.name}
                      </h3>
                    </Link>
                    <ProjectStatusBadge status={project.status} />
                  </div>
                  <div className="flex space-x-2">
                    <button
                      onClick={() => syncMutation.mutate(project.id)}
                      className="p-2 text-gray-400 hover:text-white hover:bg-gray-700 rounded transition-colors"
                      title="Sync repository"
                      disabled={syncMutation.isPending}
                    >
                      <RefreshCw
                        size={16}
                        className={syncMutation.isPending ? 'animate-spin' : ''}
                      />
                    </button>
                    <button
                      onClick={() => {
                        if (confirm('Are you sure you want to delete this project?')) {
                          deleteMutation.mutate(project.id);
                        }
                      }}
                      className="p-2 text-gray-400 hover:text-red-400 hover:bg-gray-700 rounded transition-colors"
                      title="Delete project"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </div>

                <p className="text-sm text-gray-400 mb-4 line-clamp-2">
                  {project.description || 'No description'}
                </p>

                {project.status === 'failed' && project.status_message && (
                  <div className="mb-4 p-2 bg-red-900 bg-opacity-30 border border-red-700 rounded">
                    <p className="text-xs text-red-300">
                      <strong>Error:</strong> {project.status_message}
                    </p>
                  </div>
                )}

                <div className="space-y-2">
                  <div className="flex items-center space-x-2 text-sm text-gray-400">
                    <GitBranch size={14} />
                    <span>{project.branch}</span>
                  </div>
                  <div className="text-xs text-gray-500">
                    Last synced: {project.last_sync ? new Date(project.last_sync).toLocaleString() : 'Never'}
                  </div>
                </div>

                <div className="mt-4 pt-4 border-t border-gray-700">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-gray-400">
                      {project.packages_count || 0} packages
                    </span>
                    <Link
                      to={`/projects/${project.id}`}
                      className="text-blue-400 hover:text-blue-300"
                    >
                      View details →
                    </Link>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-center py-12 bg-gray-800 rounded-lg border border-gray-700">
          <p className="text-gray-400 mb-4">No projects yet. Create your first project to get started.</p>
          <button
            onClick={() => setShowCreateModal(true)}
            className="inline-flex items-center space-x-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            <Plus size={20} />
            <span>Create Project</span>
          </button>
        </div>
      )}

      {showCreateModal && (
        <CreateProjectModal
          onClose={() => setShowCreateModal(false)}
          onSuccess={() => {
            setShowCreateModal(false);
            queryClient.invalidateQueries(['projects']);
          }}
        />
      )}
    </div>
  );
}

function CreateProjectModal({ onClose, onSuccess }) {
  const [formData, setFormData] = useState({
    name: '',
    git_url: '',
    branch: 'main',
    description: '',
    requirements_files: [],
    python_version: 'default',
    rhel_versions: [],
  });
  const [error, setError] = useState('');
  const [branches, setBranches] = useState([]);
  const [fetchingBranches, setFetchingBranches] = useState(false);
  const [branchesError, setBranchesError] = useState('');
  const [requirementsFiles, setRequirementsFiles] = useState([]);
  const [fetchingRequirements, setFetchingRequirements] = useState(false);
  const [requirementsError, setRequirementsError] = useState('');
  const debounceTimerRef = useRef(null);
  const requirementsDebounceRef = useRef(null);

  const createMutation = useMutation({
    mutationFn: (data) => projectsAPI.create(data),
    onSuccess: () => {
      onSuccess();
    },
    onError: (err) => {
      console.error('Create project error:', err.response?.data);
      console.error('Full error details:', JSON.stringify(err.response?.data, null, 2));
      const errorData = err.response?.data;
      if (typeof errorData === 'object' && errorData !== null) {
        // Handle validation errors
        const errors = Object.entries(errorData)
          .map(([field, messages]) => `${field}: ${Array.isArray(messages) ? messages.join(', ') : messages}`)
          .join('\n');
        setError(errors || 'Failed to create project');
      } else {
        setError(errorData?.detail || errorData || 'Failed to create project');
      }
    },
  });

  // Fetch branches when repository URL changes (with debounce)
  useEffect(() => {
    const url = formData.git_url;
    
    // Clear previous timer
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }

    // Reset branches when URL changes
    setBranches([]);
    setBranchesError('');

    // Only fetch if URL looks complete
    if (url && (url.endsWith('.git') || url.match(/github\.com\/[^\/]+\/[^\/]+\/?$/))) {
      debounceTimerRef.current = setTimeout(async () => {
        setFetchingBranches(true);
        try {
          const response = await projectsAPI.fetchBranches(url);
          setBranches(response.data.branches || []);
          // Set default branch
          if (response.data.default) {
            setFormData(prev => ({ ...prev, branch: response.data.default }));
          }
        } catch (err) {
          setBranchesError('Could not fetch branches. You can still enter a branch name manually.');
          console.error('Error fetching branches:', err);
        } finally {
          setFetchingBranches(false);
        }
      }, 500); // Wait 500ms after user stops typing
    }

    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, [formData.git_url]);
  
  // Fetch requirements files when branch changes
  useEffect(() => {
    const { git_url, branch } = formData;
    
    // Clear previous timer
    if (requirementsDebounceRef.current) {
      clearTimeout(requirementsDebounceRef.current);
    }
    
    // Reset requirements files
    setRequirementsFiles([]);
    setRequirementsError('');
    
    // Only fetch if we have both URL and branch
    if (git_url && branch && (git_url.endsWith('.git') || git_url.match(/github\.com\/[^\/]+\/[^\/]+\/?$/))) {
      requirementsDebounceRef.current = setTimeout(async () => {
        setFetchingRequirements(true);
        try {
          const response = await projectsAPI.fetchRequirementsFiles(git_url, branch);
          const files = response.data.requirements_files || [];
          setRequirementsFiles(files);
          
          // Auto-select default or all files
          if (files.length > 0) {
            const defaultFile = response.data.default;
            setFormData(prev => ({
              ...prev,
              requirements_files: defaultFile ? [defaultFile] : files
            }));
          }
        } catch (err) {
          setRequirementsError('Could not find requirements files. You can proceed anyway.');
          console.error('Error fetching requirements:', err);
        } finally {
          setFetchingRequirements(false);
        }
      }, 800);
    }
    
    return () => {
      if (requirementsDebounceRef.current) {
        clearTimeout(requirementsDebounceRef.current);
      }
    };
  }, [formData.git_url, formData.branch]);

  const handleSubmit = (e) => {
    e.preventDefault();
    console.log('Submitting project data:', formData);
    createMutation.mutate(formData);
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg p-6 max-w-md w-full">
        <h2 className="text-2xl font-bold text-white mb-4">Create New Project</h2>

        {error && (
          <div className="mb-4 p-3 bg-red-900 bg-opacity-50 border border-red-700 rounded text-red-200 text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Project Name *
            </label>
            <input
              type="text"
              required
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Git Repository URL *
            </label>
            <input
              type="url"
              required
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              value={formData.git_url}
              onChange={(e) => setFormData({ ...formData, git_url: e.target.value })}
              placeholder="https://github.com/user/repo.git"
            />
            {fetchingBranches && (
              <p className="mt-1 text-xs text-blue-400">Fetching branches...</p>
            )}
            {branchesError && (
              <p className="mt-1 text-xs text-yellow-400">{branchesError}</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Branch
            </label>
            {branches.length > 0 ? (
              <select
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                value={formData.branch}
                onChange={(e) => setFormData({ ...formData, branch: e.target.value })}
              >
                {branches.map((branch) => (
                  <option key={branch} value={branch}>
                    {branch}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                value={formData.branch}
                onChange={(e) => setFormData({ ...formData, branch: e.target.value })}
                placeholder="main"
              />
            )}
          </div>

          {requirementsFiles.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">
                Requirements Files
              </label>
              <div className="space-y-2 max-h-48 overflow-y-auto p-3 bg-gray-900 rounded border border-gray-600">
                {requirementsFiles.map((file) => (
                  <label key={file} className="flex items-center space-x-2 text-sm text-gray-300 hover:bg-gray-800 p-2 rounded cursor-pointer">
                    <input
                      type="checkbox"
                      checked={formData.requirements_files.includes(file)}
                      onChange={(e) => {
                        const checked = e.target.checked;
                        setFormData(prev => ({
                          ...prev,
                          requirements_files: checked
                            ? [...prev.requirements_files, file]
                            : prev.requirements_files.filter(f => f !== file)
                        }));
                      }}
                      className="w-4 h-4 text-blue-600 bg-gray-700 border-gray-600 rounded focus:ring-blue-500"
                    />
                    <span className="flex-1 font-mono text-xs">{file}</span>
                  </label>
                ))}
              </div>
              <p className="mt-1 text-xs text-gray-400">
                {formData.requirements_files.length} file(s) selected
              </p>
            </div>
          )}
          
          {fetchingRequirements && (
            <div className="p-3 bg-blue-900 bg-opacity-30 border border-blue-700 rounded text-blue-200 text-sm">
              Searching for requirements files...
            </div>
          )}
          
          {requirementsError && (
            <div className="p-3 bg-yellow-900 bg-opacity-30 border border-yellow-700 rounded text-yellow-200 text-sm">
              {requirementsError}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">
              Description
            </label>
            <textarea
              rows={3}
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            />
          </div>

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
            <label className="block text-sm font-medium text-gray-300 mb-1">
              RHEL Versions to Build *
            </label>
            <div className="space-y-2">
              {['8', '9', '10'].map((version) => (
                <label key={version} className="flex items-center space-x-2">
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

          <div className="flex space-x-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 bg-gray-700 text-white rounded hover:bg-gray-600 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={createMutation.isPending}
              className="flex-1 px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors disabled:opacity-50"
            >
              {createMutation.isPending ? 'Creating...' : 'Create Project'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function ProjectStatusBadge({ status }) {
  const statusConfig = {
    pending: { color: 'bg-yellow-500', text: 'Pending', icon: '⏳' },
    cloning: { color: 'bg-blue-500', text: 'Cloning', icon: '📥' },
    analyzing: { color: 'bg-blue-500', text: 'Analyzing', icon: '🔍' },
    ready: { color: 'bg-green-500', text: 'Ready', icon: '✓' },
    failed: { color: 'bg-red-500', text: 'Failed', icon: '✗' },
  };

  const config = statusConfig[status] || statusConfig.pending;

  return (
    <span className={`inline-flex items-center mt-1 px-2 py-0.5 text-xs font-medium text-white rounded ${config.color}`}>
      <span className="mr-1">{config.icon}</span>
      {config.text}
    </span>
  );
}
