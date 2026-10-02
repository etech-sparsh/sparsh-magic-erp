// Real-time task events over SSE (backend: GET /api/tasks/stream).
// EventSource can't set an Authorization header, so the JWT is passed as a query param
// (the backend validates it the same way as the bearer token). EventSource also gives us
// automatic reconnection for free.

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';
const TASK_EVENT_TYPES = ['task_created', 'task_updated', 'task_completed', 'task_assigned', 'task_deleted'];

// Opens the stream and invokes onEvent(type, data) for each task event.
// Returns a cleanup function that closes the connection (call it on unmount).
export const openTaskEventStream = (onEvent) => {
  const token = localStorage.getItem('token');
  if (!token) return () => {};

  const url = `${API_BASE_URL}/tasks/stream?token=${encodeURIComponent(token)}`;
  let es;
  try {
    es = new EventSource(url);
  } catch {
    return () => {};
  }

  const handlers = {};
  TASK_EVENT_TYPES.forEach((type) => {
    const h = (e) => {
      let data = {};
      try { data = JSON.parse(e.data); } catch { /* keepalive/non-JSON */ }
      onEvent(type, data);
    };
    handlers[type] = h;
    es.addEventListener(type, h);
  });

  return () => {
    try {
      TASK_EVENT_TYPES.forEach((type) => es.removeEventListener(type, handlers[type]));
      es.close();
    } catch { /* already closed */ }
  };
};
