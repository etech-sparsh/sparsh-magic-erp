import api from '../../../services/api';

// Streaming uses native fetch + ReadableStream because EventSource cannot send
// the Authorization header or a POST body. Non-streaming endpoints reuse the
// shared axios instance (which already injects the JWT).

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

function getToken() {
  return localStorage.getItem('token');
}

/**
 * POST /assistant/ask with stream:true and dispatch SSE events.
 * onEvent(eventName, data) is called for: meta | tool | token | done.
 * Throws an Error (with .status / .retryAfter) on non-OK responses.
 */
export async function streamAsk({ message, conversationId, editFromIndex, attachmentIds, signal, onEvent }) {
  const res = await fetch(`${API_BASE}/assistant/ask`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify({
      message,
      conversation_id: conversationId || null,
      stream: true,
      // Present only for edit-and-resend; truncates stored history server-side.
      ...(editFromIndex != null ? { edit_from_index: editFromIndex } : {}),
      // Previously-uploaded, fully-processed attachments to include as context.
      ...(attachmentIds && attachmentIds.length ? { attachment_ids: attachmentIds } : {}),
    }),
    signal,
  });

  if (!res.ok) {
    let detail = '';
    try {
      const body = await res.json();
      detail = body.detail || '';
    } catch {
      /* non-JSON error body */
    }
    const err = new Error(detail || `Request failed (${res.status})`);
    err.status = res.status;
    const retry = res.headers.get('Retry-After');
    if (retry) err.retryAfter = Number(retry);
    throw err;
  }

  // If streaming is disabled server-side (STREAMING_ENABLED=false), the backend
  // returns a JSON AskResponse instead of SSE. Adapt it to the same event flow.
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    const data = await res.json();
    const meta = data.meta || {};
    if (data.conversation_id) onEvent('meta', { conversation_id: data.conversation_id });
    if (data.answer) onEvent('token', { text: data.answer });
    onEvent('done', {
      conversation_id: data.conversation_id,
      sources: data.sources || [],
      attributions: meta.attributions || [],
      usage: meta.usage,
      cost: meta.cost,
      latency_ms: meta.latency_ms,
      title: meta.title,
    });
    return;
  }

  // Fallback if the environment doesn't expose a readable stream.
  if (!res.body || !res.body.getReader) {
    const text = await res.text();
    text.split('\n\n').forEach((frame) => dispatchFrame(frame, onEvent));
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    // Normalize CRLF that some proxies inject, then split into SSE frames.
    buffer += decoder.decode(value, { stream: true }).replace(/\r/g, '');
    let sep;
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      dispatchFrame(frame, onEvent);
    }
  }
  if (buffer.trim()) dispatchFrame(buffer, onEvent);
}

function dispatchFrame(frame, onEvent) {
  if (!frame.trim()) return;
  let event = 'message';
  const dataLines = [];
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return;
  let data;
  try {
    data = JSON.parse(dataLines.join('\n'));
  } catch {
    data = { raw: dataLines.join('\n') };
  }
  onEvent(event, data);
}

/** Non-streaming fallback. Returns { conversation_id, answer, sources, meta }. */
export async function askOnce({ message, conversationId, editFromIndex }) {
  const res = await api.post('/assistant/ask', {
    message,
    conversation_id: conversationId || null,
    stream: false,
    ...(editFromIndex != null ? { edit_from_index: editFromIndex } : {}),
  });
  return res.data;
}

// ── Conversation management (used in Milestone B) ──────────────────────────
export async function listConversations() {
  const res = await api.get('/assistant/conversations');
  return res.data.conversations || [];
}

export async function getConversation(id) {
  const res = await api.get(`/assistant/conversations/${id}`);
  return res.data;
}

export async function deleteConversation(id) {
  const res = await api.delete(`/assistant/conversations/${id}`);
  return res.data;
}

// ── Chat export (PDF) ───────────────────────────────────────────────────────

/**
 * Export a conversation as a PDF. Returns { blob, filename }.
 * The browser is responsible for triggering the actual download (see the hook).
 */
export async function exportConversationPdf(conversationId, userMessage) {
  const res = await api.post(
    `/assistant/conversations/${conversationId}/export-pdf`,
    userMessage ? { user_message: userMessage } : {},
    { responseType: 'blob' },
  );
  // Prefer the server-provided filename; fall back to a dated default.
  const disposition = res.headers['content-disposition'] || '';
  const match = /filename="?([^"]+)"?/.exec(disposition);
  // The server names the file using IST; this fallback uses the browser's local
  // date (not UTC) only if the header is missing/unparseable.
  const d = new Date();
  const localDate = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const filename = (match && match[1]) || `chat-conversation-${localDate}.pdf`;
  return { blob: res.data, filename };
}

// ── Multi-modal attachments ────────────────────────────────────────────────

/**
 * Upload a single file as multipart. Returns the stub { id, status, ... }.
 * onProgress(percent) is called during the upload (0–100).
 */
export async function uploadAttachment(file, conversationId, { onProgress, signal } = {}) {
  const form = new FormData();
  form.append('file', file);
  if (conversationId) form.append('conversation_id', conversationId);
  const res = await api.post('/assistant/attachments', form, {
    signal,
    // Bound the whole request so a slow/hung server can't leave the file stuck
    // at "100%" forever — the upload itself reports progress below, and the
    // server's stub reply normally comes back in well under a second.
    timeout: 120000,
    onUploadProgress: (e) => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100));
    },
  });
  return res.data;
}

/** Poll an attachment's processing status. Returns { id, status, summary, url, ... }. */
export async function getAttachment(id) {
  const res = await api.get(`/assistant/attachments/${id}`);
  return res.data;
}

/** Delete an attachment (doc + stored file + retrieval chunks). */
export async function deleteAttachment(id) {
  const res = await api.delete(`/assistant/attachments/${id}`);
  return res.data;
}

/** Re-run extraction for an attachment (retry processing). */
export async function analyzeAttachment(id) {
  const res = await api.post(`/assistant/attachments/${id}/analyze`);
  return res.data;
}

/** List the files attached to a conversation. */
export async function listConversationFiles(conversationId) {
  const res = await api.get(`/assistant/conversations/${conversationId}/files`);
  return res.data.files || [];
}
