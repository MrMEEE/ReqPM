import { useEffect, useRef, useState } from 'react';
import { X, Terminal, CheckCircle, XCircle, AlertTriangle } from 'lucide-react';

export default function LiveBuildLog({ queueItemId, onClose }) {
  const [log, setLog] = useState('');
  const [status, setStatus] = useState('connecting');
  const [packageInfo, setPackageInfo] = useState(null);
  const [errors, setErrors] = useState([]);
  const [isCompleted, setIsCompleted] = useState(false);
  const wsRef = useRef(null);
  const logEndRef = useRef(null);
  const logContainerRef = useRef(null);
  const [autoScroll, setAutoScroll] = useState(true);

  useEffect(() => {
    // Determine WebSocket URL - proxy through frontend
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/builds/queue/${queueItemId}/log/`;

    // Create WebSocket connection
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('WebSocket connected');
      setStatus('connected');
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.type) {
        case 'status':
          setStatus(data.status);
          if (data.package) {
            setPackageInfo({
              name: data.package,
              rhel_version: data.rhel_version,
            });
          }
          if (data.completed) {
            setIsCompleted(true);
          }
          break;

        case 'log':
          setLog((prev) => prev + data.data);
          break;

        case 'errors':
          setErrors(data.errors || []);
          break;

        case 'error':
          console.error('WebSocket error:', data.message);
          setStatus('error');
          setLog((prev) => prev + `\nError: ${data.message}\n`);
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
  }, [queueItemId]);

  // Auto-scroll to bottom when new log content arrives
  useEffect(() => {
    if (autoScroll && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [log, autoScroll]);

  // Check if user has scrolled away from bottom
  const handleScroll = () => {
    if (!logContainerRef.current) return;
    
    const { scrollTop, scrollHeight, clientHeight } = logContainerRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 50;
    setAutoScroll(isAtBottom);
  };

  const getStatusColor = () => {
    switch (status) {
      case 'completed':
        return 'text-green-400';
      case 'failed':
        return 'text-red-400';
      case 'building':
        return 'text-blue-400';
      case 'error':
        return 'text-red-400';
      default:
        return 'text-gray-400';
    }
  };

  const getStatusIcon = () => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="h-5 w-5" />;
      case 'failed':
        return <XCircle className="h-5 w-5" />;
      case 'building':
        return <Terminal className="h-5 w-5 animate-pulse" />;
      default:
        return <Terminal className="h-5 w-5" />;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="w-full max-w-6xl h-[90vh] bg-gray-900 rounded-lg shadow-2xl flex flex-col border border-gray-700">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-700">
          <div className="flex items-center gap-3">
            <div className={getStatusColor()}>
              {getStatusIcon()}
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">
                {packageInfo ? `Building ${packageInfo.name}` : 'Build Log'}
              </h2>
              {packageInfo && (
                <p className="text-sm text-gray-400">
                  RHEL {packageInfo.rhel_version} • Status: <span className={getStatusColor()}>{status}</span>
                </p>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Error Analysis */}
        {errors.length > 0 && (
          <div className="p-4 border-b border-gray-700 bg-yellow-900/10 max-h-64 overflow-y-auto">
            <h3 className="text-sm font-semibold text-yellow-400 mb-3 flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" />
              Error Analysis ({errors.length})
            </h3>
            <div className="space-y-3">
              {errors.map((error, idx) => (
                <div key={idx} className="bg-yellow-900/20 border border-yellow-700/50 rounded p-3">
                  <div className="text-sm font-medium text-yellow-300 mb-1">
                    {error.category}
                  </div>
                  <div className="text-xs text-gray-300 mb-2">
                    {error.message}
                  </div>
                  {error.items && error.items.length > 0 && (
                    <div className="bg-gray-800/50 rounded p-2 mb-2">
                      <ul className="text-xs text-gray-400 space-y-1">
                        {error.items.slice(0, 5).map((item, i) => (
                          <li key={i} className="font-mono">• {item}</li>
                        ))}
                        {error.items.length > 5 && (
                          <li className="text-gray-500">... and {error.items.length - 5} more</li>
                        )}
                      </ul>
                    </div>
                  )}
                  {error.suggestion && (
                    <div className="text-xs text-indigo-300 flex items-start gap-2">
                      <span className="text-indigo-400">💡</span>
                      <span>{error.suggestion}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Log Content */}
        <div
          ref={logContainerRef}
          onScroll={handleScroll}
          className="flex-1 overflow-y-auto p-4 bg-gray-950"
        >
          <pre className="text-xs text-gray-300 font-mono whitespace-pre-wrap">
            {log || 'Waiting for build to start...'}
            <div ref={logEndRef} />
          </pre>
        </div>

        {/* Footer */}
        <div className="p-3 border-t border-gray-700 bg-gray-800/50 flex items-center justify-between">
          <div className="text-xs text-gray-400">
            {!autoScroll && (
              <button
                onClick={() => {
                  setAutoScroll(true);
                  logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
                }}
                className="px-2 py-1 bg-indigo-600 hover:bg-indigo-700 text-white rounded text-xs transition-colors"
              >
                Enable Auto-scroll
              </button>
            )}
          </div>
          <div className="text-xs text-gray-400">
            {isCompleted ? (
              <span className={getStatusColor()}>Build {status}</span>
            ) : (
              <span className="text-blue-400">Build in progress...</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
