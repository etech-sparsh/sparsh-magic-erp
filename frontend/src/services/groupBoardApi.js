import api from './api';

// Ideaboard (kanban) card CRUD, scoped to a group (backend/app/routes/group_board.py).
export const getBoardCards = (groupId) => api.get(`/groups/${groupId}/board`);
export const createBoardCard = (groupId, payload) => api.post(`/groups/${groupId}/board`, payload);
export const updateBoardCard = (groupId, cardId, updates) => api.patch(`/groups/${groupId}/board/${cardId}`, updates);
export const moveBoardCard = (groupId, cardId, payload) => api.post(`/groups/${groupId}/board/${cardId}/move`, payload);
export const deleteBoardCard = (groupId, cardId) => api.delete(`/groups/${groupId}/board/${cardId}`);
