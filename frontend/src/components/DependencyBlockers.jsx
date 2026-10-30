import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Unlink, X } from 'lucide-react';
import { packagesAPI } from '../lib/api';
import { useToast } from '../contexts/ToastContext';

function IgnoreVersionButton({ packageId, packageName, dependency }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  const handleClick = async (event) => {
    event.stopPropagation();
    if (!window.confirm(
      `Patch ${packageName} to ignore its upstream version requirements on ${dependency} and rebuild it?`,
    )) return;
    setBusy(true);
    try {
      const { data } = await packagesAPI.ignoreVersionRequirement(packageId, dependency);
      toast.success(data.detail + (data.rebuilding ? ' — rebuild queued' : ''));
      ['project-packages', 'package', 'packages', 'package-specs', 'package-dependencies'].forEach((key) => {
        queryClient.invalidateQueries({ queryKey: [key] });
      });
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to ignore version requirement');
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={busy}
      title={`Strip version specifiers for ${dependency} from ${packageName}'s upstream build metadata`}
      className="ml-2 inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded bg-amber-700 hover:bg-amber-600 text-white disabled:opacity-50"
    >
      <Unlink className="w-3 h-3" />
      {busy ? 'Patching…' : 'Ignore version requirement'}
    </button>
  );
}

export function IgnoredVersionRequirements({ packageId, packageName, dependencies = [] }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState(null);

  if (!dependencies.length) return null;

  const restore = async (dependency) => {
    if (!window.confirm(`Stop ignoring ${packageName}'s version requirements on ${dependency} and rebuild it?`)) return;
    setBusy(dependency);
    try {
      const { data } = await packagesAPI.restoreVersionRequirement(packageId, dependency);
      toast.success(data.detail + (data.rebuilding ? ' — rebuild queued' : ''));
      ['project-packages', 'package', 'packages', 'package-specs', 'package-dependencies'].forEach((key) => {
        queryClient.invalidateQueries({ queryKey: [key] });
      });
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to restore version requirement');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mt-3 text-sm" aria-label="Ignored version requirements">
      <h3 className="font-medium text-amber-300">Ignored version requirements</h3>
      <ul className="mt-1 flex flex-wrap gap-2">
        {dependencies.map((dependency) => (
          <li key={dependency} className="inline-flex items-center gap-1 pl-2 pr-1 py-0.5 rounded bg-amber-900/40 border border-amber-700 text-amber-200">
            <code>{dependency}</code>
            <button
              type="button"
              onClick={() => restore(dependency)}
              disabled={busy === dependency}
              title={`Restore upstream version requirements on ${dependency}`}
              aria-label={`Restore version requirements on ${dependency}`}
              className="p-0.5 rounded hover:bg-amber-700 disabled:opacity-50"
            >
              <X className="w-3 h-3" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function DependencyBlockers({ blockers = [] }) {
  if (!blockers.length) return null;

  return (
    <div className="mt-3 space-y-3 whitespace-normal min-w-48 max-w-xl" aria-label="Current missing dependencies">
      <h3 className="text-sm font-medium text-amber-300">Current missing dependencies</h3>
      {blockers.map((blocker, index) => (
        <div key={`${blocker.package_id}-${index}`} className="text-sm break-words">
          <p className="text-gray-300">
            <Link to={`/packages/${blocker.package_id}`} onClick={(event) => event.stopPropagation()} className="text-indigo-400 hover:underline">
              {blocker.package_name}
            </Link>
            {' requires '}
            <code>{blocker.requirement}</code>
          </p>
          {blocker.candidates.length === 0 ? (
            <p className="text-amber-300">No matching package in this project.</p>
          ) : blocker.candidates.map((candidate) => (
            <p key={candidate.id} className="text-amber-300">
              {candidate.reason}: {' '}
              <Link to={`/packages/${candidate.id}`} onClick={(event) => event.stopPropagation()} className="text-indigo-400 hover:underline">
                {candidate.name} {candidate.version}
              </Link>
              {' '}(current status: {candidate.build_status.replaceAll('_', ' ')})
              {candidate.reason === 'Version conflict' && (
                <IgnoreVersionButton
                  packageId={blocker.package_id}
                  packageName={blocker.package_name}
                  dependency={candidate.name}
                />
              )}
            </p>
          ))}
        </div>
      ))}
    </div>
  );
}
