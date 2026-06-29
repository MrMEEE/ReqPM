import { createContext, useContext, useRef, useState } from 'react';
import Toast from '../components/Toast';

const ToastContext = createContext();

export const useToast = () => {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within ToastProvider');
  }
  return context;
};

export const ToastProvider = ({ children }) => {
  const [toasts, setToasts] = useState([]);
  const recentToastTimesRef = useRef(new Map());

  const TOAST_DEDUPE_WINDOW_MS = 2000;
  const TOAST_DEDUPE_MAX_AGE_MS = 60000;

  const showToast = (message, type = 'info', duration = 5000) => {
    const now = Date.now();
    const dedupeKey = `${type}:${message}`;

    setToasts((prev) => {
      const hasActiveDuplicate = prev.some(
        (t) => t.type === type && t.message === message
      );
      const lastShownAt = recentToastTimesRef.current.get(dedupeKey) || 0;
      const isRecentDuplicate = now - lastShownAt < TOAST_DEDUPE_WINDOW_MS;

      if (hasActiveDuplicate || isRecentDuplicate) {
        return prev;
      }

      // Keep map size bounded by dropping old entries opportunistically.
      for (const [k, ts] of recentToastTimesRef.current.entries()) {
        if (now - ts > TOAST_DEDUPE_MAX_AGE_MS) {
          recentToastTimesRef.current.delete(k);
        }
      }

      recentToastTimesRef.current.set(dedupeKey, now);
      const id = `${now}-${Math.random().toString(36).slice(2, 10)}`;
      return [...prev, { id, message, type, duration }];
    });
  };

  const removeToast = (id) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  };

  const toast = {
    success: (message, duration) => showToast(message, 'success', duration),
    error: (message, duration) => showToast(message, 'error', duration),
    warning: (message, duration) => showToast(message, 'warning', duration),
    info: (message, duration) => showToast(message, 'info', duration),
  };

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map((toast) => (
          <Toast
            key={toast.id}
            message={toast.message}
            type={toast.type}
            duration={toast.duration}
            onClose={() => removeToast(toast.id)}
          />
        ))}
      </div>
    </ToastContext.Provider>
  );
};
