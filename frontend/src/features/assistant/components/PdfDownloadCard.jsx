import React, { useState } from 'react';
import { FileText, Download, Loader2, AlertCircle } from 'lucide-react';

const CARD_CLASS =
  'mt-2 inline-flex items-center gap-2 rounded-xl border border-[var(--accent-indigo-border,var(--border))] bg-[var(--accent-indigo-bg)] px-3 py-2 text-xs font-medium text-[var(--accent-indigo)] transition-opacity hover:opacity-90';

/**
 * Renders the in-chat PDF export state for an assistant message:
 *  - `pending`           → "Generating PDF…" with a spinner
 *  - `pdf={url,name}`    → a "Download PDF" link (fresh export; uses the blob URL)
 *  - `onDownload`        → a "Download PDF" button that re-fetches the file
 *                          (used for export turns restored after a page reload,
 *                          whose original blob URL no longer exists)
 *
 * Self-contained so it can be dropped into any message bubble.
 */
export default function PdfDownloadCard({ pending, pdf, onDownload }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  if (pending) {
    return (
      <div className="mt-2 flex items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--bg-main)] px-3 py-2 text-xs text-[var(--text-muted)]">
        <Loader2 size={14} className="animate-spin" />
        <span>Preparing your file…</span>
      </div>
    );
  }

  // Fresh export — download straight from the in-memory blob URL.
  if (pdf?.url) {
    return (
      <a href={pdf.url} download={pdf.filename || 'chat-conversation.pdf'} className={CARD_CLASS}>
        <FileText size={15} className="shrink-0" />
        <span className="max-w-[180px] truncate">{pdf.filename || 'chat-conversation.pdf'}</span>
        <Download size={14} className="shrink-0" />
      </a>
    );
  }

  // Restored-after-reload export — re-fetch the PDF on click.
  if (onDownload) {
    const handleClick = async () => {
      if (busy) return;
      setBusy(true);
      setFailed(false);
      const ok = await onDownload();
      setBusy(false);
      if (!ok) setFailed(true);
    };
    return (
      <button type="button" onClick={handleClick} disabled={busy} className={CARD_CLASS}>
        {busy ? (
          <Loader2 size={15} className="shrink-0 animate-spin" />
        ) : failed ? (
          <AlertCircle size={15} className="shrink-0" />
        ) : (
          <FileText size={15} className="shrink-0" />
        )}
        <span className="max-w-[180px] truncate">
          {busy ? 'Preparing…' : failed ? 'Failed — retry' : 'Download PDF'}
        </span>
        {!busy && <Download size={14} className="shrink-0" />}
      </button>
    );
  }

  return null;
}
