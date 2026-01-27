import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Boxes, Search, Filter, Play, XCircle, CheckCircle, Clock, Loader, Trash2 } from 'lucide-react';
import { buildsAPI } from '../lib/api';
import SystemHealthBanner from '../components/SystemHealthBanner';
import ConfirmDialog from '../components/ConfirmDialog';

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

export default function Builds() {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [currentPage, setCurrentPage] = useState(1);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [buildToDelete, setBuildToDelete] = useState(null);
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ['builds', currentPage, statusFilter, search],
    queryFn: async () => {
      const params = {
        page: currentPage,
        page_size: 20,
        ordering: '-created_at',
      };
      
      if (statusFilter !== 'all') {
        params.status = statusFilter;
      }
      
      if (search) {
        params.search = search;
      }

      const response = await buildsAPI.list(params);
      return response.data;
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (buildId) => buildsAPI.delete(buildId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['builds'] });
    },
    onError: (error) => {
      alert(`Failed to delete build: ${error.response?.data?.detail || error.message}`);
    },
  });

  const handleDeleteClick = (build, e) => {
    e.preventDefault();
    e.stopPropagation();
    setBuildToDelete(build);
    setDeleteDialogOpen(true);
  };

  const handleDeleteConfirm = async () => {
    if (buildToDelete) {
      await deleteMutation.mutateAsync(buildToDelete.id);
      setBuildToDelete(null);
    }
  };

  if (error) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <XCircle className="h-12 w-12 text-red-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-white mb-2">Error loading builds</h3>
          <p className="text-gray-400">{error.message}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <Boxes className="h-7 w-7" />
            Build Jobs
          </h1>
          <p className="text-gray-400 mt-1">Manage and monitor RPM build jobs</p>
        </div>
      </div>

      {/* System Health Warning */}
      <SystemHealthBanner />

      {/* Filters */}
      <div className="bg-gray-800 shadow rounded-lg p-4 border border-gray-700">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-gray-400" />
            <input
              type="text"
              placeholder="Search builds..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-gray-900 border border-gray-600 rounded-lg text-gray-200 placeholder-gray-500 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
          </div>

          {/* Status Filter */}
          <div className="relative">
            <Filter className="absolute left-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-gray-400" />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="w-full pl-10 pr-4 py-2 bg-gray-900 border border-gray-600 rounded-lg text-gray-200 focus:ring-2 focus:ring-indigo-500 focus:border-transparent appearance-none cursor-pointer"
            >
              <option value="all">All Status</option>
              <option value="pending">Pending</option>
              <option value="preparing">Preparing</option>
              <option value="queued">Queued</option>
              <option value="running">Running</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </div>
        </div>
      </div>

      {/* Builds List */}
      <div className="bg-gray-800 shadow rounded-lg border border-gray-700">
        {isLoading ? (
          <div className="flex items-center justify-center h-64">
            <Loader className="h-8 w-8 text-indigo-400 animate-spin" />
          </div>
        ) : data?.results?.length > 0 ? (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-700">
                <thead className="bg-gray-700/50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">
                      Build ID
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">
                      Project
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">
                      Version
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">
                      Progress
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">
                      Created
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700">
                  {data.results.map((build) => (
                    <tr
                      key={build.id}
                      className="hover:bg-gray-700/30 transition-colors"
                    >
                      <td className="px-6 py-4 whitespace-nowrap">
                        <Link
                          to={`/builds/${build.id}`}
                          className="text-indigo-400 hover:text-indigo-300 font-medium"
                        >
                          #{build.id}
                        </Link>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <Link
                          to={`/projects/${build.project}`}
                          className="text-gray-200 hover:text-white"
                        >
                          {build.project_name || `Project #${build.project}`}
                        </Link>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className="text-gray-300">{build.build_version}</span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <StatusBadge status={build.status} />
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          <div className="flex-1 bg-gray-700 rounded-full h-2 w-32">
                            <div
                              className={`h-2 rounded-full ${
                                build.status === 'failed'
                                  ? 'bg-red-500'
                                  : build.status === 'completed'
                                  ? 'bg-green-500'
                                  : 'bg-indigo-500'
                              }`}
                              style={{
                                width: `${
                                  build.total_packages > 0
                                    ? (build.completed_packages / build.total_packages) * 100
                                    : 0
                                }%`,
                              }}
                            />
                          </div>
                          <span className="text-xs text-gray-400">
                            {build.completed_packages}/{build.total_packages}
                          </span>
                        </div>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-400">
                        {new Date(build.created_at).toLocaleString()}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                        <button
                          onClick={(e) => handleDeleteClick(build, e)}
                          disabled={deleteMutation.isPending}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-red-400 hover:text-red-300 hover:bg-red-900/20 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                          title="Delete build"
                        >
                          <Trash2 className="h-4 w-4" />
                          {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {data.count > 20 && (
              <div className="px-6 py-4 border-t border-gray-700 flex items-center justify-between">
                <div className="text-sm text-gray-400">
                  Showing {(currentPage - 1) * 20 + 1} to{' '}
                  {Math.min(currentPage * 20, data.count)} of {data.count} builds
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                    disabled={!data.previous}
                    className="px-4 py-2 bg-gray-700 hover:bg-gray-600 disabled:bg-gray-800 disabled:text-gray-600 text-gray-200 rounded-lg transition-colors"
                  >
                    Previous
                  </button>
                  <button
                    onClick={() => setCurrentPage((p) => p + 1)}
                    disabled={!data.next}
                    className="px-4 py-2 bg-gray-700 hover:bg-gray-600 disabled:bg-gray-800 disabled:text-gray-600 text-gray-200 rounded-lg transition-colors"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="text-center py-12">
            <Boxes className="h-12 w-12 text-gray-600 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-400 mb-2">No builds found</h3>
            <p className="text-gray-500">Start by creating a build job for your project</p>
          </div>
        )}
      </div>

      {/* Delete Confirmation Dialog */}
      <ConfirmDialog
        isOpen={deleteDialogOpen}
        onClose={() => {
          setDeleteDialogOpen(false);
          setBuildToDelete(null);
        }}
        onConfirm={handleDeleteConfirm}
        title="Delete Build Job"
        message={
          buildToDelete
            ? `Are you sure you want to delete build #${buildToDelete.id} for ${buildToDelete.project_name || 'this project'}? This action cannot be undone.`
            : ''
        }
        confirmText="Delete"
        cancelText="Cancel"
        variant="danger"
      />
    </div>
  );
}
