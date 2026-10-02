import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bot, User, AlertCircle, Copy, Check, Pencil } from 'lucide-react';
import SourceList from './SourceList';
import MessageAttachments from './MessageAttachments';
import PdfDownloadCard from './PdfDownloadCard';

// Custom renderers for the assistant's markdown.
//  - Links open in a new tab (rel guards against reverse-tabnabbing/referrer leak).
//  - GFM tables (parsed by remark-gfm) get explicit borders, padding, cell text
//    wrapping, and a horizontal-scroll wrapper so wide tables never overflow the
//    chat bubble on desktop or mobile.
const markdownComponents = {
  a: (props) => <a {...props} target="_blank" rel="noopener noreferrer" />,
  table: (props) => (
    <div className="my-2 max-w-full overflow-x-auto rounded-lg border border-[var(--border)]">
      <table className="w-full border-collapse text-left text-xs" {...props} />
    </div>
  ),
  thead: (props) => <thead className="bg-[var(--bg-card)]" {...props} />,
  tr: (props) => <tr className="border-b border-[var(--border)] last:border-0" {...props} />,
  th: (props) => (
    <th
      className="min-w-[110px] whitespace-normal break-words border-r border-[var(--border)] px-3 py-2 align-top font-semibold text-[var(--text-main)] last:border-r-0"
      {...props}
    />
  ),
  td: (props) => (
    <td
      className="min-w-[110px] max-w-[280px] whitespace-normal break-words border-r border-[var(--border)] px-3 py-2 align-top text-[var(--text-main)] last:border-r-0"
      {...props}
    />
  ),
};

/**
 * A single chat message. Assistant content is rendered as markdown; user content
 * is plain text. User messages can be copied and edited (which resends the turn);
 * assistant messages can be copied. Assistant messages also show source chips.
 */
export default function MessageBubble({ message, onEdit, onDownloadPdf, disabled }) {
  const isUser = message.role === 'user';
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content || '');
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked (e.g. insecure context); ignore */
    }
  };

  const startEdit = () => {
    setDraft(message.content);
    setEditing(true);
  };

  const cancelEdit = () => setEditing(false);

  const saveEdit = () => {
    const text = draft.trim();
    if (!text || text === message.content) {
      setEditing(false);
      return;
    }
    setEditing(false);
    onEdit?.(message.id, text);
  };

  const onEditKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      saveEdit();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      cancelEdit();
    }
  };

  const canCopy = Boolean(message.content) && !message.streaming;
  const canEdit = isUser && !message.streaming && typeof onEdit === 'function';

  const hasAttachments = Array.isArray(message.attachments) && message.attachments.length > 0;

  return (
    <div className="group flex flex-col">
      {hasAttachments && (
        <div className={isUser ? 'pr-9' : 'pl-9'}>
          <MessageAttachments attachments={message.attachments} isUser={isUser} />
        </div>
      )}
      <div className={`flex gap-2.5 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
        <div
          className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
            isUser ? 'bg-[var(--accent-indigo)] text-white' : 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
          }`}
        >
          {isUser ? <User size={15} /> : <Bot size={15} />}
        </div>

        {isUser && !message.content && hasAttachments ? (
          // Attachment-only message: chips already render above; skip empty bubble.
          <span className="sr-only">Sent attachments</span>
        ) : editing ? (
          <div className="flex max-w-[82%] flex-1 flex-col gap-2">
            <textarea
              autoFocus
              rows={2}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onEditKeyDown}
              className="w-full resize-none rounded-2xl border border-[var(--input-border)] bg-[var(--input-bg)] px-3.5 py-2 text-sm text-[var(--text-main)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-indigo)]"
            />
            <div className="flex justify-end gap-2">
              <button
                onClick={cancelEdit}
                className="rounded-lg px-2.5 py-1 text-xs text-[var(--text-muted)] hover:bg-[var(--bg-main)] hover:text-[var(--text-main)]"
              >
                Cancel
              </button>
              <button
                onClick={saveEdit}
                disabled={disabled || !draft.trim()}
                className="rounded-lg bg-[var(--accent-indigo)] px-2.5 py-1 text-xs text-white hover:opacity-90 disabled:opacity-40"
              >
                Save &amp; send
              </button>
            </div>
          </div>
        ) : (
          <div
            className={`max-w-[82%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed ${
              isUser
                ? 'bg-[var(--accent-indigo)] text-white'
                : message.errored
                  ? 'bg-[var(--accent-red-bg)] text-[var(--text-main)] border border-[var(--accent-red-border)]'
                  : 'bg-[var(--bg-main)] text-[var(--text-main)] border border-[var(--border)]'
            }`}
          >
            {isUser ? (
              <span className="whitespace-pre-wrap break-words">{message.content}</span>
            ) : message.errored && !message.content ? (
              <span className="flex items-center gap-1.5 text-[var(--accent-red)]">
                <AlertCircle size={14} /> Couldn’t complete that. Please try again.
              </span>
            ) : (
              <div className="prose prose-sm max-w-none break-words dark:prose-invert prose-p:my-1.5 prose-headings:my-2 prose-ul:my-1.5 prose-li:my-0.5">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                  {message.content || ''}
                </ReactMarkdown>
              </div>
            )}
          </div>
        )}
      </div>

      {/* PDF export (in-chat download) */}
      {!isUser && (message.pdfPending || message.pdf || message.pdfReload) && (
        <div className="pl-9">
          <PdfDownloadCard
            pending={message.pdfPending}
            pdf={message.pdf}
            onDownload={message.pdfReload && !message.pdf ? onDownloadPdf : undefined}
          />
        </div>
      )}

      {/* Hover actions */}
      {!editing && (canCopy || canEdit) && (
        <div
          className={`mt-1 flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 ${
            isUser ? 'flex-row-reverse pr-9' : 'pl-9'
          }`}
        >
          {canCopy && (
            <button
              onClick={copy}
              title={copied ? 'Copied' : 'Copy'}
              className="flex h-6 w-6 items-center justify-center rounded-md text-[var(--text-muted)] hover:bg-[var(--bg-main)] hover:text-[var(--text-main)]"
            >
              {copied ? <Check size={13} /> : <Copy size={13} />}
            </button>
          )}
          {canEdit && (
            <button
              onClick={startEdit}
              disabled={disabled}
              title="Edit"
              className="flex h-6 w-6 items-center justify-center rounded-md text-[var(--text-muted)] hover:bg-[var(--bg-main)] hover:text-[var(--text-main)] disabled:opacity-40"
            >
              <Pencil size={13} />
            </button>
          )}
        </div>
      )}

      {!isUser && !message.streaming && <SourceList sources={message.sources} />}
    </div>
  );
}
