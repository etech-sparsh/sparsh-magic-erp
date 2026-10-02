import { useCallback, useRef, useState } from 'react';
import {
  uploadAttachment,
  getAttachment,
  deleteAttachment,
  analyzeAttachment,
} from '../services/assistantApi';
import { kindOf } from '../utils/fileIcons';

// Client-side limits (kept in sync with backend AssistantConfig).
const MAX_FILES = 25;
const MAX_FILE_MB = 100;
const POLL_MS = 1500;
// Stop polling after this long so a stuck file never spins forever.
const MAX_POLL_MS = 3 * 60 * 1000; // 3 minutes

let _seq = 0;
const localId = () => `att-${Date.now()}-${_seq++}`;

/**
 * Owns the pending-attachment list for the composer. Each item:
 *   { localId, id, name, size, type, kind,
 *     status: 'uploading'|'processing'|'completed'|'failed',
 *     progress, url, error }
 * Files upload on add and are polled until completed/failed. `attachmentIds`
 * exposes the server ids of completed files for sending with a message.
 */
export default function useAttachments() {
  const [items, setItems] = useState([]);
  const pollers = useRef({}); // localId → timeout id

  const update = useCallback((lid, fields) => {
    setItems((list) =>
      list.map((it) => (it.localId === lid ? { ...it, ...(typeof fields === 'function' ? fields(it) : fields) } : it)),
    );
  }, []);

  const stopPoll = useCallback((lid) => {
    if (pollers.current[lid]) {
      clearTimeout(pollers.current[lid]);
      delete pollers.current[lid];
    }
  }, []);

  const poll = useCallback(
    (lid, serverId) => {
      const startedAt = Date.now();
      const tick = async () => {
        // Give up gracefully instead of spinning forever on a stuck file.
        if (Date.now() - startedAt > MAX_POLL_MS) {
          stopPoll(lid);
          update(lid, {
            status: 'failed',
            error: 'Taking too long to process — tap to retry.',
          });
          return;
        }
        try {
          const data = await getAttachment(serverId);
          if (data.status === 'completed') {
            stopPoll(lid);
            update(lid, { status: 'completed', summary: data.summary, url: data.url });
          } else if (data.status === 'failed') {
            stopPoll(lid);
            update(lid, { status: 'failed', error: data.error || 'Processing failed' });
          } else {
            pollers.current[lid] = setTimeout(tick, POLL_MS);
          }
        } catch {
          pollers.current[lid] = setTimeout(tick, POLL_MS * 2);
        }
      };
      pollers.current[lid] = setTimeout(tick, POLL_MS);
    },
    [stopPoll, update],
  );

  const startUpload = useCallback(
    async (lid, file, conversationId) => {
      try {
        const stub = await uploadAttachment(file, conversationId, {
          onProgress: (p) => update(lid, { progress: p }),
        });
        update(lid, { id: stub.id, status: 'processing', progress: 100 });
        poll(lid, stub.id);
      } catch (e) {
        // A hung/slow server trips the axios timeout (ECONNABORTED) — surface a
        // clear, retryable message instead of leaving the file stuck at 100%.
        const timedOut = e?.code === 'ECONNABORTED' || /timeout/i.test(e?.message || '');
        const detail = timedOut
          ? 'Upload timed out — tap to retry.'
          : e?.response?.data?.detail || 'Upload failed';
        update(lid, { status: 'failed', error: detail });
      }
    },
    [poll, update],
  );

  const addFiles = useCallback(
    (fileList, conversationId) => {
      const files = Array.from(fileList || []);
      setItems((list) => {
        const room = MAX_FILES - list.length;
        const accepted = files.slice(0, Math.max(0, room));
        const next = accepted.map((file) => {
          const lid = localId();
          const tooBig = file.size > MAX_FILE_MB * 1024 * 1024;
          const item = {
            localId: lid,
            id: null,
            name: file.name,
            size: file.size,
            type: file.type,
            kind: kindOf(file.name),
            status: tooBig ? 'failed' : 'uploading',
            progress: 0,
            url: null,
            error: tooBig ? `Exceeds ${MAX_FILE_MB} MB limit` : null,
            _file: file,
          };
          if (!tooBig) {
            // Defer the network call until after state commit.
            setTimeout(() => startUpload(lid, file, conversationId), 0);
          }
          return item;
        });
        return [...list, ...next];
      });
    },
    [startUpload],
  );

  const remove = useCallback(
    (lid) => {
      stopPoll(lid);
      setItems((list) => {
        const target = list.find((it) => it.localId === lid);
        if (target?.id) deleteAttachment(target.id).catch(() => {});
        return list.filter((it) => it.localId !== lid);
      });
    },
    [stopPoll],
  );

  const retry = useCallback(
    (lid, conversationId) => {
      const target = items.find((it) => it.localId === lid);
      if (!target) return;
      if (target.id) {
        // Already uploaded but processing failed — re-run extraction.
        update(lid, { status: 'processing', error: null });
        analyzeAttachment(target.id).then(() => poll(lid, target.id)).catch(() =>
          update(lid, { status: 'failed', error: 'Retry failed' }),
        );
      } else if (target._file) {
        update(lid, { status: 'uploading', progress: 0, error: null });
        startUpload(lid, target._file, conversationId);
      }
    },
    [items, poll, startUpload, update],
  );

  const clear = useCallback(() => {
    Object.keys(pollers.current).forEach(stopPoll);
    setItems([]);
  }, [stopPoll]);

  const completedIds = items.filter((it) => it.status === 'completed' && it.id).map((it) => it.id);
  const hasPending = items.some((it) => it.status === 'uploading' || it.status === 'processing');

  return {
    items,
    addFiles,
    remove,
    retry,
    clear,
    completedIds,
    hasPending,
    // Compact metas for optimistic rendering on the sent message bubble.
    metas: items
      .filter((it) => it.status === 'completed' && it.id)
      .map((it) => ({ id: it.id, filename: it.name, size: it.size, kind: it.kind, mime_type: it.type })),
  };
}
