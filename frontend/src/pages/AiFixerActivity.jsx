import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Bot, AlertCircle, CheckCircle, Clock, Loader, Activity, Brain, ThumbsUp, ThumbsDown, Wrench } from 'lucide-react';
import { settingsAPI } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';

function formatDuration(seconds) {
  const s = Number(seconds || 0);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return `${m}m ${rem}s`;
  const h = Math.floor(m / 60);
  const remM = m % 60;
  return `${h}h ${remM}m`;
}

function StateBadge({ state }) {
  const waiting = state === 'waiting_for_slot';
  const fixing = state === 'fixing';
  const cls = waiting
    ? 'bg-amber-100 text-amber-800'
    : fixing
    ? 'bg-violet-100 text-violet-800'
    : 'bg-blue-100 text-blue-800';
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${cls}`}>
      {waiting ? <Clock className="h-3 w-3" /> : fixing ? <Wrench className="h-3 w-3" /> : <Loader className="h-3 w-3 animate-spin" />}
      {waiting ? 'Waiting For Slot' : fixing ? 'Fixing' : 'Running'}
    </span>
  );
}

function CorrectionDescriptionCell({ description, note }) {
  const text = (description || note || '').trim();
  if (!text) {
    return <span className="text-gray-500">No correction description yet</span>;
  }

  const actions = (description || '')
    .split(';')
    .map((s) => s.trim())
    .filter(Boolean);

  if (!actions.length) {
    return <span className="text-gray-300">{text}</span>;
  }

  return (
    <details className="group">
      <summary className="cursor-pointer text-gray-300 hover:text-white list-none">
        <span className="inline-flex items-center gap-2">
          <span className="truncate max-w-lg">{actions[0]}</span>
          {actions.length > 1 ? (
            <span className="text-xs text-purple-300">+{actions.length - 1} more</span>
          ) : null}
        </span>
      </summary>
      <ul className="mt-2 space-y-1">
        {actions.map((action, idx) => (
          <li key={`${action}-${idx}`} className="text-xs text-gray-300 flex items-start gap-2">
            <span className="text-purple-400 mt-0.5">•</span>
            <span>{action}</span>
          </li>
        ))}
      </ul>
      {note ? <div className="mt-2 text-xs text-cyan-300">Note: {note}</div> : null}
    </details>
  );
}

export default function AiFixerActivity() {
  const { user } = useAuth();
  const isAdmin = user?.is_staff || user?.is_superuser;
  const [message, setMessage] = useState(null);
  const [actionError, setActionError] = useState(null);

  const {
    data,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['ai-fixer-packages'],
    queryFn: () => settingsAPI.aiFixerPackages().then((res) => res.data),
    refetchInterval: 5000,
  });

  const {
    data: aiLearningStats,
    isLoading: isLearningLoading,
    refetch: refetchLearningStats,
  } = useQuery({
    queryKey: ['ai-learning-stats'],
    queryFn: () => settingsAPI.aiLearningStats().then((res) => res.data),
    refetchInterval: 20000,
  });

  const handleUnlearnRevision = async (revisionId) => {
    if (!isAdmin) {
      setActionError('Only administrators can unlearn AI revisions');
      return;
    }
    setActionError(null);
    try {
      await settingsAPI.aiUnlearnRevision(revisionId);
      setMessage('Revision removed from AI learning set');
      await refetchLearningStats();
      window.setTimeout(() => setMessage(null), 3000);
    } catch (err) {
      setActionError(err.response?.data?.detail || 'Failed to unlearn revision');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <Bot className="h-7 w-7 text-blue-400" />
            AI Fixer Activity
          </h1>
          <p className="text-gray-400 mt-1">Live view of packages currently being processed by the AI fixer</p>
        </div>
        <div className="bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-sm text-gray-300">
          Slots in use: <span className="font-semibold text-white">{data?.active_count ?? 0}</span>
          <span className="text-gray-500"> / </span>
          <span className="font-semibold text-white">{data?.max_concurrent ?? 0}</span>
        </div>
      </div>

      {!isLoading && data && data.enabled === false && (
        <div className="bg-yellow-900/30 border border-yellow-700 rounded-lg p-4 flex items-center gap-3">
          <AlertCircle className="h-5 w-5 text-yellow-400" />
          <div className="text-yellow-200">
            AI fixer is disabled in settings.
            <Link to="/settings" className="ml-2 text-blue-300 hover:text-blue-200">Open settings</Link>
          </div>
        </div>
      )}

      {message && (
        <div className="bg-green-900/50 border border-green-500 rounded-lg p-4 flex items-center gap-2">
          <CheckCircle className="h-5 w-5 text-green-400" />
          <span className="text-green-200">{message}</span>
        </div>
      )}

      {actionError && (
        <div className="bg-red-900/50 border border-red-500 rounded-lg p-4 flex items-center gap-2">
          <AlertCircle className="h-5 w-5 text-red-400" />
          <span className="text-red-200">{actionError}</span>
        </div>
      )}

      <div className="bg-gray-800 shadow rounded-lg border border-gray-700">
        {isLoading ? (
          <div className="flex items-center justify-center h-56">
            <Loader className="h-8 w-8 text-indigo-400 animate-spin" />
          </div>
        ) : isError ? (
          <div className="text-center py-12">
            <AlertCircle className="h-12 w-12 text-red-400 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-white mb-2">Error loading AI fixer activity</h3>
            <p className="text-gray-400">{error?.message || 'Unknown error'}</p>
          </div>
        ) : data?.packages?.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-700">
              <thead className="bg-gray-700/40">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Package</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Project</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">State</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Attempts</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">In Process</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Correction Description</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-300 uppercase tracking-wider">Last AI Log</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700">
                {data.packages.map((pkg) => (
                  <tr key={pkg.id} className="hover:bg-gray-700/30 transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <Link to={`/packages/${pkg.id}`} className="text-indigo-400 hover:text-indigo-300 font-medium">
                        {pkg.name} {pkg.version || ''}
                      </Link>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-gray-300">
                      {pkg.project_name || `Project #${pkg.project_id}`}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <StateBadge state={pkg.state} />
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-gray-300">
                      {pkg.ai_attempt_count ?? 0}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-gray-300">
                      {formatDuration(pkg.ai_elapsed_seconds)}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-300 align-top max-w-xl">
                      <CorrectionDescriptionCell
                        description={pkg.latest_correction_description}
                        note={pkg.latest_correction_note}
                      />
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-400 max-w-xl truncate" title={pkg.last_ai_log || ''}>
                      {pkg.last_ai_log || 'No AI log yet'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-center py-12 text-gray-400">
            <CheckCircle className="h-12 w-12 mx-auto mb-4 text-green-400 opacity-80" />
            <h3 className="text-lg font-medium text-gray-300 mb-2">No active AI fixer packages</h3>
            <p>Packages will appear here when rule-based fixers hand off to AI fixer.</p>
          </div>
        )}
      </div>

      <div className="bg-gray-800 rounded-lg border border-gray-700 p-4">
        <div className="text-sm text-gray-300 flex items-center gap-2">
          <Activity className="h-4 w-4 text-blue-400" />
          Refreshes every 5 seconds.
        </div>
      </div>

      {!isLearningLoading && aiLearningStats && (
        <div className="bg-gray-800 rounded-lg shadow-lg p-6 border border-gray-700">
          <div className="flex items-center space-x-2 mb-6">
            <Brain className="text-cyan-400" size={24} />
            <h2 className="text-xl font-semibold text-white">AI Learning Insights</h2>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <div className="bg-gray-900/50 rounded-lg p-4">
              <div className="text-gray-400 text-sm mb-1">AI Fixes</div>
              <div className="text-3xl font-bold text-white">{aiLearningStats.totals?.ai_fixes ?? 0}</div>
            </div>
            <div className="bg-gray-900/50 rounded-lg p-4">
              <div className="text-gray-400 text-sm mb-1">Taught Revisions</div>
              <div className="text-3xl font-bold text-cyan-400">{aiLearningStats.totals?.taught_revisions ?? 0}</div>
            </div>
            <div className="bg-gray-900/50 rounded-lg p-4">
              <div className="text-gray-400 text-sm mb-1">Recent AI Fixes Analyzed</div>
              <div className="text-3xl font-bold text-purple-400">{aiLearningStats.totals?.recent_ai_fixes_considered ?? 0}</div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <div className="bg-green-900/20 border border-green-700/50 rounded-lg p-4">
              <div className="text-green-300 text-sm mb-2 flex items-center gap-2"><ThumbsUp size={14} /> Correct</div>
              <div className="text-2xl font-bold text-green-300">{aiLearningStats.feedback?.correct ?? 0}</div>
            </div>
            <div className="bg-red-900/20 border border-red-700/50 rounded-lg p-4">
              <div className="text-red-300 text-sm mb-2 flex items-center gap-2"><ThumbsDown size={14} /> Wrong</div>
              <div className="text-2xl font-bold text-red-300">{aiLearningStats.feedback?.wrong ?? 0}</div>
            </div>
            <div className="bg-gray-900/40 border border-gray-700 rounded-lg p-4">
              <div className="text-gray-300 text-sm mb-2">Unlabeled</div>
              <div className="text-2xl font-bold text-gray-300">{aiLearningStats.feedback?.unknown ?? 0}</div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="bg-gray-900/40 border border-gray-700 rounded-lg p-4">
              <div className="text-sm text-gray-300 mb-3">Most-Used Learned Examples (Recent AI Fixes)</div>
              {aiLearningStats.top_learned_examples_recent?.length ? (
                <div className="space-y-2">
                  {aiLearningStats.top_learned_examples_recent.map((ex, idx) => (
                    <div key={`${ex.package}-${idx}`} className="flex items-center justify-between text-sm">
                      <div className="text-gray-200">
                        {ex.package}
                        {ex.taught ? <span className="ml-2 text-xs text-cyan-300">taught</span> : null}
                        {ex.feedback === 'correct' ? <span className="ml-2 text-xs text-green-300">correct</span> : null}
                      </div>
                      <div className="text-purple-300 font-medium">{ex.used_count}x</div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-gray-500">No learned examples have been reused yet.</p>
              )}
            </div>

            <div className="bg-gray-900/40 border border-gray-700 rounded-lg p-4">
              <div className="text-sm text-gray-300 mb-3">Recently Taught Revisions</div>
              {aiLearningStats.recent_taught_revisions?.length ? (
                <div className="space-y-2">
                  {aiLearningStats.recent_taught_revisions.map((item, idx) => (
                    <div key={`${item.revision_id}-${idx}`} className="text-sm bg-gray-800/40 rounded p-2 border border-gray-700">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-gray-200">{item.package_name}</div>
                          <div className="text-xs text-gray-500">
                            {item.taught_at ? new Date(item.taught_at).toLocaleString() : 'Unknown time'}
                          </div>
                          <div className="text-xs text-gray-300 mt-1">
                            {item.correction_description || 'No correction description saved for this revision.'}
                          </div>
                          {item.note ? <div className="text-xs text-cyan-300 mt-1">{item.note}</div> : null}
                        </div>
                        {isAdmin && (
                          <button
                            onClick={() => handleUnlearnRevision(item.revision_id)}
                            className="px-2 py-1 text-xs rounded bg-red-900/40 text-red-300 hover:bg-red-800/60"
                          >
                            Unlearn
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-gray-500">No taught revisions yet.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
