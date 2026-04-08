import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { X, Terminal, CheckCircle, XCircle, AlertTriangle, Download, Lightbulb, ChevronDown, ChevronRight } from 'lucide-react';
import { packagesAPI } from '../lib/api';

// Source labels and default visibility
const SOURCE_LABELS = {
  'build.log': 'Build',
  'root.log': 'Root',
  'state.log': 'State',
  'output': 'Mock Output',
};
const SOURCE_COLORS = {
  'build.log': 'bg-blue-600 hover:bg-blue-500',
  'root.log': 'bg-purple-700 hover:bg-purple-600',
  'state.log': 'bg-gray-600 hover:bg-gray-500',
  'output': 'bg-gray-700 hover:bg-gray-600',
};
const DEFAULT_VISIBLE_SOURCES = new Set(['build.log']);

/** Parse a raw line into {source, content}. Lines arriving from the backend are prefixed
 *  as "build.log - <content>" or "root.log - <content>" etc. */
function parseRawLine(raw) {
  const m = raw.match(/^([\w-]+\.log) - (.*)$/);
  if (m) return { source: m[1], content: m[2] };
  return { source: 'output', content: raw };
}

function classifyLogLine(line) {
  const l = line.toLowerCase();
  // Error patterns
  if (/\berror\b|bad exit status|failed\b|exception:|traceback|no such file|command not found|child return code was: [^0]/.test(l)) {
    return 'error';
  }
  // Warning patterns
  if (/\bwarning\b|deprecated|skipping|not found/.test(l)) {
    return 'warning';
  }
  // Success patterns
  if (/\bwrote:\b|successfully|installed:|installing:|packages installed|finish:|checking build|arch independent/.test(l)) {
    return 'success';
  }
  // Section/stage headers (RPM phase markers and mock stages)
  if (/^(\+ )?%(build|install|prep|check|clean|generate_buildrequires|pyproject_wheel|pyproject_install|pyproject_buildrequires|autosetup|files)|^INFO \w|^BUILDING|^mock:|^=+$|^-+$/.test(line)) {
    return 'section';
  }
  // Shell commands being executed (lines starting with +)
  if (/^\+/.test(line)) {
    return 'command';
  }
  // Debug / verbose
  if (/^debug:|^\[DEBUG\]|reusing|cached|checking/.test(l)) {
    return 'debug';
  }
  return 'default';
}

const LOG_LINE_COLORS = {
  error:   'text-red-400 bg-red-950/30',
  warning: 'text-yellow-300 bg-yellow-950/20',
  success: 'text-green-400',
  section: 'text-cyan-300 font-semibold',
  command: 'text-blue-300 opacity-80',
  debug:   'text-gray-500',
  default: 'text-gray-300',
};

const categoryIcons = {
  'Missing Dependencies': '📦',
  'Missing Packages': '📦',
  'Missing Python Modules': '🐍',
  'Missing Header Files': '📄',
  'Ambiguous Python Shebang': '🐍',
  'Empty Debug Info': '🔍',
  'Missing Rust/Cargo': '🦀',
  'Missing Python Wheel': '🐍',
  'Missing GCC': '⚙️',
  'Architecture Mismatch': '🏗️',
  'Bad Interpreter': '⚠️',
  'Permission Denied': '🔒',
  'Disk Space': '💾',
  'Network Error': '🌐',
  'Source File Missing': '📁',
  'RPM Macro Error': '⚙️',
  'Python Syntax Error': '🐍',
  'Python Import Error': '🐍',
  'Test Failures': '🧪',
  'File Conflicts': '⚠️',
  'Unpackaged Files': '📂',
  'Scriplet Error': '📜',
};

function ErrorAnalysisPanel({ errors }) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="mb-4 bg-amber-900/15 border border-amber-700/50 rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full p-3 flex items-center gap-2 hover:bg-amber-900/20 transition-colors"
      >
        {expanded ? (
          <ChevronDown className="h-4 w-4 text-amber-400" />
        ) : (
          <ChevronRight className="h-4 w-4 text-amber-400" />
        )}
        <AlertTriangle className="h-4 w-4 text-amber-400" />
        <span className="text-sm font-semibold text-amber-300">
          Build Error Analysis — {errors.length} issue{errors.length !== 1 ? 's' : ''} detected
        </span>
      </button>

      {expanded && (
        <div className="px-3 pb-3 space-y-3">
          {errors.map((error, idx) => (
            <div
              key={idx}
              className="bg-gray-800/60 rounded-lg p-3 border border-gray-700/50"
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="text-base">{categoryIcons[error.category] || '❌'}</span>
                <h5 className="text-sm font-semibold text-gray-200">{error.category}</h5>
                <span className="text-xs text-gray-400">{error.message}</span>
              </div>

              {error.items && error.items.length > 0 && (
                <ul className="ml-7 mt-1 space-y-0.5">
                  {error.items.map((item, i) => (
                    <li key={i} className="text-xs font-mono text-red-300">
                      • {item}
                    </li>
                  ))}
                </ul>
              )}

              {error.suggestion && (
                <div className="flex items-start gap-1.5 ml-7 mt-2">
                  <Lightbulb className="h-3.5 w-3.5 text-yellow-400 flex-shrink-0 mt-0.5" />
                  <span className="text-xs text-yellow-300/80">{error.suggestion}</span>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function LivePackageBuildLog({ packageId, packageName, onClose }) {
  // All lines stored in a ref to avoid expensive React state for 150k+ entries.
  // We increment flushCount to trigger re-renders after each batch.
  const allLinesRef = useRef([]);          // [{source, content, kind}]
  const pendingRef = useRef([]);           // lines waiting to be flushed
  const lineBufferRef = useRef('');        // incomplete line at end of chunk
  const flushTimerRef = useRef(null);
  const [flushCount, setFlushCount] = useState(0);

  // Detected sources so we can show toggles dynamically
  const detectedSourcesRef = useRef(new Set(['build.log']));
  const [detectedSources, setDetectedSources] = useState(new Set(['build.log']));
  const [visibleSources, setVisibleSources] = useState(DEFAULT_VISIBLE_SOURCES);

  const [status, setStatus] = useState('connecting');
  const [buildInfo, setBuildInfo] = useState(null);
  const [errorMessage, setErrorMessage] = useState('');
  const [analyzedErrors, setAnalyzedErrors] = useState([]);
  const [isCompleted, setIsCompleted] = useState(false);
  const wsRef = useRef(null);
  const logContainerRef = useRef(null);
  const [autoScroll, setAutoScroll] = useState(true);

  // Batch incoming lines and flush to allLinesRef every 100ms
  const scheduleFlush = useCallback(() => {
    if (flushTimerRef.current) return;
    flushTimerRef.current = setTimeout(() => {
      flushTimerRef.current = null;
      const newLines = pendingRef.current.splice(0);
      if (newLines.length === 0) return;
      allLinesRef.current.push(...newLines);
      // Check for newly discovered sources
      let hadNew = false;
      for (const l of newLines) {
        if (!detectedSourcesRef.current.has(l.source)) {
          detectedSourcesRef.current.add(l.source);
          hadNew = true;
        }
      }
      if (hadNew) setDetectedSources(new Set(detectedSourcesRef.current));
      setFlushCount((c) => c + 1);
    }, 100);
  }, []);

  const appendLogChunk = useCallback((chunk) => {
    lineBufferRef.current += chunk;
    const parts = lineBufferRef.current.split('\n');
    lineBufferRef.current = parts.pop(); // keep incomplete last fragment
    if (parts.length === 0) return;
    const parsed = parts.map((raw) => {
      const { source, content } = parseRawLine(raw);
      return { source, content, kind: classifyLogLine(content) };
    });
    pendingRef.current.push(...parsed);
    scheduleFlush();
  }, [scheduleFlush]);

  useEffect(() => {
    // Determine WebSocket URL
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/packages/${packageId}/build-log/`;

    // Create WebSocket connection
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('WebSocket connected for package', packageId);
      setStatus('connected');
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.type) {
        case 'status':
          setStatus(data.status);
          if (data.package) {
            setBuildInfo({
              name: data.package,
              build_started_at: data.build_started_at,
              build_completed_at: data.build_completed_at,
              srpm_path: data.srpm_path,
              rpm_path: data.rpm_path,
            });
          }
          if (data.completed) {
            setIsCompleted(true);
          }
          // analyzed_errors is also embedded here as a guarantee
          if (data.analyzed_errors && data.analyzed_errors.length > 0) {
            setAnalyzedErrors(data.analyzed_errors);
          }
          break;

        case 'clear_log':
          allLinesRef.current = [];
          pendingRef.current = [];
          lineBufferRef.current = '';
          detectedSourcesRef.current = new Set(['build.log']);
          setDetectedSources(new Set(['build.log']));
          setAnalyzedErrors([]);
          setErrorMessage('');
          setFlushCount((c) => c + 1);
          break;

        case 'log':
          appendLogChunk(data.data);
          break;

        case 'error_message':
          setErrorMessage(data.message);
          break;

        case 'analyzed_errors':
          setAnalyzedErrors(data.errors || []);
          break;

        case 'error':
          console.error('WebSocket error:', data.message);
          setStatus('error');
          appendLogChunk(`\nError: ${data.message}\n`);
          break;

        default:
          console.log('Unknown message type:', data.type);
      }
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      setStatus('error');
    };

    ws.onclose = () => {
      console.log('WebSocket closed');
      setStatus('disconnected');
    };

    return () => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.close();
      }
    };
  }, [packageId, appendLogChunk]);

  // Filtered lines — recomputed only when flush fires or source filter changes
  const filteredLines = useMemo(
    () => allLinesRef.current.filter((l) => visibleSources.has(l.source)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [flushCount, visibleSources]
  );

  // Virtual list — renders only ~50 rows regardless of total count
  const rowVirtualizer = useVirtualizer({
    count: filteredLines.length,
    getScrollElement: () => logContainerRef.current,
    estimateSize: () => 20,   // 20px per line (text-xs, leading-5)
    overscan: 80,
  });

  // Auto-scroll: when new lines arrive and user is at the bottom, jump to end
  useEffect(() => {
    if (autoScroll && logContainerRef.current && filteredLines.length > 0) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [filteredLines.length, autoScroll]);

  const handleScroll = () => {
    if (!logContainerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = logContainerRef.current;
    setAutoScroll(scrollHeight - scrollTop - clientHeight < 60);
  };

  const toggleSource = (source) => {
    setVisibleSources((prev) => {
      const next = new Set(prev);
      if (next.has(source)) next.delete(source);
      else next.add(source);
      return next;
    });
  };

  const getStatusColor = () => {
    switch (status) {
      case 'completed':
        return 'text-green-400';
      case 'failed':
        return 'text-red-400';
      case 'building':
        return 'text-blue-400';
      case 'pending':
        return 'text-yellow-400';
      case 'error':
        return 'text-red-400';
      default:
        return 'text-gray-400';
    }
  };

  const getStatusIcon = () => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="h-5 w-5 text-green-400" />;
      case 'failed':
        return <XCircle className="h-5 w-5 text-red-400" />;
      case 'building':
        return <Terminal className="h-5 w-5 text-blue-400 animate-pulse" />;
      case 'error':
        return <AlertTriangle className="h-5 w-5 text-red-400" />;
      default:
        return <Terminal className="h-5 w-5 text-gray-400" />;
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 rounded-lg shadow-xl w-full max-w-6xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-gray-700 flex items-center justify-between">
          <div className="flex items-center gap-3">
            {getStatusIcon()}
            <div>
              <h3 className="text-lg font-semibold text-white">
                Live Build Log: {packageName}
              </h3>
              <p className={`text-sm ${getStatusColor()}`}>
                Status: {status}
                {buildInfo?.build_started_at && ` | Started: ${new Date(buildInfo.build_started_at).toLocaleTimeString()}`}
                {buildInfo?.build_completed_at && ` | Completed: ${new Date(buildInfo.build_completed_at).toLocaleTimeString()}`}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-800 rounded-lg transition-colors"
          >
            <X className="h-5 w-5 text-gray-400" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden flex flex-col p-4">
          {errorMessage && (
            <div className="mb-4 p-3 bg-red-900/20 border border-red-700 rounded-lg flex-shrink-0">
              <div className="flex items-start gap-2">
                <AlertTriangle className="h-5 w-5 text-red-400 flex-shrink-0 mt-0.5" />
                <div>
                  <h4 className="text-sm font-semibold text-red-400 mb-1">Build Error</h4>
                  <p className="text-sm text-red-300 font-mono whitespace-pre-wrap">{errorMessage}</p>
                </div>
              </div>
            </div>
          )}

          {/* Analyzed errors section */}
          {analyzedErrors.length > 0 && (
            <div className="flex-shrink-0">
              <ErrorAnalysisPanel errors={analyzedErrors} />
            </div>
          )}

          {/* Log source filter toggles */}
          {detectedSources.size > 0 && (
            <div className="mb-2 flex items-center gap-2 flex-wrap flex-shrink-0">
              <span className="text-xs text-gray-400">Show:</span>
              {[...detectedSources].map((src) => (
                <button
                  key={src}
                  onClick={() => toggleSource(src)}
                  className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
                    visibleSources.has(src)
                      ? (SOURCE_COLORS[src] || 'bg-blue-600 hover:bg-blue-500') + ' text-white'
                      : 'bg-gray-800 text-gray-500 hover:bg-gray-700 hover:text-gray-300'
                  }`}
                >
                  {SOURCE_LABELS[src] || src}
                </button>
              ))}
              <span className="ml-auto text-xs text-gray-500">
                {filteredLines.length.toLocaleString()} / {allLinesRef.current.length.toLocaleString()} lines
              </span>
            </div>
          )}

          {/* Virtualized log container */}
          <div
            ref={logContainerRef}
            onScroll={handleScroll}
            className="flex-1 min-h-0 bg-black rounded-lg overflow-auto font-mono text-xs"
          >
            {filteredLines.length > 0 ? (
              <div
                style={{ height: `${rowVirtualizer.getTotalSize()}px`, position: 'relative' }}
              >
                {rowVirtualizer.getVirtualItems().map((vRow) => {
                  const line = filteredLines[vRow.index];
                  return (
                    <div
                      key={vRow.index}
                      style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        transform: `translateY(${vRow.start}px)`,
                        height: `${vRow.size}px`,
                      }}
                      className={`flex items-center px-4 leading-5 whitespace-pre ${LOG_LINE_COLORS[line.kind]}`}
                    >
                      {line.content || '\u00a0'}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="text-center py-12 text-gray-500">
                <Terminal className="h-12 w-12 mx-auto mb-3 opacity-50 animate-pulse" />
                <p>Waiting for build logs...</p>
              </div>
            )}
          </div>

          {!autoScroll && filteredLines.length > 0 && (
            <div className="mt-2 text-center">
              <button
                onClick={() => {
                  setAutoScroll(true);
                  if (logContainerRef.current) {
                    logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
                  }
                }}
                className="px-3 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700"
              >
                ↓ Scroll to bottom
              </button>
            </div>
          )}

          {/* Build artifacts */}
          {isCompleted && (buildInfo?.srpm_path || buildInfo?.rpm_path) && (
            <div className="mt-4 p-3 bg-gray-800 rounded-lg">
              <h4 className="text-sm font-semibold text-gray-300 mb-2 flex items-center gap-2">
                <Download className="h-4 w-4" />
                Build Artifacts
              </h4>
              <div className="space-y-2">
                {buildInfo.srpm_path && (
                  <div className="text-sm">
                    <span className="text-gray-400">SRPM:</span>
                    <button
                      onClick={async () => {
                        try {
                          const response = await packagesAPI.downloadSrpm(packageId);
                          const url = window.URL.createObjectURL(response.data);
                          const link = document.createElement('a');
                          link.href = url;
                          link.download = buildInfo.srpm_path.split('/').pop();
                          document.body.appendChild(link);
                          link.click();
                          document.body.removeChild(link);
                          window.URL.revokeObjectURL(url);
                        } catch (error) {
                          console.error('Download failed:', error);
                        }
                      }}
                      className="ml-2 text-blue-400 hover:text-blue-300 underline font-mono cursor-pointer bg-transparent border-none"
                    >
                      {buildInfo.srpm_path.split('/').pop()}
                    </button>
                  </div>
                )}
                {buildInfo.rpm_path && (
                  <div className="text-sm">
                    <span className="text-gray-400">RPM:</span>
                    <button
                      onClick={async () => {
                        try {
                          const response = await packagesAPI.downloadRpm(packageId);
                          const url = window.URL.createObjectURL(response.data);
                          const link = document.createElement('a');
                          link.href = url;
                          link.download = buildInfo.rpm_path.split('/').pop();
                          document.body.appendChild(link);
                          link.click();
                          document.body.removeChild(link);
                          window.URL.revokeObjectURL(url);
                        } catch (error) {
                          console.error('Download failed:', error);
                        }
                      }}
                      className="ml-2 text-blue-400 hover:text-blue-300 underline font-mono cursor-pointer bg-transparent border-none"
                    >
                      {buildInfo.rpm_path.split('/').pop()}
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-gray-700 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 bg-gray-700 text-white rounded-lg hover:bg-gray-600 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
