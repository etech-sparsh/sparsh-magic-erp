import api from './api';

// Task Groups CRUD (backend/app/routes/group.py). Tasks are scoped to a group via the
// task's group_id (sent through the normal task-create flow).
export const getGroups = () => api.get('/groups');
export const createGroup = (payload) => api.post('/groups', payload);
export const getGroup = (id) => api.get(`/groups/${id}`);
export const updateGroup = (id, payload) => api.put(`/groups/${id}`, payload);
export const deleteGroup = (id) => api.delete(`/groups/${id}`);

export const addGroupLink = (groupId, payload) => api.post(`/groups/${groupId}/links`, payload);
export const deleteGroupLink = (groupId, linkId) => api.delete(`/groups/${groupId}/links/${linkId}`);
