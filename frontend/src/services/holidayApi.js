import api from './api';

// Holiday master CRUD (backend/app/routes/holiday.py). holiday_date is an ISO "YYYY-MM-DD".
export const getHolidays = (params) => api.get('/holidays', { params });
export const createHoliday = (payload) => api.post('/holidays', payload);
export const updateHoliday = (id, payload) => api.put(`/holidays/${id}`, payload);
export const deleteHoliday = (id) => api.delete(`/holidays/${id}`);
