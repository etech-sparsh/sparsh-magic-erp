import React, { useState } from 'react';
import { Download } from 'lucide-react';
import { iconForFile, formatSize } from '../utils/fileIcons';
import { getAttachment } from '../services/assistantApi';

/**
 * File chips rendered inside a message bubble for any attachments sent with that
 * turn. Signed/download URLs expire, so we fetch a fresh one lazily on download.
 */
export default function MessageAttachments({ attachments, isUser }) {
  if (!attachments || attachments.length === 0) return null;

  return (
    <div className={`mb-1.5 flex flex-wrap gap-2 ${isUser ? 'justify-end' : ''}`}>
      {attachments.map((a) => (
        <AttachmentChip key={a.id || a.filename} attachment={a} />
      ))}
    </div>
  );
}

function AttachmentChip({ attachment }) {
  const [busy, setBusy] = useState(false);
  const Icon = iconForFile(attachment.kind || attachment.filename);

  const download = async () => {
    if (!attachment.id || busy) return;
    setBusy(true);
    try {
      const fresh = await getAttachment(attachment.id);
      if (fresh.url) {
        const href = fresh.url.startsWith('http') ? fresh.url : `${window.location.origin}${fresh.url}`;
        window.open(href, '_blank', 'noopener,noreferrer');
      }
    } catch {
      /* ignore — file may have been deleted */
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex max-w-[220px] items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-2.5 py-1.5">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
        <Icon size={15} />
      </div>
      <div className="min-w-0 flex-1 leading-tight">
        <p className="truncate text-xs font-medium text-[var(--text-main)]">{attachment.filename}</p>
        {attachment.size != null && (
          <p className="text-[10px] text-[var(--text-muted)]">{formatSize(attachment.size)}</p>
        )}
      </div>
      {attachment.id && (
        <button
          type="button"
          onClick={download}
          disabled={busy}
          title="Download"
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[var(--text-muted)] hover:bg-[var(--bg-main)] hover:text-[var(--text-main)] disabled:opacity-40"
        >
          <Download size={13} />
        </button>
      )}
    </div>
  );
}
