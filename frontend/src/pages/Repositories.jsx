import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Database, Search, Filter, CheckCircle, XCircle, Loader, Archive } from 'lucide-react';
import { repositoriesAPI } from '../lib/api';

const StatusBadge = ({ status }) => {
  const statusConfig = {
    creating: { color: 'bg-blue-100 text-blue-800', icon: Loader, label: 'Creating' },
    active: { color: 'bg-green-100 text-green-800', icon: CheckCircle, label: 'Active' },
    updating: { color: 'bg-yellow-100 text-yellow-800', icon: Loader, label: 'Updating' },
    error: { color: 'bg-red-100 text-red-800', icon: XCircle, label: 'Error' },
    archived: { color: 'bg-gray-100 text-gray-800', icon: Archive, label: 'Archived' },
  };

  const config = statusConfig[status] || statusConfig.creating;
  const Icon = config.icon;

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${config.color}`}>
      <Icon className="h-3 w-3" />
      {config.label}
    </span>
  );
};

export default function Repositories() {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [currentPage, setCurrentPage] = useState(1);

  const { data, isLoading, error } = useQuery({
    queryKey: ['repositories', currentPage, statusFilter, search],
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

      const response = await repositoriesAPI.list(params);
      return response.data;
    },
  });

  if (error) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <XCircle className="h-12 w-12 text-red-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-white mb-2">Error loading repositories</h3>
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
            <Database className="h-7 w-7" />
            RPM Repositories
          </h1>
          <p className="text-gray-400 mt-1">Manage YUM/DNF repositories for built packages</p>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-gray-800 shadow rounded-lg p-4 border border-gray-700">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-gray-400" />
            <input
              type="text"
              placeholder="Search repositories..."
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
              <option value="creating">Creating</option>
              <option value="active">Active</option>
              <option value="updating">Updating</option>
              <option value="error">Error</option>
              <option value="archived">Archived</option>
            </select>
          </div>
        </div>
      </div>

      {/* Repositories Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {isLoading ? (
          <div className="col-span-2 flex items-center justify-center h-64">
            <Loader className="h-8 w-8 text-indigo-400 animate-spin" />
          </div>
        ) : data?.results?.length > 0 ? (
          data.results.map((repo) => (
            <div
              key={repo.id}
              className="bg-gray-800 shadow rounded-lg p-6 border border-gray-700 hover:border-gray-600 transition-colors"
            >
              <div className="flex items-start justify-between mb-4">
                <div className="flex-1">
                  <h3 className="text-lg font-semibold text-white mb-1">{repo.name}</h3>
                  {repo.description && (
                    <p className="text-sm text-gray-400 mb-2">{repo.description}</p>
                  )}
                  <div className="flex items-center gap-2 mb-3">
                    <StatusBadge status={repo.status} />
                    <span className="px-2 py-1 bg-gray-700 text-gray-300 text-xs rounded">
                      RHEL {repo.rhel_version}
                    </span>
                    <span className="px-2 py-1 bg-gray-700 text-gray-300 text-xs rounded">
                      {repo.architecture}
                    </span>
                  </div>
                </div>
              </div>

              <div className="space-y-2 mb-4">
                {repo.baseurl && (
                  <div>
                    <label className="text-xs font-medium text-gray-400">Base URL</label>
                    <p className="text-sm text-gray-300 font-mono break-all">{repo.baseurl}</p>
                  </div>
                )}
                {repo.repo_url && (
                  <div>
                    <label className="text-xs font-medium text-gray-400">Repository URL</label>
                    <a
                      href={repo.repo_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-indigo-400 hover:text-indigo-300 font-mono break-all"
                    >
                      {repo.repo_url}
                    </a>
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2 pt-4 border-t border-gray-700">
                <Link
                  to={`/projects/${repo.project}`}
                  className="text-sm text-indigo-400 hover:text-indigo-300"
                >
                  View Project
                </Link>
                {repo.repo_url && (
                  <a
                    href={repo.repo_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-gray-400 hover:text-gray-300"
                  >
                    Browse Repository
                  </a>
                )}
              </div>

              {repo.status_message && (
                <div className="mt-4 p-3 bg-gray-700/50 rounded border border-gray-600">
                  <p className="text-xs text-gray-400">{repo.status_message}</p>
                </div>
              )}
            </div>
          ))
        ) : (
          <div className="col-span-2 text-center py-12">
            <Database className="h-12 w-12 text-gray-600 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-400 mb-2">No repositories found</h3>
            <p className="text-gray-500">Repositories will be created after building packages</p>
          </div>
        )}
      </div>

      {/* Pagination */}
      {data?.count > 20 && (
        <div className="bg-gray-800 shadow rounded-lg p-4 border border-gray-700 flex items-center justify-between">
          <div className="text-sm text-gray-400">
            Showing {(currentPage - 1) * 20 + 1} to{' '}
            {Math.min(currentPage * 20, data.count)} of {data.count} repositories
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
    </div>
  );
}
