import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, GitBranch, Package, AlertCircle, CheckCircle, Clock, XCircle, Edit2, RefreshCw, ChevronLeft, ChevronRight, Hammer, Download, X, Terminal, FileCode } from 'lucide-react';
import { useState, useEffect, useRef } from 'react';
import { projectsAPI, buildsAPI, packagesAPI } from '../lib/api';
import { MockStatus } from '../components/SystemHealthBanner';
import ConfirmDialog from '../components/ConfirmDialog';
import LivePackageBuildLog from '../components/LivePackageBuildLog';

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

const VersionDropdown = ({ packageId, currentVersion, onVersionChange }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [versions, setVersions] = useState([]);
  const [loading, setLoading] = useState(false);

  const handleClick = async () => {
    if (!isOpen && versions.length === 0) {
      setLoading(true);
      try {
        const response = await packagesAPI.getVersions(packageId);
        setVersions(response.data.versions || []);
      } catch (error) {
        console.error('Failed to fetch versions:', error);
        alert('Failed to fetch versions');
      } finally {
        setLoading(false);
      }
    }
    setIsOpen(!isOpen);
  };

  const handleVersionSelect = (version) => {
    setIsOpen(false);
    if (version !== currentVersion) {
      onVersionChange(packageId, version);
    }
  };

  return (
    <div className="relative">
      <button
        onClick={handleClick}
        className="text-blue-400 hover:text-blue-300 underline text-sm"
        disabled={loading}
      >
        {loading ? 'Loading...' : currentVersion}
      </button>
      {isOpen && (
        <>
          <div
            className="fixed inset-0 z-10"
            onClick={() => setIsOpen(false)}
          />
          <div className="absolute z-20 mt-1 w-32 bg-gray-700 border border-gray-600 rounded-md shadow-lg max-h-60 overflow-auto flex flex-col">
            {versions.length === 0 ? (
              <div className="px-3 py-2 text-sm text-gray-400">No versions</div>
            ) : (
              versions.map((version) => (
                <button
                  key={version}
                  onClick={() => handleVersionSelect(version)}
                  className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-600 ${
                    version === currentVersion ? 'bg-gray-600 text-white' : 'text-gray-200'
                  }`}
                >
                  {version}
                </button>
              ))
            )}
          </div>
        </>
      )}
    </div>
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
  const [showBuildLog, setShowBuildLog] = useState(false);
  const [selectedPackageLog, setSelectedPackageLog] = useState(null);
  const [directPage, setDirectPage] = useState(1);
  const [transitivePage, setTransitivePage] = useState(1);
  const [pageSize] = useState(20);
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef(null);

  const { data: project, isLoading, error } = useQuery({
    queryKey: ['project', id],
    queryFn: async () => {
      const response = await projectsAPI.get(id);
      return response.data;
    },
    refetchInterval: (data) => {
      // Auto-refresh every 3 seconds if project is processing (fallback if WebSocket fails)
      const status = data?.status;
      return ['pending', 'cloning', 'analyzing'].includes(status) && !wsConnected ? 3000 : false;
    },
  });

  const { data: packagesData } = useQuery({
    queryKey: ['project-packages', id],
    queryFn: async () => {
      const response = await projectsAPI.packages(id);
      return response.data;
    },
    enabled: !!project,
  });

  // WebSocket connection for real-time updates
  useEffect(() => {
    if (!id) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/projects/${id}/`;
    
    const connectWebSocket = () => {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log('WebSocket connected for project', id);
        setWsConnected(true);
      };

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log('WebSocket message:', data);

        if (data.type === 'package_update') {
          // Update the package in cache across all arrays
          queryClient.setQueryData(['project-packages', id], (oldData) => {
            if (!oldData) return oldData;
            
            const updatePackage = (pkg) => 
              pkg.id === data.package.id ? { ...pkg, ...data.package } : pkg;
            
            return {
              ...oldData,
              packages: oldData.packages?.map(updatePackage),
              direct_dependencies: oldData.direct_dependencies?.map(updatePackage),
              transitive_dependencies: oldData.transitive_dependencies?.map(updatePackage),
            };
          });
        } else if (data.type === 'initial_data' || data.type === 'refresh') {
          // Optionally update with full data
          if (data.project) {
            queryClient.setQueryData(['project', id], (oldData) => ({
              ...oldData,
              ...data.project
            }));
          }
        }
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        setWsConnected(false);
      };

      ws.onclose = () => {
        console.log('WebSocket closed for project', id);
        setWsConnected(false);
        // Attempt to reconnect after 3 seconds
        setTimeout(connectWebSocket, 3000);
      };
    };

    connectWebSocket();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [id, queryClient]);


  const resolveDependenciesMutation = useMutation({
    mutationFn: async () => {
      const response = await projectsAPI.resolveDependencies(id);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['project', id]);
      queryClient.invalidateQueries(['project-packages', id]);
      setShowLogs(true);
    },
    onError: (error) => {
      alert(`Failed to resolve dependencies: ${error.response?.data?.detail || error.message}`);
    },
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

  const fetchSourceMutation = useMutation({
    mutationFn: async (packageId) => {
      const response = await packagesAPI.fetchSource(packageId);
      return response.data;
    },
    onSuccess: () => {
      // Show logs so user can see progress
      setShowLogs(true);
    },
    onError: (error) => {
      alert(`Failed to fetch source: ${error.response?.data?.detail || error.message}`);
    },
  });

  const handleFetchSource = (packageId) => {
    fetchSourceMutation.mutate(packageId);
  };

  const generateSpecMutation = useMutation({
    mutationFn: async (packageId) => {
      const response = await packagesAPI.generateSpec(packageId, { force: true });
      return response.data;
    },
    onSuccess: (data) => {
      console.log('Spec generation triggered:', data);
      queryClient.invalidateQueries(['project-packages', id]);
      // Refresh the package data after a short delay to show updated spec_files_count
      setTimeout(() => {
        queryClient.invalidateQueries(['project-packages', id]);
      }, 2000);
    },
    onError: (error) => {
      console.error('Spec generation error:', error);
      alert(`Failed to generate spec: ${error.response?.data?.detail || error.message}`);
    },
  });

  const handleGenerateSpec = (packageId) => {
    console.log('Generating spec for package:', packageId);
    generateSpecMutation.mutate(packageId);
  };

  const toggleExtraMutation = useMutation({
    mutationFn: async ({ packageId, extraId, enabled }) => {
      const response = await packagesAPI.updateExtra(packageId, extraId, { enabled });
      return response.data;
    },
    onSuccess: (data, variables) => {
      // Update the package in cache
      queryClient.setQueryData(['project-packages', id], (oldData) => {
        if (!oldData || !oldData.packages) return oldData;
        
        const updatedPackages = oldData.packages.map(pkg => {
          if (pkg.id === variables.packageId) {
            return {
              ...pkg,
              extras: pkg.extras.map(extra =>
                extra.id === variables.extraId ? { ...extra, enabled: variables.enabled } : extra
              )
            };
          }
          return pkg;
        });
        
        // Update direct_dependencies
        const updatedDirect = oldData.direct_dependencies?.map(pkg => {
          if (pkg.id === variables.packageId) {
            return {
              ...pkg,
              extras: pkg.extras.map(extra =>
                extra.id === variables.extraId ? { ...extra, enabled: variables.enabled } : extra
              )
            };
          }
          return pkg;
        });
        
        // Update transitive_dependencies
        const updatedTransitive = oldData.transitive_dependencies?.map(pkg => {
          if (pkg.id === variables.packageId) {
            return {
              ...pkg,
              extras: pkg.extras.map(extra =>
                extra.id === variables.extraId ? { ...extra, enabled: variables.enabled } : extra
              )
            };
          }
          return pkg;
        });
        
        return {
          ...oldData,
          packages: updatedPackages,
          direct_dependencies: updatedDirect,
          transitive_dependencies: updatedTransitive
        };
      });
    },
    onError: (error) => {
      alert(`Failed to toggle extra: ${error.response?.data?.error || error.message}`);
    },
  });

  const handleToggleExtra = (packageId, extraId, currentEnabled) => {
    toggleExtraMutation.mutate({ packageId, extraId, enabled: !currentEnabled });
  };

  const changeVersionMutation = useMutation({
    mutationFn: async ({ packageId, version }) => {
      const response = await packagesAPI.changeVersion(packageId, version);
      return response.data;
    },
    onSuccess: () => {
      // Refetch packages after version change
      queryClient.invalidateQueries(['project-packages', id]);
      queryClient.invalidateQueries(['project', id]);
    },
    onError: (error) => {
      alert(`Failed to change version: ${error.response?.data?.error || error.message}`);
    },
  });

  const fetchAllSourcesMutation = useMutation({
    mutationFn: async () => {
      const response = await projectsAPI.fetchAllSources(id);
      return response.data;
    },
    onSuccess: (data) => {
      alert(`Started fetching sources for ${data.count} packages`);
      // Refetch packages to update source status
      queryClient.invalidateQueries(['project-packages', id]);
    },
    onError: (error) => {
      alert(`Failed to fetch sources: ${error.response?.data?.error || error.message}`);
    },
  });

  const handleFetchAllSources = () => {
    fetchAllSourcesMutation.mutate();
  };

  const buildPackageMutation = useMutation({
    mutationFn: async (packageId) => {
      const response = await packagesAPI.buildPackage(packageId);
      return response.data;
    },
    onSuccess: (data) => {
      setShowLogs(true);
      queryClient.invalidateQueries(['project-packages', id]);
    },
    onError: (error) => {
      alert(`Failed to build package: ${error.response?.data?.detail || error.message}`);
    },
  });

  const rebuildPackageMutation = useMutation({
    mutationFn: async (packageId) => {
      const response = await packagesAPI.rebuildPackage(packageId);
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries(['project-packages', id]);
      setShowLogs(true);
    },
    onError: (error) => {
      alert(`Failed to rebuild package: ${error.response?.data?.detail || error.message}`);
    },
  });

  const cancelBuildMutation = useMutation({
    mutationFn: async (packageId) => {
      const response = await packagesAPI.cancelBuild(packageId);
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries(['project-packages', id]);
    },
    onError: (error) => {
      alert(`Failed to cancel build: ${error.response?.data?.detail || error.message}`);
    },
  });

  const buildAllPackagesMutation = useMutation({
    mutationFn: async () => {
      const response = await projectsAPI.buildAllPackages(id);
      return response.data;
    },
    onSuccess: (data) => {
      alert(`Started building ${data.count} packages`);
      setShowLogs(true);
      queryClient.invalidateQueries(['project-packages', id]);
    },
    onError: (error) => {
      alert(`Failed to build packages: ${error.response?.data?.detail || error.message}`);
    },
  });

  const handleBuildPackage = (packageId) => {
    buildPackageMutation.mutate(packageId);
  };

  const handleRebuildPackage = (packageId) => {
    rebuildPackageMutation.mutate(packageId);
  };

  const handleCancelBuild = (packageId) => {
    cancelBuildMutation.mutate(packageId);
  };

  const handleBuildAllPackages = () => {
    buildAllPackagesMutation.mutate();
  };

  const handleRegenerateSpecs = () => {
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

  const handleViewBuildLog = (pkg) => {
    setSelectedPackageLog(pkg);
    setShowBuildLog(true);
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
          {wsConnected && (
            <div className="flex items-center gap-1.5 text-xs text-green-600">
              <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
              Live
            </div>
          )}
        </div>
        <div className="flex items-center gap-3">
          {project.status === 'ready' && (
            <>
              <button
                onClick={() => resolveDependenciesMutation.mutate()}
                disabled={resolveDependenciesMutation.isPending}
                className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                title="Recalculate package dependencies"
              >
                <RefreshCw className={`h-4 w-4 ${resolveDependenciesMutation.isPending ? 'animate-spin' : ''}`} />
                Recalculate Dependencies
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
              <button
                onClick={handleFetchAllSources}
                disabled={fetchAllSourcesMutation.isPending}
                className="flex items-center gap-2 px-4 py-2 bg-cyan-600 text-white rounded-lg hover:bg-cyan-700 disabled:opacity-50 transition-colors"
                title="Fetch source files for all packages with spec files"
              >
                <Download className={`h-4 w-4 ${fetchAllSourcesMutation.isPending ? 'animate-spin' : ''}`} />
                Fetch All Sources
              </button>
              <button
                onClick={handleBuildAllPackages}
                disabled={buildAllPackagesMutation.isPending}
                className="flex items-center gap-2 px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:opacity-50 transition-colors"
                title="Build all packages with specs and sources"
              >
                <Hammer className={`h-4 w-4 ${buildAllPackagesMutation.isPending ? 'animate-spin' : ''}`} />
                Build All Packages
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
        <LiveLogs projectId={id} />
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

      {/* Packages - Split into Direct and Transitive Dependencies */}
      <div className="bg-gray-800 shadow rounded-lg border border-gray-700">
        <div className="p-6 border-b border-gray-700">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <Package className="h-5 w-5" />
              Packages ({packagesData?.count || 0})
            </h2>
          </div>
        </div>
        
        {packagesData && packagesData.packages && packagesData.packages.length > 0 ? (
          <div className="space-y-6 p-6">
            {/* Direct Dependencies */}
            {packagesData.direct_dependencies && packagesData.direct_dependencies.length > 0 && (() => {
              const startIdx = (directPage - 1) * pageSize;
              const endIdx = startIdx + pageSize;
              const paginatedDirect = packagesData.direct_dependencies.slice(startIdx, endIdx);
              const totalPages = Math.ceil(packagesData.direct_dependencies.length / pageSize);
              
              return (
              <div>
                <h3 className="text-md font-semibold text-white mb-4 flex items-center gap-2">
                  📋 Direct Dependencies ({packagesData.direct_count || packagesData.direct_dependencies.length})
                  <span className="text-xs text-gray-400 font-normal">
                    Packages from requirements files
                  </span>
                </h3>
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
                          Requirements File
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                          Extras
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                          Build Order
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                          Status
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                          Source
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                          Build Status
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                          RPM/SRPM
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                          Actions
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-700">
                      {paginatedDirect.map((pkg) => (
                        <tr
                          key={pkg.id}
                          className="hover:bg-gray-700/50"
                        >
                          <td 
                            className="px-4 py-3 whitespace-nowrap text-sm font-medium text-gray-200 cursor-pointer"
                            onClick={() => navigate(`/packages/${pkg.id}`)}
                          >
                            {pkg.name}
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-300">
                            <VersionDropdown
                              packageId={pkg.id}
                              currentVersion={pkg.version || '-'}
                              onVersionChange={(pkgId, version) => changeVersionMutation.mutate({ packageId: pkgId, version })}
                            />
                          </td>
                          <td 
                            className="px-4 py-3 whitespace-nowrap text-sm text-gray-300 cursor-pointer"
                            onClick={() => navigate(`/packages/${pkg.id}`)}
                          >
                            <span className="px-2 py-1 bg-blue-900/30 text-blue-300 text-xs rounded">
                              {pkg.requirements_file || 'requirements.txt'}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-300">
                            {pkg.extras && pkg.extras.length > 0 ? (
                              <div className="flex flex-wrap gap-1">
                                {pkg.extras.map((extra) => (
                                  <button
                                    key={extra.id}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleToggleExtra(pkg.id, extra.id, extra.enabled);
                                    }}
                                    className={`px-2 py-1 text-xs rounded cursor-pointer transition-colors ${
                                      extra.enabled
                                        ? 'bg-green-900/30 text-green-300 hover:bg-green-900/50'
                                        : 'bg-red-900/30 text-red-300 hover:bg-red-900/50'
                                    }`}
                                    title={extra.enabled ? `Click to disable extra: ${extra.name}` : `Click to enable extra: ${extra.name}`}
                                  >
                                    {extra.name}
                                  </button>
                                ))}
                              </div>
                            ) : (
                              <span className="text-gray-500">-</span>
                            )}
                          </td>
                          <td 
                            className="px-4 py-3 whitespace-nowrap text-sm text-gray-300 cursor-pointer"
                            onClick={() => navigate(`/packages/${pkg.id}`)}
                          >
                            {pkg.build_order ?? '-'}
                          </td>
                          <td 
                            className="px-4 py-3 whitespace-nowrap text-sm cursor-pointer"
                            onClick={() => navigate(`/packages/${pkg.id}`)}
                          >
                            <StatusBadge status={pkg.status} />
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-300">
                            {pkg.source_fetched ? (
                              <a
                                href={`file://${pkg.source_path}`}
                                className="text-green-400 hover:text-green-300 underline"
                                onClick={(e) => e.stopPropagation()}
                              >
                                Downloaded
                              </a>
                            ) : (
                              <span className="text-gray-500">Not fetched</span>
                            )}
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap text-sm">
                            {pkg.build_status === 'completed' && (
                              <span className="px-2 py-1 bg-green-900/30 text-green-300 text-xs rounded">
                                Built
                              </span>
                            )}
                            {pkg.build_status === 'failed' && (
                              <span className="px-2 py-1 bg-red-900/30 text-red-300 text-xs rounded" title={pkg.build_error_message}>
                                Failed
                              </span>
                            )}
                            {pkg.build_status === 'building' && (
                              <span className="px-2 py-1 bg-blue-900/30 text-blue-300 text-xs rounded flex items-center gap-1">
                                <RefreshCw className="h-3 w-3 animate-spin" />
                                Building
                              </span>
                            )}
                            {pkg.build_status === 'waiting_for_deps' && (
                              <span className="px-2 py-1 bg-orange-900/30 text-orange-300 text-xs rounded flex items-center gap-1">
                                <Clock className="h-3 w-3" />
                                Waiting for deps
                              </span>
                            )}
                            {pkg.build_status === 'pending' && (
                              <span className="px-2 py-1 bg-yellow-900/30 text-yellow-300 text-xs rounded">
                                Pending
                              </span>
                            )}
                            {pkg.build_status === 'not_built' && (
                              <span className="px-2 py-1 bg-gray-700 text-gray-400 text-xs rounded">
                                Not Built
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-300">
                            <div className="flex flex-col gap-1">
                              {pkg.rpm_path && (
                                <button
                                  onClick={async (e) => {
                                    e.stopPropagation();
                                    try {
                                      const response = await packagesAPI.downloadRpm(pkg.id);
                                      const url = window.URL.createObjectURL(response.data);
                                      const link = document.createElement('a');
                                      link.href = url;
                                      link.download = pkg.rpm_path.split('/').pop();
                                      document.body.appendChild(link);
                                      link.click();
                                      document.body.removeChild(link);
                                      window.URL.revokeObjectURL(url);
                                    } catch (error) {
                                      console.error('Download failed:', error);
                                    }
                                  }}
                                  className="text-blue-400 hover:text-blue-300 underline text-xs bg-transparent border-none cursor-pointer text-left"
                                >
                                  RPM
                                </button>
                              )}
                              {pkg.srpm_path && (
                                <button
                                  onClick={async (e) => {
                                    e.stopPropagation();
                                    try {
                                      const response = await packagesAPI.downloadSrpm(pkg.id);
                                      const url = window.URL.createObjectURL(response.data);
                                      const link = document.createElement('a');
                                      link.href = url;
                                      link.download = pkg.srpm_path.split('/').pop();
                                      document.body.appendChild(link);
                                      link.click();
                                      document.body.removeChild(link);
                                      window.URL.revokeObjectURL(url);
                                    } catch (error) {
                                      console.error('Download failed:', error);
                                    }
                                  }}
                                  className="text-blue-400 hover:text-blue-300 underline text-xs bg-transparent border-none cursor-pointer text-left"
                                >
                                  SRPM
                                </button>
                              )}
                              {!pkg.rpm_path && !pkg.srpm_path && (
                                <span className="text-gray-500 text-xs">-</span>
                              )}
                            </div>
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-300">
                            <div className="flex items-center gap-2 flex-wrap">
                              {['building', 'pending'].includes(pkg.build_status) && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleViewBuildLog(pkg);
                                  }}
                                  className="px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 flex items-center gap-1 animate-pulse"
                                  title="View live build log"
                                >
                                  <Terminal className="h-3 w-3" />
                                  Live Log
                                </button>
                              )}
                              {!['building', 'pending', 'waiting_for_deps'].includes(pkg.build_status) && (pkg.has_build_log || pkg.build_error_message || pkg.build_status === 'completed' || pkg.build_status === 'failed') && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleViewBuildLog(pkg);
                                  }}
                                  className="px-3 py-1 bg-gray-700 text-white rounded hover:bg-gray-600 flex items-center gap-1"
                                  title="View build log"
                                >
                                  <Terminal className="h-3 w-3" />
                                  Log
                                </button>
                              )}
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleGenerateSpec(pkg.id);
                                }}
                                className="px-3 py-1 bg-purple-600 text-white rounded hover:bg-purple-700 flex items-center gap-1"
                                title="Generate SPEC file for this package"
                              >
                                <FileCode className="h-3 w-3" />
                                Gen Spec
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleFetchSource(pkg.id);
                                }}
                                disabled={!pkg.spec_files_count || pkg.spec_files_count === 0}
                                className="px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                                title={!pkg.spec_files_count || pkg.spec_files_count === 0 ? "Generate spec file first" : "Fetch source files"}
                              >
                                <Download className="h-3 w-3" />
                                Fetch
                              </button>
                              {pkg.build_status === 'waiting_for_deps' ? (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleCancelBuild(pkg.id);
                                  }}
                                  className="px-3 py-1 bg-red-600 text-white rounded hover:bg-red-700 flex items-center gap-1"
                                  title="Cancel waiting build"
                                >
                                  <X className="h-3 w-3" />
                                  Cancel
                                </button>
                              ) : pkg.build_status === 'not_built' || pkg.build_status === 'pending' ? (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleBuildPackage(pkg.id);
                                  }}
                                  disabled={!pkg.source_fetched || !pkg.spec_files_count || pkg.build_status === 'building' || pkg.build_status === 'pending'}
                                  className="px-3 py-1 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                                  title={!pkg.source_fetched ? "Fetch source first" : !pkg.spec_files_count ? "Generate spec file first" : "Build package"}
                                >
                                  <Hammer className="h-3 w-3" />
                                  Build
                                </button>
                              ) : (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleRebuildPackage(pkg.id);
                                  }}
                                  disabled={!pkg.source_fetched || !pkg.spec_files_count || pkg.build_status === 'building' || pkg.build_status === 'pending'}
                                  className="px-3 py-1 bg-orange-600 text-white rounded hover:bg-orange-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                                  title="Rebuild package"
                                >
                                  <RefreshCw className="h-3 w-3" />
                                  Rebuild
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {/* Direct Dependencies Pagination */}
                {totalPages > 1 && (
                  <div className="mt-4 flex items-center justify-between">
                    <div className="text-sm text-gray-400">
                      Showing {startIdx + 1} to {Math.min(endIdx, packagesData.direct_dependencies.length)} of {packagesData.direct_dependencies.length} direct dependencies
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => setDirectPage(p => Math.max(1, p - 1))}
                        disabled={directPage === 1}
                        className="px-3 py-1 bg-gray-800 text-gray-300 rounded hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                      >
                        <ChevronLeft className="h-4 w-4" />
                        Previous
                      </button>
                      <span className="text-sm text-gray-400">
                        Page {directPage} of {totalPages}
                      </span>
                      <button
                        onClick={() => setDirectPage(p => Math.min(totalPages, p + 1))}
                        disabled={directPage === totalPages}
                        className="px-3 py-1 bg-gray-800 text-gray-300 rounded hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                      >
                        Next
                        <ChevronRight className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                )}
              </div>
              );
            })()}

            {/* Transitive Dependencies */}
            {packagesData.transitive_dependencies && packagesData.transitive_dependencies.length > 0 && (() => {
              const startIdx = (transitivePage - 1) * pageSize;
              const endIdx = startIdx + pageSize;
              const paginatedTransitive = packagesData.transitive_dependencies.slice(startIdx, endIdx);
              const totalPages = Math.ceil(packagesData.transitive_dependencies.length / pageSize);
              
              return (
              <div>
                <h3 className="text-md font-semibold text-white mb-4 flex items-center gap-2">
                  🔗 Transitive Dependencies ({packagesData.transitive_count || packagesData.transitive_dependencies.length})
                  <span className="text-xs text-gray-400 font-normal">
                    Dependencies of dependencies
                  </span>
                </h3>
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
                          Depended By
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                          Extras
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                          Build Order
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                          Status
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                          Source
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                          Build Status
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                          RPM/SRPM
                        </th>
                        <th className="px-4 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">
                          Actions
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-700">
                      {paginatedTransitive.map((pkg) => (
                        <tr
                          key={pkg.id}
                          className="hover:bg-gray-700/50"
                        >
                          <td 
                            className="px-4 py-3 whitespace-nowrap text-sm font-medium text-gray-200 cursor-pointer"
                            onClick={() => navigate(`/packages/${pkg.id}`)}
                          >
                            {pkg.name}
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-300">
                            <VersionDropdown
                              packageId={pkg.id}
                              currentVersion={pkg.version || '-'}
                              onVersionChange={(pkgId, version) => changeVersionMutation.mutate({ packageId: pkgId, version })}
                            />
                          </td>
                          <td 
                            className="px-4 py-3 text-sm text-gray-300 cursor-pointer"
                            onClick={() => navigate(`/packages/${pkg.id}`)}
                          >
                            {pkg.dependent_packages && pkg.dependent_packages.length > 0 ? (
                              <div className="flex flex-wrap gap-1">
                                {pkg.dependent_packages.slice(0, 3).map((dep, idx) => (
                                  <span key={idx} className="px-2 py-1 bg-purple-900/30 text-purple-300 text-xs rounded">
                                    {dep}
                                  </span>
                                ))}
                                {pkg.dependent_packages.length > 3 && (
                                  <span className="px-2 py-1 bg-gray-700 text-gray-400 text-xs rounded">
                                    +{pkg.dependent_packages.length - 3} more
                                  </span>
                                )}
                              </div>
                            ) : (
                              <span className="text-gray-500">-</span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-sm text-gray-300">
                            {pkg.extras && pkg.extras.length > 0 ? (
                              <div className="flex flex-wrap gap-1">
                                {pkg.extras.map((extra) => (
                                  <button
                                    key={extra.id}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleToggleExtra(pkg.id, extra.id, extra.enabled);
                                    }}
                                    className={`px-2 py-1 text-xs rounded cursor-pointer transition-colors ${
                                      extra.enabled
                                        ? 'bg-green-900/30 text-green-300 hover:bg-green-900/50'
                                        : 'bg-red-900/30 text-red-300 hover:bg-red-900/50'
                                    }`}
                                    title={extra.enabled ? `Click to disable extra: ${extra.name}` : `Click to enable extra: ${extra.name}`}
                                  >
                                    {extra.name}
                                  </button>
                                ))}
                              </div>
                            ) : (
                              <span className="text-gray-500">-</span>
                            )}
                          </td>
                          <td 
                            className="px-4 py-3 whitespace-nowrap text-sm text-gray-300 cursor-pointer"
                            onClick={() => navigate(`/packages/${pkg.id}`)}
                          >
                            {pkg.build_order ?? '-'}
                          </td>
                          <td 
                            className="px-4 py-3 whitespace-nowrap text-sm cursor-pointer"
                            onClick={() => navigate(`/packages/${pkg.id}`)}
                          >
                            <StatusBadge status={pkg.status} />
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-300">
                            {pkg.source_fetched ? (
                              <a
                                href={`file://${pkg.source_path}`}
                                className="text-green-400 hover:text-green-300 underline"
                                onClick={(e) => e.stopPropagation()}
                              >
                                Downloaded
                              </a>
                            ) : (
                              <span className="text-gray-500">Not fetched</span>
                            )}
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap text-sm">
                            {pkg.build_status === 'completed' && (
                              <span className="px-2 py-1 bg-green-900/30 text-green-300 text-xs rounded">
                                Built
                              </span>
                            )}
                            {pkg.build_status === 'failed' && (
                              <span className="px-2 py-1 bg-red-900/30 text-red-300 text-xs rounded" title={pkg.build_error_message}>
                                Failed
                              </span>
                            )}
                            {pkg.build_status === 'building' && (
                              <span className="px-2 py-1 bg-blue-900/30 text-blue-300 text-xs rounded flex items-center gap-1">
                                <RefreshCw className="h-3 w-3 animate-spin" />
                                Building
                              </span>
                            )}
                            {pkg.build_status === 'waiting_for_deps' && (
                              <span className="px-2 py-1 bg-orange-900/30 text-orange-300 text-xs rounded flex items-center gap-1">
                                <Clock className="h-3 w-3" />
                                Waiting for deps
                              </span>
                            )}
                            {pkg.build_status === 'pending' && (
                              <span className="px-2 py-1 bg-yellow-900/30 text-yellow-300 text-xs rounded">
                                Pending
                              </span>
                            )}
                            {pkg.build_status === 'not_built' && (
                              <span className="px-2 py-1 bg-gray-700 text-gray-400 text-xs rounded">
                                Not Built
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-300">
                            <div className="flex flex-col gap-1">
                              {pkg.rpm_path && (
                                <button
                                  onClick={async (e) => {
                                    e.stopPropagation();
                                    try {
                                      const response = await packagesAPI.downloadRpm(pkg.id);
                                      const url = window.URL.createObjectURL(response.data);
                                      const link = document.createElement('a');
                                      link.href = url;
                                      link.download = pkg.rpm_path.split('/').pop();
                                      document.body.appendChild(link);
                                      link.click();
                                      document.body.removeChild(link);
                                      window.URL.revokeObjectURL(url);
                                    } catch (error) {
                                      console.error('Download failed:', error);
                                    }
                                  }}
                                  className="text-blue-400 hover:text-blue-300 underline text-xs bg-transparent border-none cursor-pointer text-left"
                                >
                                  RPM
                                </button>
                              )}
                              {pkg.srpm_path && (
                                <button
                                  onClick={async (e) => {
                                    e.stopPropagation();
                                    try {
                                      const response = await packagesAPI.downloadSrpm(pkg.id);
                                      const url = window.URL.createObjectURL(response.data);
                                      const link = document.createElement('a');
                                      link.href = url;
                                      link.download = pkg.srpm_path.split('/').pop();
                                      document.body.appendChild(link);
                                      link.click();
                                      document.body.removeChild(link);
                                      window.URL.revokeObjectURL(url);
                                    } catch (error) {
                                      console.error('Download failed:', error);
                                    }
                                  }}
                                  className="text-blue-400 hover:text-blue-300 underline text-xs bg-transparent border-none cursor-pointer text-left"
                                >
                                  SRPM
                                </button>
                              )}
                              {!pkg.rpm_path && !pkg.srpm_path && (
                                <span className="text-gray-500 text-xs">-</span>
                              )}
                            </div>
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-300">
                            <div className="flex items-center gap-2 flex-wrap">
                              {['building', 'pending'].includes(pkg.build_status) && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleViewBuildLog(pkg);
                                  }}
                                  className="px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 flex items-center gap-1 animate-pulse"
                                  title="View live build log"
                                >
                                  <Terminal className="h-3 w-3" />
                                  Live Log
                                </button>
                              )}
                              {!['building', 'pending', 'waiting_for_deps'].includes(pkg.build_status) && (pkg.has_build_log || pkg.build_error_message || pkg.build_status === 'completed' || pkg.build_status === 'failed') && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleViewBuildLog(pkg);
                                  }}
                                  className="px-3 py-1 bg-gray-700 text-white rounded hover:bg-gray-600 flex items-center gap-1"
                                  title="View build log"
                                >
                                  <Terminal className="h-3 w-3" />
                                  Log
                                </button>
                              )}
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleGenerateSpec(pkg.id);
                                }}
                                className="px-3 py-1 bg-purple-600 text-white rounded hover:bg-purple-700 flex items-center gap-1"
                                title="Generate SPEC file for this package"
                              >
                                <FileCode className="h-3 w-3" />
                                Gen Spec
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleFetchSource(pkg.id);
                                }}
                                disabled={!pkg.spec_files_count || pkg.spec_files_count === 0}
                                className="px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                                title={!pkg.spec_files_count || pkg.spec_files_count === 0 ? "Generate spec file first" : "Fetch source files"}
                              >
                                <Download className="h-3 w-3" />
                                Fetch
                              </button>
                              {pkg.build_status === 'waiting_for_deps' ? (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleCancelBuild(pkg.id);
                                  }}
                                  className="px-3 py-1 bg-red-600 text-white rounded hover:bg-red-700 flex items-center gap-1"
                                  title="Cancel waiting build"
                                >
                                  <X className="h-3 w-3" />
                                  Cancel
                                </button>
                              ) : pkg.build_status === 'not_built' || pkg.build_status === 'pending' ? (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleBuildPackage(pkg.id);
                                  }}
                                  disabled={!pkg.source_fetched || !pkg.spec_files_count || pkg.build_status === 'building' || pkg.build_status === 'pending'}
                                  className="px-3 py-1 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                                  title={!pkg.source_fetched ? "Fetch source first" : !pkg.spec_files_count ? "Generate spec file first" : "Build package"}
                                >
                                  <Hammer className="h-3 w-3" />
                                  Build
                                </button>
                              ) : (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleRebuildPackage(pkg.id);
                                  }}
                                  disabled={!pkg.source_fetched || !pkg.spec_files_count || pkg.build_status === 'building' || pkg.build_status === 'pending'}
                                  className="px-3 py-1 bg-orange-600 text-white rounded hover:bg-orange-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                                  title="Rebuild package"
                                >
                                  <RefreshCw className="h-3 w-3" />
                                  Rebuild
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {/* Transitive Dependencies Pagination */}
                {totalPages > 1 && (
                  <div className="mt-4 flex items-center justify-between">
                    <div className="text-sm text-gray-400">
                      Showing {startIdx + 1} to {Math.min(endIdx, packagesData.transitive_dependencies.length)} of {packagesData.transitive_dependencies.length} transitive dependencies
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => setTransitivePage(p => Math.max(1, p - 1))}
                        disabled={transitivePage === 1}
                        className="px-3 py-1 bg-gray-800 text-gray-300 rounded hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                      >
                        <ChevronLeft className="h-4 w-4" />
                        Previous
                      </button>
                      <span className="text-sm text-gray-400">
                        Page {transitivePage} of {totalPages}
                      </span>
                      <button
                        onClick={() => setTransitivePage(p => Math.min(totalPages, p + 1))}
                        disabled={transitivePage === totalPages}
                        className="px-3 py-1 bg-gray-800 text-gray-300 rounded hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                      >
                        Next
                        <ChevronRight className="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                )}
              </div>
              );
            })()}
          </div>
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
          isOpen={true}
          onClose={() => setShowRegenerateConfirm(false)}
          title="Regenerate Spec Files"
          message={`This will regenerate spec files for all ${packagesData?.count || 0} packages in this project. WARNING: Any manually changed package versions will be reset to the versions specified in the requirements files. This action cannot be undone. Continue?`}
          confirmText="Regenerate"
          cancelText="Cancel"
          onConfirm={handleRegenerateSpecs}
          variant="warning"
        />
      )}

      {/* Build Log Modal - WebSocket-based live streaming */}
      {showBuildLog && selectedPackageLog && (
        <LivePackageBuildLog
          packageId={selectedPackageLog.id}
          packageName={selectedPackageLog.name}
          onClose={() => {
            setShowBuildLog(false);
            setSelectedPackageLog(null);
          }}
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
  const logsContainerRef = useRef(null);

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
    // Auto-scroll to bottom within the container only
    if (logsContainerRef.current) {
      logsContainerRef.current.scrollTop = logsContainerRef.current.scrollHeight;
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
      <div 
        ref={logsContainerRef}
        className="bg-gray-900 rounded border border-gray-700 p-4 h-96 overflow-y-auto font-mono text-sm"
      >
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
          </>
        )}
      </div>
    </div>
  );
}
