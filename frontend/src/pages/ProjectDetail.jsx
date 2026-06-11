import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, GitBranch, Package, AlertCircle, AlertTriangle, CheckCircle, Clock, XCircle, Edit2, RefreshCw, ChevronLeft, ChevronRight, ChevronUp, ChevronDown, ChevronsUpDown, Hammer, Download, X, Terminal, FileCode, Wrench, Network } from 'lucide-react';
import { useState, useEffect, useRef } from 'react';
import { projectsAPI, buildsAPI, packagesAPI } from '../lib/api';
import { MockStatus } from '../components/SystemHealthBanner';
import ConfirmDialog from '../components/ConfirmDialog';
import LivePackageBuildLog from '../components/LivePackageBuildLog';
import { useToast } from '../contexts/ToastContext';

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

const VersionDropdown = ({ packageId, currentVersion, onVersionChange, toast }) => {
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
        toast.error('Failed to fetch versions');
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

const BUILD_SYSTEMS = [
  { value: 'unknown', label: 'Unknown' },
  { value: 'setuptools', label: 'Setuptools' },
  { value: 'poetry', label: 'Poetry' },
  { value: 'flit', label: 'Flit' },
  { value: 'hatchling', label: 'Hatchling' },
  { value: 'pdm', label: 'PDM' },
  { value: 'meson', label: 'Meson' },
  { value: 'scikit-build', label: 'Scikit-Build' },
  { value: 'other-pyproject', label: 'Other (pyproject)' },
];

const BUILD_SYSTEM_COLORS = {
  unknown: 'text-gray-400 bg-gray-800/40 border-gray-700',
  setuptools: 'text-yellow-400 bg-yellow-900/20 border-yellow-800/50',
  poetry: 'text-pink-400 bg-pink-900/20 border-pink-800/50',
  flit: 'text-cyan-400 bg-cyan-900/20 border-cyan-800/50',
  hatchling: 'text-orange-400 bg-orange-900/20 border-orange-800/50',
  pdm: 'text-blue-400 bg-blue-900/20 border-blue-800/50',
  meson: 'text-red-400 bg-red-900/20 border-red-800/50',
  'scikit-build': 'text-green-400 bg-green-900/20 border-green-800/50',
  'other-pyproject': 'text-purple-400 bg-purple-900/20 border-purple-800/50',
};

const BuildSystemDropdown = ({ packageId, currentBuildSystem, onBuildSystemChange }) => {
  const [isOpen, setIsOpen] = useState(false);
  const current = BUILD_SYSTEMS.find(bs => bs.value === currentBuildSystem);
  const label = current ? current.label : (currentBuildSystem || 'unknown');
  const colorClass = BUILD_SYSTEM_COLORS[currentBuildSystem] || BUILD_SYSTEM_COLORS.unknown;

  return (
    <div className="relative">
      <button
        onClick={(e) => { e.stopPropagation(); setIsOpen(!isOpen); }}
        className={`text-xs px-2 py-0.5 rounded border font-mono ${colorClass} hover:opacity-80`}
      >
        {label}
      </button>
      {isOpen && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setIsOpen(false)} />
          <div className="absolute z-20 mt-1 w-44 bg-gray-700 border border-gray-600 rounded-md shadow-lg max-h-60 overflow-auto flex flex-col">
            {BUILD_SYSTEMS.map((bs) => (
              <button
                key={bs.value}
                onClick={(e) => { e.stopPropagation(); setIsOpen(false); if (bs.value !== currentBuildSystem) onBuildSystemChange(packageId, bs.value); }}
                className={`w-full text-left px-3 py-2 text-xs hover:bg-gray-600 ${
                  bs.value === currentBuildSystem ? 'bg-gray-600 text-white' : 'text-gray-200'
                }`}
              >
                {bs.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
};

function sortPackages(list, { key, dir }) {
  if (!key) return list;
  return [...list].sort((a, b) => {
    let av = a[key];
    let bv = b[key];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (Array.isArray(av)) av = av.length;
    if (Array.isArray(bv)) bv = bv.length;
    if (typeof av === 'boolean') { av = av ? 1 : 0; bv = typeof bv === 'boolean' ? (bv ? 1 : 0) : 0; }
    if (typeof av === 'number' && typeof bv === 'number') return dir === 'asc' ? av - bv : bv - av;
    const cmp = String(av).toLowerCase().localeCompare(String(bv).toLowerCase());
    return dir === 'asc' ? cmp : -cmp;
  });
}

const SortTh = ({ label, sortKey, sort, onSort }) => {
  const active = sortKey && sort.key === sortKey;
  const Icon = active ? (sort.dir === 'asc' ? ChevronUp : ChevronDown) : ChevronsUpDown;
  return (
    <th
      className={`px-4 py-3 text-left text-xs font-medium uppercase tracking-wider ${
        sortKey ? 'cursor-pointer select-none text-gray-400 hover:text-white' : 'text-gray-400'
      }`}
      onClick={sortKey ? () => onSort(sortKey) : undefined}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {sortKey && <Icon className={`h-3 w-3 ${active ? 'text-blue-400' : 'opacity-30'}`} />}
      </span>
    </th>
  );
};

export default function ProjectDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [showEditRequirements, setShowEditRequirements] = useState(false);
  const [showLogs, setShowLogs] = useState(false);
  const [showEditConfig, setShowEditConfig] = useState(false);
  const [showRegenerateConfirm, setShowRegenerateConfirm] = useState(false);
  const [showBuildLog, setShowBuildLog] = useState(false);
  const [selectedPackageLog, setSelectedPackageLog] = useState(null);
  const [directPage, setDirectPage] = useState(1);
  const [transitivePage, setTransitivePage] = useState(1);
  const [pageSize] = useState(20);
  const [packageSearch, setPackageSearch] = useState('');
  const [directSort, setDirectSort] = useState({ key: null, dir: 'asc' });
  const [transitiveSort, setTransitiveSort] = useState({ key: null, dir: 'asc' });
  const [wsConnected, setWsConnected] = useState(false);
  const [generatingSpecPackages, setGeneratingSpecPackages] = useState(new Set());
  const [buildStatusFilter, setBuildStatusFilter] = useState(null);
  const wsRef = useRef(null);

  // Build status → actual build_status values to match
  const STATUS_FILTER_MAP = {
    completed:        ['completed'],
    building:         ['building'],
    failed:           ['failed', 'missing_packages'],
    pending:          ['pending'],
    waiting_for_deps: ['waiting_for_deps'],
    dep_build_pending:['dep_build_pending'],
    not_built:        ['not_built'],
  };

  const handleStatusFilterClick = (key) => {
    setBuildStatusFilter(prev => prev === key ? null : key);
    setDirectPage(1);
    setTransitivePage(1);
  };

  const applyBuildStatusFilter = (list) => {
    if (!buildStatusFilter) return list;
    const allowed = STATUS_FILTER_MAP[buildStatusFilter] || [];
    return list.filter(p => allowed.includes(p.build_status));
  };

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

  // Track package statuses for change notifications
  const prevPkgStatusRef = useRef({});
  const pkgStatusInitializedRef = useRef(false);

  // Initialize status tracking when package data first loads
  useEffect(() => {
    if (!packagesData || pkgStatusInitializedRef.current) return;
    const allPkgs = [
      ...(packagesData.packages || []),
      ...(packagesData.direct_dependencies || []),
      ...(packagesData.transitive_dependencies || []),
    ];
    allPkgs.forEach(pkg => {
      prevPkgStatusRef.current[pkg.id] = pkg.build_status;
    });
    pkgStatusInitializedRef.current = true;
  }, [packagesData]);

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
          const updatedPkg = data.package;
          const prevStatus = prevPkgStatusRef.current[updatedPkg.id];

          if (pkgStatusInitializedRef.current) {
            if (prevStatus === undefined) {
              toast.info(`Dependency added: ${updatedPkg.name}`);
            } else if (prevStatus !== updatedPkg.build_status) {
              if (updatedPkg.build_status === 'failed') {
                toast.error(`Package failed: ${updatedPkg.name}`);
              } else if (updatedPkg.build_status === 'completed') {
                toast.success(`Built: ${updatedPkg.name}`);
              }
            }
          }
          prevPkgStatusRef.current[updatedPkg.id] = updatedPkg.build_status;

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
      toast.error(`Failed to resolve dependencies: ${error.response?.data?.detail || error.message}`);
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
      toast.error(`Failed to start build: ${error.response?.data?.detail || error.message}`);
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
      toast.error(`Failed to regenerate specs: ${error.response?.data?.detail || error.message}`);
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
      toast.error(`Failed to fetch source: ${error.response?.data?.detail || error.message}`);
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
    onMutate: (packageId) => {
      setGeneratingSpecPackages(prev => new Set(prev).add(packageId));
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
      toast.error(`Failed to generate spec: ${error.response?.data?.detail || error.message}`);
    },
    onSettled: (data, error, packageId) => {
      // Remove from pending set after completion (success or error)
      setGeneratingSpecPackages(prev => {
        const next = new Set(prev);
        next.delete(packageId);
        return next;
      });
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
      toast.error(`Failed to toggle extra: ${error.response?.data?.error || error.message}`);
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
      queryClient.invalidateQueries(['project-packages', id]);
      queryClient.invalidateQueries(['project', id]);
    },
    onError: (error) => {
      toast.error(`Failed to change version: ${error.response?.data?.error || error.message}`);
    },
  });

  const changeBuildSystemMutation = useMutation({
    mutationFn: async ({ packageId, buildSystem }) => {
      const response = await packagesAPI.changeBuildSystem(packageId, buildSystem);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['project-packages', id]);
    },
    onError: (error) => {
      toast.error(`Failed to change build system: ${error.response?.data?.error || error.message}`);
    },
  });

  const fetchAllSourcesMutation = useMutation({
    mutationFn: async () => {
      const response = await projectsAPI.fetchAllSources(id);
      return response.data;
    },
    onSuccess: (data) => {
      toast.info(`Started fetching sources for ${data.count} packages`);
      // Refetch packages to update source status
      queryClient.invalidateQueries(['project-packages', id]);
    },
    onError: (error) => {
      toast.error(`Failed to fetch sources: ${error.response?.data?.error || error.message}`);
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
    onMutate: (packageId) => {
      const setPending = (pkg) => pkg.id === packageId ? { ...pkg, build_status: 'pending' } : pkg;
      queryClient.setQueryData(['project-packages', id], (old) => {
        if (!old) return old;
        return {
          ...old,
          packages: old.packages?.map(setPending),
          direct_dependencies: old.direct_dependencies?.map(setPending),
          transitive_dependencies: old.transitive_dependencies?.map(setPending),
        };
      });
    },
    onSuccess: (data) => {
      setShowLogs(true);
      queryClient.invalidateQueries(['project-packages', id]);
    },
    onError: (error) => {
      queryClient.invalidateQueries(['project-packages', id]);
      toast.error(`Failed to build package: ${error.response?.data?.detail || error.message}`);
    },
  });

  const rebuildPackageMutation = useMutation({
    mutationFn: async (packageId) => {
      const response = await packagesAPI.rebuildPackage(packageId);
      return response.data;
    },
    onMutate: (packageId) => {
      const setPending = (pkg) => pkg.id === packageId ? { ...pkg, build_status: 'pending' } : pkg;
      queryClient.setQueryData(['project-packages', id], (old) => {
        if (!old) return old;
        return {
          ...old,
          packages: old.packages?.map(setPending),
          direct_dependencies: old.direct_dependencies?.map(setPending),
          transitive_dependencies: old.transitive_dependencies?.map(setPending),
        };
      });
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries(['project-packages', id]);
      setShowLogs(true);
    },
    onError: (error) => {
      queryClient.invalidateQueries(['project-packages', id]);
      toast.error(`Failed to rebuild package: ${error.response?.data?.detail || error.message}`);
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
      toast.error(`Failed to cancel build: ${error.response?.data?.detail || error.message}`);
    },
  });

  const buildAllPackagesMutation = useMutation({
    mutationFn: async () => {
      const response = await projectsAPI.buildAllPackages(id);
      return response.data;
    },
    onSuccess: (data) => {
      // Refetch first so real DB statuses load while the toast is visible
      queryClient.invalidateQueries(['project-packages', id]);
      setShowLogs(true);
      toast.success(`Started building ${data.count} packages`);
    },
    onError: (error) => {
      queryClient.invalidateQueries(['project-packages', id]);
      toast.error(`Failed to build packages: ${error.response?.data?.detail || error.message}`);
    },
  });

  const regenerateFailedSpecsMutation = useMutation({
    mutationFn: async () => {
      const response = await projectsAPI.regenerateFailedSpecs(id);
      return response.data;
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries(['project-packages', id]);
      setShowLogs(true);
      toast.info(`Regenerating specs for ${data.count} failed package(s)`);
    },
    onError: (error) => {
      toast.error(`Failed to regenerate specs: ${error.response?.data?.detail || error.message}`);
    },
  });

  const handleBuildPackage = (packageId) => {
    buildPackageMutation.mutate(packageId);
  };

  const handleRebuildPackage = (packageId) => {
    rebuildPackageMutation.mutate(packageId);
  };

  const fixAndRebuildMutation = useMutation({
    mutationFn: async (packageId) => {
      const response = await packagesAPI.fixAndRebuild(packageId);
      return response.data;
    },
    onMutate: (packageId) => {
      const setPending = (pkg) => pkg.id === packageId ? { ...pkg, build_status: 'pending' } : pkg;
      queryClient.setQueryData(['project-packages', id], (old) => {
        if (!old) return old;
        return {
          ...old,
          packages: old.packages?.map(setPending),
          direct_dependencies: old.direct_dependencies?.map(setPending),
          transitive_dependencies: old.transitive_dependencies?.map(setPending),
        };
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['project-packages', id]);
      setShowLogs(true);
    },
    onError: (error) => {
      queryClient.invalidateQueries(['project-packages', id]);
      toast.error(`Failed to fix & rebuild: ${error.response?.data?.detail || error.message}`);
    },
  });

  const handleFixAndRebuild = (packageId) => {
    fixAndRebuildMutation.mutate(packageId);
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
      toast.warning('Please configure RHEL versions in project settings before building');
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
          <button
            onClick={() => navigate(`/projects/${id}/dependency-map`)}
            className="flex items-center gap-2 px-4 py-2 bg-teal-700 text-white rounded-lg hover:bg-teal-600 transition-colors"
            title="View dependency map for this project"
          >
            <Network className="h-4 w-4" />
            Dependency Map
          </button>
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
                onClick={() => regenerateFailedSpecsMutation.mutate()}
                disabled={regenerateFailedSpecsMutation.isPending}
                className="flex items-center gap-2 px-4 py-2 bg-rose-600 text-white rounded-lg hover:bg-rose-700 disabled:opacity-50 transition-colors"
                title="Regenerate spec files only for packages with failed builds"
              >
                <Wrench className={`h-4 w-4 ${regenerateFailedSpecsMutation.isPending ? 'animate-spin' : ''}`} />
                Regen Failed Specs
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
                title="Build all packages that failed or haven't been built yet"
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

      {/* Build Stats Bar */}
      {packagesData?.packages?.length > 0 && (() => {
        const all = packagesData.packages;
        const count = (statuses) => all.filter(p => statuses.includes(p.build_status)).length;
        const total = all.length;
        const stats = [
          { key: 'completed',         label: 'Built',            n: count(['completed']),                          color: 'text-green-400',  ring: 'ring-green-500',  bg: 'bg-green-500/10',  dot: 'bg-green-400' },
          { key: 'building',          label: 'Building',         n: count(['building']),                           color: 'text-blue-400',   ring: 'ring-blue-500',   bg: 'bg-blue-500/10',   dot: 'bg-blue-400', pulse: true },
          { key: 'failed',            label: 'Failed',           n: count(['failed', 'missing_packages']),          color: 'text-red-400',    ring: 'ring-red-500',    bg: 'bg-red-500/10',    dot: 'bg-red-400' },
          { key: 'pending',           label: 'Pending',          n: count(['pending']),                            color: 'text-gray-400',   ring: 'ring-gray-500',   bg: 'bg-gray-500/10',   dot: 'bg-gray-400' },
          { key: 'waiting_for_deps',  label: 'Waiting for deps', n: count(['waiting_for_deps']),                   color: 'text-amber-400',  ring: 'ring-amber-500',  bg: 'bg-amber-500/10',  dot: 'bg-amber-400' },
          { key: 'dep_build_pending', label: 'Blocked by deps',  n: count(['dep_build_pending']),                  color: 'text-orange-400', ring: 'ring-orange-500', bg: 'bg-orange-500/10', dot: 'bg-orange-400' },
          { key: 'not_built',         label: 'Not built',        n: count(['not_built']),                          color: 'text-gray-500',   ring: 'ring-gray-600',   bg: 'bg-gray-600/10',   dot: 'bg-gray-500' },
        ];
        // Progress bar: completed / total
        const builtPct = total ? Math.round((count(['completed']) / total) * 100) : 0;
        return (
          <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
            {/* Progress bar */}
            <div className="flex items-center gap-3 mb-3">
              <div className="flex-1 h-2 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-green-500 transition-all duration-500"
                  style={{ width: `${builtPct}%` }}
                />
              </div>
              <span className="text-xs text-gray-400 shrink-0">{builtPct}% built ({count(['completed'])}/{total})</span>
              {buildStatusFilter && (
                <button
                  onClick={() => { setBuildStatusFilter(null); setDirectPage(1); setTransitivePage(1); }}
                  className="text-xs text-gray-400 hover:text-white underline shrink-0"
                >
                  Clear filter
                </button>
              )}
            </div>
            {/* Stat cards */}
            <div className="flex flex-wrap gap-2">
              {stats.filter(s => s.n > 0).map(s => (
                <button
                  key={s.key}
                  onClick={() => handleStatusFilterClick(s.key)}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border transition-all text-sm ${
                    buildStatusFilter === s.key
                      ? `${s.bg} border-current ring-1 ${s.ring} ${s.color}`
                      : 'bg-gray-900/50 border-gray-700 text-gray-300 hover:border-gray-500'
                  }`}
                >
                  <span className={`w-2 h-2 rounded-full shrink-0 ${s.dot} ${s.pulse ? 'animate-pulse' : ''}`} />
                  <span className={`font-semibold ${buildStatusFilter === s.key ? s.color : ''}`}>{s.n}</span>
                  <span className={`${buildStatusFilter === s.key ? s.color : 'text-gray-400'}`}>{s.label}</span>
                </button>
              ))}
            </div>
          </div>
        );
      })()}

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
              <label className="text-sm font-medium text-gray-400">RHEL Version</label>
              <p className="text-sm text-gray-300 mt-1">
                {project.rhel_version ? `RHEL ${project.rhel_version}` : 'Not specified'}
              </p>
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
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <Package className="h-5 w-5" />
              Packages ({packagesData?.count || 0})
            </h2>
            <input
              type="text"
              placeholder="Filter packages…"
              value={packageSearch}
              onChange={(e) => {
                setPackageSearch(e.target.value);
                setDirectPage(1);
                setTransitivePage(1);
              }}
              className="px-3 py-1.5 bg-gray-700 border border-gray-600 rounded text-sm text-white placeholder-gray-400 focus:outline-none focus:border-blue-500 w-56"
            />
          </div>
        </div>
        
        {packagesData && packagesData.packages && packagesData.packages.length > 0 ? (
          <div className="space-y-6 p-6">
            {/* Direct Dependencies */}
            {packagesData.direct_dependencies && packagesData.direct_dependencies.length > 0 && (() => {
              const searchLower = packageSearch.toLowerCase();
              const filteredDirect = applyBuildStatusFilter(
                packageSearch
                  ? packagesData.direct_dependencies.filter(p => p.name.toLowerCase().includes(searchLower))
                  : packagesData.direct_dependencies
              );
              const sortedDirect = sortPackages(filteredDirect, directSort);
              const startIdx = (directPage - 1) * pageSize;
              const endIdx = startIdx + pageSize;
              const paginatedDirect = sortedDirect.slice(startIdx, endIdx);
              const totalPages = Math.ceil(filteredDirect.length / pageSize);
              if (filteredDirect.length === 0) return null;
              
              return (
              <div>
                <h3 className="text-md font-semibold text-white mb-4 flex items-center gap-2">
                  📋 Direct Dependencies ({(packageSearch || buildStatusFilter) ? `${filteredDirect.length} of ` : ''}{packagesData.direct_count || packagesData.direct_dependencies.length})
                  <span className="text-xs text-gray-400 font-normal">
                    Packages from requirements files
                  </span>
                </h3>
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-700">
                    <thead className="bg-gray-900">
                      <tr>
                        <SortTh label="Package Name" sortKey="name" sort={directSort} onSort={(k) => { setDirectSort(p => p.key===k ? {key:k,dir:p.dir==='asc'?'desc':'asc'} : {key:k,dir:'asc'}); setDirectPage(1); }} />
                        <SortTh label="Version" sortKey="version" sort={directSort} onSort={(k) => { setDirectSort(p => p.key===k ? {key:k,dir:p.dir==='asc'?'desc':'asc'} : {key:k,dir:'asc'}); setDirectPage(1); }} />
                        <SortTh label="Build System" sortKey="build_system" sort={directSort} onSort={(k) => { setDirectSort(p => p.key===k ? {key:k,dir:p.dir==='asc'?'desc':'asc'} : {key:k,dir:'asc'}); setDirectPage(1); }} />
                        <SortTh label="Requirements File" sortKey="requirements_file" sort={directSort} onSort={(k) => { setDirectSort(p => p.key===k ? {key:k,dir:p.dir==='asc'?'desc':'asc'} : {key:k,dir:'asc'}); setDirectPage(1); }} />
                        <SortTh label="Extras" sortKey={null} sort={directSort} onSort={() => {}} />
                        <SortTh label="Build Order" sortKey="build_order" sort={directSort} onSort={(k) => { setDirectSort(p => p.key===k ? {key:k,dir:p.dir==='asc'?'desc':'asc'} : {key:k,dir:'asc'}); setDirectPage(1); }} />
                        <SortTh label="Status" sortKey="status" sort={directSort} onSort={(k) => { setDirectSort(p => p.key===k ? {key:k,dir:p.dir==='asc'?'desc':'asc'} : {key:k,dir:'asc'}); setDirectPage(1); }} />
                        <SortTh label="Source" sortKey="source_fetched" sort={directSort} onSort={(k) => { setDirectSort(p => p.key===k ? {key:k,dir:p.dir==='asc'?'desc':'asc'} : {key:k,dir:'asc'}); setDirectPage(1); }} />
                        <SortTh label="Build Status" sortKey="build_status" sort={directSort} onSort={(k) => { setDirectSort(p => p.key===k ? {key:k,dir:p.dir==='asc'?'desc':'asc'} : {key:k,dir:'asc'}); setDirectPage(1); }} />
                        <SortTh label="RPM/SRPM" sortKey="rpm_path" sort={directSort} onSort={(k) => { setDirectSort(p => p.key===k ? {key:k,dir:p.dir==='asc'?'desc':'asc'} : {key:k,dir:'asc'}); setDirectPage(1); }} />
                        <SortTh label="Actions" sortKey={null} sort={directSort} onSort={() => {}} />
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
                              toast={toast}
                            />
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-300">
                            <BuildSystemDropdown
                              packageId={pkg.id}
                              currentBuildSystem={pkg.build_system || 'unknown'}
                              onBuildSystemChange={(pkgId, buildSystem) => changeBuildSystemMutation.mutate({ packageId: pkgId, buildSystem })}
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
                            {pkg.build_status === 'missing_packages' && (
                              <span
                                className="px-2 py-1 bg-amber-900/30 text-amber-300 text-xs rounded inline-flex items-center gap-1 cursor-help"
                                title={pkg.analyzed_errors?.filter(e => ['Missing Packages','Missing Dependencies','Missing Python Modules','Missing Header Files','Missing Rust/Cargo','Missing Python Wheel','Missing GCC'].includes(e.category)).flatMap(e => e.items || []).join('\n') || pkg.build_error_message}
                              >
                                <AlertTriangle className="h-3 w-3" />
                                Missing Deps
                              </span>
                            )}
                            {pkg.build_status === 'building' && (
                              <span className="px-2 py-1 bg-blue-900/30 text-blue-300 text-xs rounded flex items-center gap-1">
                                <RefreshCw className="h-3 w-3 animate-spin" />
                                Building
                              </span>
                            )}
                            {pkg.build_status === 'waiting_for_deps' && (
                              <span
                                className={`px-2 py-1 ${(pkg.failed_dep_names?.length && !pkg.waiting_for_dep_names?.length) ? 'bg-red-900/30 text-red-300' : 'bg-orange-900/30 text-orange-300'} text-xs rounded inline-flex items-center gap-1 cursor-help`}
                                title={[
                                  pkg.failed_dep_names?.length ? `Blocked by failed dep(s):\n${pkg.failed_dep_names.join('\n')}` : '',
                                  pkg.waiting_for_dep_names?.length ? `Waiting for:\n${pkg.waiting_for_dep_names.join('\n')}` : '',
                                ].filter(Boolean).join('\n\n') || 'Waiting for dependencies to be built'}
                              >
                                <Clock className="h-3 w-3" />
                                {(pkg.failed_dep_names?.length && !pkg.waiting_for_dep_names?.length) ? 'Dep Failed' : 'Waiting for deps'}
                              </span>
                            )}
                            {pkg.build_status === 'dep_build_pending' && (
                              <span
                                className="px-2 py-1 bg-cyan-900/30 text-cyan-300 text-xs rounded inline-flex items-center gap-1 cursor-help"
                                title={pkg.dep_blocking_items?.length ? `Still waiting for:\n${pkg.dep_blocking_items.join('\n')}` : 'Waiting for project packages to be built'}
                              >
                                <Clock className="h-3 w-3" />
                                Dep Build Pending
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
                              {!['building', 'pending', 'waiting_for_deps'].includes(pkg.build_status) && (pkg.has_build_log || pkg.build_error_message || pkg.build_status === 'completed' || pkg.build_status === 'failed' || pkg.build_status === 'missing_packages' || pkg.build_status === 'dep_build_pending') && (
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
                                disabled={generatingSpecPackages.has(pkg.id)}
                                className="px-3 py-1 bg-purple-600 text-white rounded hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                                title={generatingSpecPackages.has(pkg.id) ? "Generating spec..." : "Generate SPEC file for this package"}
                              >
                                <FileCode className="h-3 w-3" />
                                {generatingSpecPackages.has(pkg.id) ? 'Generating...' : 'Gen Spec'}
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
                              {(['waiting_for_deps', 'dep_build_pending', 'missing_packages', 'pending', 'building'].includes(pkg.build_status)) ? (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleCancelBuild(pkg.id);
                                  }}
                                  className="px-3 py-1 bg-red-600 text-white rounded hover:bg-red-700 flex items-center gap-1"
                                  title={pkg.build_status === 'building' ? "Cancel running build" : "Cancel waiting build"}
                                >
                                  <X className="h-3 w-3" />
                                  Cancel
                                </button>
                              ) : pkg.build_status === 'not_built' ? (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleBuildPackage(pkg.id);
                                  }}
                                  disabled={!pkg.source_fetched || !pkg.spec_files_count || pkg.build_status === 'building'}
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
                                  disabled={!pkg.source_fetched || !pkg.spec_files_count || pkg.build_status === 'building'}
                                  className="px-3 py-1 bg-orange-600 text-white rounded hover:bg-orange-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                                  title="Rebuild package"
                                >
                                  <RefreshCw className="h-3 w-3" />
                                  Rebuild
                                </button>
                              )}
                              {['missing_packages', 'failed'].includes(pkg.build_status) && pkg.source_fetched && pkg.spec_files_count > 0 && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleFixAndRebuild(pkg.id);
                                  }}
                                  className="px-3 py-1 bg-teal-600 text-white rounded hover:bg-teal-700 flex items-center gap-1"
                                  title="Apply auto-fixes to spec and rebuild"
                                >
                                  <Wrench className="h-3 w-3" />
                                  Fix &amp; Rebuild
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
                      Showing {startIdx + 1} to {Math.min(endIdx, filteredDirect.length)} of {filteredDirect.length} direct dependencies
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
              const searchLower = packageSearch.toLowerCase();
              const filteredTransitive = applyBuildStatusFilter(
                packageSearch
                  ? packagesData.transitive_dependencies.filter(p => p.name.toLowerCase().includes(searchLower))
                  : packagesData.transitive_dependencies
              );
              const sortedTransitive = sortPackages(filteredTransitive, transitiveSort);
              const startIdx = (transitivePage - 1) * pageSize;
              const endIdx = startIdx + pageSize;
              const paginatedTransitive = sortedTransitive.slice(startIdx, endIdx);
              const totalPages = Math.ceil(filteredTransitive.length / pageSize);
              if (filteredTransitive.length === 0) return null;
              
              return (
              <div>
                <h3 className="text-md font-semibold text-white mb-4 flex items-center gap-2">
                  🔗 Transitive Dependencies ({(packageSearch || buildStatusFilter) ? `${filteredTransitive.length} of ` : ''}{packagesData.transitive_count || packagesData.transitive_dependencies.length})
                  <span className="text-xs text-gray-400 font-normal">
                    Dependencies of dependencies
                  </span>
                </h3>
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-700">
                    <thead className="bg-gray-900">
                      <tr>
                        <SortTh label="Package Name" sortKey="name" sort={transitiveSort} onSort={(k) => { setTransitiveSort(p => p.key===k ? {key:k,dir:p.dir==='asc'?'desc':'asc'} : {key:k,dir:'asc'}); setTransitivePage(1); }} />
                        <SortTh label="Version" sortKey="version" sort={transitiveSort} onSort={(k) => { setTransitiveSort(p => p.key===k ? {key:k,dir:p.dir==='asc'?'desc':'asc'} : {key:k,dir:'asc'}); setTransitivePage(1); }} />
                        <SortTh label="Build System" sortKey="build_system" sort={transitiveSort} onSort={(k) => { setTransitiveSort(p => p.key===k ? {key:k,dir:p.dir==='asc'?'desc':'asc'} : {key:k,dir:'asc'}); setTransitivePage(1); }} />
                        <SortTh label="Depended By" sortKey="dependent_packages" sort={transitiveSort} onSort={(k) => { setTransitiveSort(p => p.key===k ? {key:k,dir:p.dir==='asc'?'desc':'asc'} : {key:k,dir:'asc'}); setTransitivePage(1); }} />
                        <SortTh label="Extras" sortKey={null} sort={transitiveSort} onSort={() => {}} />
                        <SortTh label="Build Order" sortKey="build_order" sort={transitiveSort} onSort={(k) => { setTransitiveSort(p => p.key===k ? {key:k,dir:p.dir==='asc'?'desc':'asc'} : {key:k,dir:'asc'}); setTransitivePage(1); }} />
                        <SortTh label="Status" sortKey="status" sort={transitiveSort} onSort={(k) => { setTransitiveSort(p => p.key===k ? {key:k,dir:p.dir==='asc'?'desc':'asc'} : {key:k,dir:'asc'}); setTransitivePage(1); }} />
                        <SortTh label="Source" sortKey="source_fetched" sort={transitiveSort} onSort={(k) => { setTransitiveSort(p => p.key===k ? {key:k,dir:p.dir==='asc'?'desc':'asc'} : {key:k,dir:'asc'}); setTransitivePage(1); }} />
                        <SortTh label="Build Status" sortKey="build_status" sort={transitiveSort} onSort={(k) => { setTransitiveSort(p => p.key===k ? {key:k,dir:p.dir==='asc'?'desc':'asc'} : {key:k,dir:'asc'}); setTransitivePage(1); }} />
                        <SortTh label="RPM/SRPM" sortKey="rpm_path" sort={transitiveSort} onSort={(k) => { setTransitiveSort(p => p.key===k ? {key:k,dir:p.dir==='asc'?'desc':'asc'} : {key:k,dir:'asc'}); setTransitivePage(1); }} />
                        <SortTh label="Actions" sortKey={null} sort={transitiveSort} onSort={() => {}} />
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
                              toast={toast}
                            />
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-300">
                            <BuildSystemDropdown
                              packageId={pkg.id}
                              currentBuildSystem={pkg.build_system || 'unknown'}
                              onBuildSystemChange={(pkgId, buildSystem) => changeBuildSystemMutation.mutate({ packageId: pkgId, buildSystem })}
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
                            {pkg.build_status === 'missing_packages' && (
                              <span
                                className="px-2 py-1 bg-amber-900/30 text-amber-300 text-xs rounded inline-flex items-center gap-1 cursor-help"
                                title={pkg.analyzed_errors?.filter(e => ['Missing Packages','Missing Dependencies','Missing Python Modules','Missing Header Files','Missing Rust/Cargo','Missing Python Wheel','Missing GCC'].includes(e.category)).flatMap(e => e.items || []).join('\n') || pkg.build_error_message}
                              >
                                <AlertTriangle className="h-3 w-3" />
                                Missing Deps
                              </span>
                            )}
                            {pkg.build_status === 'building' && (
                              <span className="px-2 py-1 bg-blue-900/30 text-blue-300 text-xs rounded flex items-center gap-1">
                                <RefreshCw className="h-3 w-3 animate-spin" />
                                Building
                              </span>
                            )}
                            {pkg.build_status === 'waiting_for_deps' && (
                              <span
                                className={`px-2 py-1 ${(pkg.failed_dep_names?.length && !pkg.waiting_for_dep_names?.length) ? 'bg-red-900/30 text-red-300' : 'bg-orange-900/30 text-orange-300'} text-xs rounded inline-flex items-center gap-1 cursor-help`}
                                title={[
                                  pkg.failed_dep_names?.length ? `Blocked by failed dep(s):\n${pkg.failed_dep_names.join('\n')}` : '',
                                  pkg.waiting_for_dep_names?.length ? `Waiting for:\n${pkg.waiting_for_dep_names.join('\n')}` : '',
                                ].filter(Boolean).join('\n\n') || 'Waiting for dependencies to be built'}
                              >
                                <Clock className="h-3 w-3" />
                                {(pkg.failed_dep_names?.length && !pkg.waiting_for_dep_names?.length) ? 'Dep Failed' : 'Waiting for deps'}
                              </span>
                            )}
                            {pkg.build_status === 'dep_build_pending' && (
                              <span
                                className="px-2 py-1 bg-cyan-900/30 text-cyan-300 text-xs rounded inline-flex items-center gap-1 cursor-help"
                                title={pkg.dep_blocking_items?.length ? `Still waiting for:\n${pkg.dep_blocking_items.join('\n')}` : 'Waiting for project packages to be built'}
                              >
                                <Clock className="h-3 w-3" />
                                Dep Build Pending
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
                              {!['building', 'pending', 'waiting_for_deps'].includes(pkg.build_status) && (pkg.has_build_log || pkg.build_error_message || pkg.build_status === 'completed' || pkg.build_status === 'failed' || pkg.build_status === 'missing_packages' || pkg.build_status === 'dep_build_pending') && (
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
                                disabled={generatingSpecPackages.has(pkg.id)}
                                className="px-3 py-1 bg-purple-600 text-white rounded hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                                title={generatingSpecPackages.has(pkg.id) ? "Generating spec..." : "Generate SPEC file for this package"}
                              >
                                <FileCode className="h-3 w-3" />
                                {generatingSpecPackages.has(pkg.id) ? 'Generating...' : 'Gen Spec'}
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
                              {(['waiting_for_deps', 'dep_build_pending', 'missing_packages', 'pending', 'building'].includes(pkg.build_status)) ? (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleCancelBuild(pkg.id);
                                  }}
                                  className="px-3 py-1 bg-red-600 text-white rounded hover:bg-red-700 flex items-center gap-1"
                                  title={pkg.build_status === 'building' ? "Cancel running build" : "Cancel waiting build"}
                                >
                                  <X className="h-3 w-3" />
                                  Cancel
                                </button>
                              ) : pkg.build_status === 'not_built' ? (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleBuildPackage(pkg.id);
                                  }}
                                  disabled={!pkg.source_fetched || !pkg.spec_files_count || pkg.build_status === 'building'}
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
                                  disabled={!pkg.source_fetched || !pkg.spec_files_count || pkg.build_status === 'building'}
                                  className="px-3 py-1 bg-orange-600 text-white rounded hover:bg-orange-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                                  title="Rebuild package"
                                >
                                  <RefreshCw className="h-3 w-3" />
                                  Rebuild
                                </button>
                              )}
                              {['missing_packages', 'failed'].includes(pkg.build_status) && pkg.source_fetched && pkg.spec_files_count > 0 && (
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    handleFixAndRebuild(pkg.id);
                                  }}
                                  className="px-3 py-1 bg-teal-600 text-white rounded hover:bg-teal-700 flex items-center gap-1"
                                  title="Apply auto-fixes to spec and rebuild"
                                >
                                  <Wrench className="h-3 w-3" />
                                  Fix &amp; Rebuild
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
                      Showing {startIdx + 1} to {Math.min(endIdx, filteredTransitive.length)} of {filteredTransitive.length} transitive dependencies
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
    rhel_version: project.rhel_version || '9',
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
              RHEL Version to Build *
            </label>
            <div className="space-y-2">
              {['8', '9', '10'].map((version) => (
                <label key={version} className="flex items-center space-x-2 cursor-pointer">
                  <input
                    type="radio"
                    name="rhel_version"
                    value={version}
                    checked={formData.rhel_version === version}
                    onChange={(e) => {
                      setFormData(prev => ({
                        ...prev,
                        rhel_version: e.target.value
                      }));
                    }}
                    className="form-radio h-4 w-4 text-blue-600 bg-gray-700 border-gray-600 focus:ring-blue-500"
                  />
                  <span className="text-gray-300">RHEL {version}</span>
                </label>
              ))}
            </div>
            <p className="mt-1 text-xs text-gray-400">
              Select RHEL version to build packages for
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
