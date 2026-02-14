import { useEffect, useRef, useState } from 'react';
import { X, Terminal, CheckCircle, XCircle, Clock, Loader, AlertTriangle } from 'lucide-react';

export default function LiveTaskLog({ taskId, taskName, onClose }) {
  const [log, setLog] = useState('');
  const [status, setStatus] = useState('connecting');
  const [taskInfo, setTaskInfo] = useState({ task_name: taskName, task_id: taskId });
  const [result, setResult] = useState('');
  const [traceback, setTraceback] = useState('');
  const [isCompleted, setIsCompleted] = useState(false);
  const [duration, setDuration] = useState(null);
  const wsRef = useRef(null);
  const logEndRef = useRef(null);
  const logContainerRef = useRef(null);
  const [autoScroll, setAutoScroll] = useState(true);

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/tasks/${taskId}/log/`;

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus('connected');
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.type) {
        case 'status':
          setStatus(data.status);
          if (data.task_name) {
            setTaskInfo(prev => ({ ...prev, task_name: data.task_name }));
          }
          if (data.completed) {
            setIsCompleted(true);
            if (data.duration) {
              setDuration(data.duration);
            }
          }
          break;

        case 'log':
          setLog(prev => prev + data.data);
          break;

        case 'result':
          setResult(data.data || '');
          break;

        case 'traceback':
          setTraceback(data.data || '');
          break;

        case 'error':
          setStatus('error');
          setLog(prev => prev + `\nError: ${data.message}\n`);
          break;

        default:
          break;
      }
    };

    ws.onerror = () => {
      setStatus('error');
    };

    ws.onclose = () => {
      if (!isCompleted) {
        setStatus('disconnected');
      }
    };

    return () => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.close();
      }
    };
  }, [taskId]);

  // Auto-scroll to bottom when new content arrives
  useEffect(() => {
    if (autoScroll && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [log, result, traceback, autoScroll]);

  const handleScroll = () => {
    if (!logContainerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = logContainerRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 50;
    setAutoScroll(isAtBottom);
  };

  const formatTaskName = (name) => {
    if (!name) return 'Unknown Task';
    return name.split('.').pop().replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  };

  const formatResult = (resultStr) => {
    if (!resultStr) return '';
    try {
      const parsed = JSON.parse(resultStr);
      return JSON.stringify(parsed, null, 2);
    } catch {
      return resultStr;
    }
  };

  const getStatusColor = () => {
    switch (status) {
      case 'SUCCESS':
        return 'text-green-400';
      case 'FAILURE':
        return 'text-red-400';
      case 'STARTED':
        return 'text-blue-400';
      case 'RETRY':
        return 'text-orange-400';
      case 'REVOKED':
        return 'text-gray-400';
      case 'error':
        return 'text-red-400';
      default:
        return 'text-yellow-400';
    }
  };

  const getStatusIcon = () => {
    switch (status) {
      case 'SUCCESS':
        return <CheckCircle className="h-5 w-5" />;
      case 'FAILURE':
        return <XCircle className="h-5 w-5" />;
      case 'STARTED':
        return <Loader className="h-5 w-5 animate-spin" />;
      case 'RETRY':
        return <AlertTriangle className="h-5 w-5" />;
      case 'REVOKED':
        return <XCircle className="h-5 w-5" />;
      case 'PENDING':
      case 'connected':
        return <Clock className="h-5 w-5" />;
      default:
        return <Terminal className="h-5 w-5" />;
    }
  };

  const getStatusLabel = () => {
    switch (status) {
      case 'connecting':
        return 'Connecting...';
      case 'connected':
        return 'Connected';
      case 'disconnected':
        return 'Disconnected';
      case 'error':
        return 'Error';
      default:
        return status;
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
                {formatTaskName(taskInfo.task_name)}
              </h2>
              <p className="text-sm text-gray-400">
                Task ID: <span className="font-mono">{taskInfo.task_id}</span>
                {' • '}
                Status: <span className={getStatusColor()}>{getStatusLabel()}</span>
                {duration && ` • Duration: ${duration}s`}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content */}
        <div
          ref={logContainerRef}
          onScroll={handleScroll}
          className="flex-1 overflow-y-auto p-4 bg-gray-950 space-y-4"
        >
          {/* Log output */}
          {log && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">Task Log</h3>
              <pre className="text-xs text-gray-300 font-mono whitespace-pre-wrap bg-black/50 rounded p-3">
                {log}
              </pre>
            </div>
          )}

          {/* Result */}
          {result && (
            <div>
              <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">
                {status === 'SUCCESS' ? '✅ Result' : 'Result'}
              </h3>
              <pre className="text-xs text-green-300 font-mono whitespace-pre-wrap bg-green-900/10 border border-green-800/30 rounded p-3 max-h-64 overflow-y-auto">
                {formatResult(result)}
              </pre>
            </div>
          )}

          {/* Traceback */}
          {traceback && (
            <div>
              <h3 className="text-xs font-semibold text-red-400 uppercase mb-2 flex items-center gap-2">
                <AlertTriangle className="h-3.5 w-3.5" />
                Error Traceback
              </h3>
              <pre className="text-xs text-red-300 font-mono whitespace-pre-wrap bg-red-900/10 border border-red-800/30 rounded p-3 max-h-64 overflow-y-auto">
                {traceback}
              </pre>
            </div>
          )}

          {/* Waiting state */}
          {!log && !result && !traceback && !isCompleted && (
            <div className="flex flex-col items-center justify-center h-48 text-gray-500">
              <Terminal className="h-12 w-12 mb-3 opacity-50" />
              <p>Waiting for task output...</p>
              {status === 'PENDING' && (
                <p className="text-sm mt-2">Task is queued, waiting for a worker...</p>
              )}
              {status === 'STARTED' && (
                <p className="text-sm mt-2">Task is running...</p>
              )}
            </div>
          )}

          <div ref={logEndRef} />
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
              <span className={getStatusColor()}>Task {status}</span>
            ) : status === 'STARTED' ? (
              <span className="text-blue-400">Task in progress...</span>
            ) : status === 'PENDING' ? (
              <span className="text-yellow-400">Task pending...</span>
            ) : (
              <span>{getStatusLabel()}</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
