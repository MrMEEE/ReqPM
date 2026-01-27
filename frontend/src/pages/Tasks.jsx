import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { List, Search, Filter, CheckCircle, XCircle, Clock, Loader, AlertCircle, ChevronDown, ChevronUp } from 'lucide-react';
import { tasksAPI } from '../lib/api';

const StatusBadge = ({ status }) => {
  const statusConfig = {
    PENDING: { color: 'bg-yellow-100 text-yellow-800', icon: Clock, label: 'Pending' },
    STARTED: { color: 'bg-blue-100 text-blue-800', icon: Loader, label: 'Started' },
    SUCCESS: { color: 'bg-green-100 text-green-800', icon: CheckCircle, label: 'Success' },
    FAILURE: { color: 'bg-red-100 text-red-800', icon: XCircle, label: 'Failed' },
    RETRY: { color: 'bg-orange-100 text-orange-800', icon: AlertCircle, label: 'Retry' },
    REVOKED: { color: 'bg-gray-100 text-gray-800', icon: XCircle, label: 'Revoked' },
  };

  const config = statusConfig[status] || statusConfig.PENDING;
  const Icon = config.icon;

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${config.color}`}>
      <Icon className="h-3 w-3" />
      {config.label}
    </span>
  );
};

export default function Tasks() {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [currentPage, setCurrentPage] = useState(1);
  const [expandedTask, setExpandedTask] = useState(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ['tasks', currentPage, statusFilter, search],
    queryFn: async () => {
      const params = {
        page: currentPage,
        page_size: 20,
        ordering: '-date_created',
      };
      
      if (statusFilter !== 'all') {
        params.status = statusFilter;
      }
      
      if (search) {
        params.search = search;
      }

      const response = await tasksAPI.list(params);
      return response.data;
    },
    refetchInterval: 5000, // Auto-refresh every 5 seconds
  });

  const toggleExpand = (taskId) => {
    setExpandedTask(expandedTask === taskId ? null : taskId);
  };

  const formatTaskName = (name) => {
    if (!name) return 'Unknown Task';
    // Remove module prefix for cleaner display
    return name.split('.').pop().replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  };

  if (error) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <XCircle className="h-12 w-12 text-red-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-white mb-2">Error loading tasks</h3>
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
            <List className="h-7 w-7" />
            Celery Tasks
          </h1>
          <p className="text-gray-400 mt-1">Monitor background task execution and results</p>
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
              placeholder="Search tasks..."
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
              <option value="PENDING">Pending</option>
              <option value="STARTED">Started</option>
              <option value="SUCCESS">Success</option>
              <option value="FAILURE">Failed</option>
              <option value="RETRY">Retry</option>
              <option value="REVOKED">Revoked</option>
            </select>
          </div>
        </div>
      </div>

      {/* Tasks List */}
      <div className="bg-gray-800 shadow rounded-lg border border-gray-700">
        {isLoading ? (
          <div className="flex items-center justify-center h-64">
            <Loader className="h-8 w-8 text-indigo-400 animate-spin" />
          </div>
        ) : data?.results?.length > 0 ? (
          <div className="divide-y divide-gray-700">
            {data.results.map((task) => (
              <div key={task.id} className="p-4 hover:bg-gray-700/30 transition-colors">
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <h3 className="text-base font-semibold text-white">
                        {formatTaskName(task.task_name)}
                      </h3>
                      <StatusBadge status={task.status} />
                      {task.duration && (
                        <span className="text-xs text-gray-400">
                          {task.duration}s
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-gray-400 space-y-1">
                      <p>
                        <span className="font-medium">Task ID:</span>{' '}
                        <span className="font-mono">{task.task_id}</span>
                      </p>
                      <p>
                        <span className="font-medium">Started:</span>{' '}
                        {new Date(task.date_created).toLocaleString()}
                      </p>
                      {task.date_done && (
                        <p>
                          <span className="font-medium">Completed:</span>{' '}
                          {new Date(task.date_done).toLocaleString()}
                        </p>
                      )}
                    </div>
                  </div>
                  <button
                    onClick={() => toggleExpand(task.id)}
                    className="p-2 hover:bg-gray-600 rounded transition-colors"
                  >
                    {expandedTask === task.id ? (
                      <ChevronUp className="h-5 w-5 text-gray-400" />
                    ) : (
                      <ChevronDown className="h-5 w-5 text-gray-400" />
                    )}
                  </button>
                </div>

                {expandedTask === task.id && (
                  <div className="mt-4 space-y-3">
                    {task.task_args && task.task_args !== '[]' && (
                      <div>
                        <label className="block text-xs font-medium text-gray-400 mb-1">
                          Arguments
                        </label>
                        <pre className="text-xs text-gray-300 p-2 bg-gray-900 rounded overflow-x-auto">
                          {task.task_args}
                        </pre>
                      </div>
                    )}
                    {task.task_kwargs && task.task_kwargs !== '{}' && (
                      <div>
                        <label className="block text-xs font-medium text-gray-400 mb-1">
                          Keyword Arguments
                        </label>
                        <pre className="text-xs text-gray-300 p-2 bg-gray-900 rounded overflow-x-auto">
                          {task.task_kwargs}
                        </pre>
                      </div>
                    )}
                    {task.result && (
                      <div>
                        <label className="block text-xs font-medium text-gray-400 mb-1">
                          Result
                        </label>
                        <pre className="text-xs text-gray-300 p-2 bg-gray-900 rounded overflow-x-auto max-h-64 overflow-y-auto">
                          {typeof task.result === 'string' ? task.result : JSON.stringify(JSON.parse(task.result), null, 2)}
                        </pre>
                      </div>
                    )}
                    {task.traceback && (
                      <div>
                        <label className="block text-xs font-medium text-red-400 mb-1">
                          Error Traceback
                        </label>
                        <pre className="text-xs text-red-300 p-2 bg-gray-900 rounded overflow-x-auto max-h-64 overflow-y-auto">
                          {task.traceback}
                        </pre>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-12">
            <List className="h-12 w-12 text-gray-600 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-400 mb-2">No tasks found</h3>
            <p className="text-gray-500">Tasks will appear here as they are executed</p>
          </div>
        )}

        {/* Pagination */}
        {data?.count > 20 && (
          <div className="px-6 py-4 border-t border-gray-700 flex items-center justify-between">
            <div className="text-sm text-gray-400">
              Showing {(currentPage - 1) * 20 + 1} to{' '}
              {Math.min(currentPage * 20, data.count)} of {data.count} tasks
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
    </div>
  );
}
