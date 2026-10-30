import { useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Bot, MessageSquare, Send, X, User, Loader2 } from 'lucide-react';
import { packagesAPI } from '../lib/api';
import { useToast } from '../contexts/ToastContext';

const STATUS_STYLES = {
  pending: 'bg-gray-700 text-gray-200',
  running: 'bg-blue-800 text-blue-100',
  applied: 'bg-green-800 text-green-100',
  no_fix: 'bg-yellow-800 text-yellow-100',
  invalid_response: 'bg-red-800 text-red-100',
  validation_failed: 'bg-red-800 text-red-100',
  unchanged: 'bg-yellow-800 text-yellow-100',
  error: 'bg-red-800 text-red-100',
};

const STATUS_LABELS = {
  pending: 'Queued',
  running: 'Thinking…',
  applied: 'Fix applied',
  no_fix: 'No fix proposed',
  invalid_response: 'Invalid response',
  validation_failed: 'Spec validation failed',
  unchanged: 'Nothing changed',
  error: 'Error',
};

const isBusy = (attempt) => attempt.status === 'pending' || attempt.status === 'running';

function prettyJson(raw) {
  if (!raw) return '';
  try {
    const match = raw.match(/\{[\s\S]*\}/);
    return JSON.stringify(JSON.parse(match ? match[0] : raw), null, 2);
  } catch {
    return raw;
  }
}

// Group attempts into threads (root first, replies in chronological order).
function buildThreads(attempts) {
  const byId = new Map(attempts.map((a) => [a.id, a]));
  const rootOf = (a) => {
    let node = a;
    const seen = new Set();
    while (node.parent && byId.has(node.parent) && !seen.has(node.id)) {
      seen.add(node.id);
      node = byId.get(node.parent);
    }
    return node.id;
  };
  const threads = new Map();
  for (const a of attempts) {
    const root = rootOf(a);
    if (!threads.has(root)) threads.set(root, []);
    threads.get(root).push(a);
  }
  return [...threads.values()]
    .map((items) => items.sort((x, y) => new Date(x.created_at) - new Date(y.created_at)))
    .sort((x, y) => new Date(y[y.length - 1].created_at) - new Date(x[x.length - 1].created_at));
}

function AttemptCard({ attempt, isLast, onReply }) {
  const busy = isBusy(attempt);
  return (
    <div className="space-y-2">
      {attempt.user_message && (
        <div className="flex gap-2 items-start">
          <User className="h-4 w-4 text-indigo-300 mt-1 shrink-0" />
          <div className="bg-indigo-900/40 border border-indigo-800 rounded p-2 text-sm text-gray-200 whitespace-pre-wrap flex-1">
            <div className="text-xs text-indigo-300 mb-1">
              {attempt.created_by_username || 'You'} · {new Date(attempt.created_at).toLocaleString()}
              {attempt.rebuild_requested ? ' · rebuild on fix' : ''}
            </div>
            {attempt.user_message}
          </div>
        </div>
      )}

      <div className="flex gap-2 items-start">
        <Bot className="h-4 w-4 text-purple-300 mt-1 shrink-0" />
        <div className="bg-gray-900 border border-gray-700 rounded p-3 text-sm text-gray-200 flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-2">
            <span className={`px-2 py-0.5 rounded text-xs font-medium flex items-center gap-1 ${STATUS_STYLES[attempt.status] || 'bg-gray-700 text-gray-200'}`}>
              {busy && <Loader2 className="h-3 w-3 animate-spin" />}
              {STATUS_LABELS[attempt.status] || attempt.status}
            </span>
            {attempt.error_category && (
              <span className="px-2 py-0.5 rounded text-xs bg-gray-700 text-gray-300">{attempt.error_category}</span>
            )}
            <span className="text-xs text-gray-500">
              #{attempt.id} · {attempt.source === 'user_reply'
                ? 'reply'
                : attempt.parent ? `automatic reconsideration of #${attempt.parent}` : 'autofix'}
              {attempt.model_name ? ` · ${attempt.model_name}` : ''}
              {` · ${new Date(attempt.completed_at || attempt.created_at).toLocaleString()}`}
            </span>
          </div>

          {attempt.source === 'autofix' && attempt.parent && (
            <p className="text-xs text-gray-400 mb-2">
              This follow-up was requested after the previous proposal made no changes.
            </p>
          )}

          {busy ? (
            <p className="text-gray-400 text-sm">Waiting for the AI model…</p>
          ) : (
            <>
              {attempt.reasoning && (
                <p className="text-gray-200 whitespace-pre-wrap mb-2">{attempt.reasoning}</p>
              )}
              {attempt.actions?.length > 0 && (
                <div className="mb-2">
                  <div className="text-xs text-gray-400 mb-1">Proposed actions</div>
                  <ul className="space-y-0.5">
                    {attempt.actions.map((a, i) => (
                      <li key={i} className="text-xs font-mono text-gray-300">
                        {a.op === 'rewrite_spec' ? (
                          <details>
                            <summary className="cursor-pointer">
                              {a.op}: complete spec ({String(a.value || '').split('\n').length} lines)
                            </summary>
                            <pre className="mt-1 max-h-96 overflow-auto whitespace-pre-wrap rounded bg-gray-950 p-2">{a.value}</pre>
                          </details>
                        ) : a.op === 'insert_lines' && a.value && typeof a.value === 'object' ? (
                          <div>
                            {a.op}: {a.value.position} <span className="text-gray-400">{a.value.anchor}</span>
                            <pre className="mt-1 overflow-auto whitespace-pre-wrap rounded bg-gray-950 p-2">{(a.value.lines || []).join('\n')}</pre>
                          </div>
                        ) : (
                          <>{a.op}: {typeof a.value === 'string' ? a.value : JSON.stringify(a.value)}</>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {attempt.applied_changes?.length > 0 && (
                <p className="text-xs text-green-300 mb-2">
                  Applied: {attempt.applied_changes.join('; ')}
                  {attempt.revision_ai_feedback && attempt.revision_ai_feedback !== 'unknown'
                    ? ` (feedback: ${attempt.revision_ai_feedback})`
                    : ''}
                </p>
              )}
              {attempt.error_message && (
                <p className="text-xs text-red-300 whitespace-pre-wrap mb-2">{attempt.error_message}</p>
              )}
              {!attempt.reasoning && !attempt.error_message && !attempt.actions?.length && (
                <p className="text-xs text-gray-400 mb-2">{attempt.summary}</p>
              )}
            </>
          )}

          <div className="flex items-center gap-3 flex-wrap">
            {attempt.raw_response && (
              <details className="text-xs w-full">
                <summary className="text-indigo-400 cursor-pointer hover:text-indigo-300">Raw AI response</summary>
                <pre className="mt-1 p-2 bg-gray-950 rounded text-gray-300 whitespace-pre-wrap overflow-x-auto max-h-64 overflow-y-auto">
                  {prettyJson(attempt.raw_response)}
                </pre>
              </details>
            )}
            {attempt.prompt && (
              <details className="text-xs w-full">
                <summary className="text-indigo-400 cursor-pointer hover:text-indigo-300">Prompt sent to AI</summary>
                <pre className="mt-1 p-2 bg-gray-950 rounded text-gray-400 whitespace-pre-wrap overflow-x-auto max-h-64 overflow-y-auto">
                  {attempt.prompt}
                </pre>
              </details>
            )}
          </div>

          {isLast && !busy && (
            <button
              onClick={() => onReply(attempt)}
              className="mt-2 px-2.5 py-1.5 text-xs rounded bg-purple-800/50 text-purple-200 hover:bg-purple-700/70 flex items-center gap-1.5 transition-colors"
            >
              <MessageSquare className="h-3.5 w-3.5" /> Reply to AI
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function ReplyModal({ attempt, submitting, onCancel, onSubmit }) {
  const [message, setMessage] = useState('');
  const [rebuild, setRebuild] = useState(true);
  if (!attempt) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-2xl rounded-lg border border-gray-700 bg-gray-800 p-5 shadow-xl">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold text-white">Reply to AI (attempt #{attempt.id})</h3>
          <button onClick={onCancel} className="text-gray-400 hover:text-white">
            <X className="h-5 w-5" />
          </button>
        </div>
        {(attempt.reasoning || attempt.summary) && (
          <div className="mb-3 p-2 rounded bg-gray-900 border border-gray-700 text-xs text-gray-300 whitespace-pre-wrap max-h-32 overflow-y-auto">
            {attempt.reasoning || attempt.summary}
          </div>
        )}
        <p className="text-sm text-gray-400 mb-2">
          Give the AI more information, e.g. what is wrong with its answer, which dependency or module name is correct,
          or hints from the build log. The current spec and latest build error are included automatically.
        </p>
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={6}
          maxLength={4000}
          autoFocus
          className="w-full rounded border border-gray-600 bg-gray-900 p-2 text-sm text-white focus:border-indigo-500 focus:outline-none"
          placeholder="The module is installed as 'google', not 'googleapis_common_protos'..."
        />
        <label className="mt-2 flex items-center gap-2 text-sm text-gray-300">
          <input type="checkbox" checked={rebuild} onChange={(e) => setRebuild(e.target.checked)} />
          Rebuild the package if the AI applies a fix
        </label>
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onCancel} className="px-3 py-1.5 text-sm rounded bg-gray-700 text-gray-200 hover:bg-gray-600">
            Cancel
          </button>
          <button
            onClick={() => onSubmit(message.trim(), rebuild)}
            disabled={submitting || !message.trim()}
            className="px-3 py-1.5 text-sm rounded bg-purple-700 text-white hover:bg-purple-600 disabled:bg-gray-600 flex items-center gap-1.5"
          >
            <Send className="h-4 w-4" /> {submitting ? 'Sending…' : 'Send'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AIConversations({ packageId }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [replyTo, setReplyTo] = useState(null);

  const { data: attempts = [] } = useQuery({
    queryKey: ['package-ai-attempts', packageId],
    queryFn: async () => (await packagesAPI.aiAttempts(packageId, { limit: 50 })).data,
    refetchInterval: (query) => ((query.state.data || []).some(isBusy) ? 3000 : 10000),
  });

  const threads = useMemo(() => buildThreads(attempts), [attempts]);

  const replyMutation = useMutation({
    mutationFn: async ({ attemptId, message, rebuild }) =>
      (await packagesAPI.replyToAiAttempt(packageId, attemptId, message, rebuild)).data,
    onSuccess: () => {
      toast.success('Reply sent to the AI fixer');
      setReplyTo(null);
      queryClient.invalidateQueries({ queryKey: ['package-ai-attempts', packageId] });
      queryClient.invalidateQueries({ queryKey: ['package-logs', packageId] });
    },
    onError: (error) => {
      toast.error(`Failed to send reply: ${error.response?.data?.detail || error.message}`);
    },
  });

  return (
    <div className="bg-gray-800 shadow rounded-lg p-6 border border-gray-700">
      <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
        <Bot className="h-5 w-5" />
        AI Conversations ({threads.length})
      </h2>
      {threads.length === 0 ? (
        <p className="text-gray-400 text-sm">The AI fixer has not been used for this package yet.</p>
      ) : (
        <div className="space-y-4">
          {threads.map((thread) => (
            <div key={thread[0].id} className="border border-gray-700 rounded-lg p-3 space-y-3">
              {thread.map((attempt, idx) => (
                <AttemptCard
                  key={attempt.id}
                  attempt={attempt}
                  isLast={idx === thread.length - 1}
                  onReply={setReplyTo}
                />
              ))}
            </div>
          ))}
        </div>
      )}

      <ReplyModal
        key={replyTo?.id ?? 'none'}
        attempt={replyTo}
        submitting={replyMutation.isPending}
        onCancel={() => setReplyTo(null)}
        onSubmit={(message, rebuild) => replyMutation.mutate({ attemptId: replyTo.id, message, rebuild })}
      />
    </div>
  );
}
