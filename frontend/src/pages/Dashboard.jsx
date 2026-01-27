import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { projectsAPI, buildsAPI } from '../lib/api';
import { Package, GitBranch, Clock, CheckCircle, XCircle, AlertCircle } from 'lucide-react';

export default function Dashboard() {
  const { data: projects, isLoading: projectsLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => projectsAPI.list().then(res => res.data),
  });

  const { data: builds, isLoading: buildsLoading } = useQuery({
    queryKey: ['builds'],
    queryFn: () => buildsAPI.list({ ordering: '-created_at', page_size: 10 }).then(res => res.data),
  });

  const stats = [
    {
      name: 'Total Projects',
      value: projects?.count || 0,
      icon: Package,
      color: 'bg-blue-500',
    },
    {
      name: 'Active Builds',
      value: builds?.results?.filter(b => ['pending', 'running'].includes(b.status)).length || 0,
      icon: GitBranch,
      color: 'bg-yellow-500',
    },
    {
      name: 'Completed Builds',
      value: builds?.results?.filter(b => b.status === 'success').length || 0,
      icon: CheckCircle,
      color: 'bg-green-500',
    },
    {
      name: 'Failed Builds',
      value: builds?.results?.filter(b => b.status === 'failed').length || 0,
      icon: XCircle,
      color: 'bg-red-500',
    },
  ];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-white">Dashboard</h1>
        <p className="mt-2 text-gray-400">Overview of your projects and builds</p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {stats.map((stat) => {
          const Icon = stat.icon;
          return (
            <div
              key={stat.name}
              className="bg-gray-800 rounded-lg shadow-lg p-6 border border-gray-700"
            >
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-400">{stat.name}</p>
                  <p className="mt-2 text-3xl font-semibold text-white">{stat.value}</p>
                </div>
                <div className={`${stat.color} p-3 rounded-lg`}>
                  <Icon className="text-white" size={24} />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Recent Projects */}
      <div className="bg-gray-800 rounded-lg shadow-lg border border-gray-700">
        <div className="p-6 border-b border-gray-700">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-semibold text-white">Recent Projects</h2>
            <Link
              to="/projects"
              className="text-sm text-blue-400 hover:text-blue-300"
            >
              View all →
            </Link>
          </div>
        </div>
        <div className="p-6">
          {projectsLoading ? (
            <div className="flex justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
            </div>
          ) : projects?.results?.length > 0 ? (
            <div className="space-y-4">
              {projects.results.slice(0, 5).map((project) => (
                <Link
                  key={project.id}
                  to={`/projects/${project.id}`}
                  className="block p-4 bg-gray-700 rounded-lg hover:bg-gray-600 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="font-medium text-white">{project.name}</h3>
                      <p className="text-sm text-gray-400 mt-1">{project.description || 'No description'}</p>
                    </div>
                    <div className="flex items-center space-x-2 text-sm text-gray-400">
                      <GitBranch size={16} />
                      <span>{project.branch}</span>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-400">
              <Package size={48} className="mx-auto mb-4 opacity-50" />
              <p>No projects yet. Create your first project to get started.</p>
              <Link
                to="/projects?action=create"
                className="mt-4 inline-block px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
              >
                Create Project
              </Link>
            </div>
          )}
        </div>
      </div>

      {/* Recent Builds */}
      <div className="bg-gray-800 rounded-lg shadow-lg border border-gray-700">
        <div className="p-6 border-b border-gray-700">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-semibold text-white">Recent Builds</h2>
            <Link
              to="/builds"
              className="text-sm text-blue-400 hover:text-blue-300"
            >
              View all →
            </Link>
          </div>
        </div>
        <div className="p-6">
          {buildsLoading ? (
            <div className="flex justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
            </div>
          ) : builds?.results?.length > 0 ? (
            <div className="space-y-4">
              {builds.results.map((build) => (
                <Link
                  key={build.id}
                  to={`/builds/${build.id}`}
                  className="block p-4 bg-gray-700 rounded-lg hover:bg-gray-600 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex-1">
                      <div className="flex items-center space-x-3">
                        <h3 className="font-medium text-white">Build #{build.id}</h3>
                        <BuildStatusBadge status={build.status} />
                      </div>
                      <p className="text-sm text-gray-400 mt-1">
                        {build.project_name || `Project ID: ${build.project}`}
                      </p>
                    </div>
                    <div className="text-right text-sm text-gray-400">
                      <div className="flex items-center space-x-2">
                        <Clock size={14} />
                        <span>{new Date(build.created_at).toLocaleDateString()}</span>
                      </div>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-400">
              <AlertCircle size={48} className="mx-auto mb-4 opacity-50" />
              <p>No builds yet.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function BuildStatusBadge({ status }) {
  const statusConfig = {
    pending: { color: 'bg-yellow-500', text: 'Pending' },
    running: { color: 'bg-blue-500', text: 'Running' },
    success: { color: 'bg-green-500', text: 'Success' },
    failed: { color: 'bg-red-500', text: 'Failed' },
    cancelled: { color: 'bg-gray-500', text: 'Cancelled' },
  };

  const config = statusConfig[status] || statusConfig.pending;

  return (
    <span className={`px-2 py-1 text-xs font-medium text-white rounded ${config.color}`}>
      {config.text}
    </span>
  );
}
