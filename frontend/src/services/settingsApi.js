import api from './api';

// Self-service profile (backend/app/routes/user.py) — PATCH /users/me only touches safe
// fields; role/permissions stay admin-only via PUT /users/{id}.
export const getMyProfile = () => api.get('/users/me');
export const updateMyProfile = (payload) => api.patch('/users/me', payload);

// Per-user notification preferences (backend/app/routes/notification.py).
export const getNotificationPrefs = () => api.get('/notifications/preferences');
export const updateNotificationPrefs = (payload) => api.put('/notifications/preferences', payload);
