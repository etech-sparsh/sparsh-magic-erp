import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

const api = axios.create({
  baseURL: API_BASE_URL,
});

// Interceptor to add auth token and handle Content-Type for FormData
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }

  // If we're sending FormData, let axios handle the Content-Type automatically (with boundary)
  if (config.data instanceof FormData) {
    delete config.headers['Content-Type'];
  } else if (!config.headers['Content-Type']) {
    // Default to JSON for other requests if not specified
    config.headers['Content-Type'] = 'application/json';
  }

  return config;
}, (error) => {
  return Promise.reject(error);
});

// Response interceptor for global error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 403) {
      // Prefer the server's own reason. A 403 is often actionable ("TPMS is not enabled for
      // this company…") and the generic string hid that, leaving the user with a failed
      // action and no explanation.
      const detail = error.response?.data?.detail;
      const event = new CustomEvent('app-error', {
        detail: {
          message: typeof detail === 'string' && detail.trim() ? detail : 'You do not have permission',
          status: 403,
        },
      });
      window.dispatchEvent(event);
    }
    return Promise.reject(error);
  }
);

export default api;
