import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Boxes, Play, XCircle, CheckCircle, Clock, Loader, Download, AlertCircle, Package as PackageIcon, ChevronDown, ChevronRight, FileText, RefreshCw } from 'lucide-react';
import { useState } from 'react';
import { buildsAPI } from '../lib/api';

const StatusBadge = ({ status }) => {
  const statusConfig = {
    pending: { color: 'bg-yellow-100 text-yellow-800', icon: Clock, label: 'Pending' },
    preparing: { color: 'bg-blue-100 text-blue-800', icon: Loader, label: 'Preparing' },
    queued: { color: 'bg-indigo-100 text-indigo-800', icon: Clock, label: 'Queued' },
    running: { color: 'bg-blue-100 text-blue-800', icon: Play, label: 'Running' },
    completed: { color: 'bg-green-100 text-green-800', icon: CheckCircle, label: 'Completed' },
    failed: { color: 'bg-red-100 text-red-800', icon: XCircle, label: 'Failed' },
    cancelled: { color: 'bg-gray-100 text-gray-800', icon: XCircle, label: 'Cancelled' },
  };

  const config = statusConfig[status] || statusConfig.pending;
  const Icon = config.icon;

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${config.color}`}>
      <Icon className="h-3 w-3" />
      {config.label}
    </span>
  );
};

export default function BuildDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [expandedLogs, setExpandedLogs] = useState({});

  const toggleLog = (itemId) => {
    setExpandedLogs(prev => ({
      ...prev,
      [itemId]: !prev[itemId]
    }));
  };

  const { data: build, isLoading, error } = useQuery({
    queryKey: ['build', id],
    queryFn: async () => {
      const response = await buildsAPI.get(id);
      return response.data;
    },
    refetchInterval: (data) => {
      // Auto-refresh if build is in progress
      if (data && ['pending', 'preparing', 'queued', 'running'].includes(data.status)) {
        return 5000; // 5 seconds
      }
      return false;
    },
  });

  const { data: queue } = useQuery({
    queryKey: ['build-queue', id],
    queryFn: async () => {
      const response = await buildsAPI.queue(id);
      return response.data;
    },
    enabled: !!build,
    refetchInterval: (data) => {
      if (build && ['pending', 'preparing', 'queued', 'running'].includes(build.status)) {
        return 5000;
      }
      return false;
    },
  });

  const cancelMutation = useMutation({
    mutationFn: async () => {
      const response = await buildsAPI.cancel(id);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['build', id]);
      queryClient.invalidateQueries(['build-queue', id]);
    },
  });

  const retryMutation = useMutation({
    mutationFn: async () => {
      const response = await buildsAPI.retry(id);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['build', id]);
      queryClient.invalidateQueries(['build-queue', id]);
    },
  });

  const retryQueueItemMutation = useMutation({
    mutationFn: async (queueItemId) => {
      const response = await buildsAPI.retryQueueItem(queueItemId);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['build', id]);
      queryClient.invalidateQueries(['build-queue', id]);
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader className="h-8 w-8 text-indigo-400 animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <XCircle className="h-12 w-12 text-red-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-white mb-2">Error loading build</h3>
          <p className="text-gray-400">{error.message}</p>
        </div>
      </div>
    );
  }

  const progress = build.total_packages > 0 
    ? (build.completed_packages / build.total_packages) * 100 
    : 0;

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
              <Boxes className="h-7 w-7" />
              Build Job #{build.id}
            </h1>
            <p className="text-gray-400 mt-1">
              {build.project_name || `Project #${build.project}`} - {build.build_version}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={build.status} />
          {build.status === 'running' && (
            <button
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 disabled:bg-gray-600 text-white rounded-lg transition-colors"
            >
              <XCircle className="h-4 w-4" />
              Cancel
            </button>
          )}
          {build.status === 'failed' && (
            <button
              onClick={() => retryMutation.mutate()}
              disabled={retryMutation.isPending}
              className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-600 text-white rounded-lg transition-colors"
            >
              <Play className="h-4 w-4" />
              Retry
            </button>
          )}
        </div>
      </div>

      {/* Build Info */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-gray-800 shadow rounded-lg p-6 border border-gray-700">
          <h2 className="text-lg font-semibold text-white mb-4">Build Information</h2>
          <div className="space-y-3">
            <div>
              <label className="text-sm font-medium text-gray-400">Git Reference</label>
              <p className="text-gray-200">{build.git_ref}</p>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-400">Git Commit</label>
              <p className="text-gray-200 font-mono text-sm">{build.git_commit}</p>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-400">RHEL Versions</label>
              <div className="flex flex-wrap gap-2 mt-1">
                {build.rhel_versions?.map((version) => (
                  <span
                    key={version}
                    className="px-2 py-1 bg-gray-700 text-gray-300 text-xs rounded"
                  >
                    RHEL {version}
                  </span>
                ))}
              </div>
            </div>
            <div>
              <label className="text-sm font-medium text-gray-400">Created</label>
              <p className="text-gray-200">{new Date(build.created_at).toLocaleString()}</p>
            </div>
            {build.started_at && (
              <div>
                <label className="text-sm font-medium text-gray-400">Started</label>
                <p className="text-gray-200">{new Date(build.started_at).toLocaleString()}</p>
              </div>
            )}
            {build.completed_at && (
              <div>
                <label className="text-sm font-medium text-gray-400">Completed</label>
                <p className="text-gray-200">{new Date(build.completed_at).toLocaleString()}</p>
              </div>
            )}
          </div>
        </div>

        <div className="bg-gray-800 shadow rounded-lg p-6 border border-gray-700">
          <h2 className="text-lg font-semibold text-white mb-4">Progress</h2>
          <div className="space-y-4">
            <div>
              <div className="flex justify-between text-sm text-gray-400 mb-2">
                <span>Overall Progress</span>
                <span>{Math.round(progress)}%</span>
              </div>
              <div className="bg-gray-700 rounded-full h-3">
                <div
                  className={`h-3 rounded-full transition-all ${
                    build.status === 'failed'
                      ? 'bg-red-500'
                      : build.status === 'completed'
                      ? 'bg-green-500'
                      : 'bg-indigo-500'
                  }`}
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>

            <div className="grid grid-cols-3 gap-4 pt-4">
              <div className="text-center">
                <div className="text-2xl font-bold text-white">{build.total_packages}</div>
                <div className="text-sm text-gray-400">Total</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-green-400">{build.completed_packages}</div>
                <div className="text-sm text-gray-400">Completed</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-red-400">{build.failed_packages}</div>
                <div className="text-sm text-gray-400">Failed</div>
              </div>
            </div>

            {build.status_message && (
              <div className="mt-4 p-3 bg-gray-700/50 rounded border border-gray-600">
                <p className="text-sm text-gray-300">{build.status_message}</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Build Queue */}
      {queue && queue.length > 0 && (
        <div className="bg-gray-800 shadow rounded-lg border border-gray-700">
          <div className="p-6 border-b border-gray-700">
            <h2 className="text-lg font-semibold text-white">Build Queue ({queue.length})</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-700">
              <thead className="bg-gray-700/50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">
                    Package
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">
                    RHEL Version
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">
                    Progress
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">
                    Artifacts
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">
                    Logs
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700">
                {queue.map((item) => (
                  <>
                    <tr key={item.id} className="hover:bg-gray-700/30 transition-colors">
                      <td className="px-6 py-4 whitespace-nowrap">
                        <Link
                          to={`/packages/${item.package.id}`}
                          className="text-indigo-400 hover:text-indigo-300 font-medium flex items-center gap-2"
                        >
                          <PackageIcon className="h-4 w-4" />
                          {item.package.name}
                        </Link>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className="text-gray-300">RHEL {item.rhel_version}</span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <StatusBadge status={item.status} />
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        {item.status === 'running' ? (
                          <Loader className="h-4 w-4 text-indigo-400 animate-spin" />
                        ) : item.status === 'completed' ? (
                          <CheckCircle className="h-4 w-4 text-green-400" />
                        ) : item.status === 'failed' ? (
                          <XCircle className="h-4 w-4 text-red-400" />
                        ) : (
                          <Clock className="h-4 w-4 text-gray-400" />
                        )}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex gap-2">
                          {item.srpm_path && (
                            <a
                              href={item.srpm_path}
                              download
                              className="text-indigo-400 hover:text-indigo-300 flex items-center gap-1 text-sm"
                            >
                              <Download className="h-3 w-3" />
                              SRPM
                            </a>
                          )}
                          {item.rpm_path && (
                            <a
                              href={item.rpm_path}
                              download
                              className="text-indigo-400 hover:text-indigo-300 flex items-center gap-1 text-sm"
                            >
                              <Download className="h-3 w-3" />
                              RPM
                            </a>
                          )}
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        {(item.build_log || item.error_message) && (
                          <button
                            onClick={() => toggleLog(item.id)}
                            className="text-indigo-400 hover:text-indigo-300 flex items-center gap-1 text-sm"
                          >
                            {expandedLogs[item.id] ? (
                              <ChevronDown className="h-4 w-4" />
                            ) : (
                              <ChevronRight className="h-4 w-4" />
                            )}
                            <FileText className="h-3 w-3" />
                            View
                          </button>
                        )}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        {(item.status === 'failed' || item.status === 'cancelled') && (
                          <button
                            onClick={() => retryQueueItemMutation.mutate(item.id)}
                            disabled={retryQueueItemMutation.isPending}
                            className="text-indigo-400 hover:text-indigo-300 disabled:text-gray-500 disabled:cursor-not-allowed flex items-center gap-1 text-sm"
                          >
                            <RefreshCw className={`h-4 w-4 ${retryQueueItemMutation.isPending ? 'animate-spin' : ''}`} />
                            Rebuild
                          </button>
                        )}
                      </td>
                    </tr>
                    {expandedLogs[item.id] && (item.build_log || item.error_message) && (
                      <tr key={`${item.id}-log`}>
                        <td colSpan="7" className="px-6 py-4 bg-gray-900">
                          <div className="space-y-4">
                            {item.error_message && (
                              <div>
                                <h4 className="text-sm font-semibold text-red-400 mb-2">Error Message:</h4>
                                <pre className="text-xs text-red-300 bg-red-900/20 p-3 rounded border border-red-800 overflow-x-auto">
                                  {item.error_message}
                                </pre>
                              </div>
                            )}
                            {item.build_log && (
                              <div>
                                <h4 className="text-sm font-semibold text-gray-300 mb-2">Build Log:</h4>
                                <pre className="text-xs text-gray-300 bg-gray-800 p-3 rounded border border-gray-700 overflow-x-auto max-h-96">
                                  {item.build_log}
                                </pre>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
