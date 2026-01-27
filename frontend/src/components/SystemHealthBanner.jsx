import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle, XCircle } from 'lucide-react';
import api from '../lib/api';

export default function SystemHealthBanner() {
  const { data: health } = useQuery({
    queryKey: ['system-health'],
    queryFn: async () => {
      const response = await api.get('/system-health/');
      return response.data;
    },
    refetchInterval: 60000, // Check every minute
  });

  if (!health) return null;

  const mockStatus = health.builders?.mock;
  
  if (!mockStatus || mockStatus.available) return null;

  return (
    <div className="bg-yellow-900/20 border-l-4 border-yellow-500 p-4 mb-6">
      <div className="flex items-start">
        <AlertTriangle className="h-5 w-5 text-yellow-500 mt-0.5 flex-shrink-0" />
        <div className="ml-3 flex-1">
          <h3 className="text-sm font-medium text-yellow-200">
            Mock Builder Not Available
          </h3>
          <div className="mt-2 text-sm text-yellow-100">
            <p>{mockStatus.message}</p>
            <p className="mt-2">
              Builds will fail until Mock is properly installed and configured.
              See{' '}
              <a
                href="https://github.com/yourusername/reqpm/blob/main/docs/MOCK_SETUP.md"
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium underline hover:text-yellow-50"
              >
                Mock Setup Guide
              </a>{' '}
              for instructions.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export function MockStatus() {
  const { data: health, isLoading } = useQuery({
    queryKey: ['system-health'],
    queryFn: async () => {
      const response = await api.get('/system-health/');
      return response.data;
    },
    refetchInterval: 60000,
  });

  if (isLoading) {
    return (
      <div className="text-sm text-gray-400">
        Checking builder status...
      </div>
    );
  }

  if (!health) return null;

  const mockStatus = health.builders?.mock;

  return (
    <div className="flex items-center gap-2">
      {mockStatus?.available ? (
        <>
          <CheckCircle className="h-4 w-4 text-green-500" />
          <span className="text-sm text-green-400">
            Mock {mockStatus.version} ready
          </span>
          {mockStatus.targets && mockStatus.targets.length > 0 && (
            <span className="text-xs text-gray-500">
              ({mockStatus.targets.length} targets)
            </span>
          )}
        </>
      ) : (
        <>
          <XCircle className="h-4 w-4 text-red-500" />
          <span className="text-sm text-red-400">Mock not available</span>
        </>
      )}
    </div>
  );
}
