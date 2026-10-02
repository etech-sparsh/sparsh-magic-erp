import React, { createContext, useContext, useState, useCallback } from 'react';

const NotificationContext = createContext();

/**
 * Guards against "Objects are not valid as a React child": a FastAPI 422 (Pydantic
 * validation failure) puts an ARRAY of {type, loc, msg, input} objects in
 * `err.response.data.detail`, not a string — every call site across the app passes that
 * straight through as `showError(err?.response?.data?.detail || fallback)`, and until now
 * a genuine validation error (a missing/mistyped field, not just a 4xx with a plain string
 * detail) would crash the toast itself instead of showing it. Normalising here, once, is
 * safer than auditing every call site.
 */
function _asDisplayString(message) {
  if (typeof message === 'string' || message == null) return message;
  if (Array.isArray(message)) {
    return message.map((e) => (typeof e === 'string' ? e : e?.msg || JSON.stringify(e))).join('; ');
  }
  if (typeof message === 'object') return message.msg || JSON.stringify(message);
  return String(message);
}

export const NotificationProvider = ({ children }) => {
  const [notification, setNotification] = useState(null);

  const showSuccess = useCallback((message) => {
    setNotification({ type: 'success', message });
  }, []);

  const showError = useCallback((message) => {
    setNotification({ type: 'error', message: _asDisplayString(message) });
  }, []);

  const clearNotification = useCallback(() => {
    setNotification(null);
  }, []);

  React.useEffect(() => {
    const handleGlobalError = (event) => {
      showError(event.detail.message);
    };
    window.addEventListener('app-error', handleGlobalError);
    return () => window.removeEventListener('app-error', handleGlobalError);
  }, [showError]);

  return (
    <NotificationContext.Provider value={{ notification, showSuccess, showError, clearNotification }}>
      {children}
    </NotificationContext.Provider>
  );
};

// eslint-disable-next-line react-refresh/only-export-components
export const useNotification = () => {
  const context = useContext(NotificationContext);
  if (!context) {
    throw new Error('useNotification must be used within a NotificationProvider');
  }
  return context;
};
