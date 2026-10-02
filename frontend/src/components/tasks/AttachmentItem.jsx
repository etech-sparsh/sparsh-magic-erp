import React, { useState } from 'react';
import { Paperclip, X, Eye } from 'lucide-react';
import { getAttachmentKind } from './taskDisplayUtils';

// Renders a single task attachment with an inline preview appropriate to its type:
//  • audio  → player
//  • image  → thumbnail
//  • pdf    → a "Preview" toggle that embeds the document inline (iframe)
//  • other document (docx/xlsx/…) → a "Preview" button that opens it in a new tab
// Shared by the assignment-attachments and completion-evidence lists so both behave the same.
const AttachmentItem = ({
  attachment,
  onRemove,
  icon: Icon = Paperclip,
  iconClass = 'text-[var(--text-muted)]',
  linkHover = 'hover:text-[var(--accent-indigo)]',
}) => {
  const [showPreview, setShowPreview] = useState(false);
  const kind = getAttachmentKind(attachment.name);
  const isDoc = kind === 'pdf' || kind === 'other';

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl px-3 py-2">
      <div className="flex items-center gap-2">
        <a href={attachment.url} target="_blank" rel="noreferrer"
          className={`flex items-center gap-2 flex-1 min-w-0 text-[11px] font-bold text-[var(--text-main)] ${linkHover}`}>
          {React.createElement(Icon, { size: 12, className: `${iconClass} shrink-0` })}
          <span className="truncate">{attachment.name}</span>
        </a>
        {/* Preview option for documents: PDFs preview inline on click; other docs open in a new tab. */}
        {isDoc && (kind === 'pdf' ? (
          <button type="button" onClick={() => setShowPreview(v => !v)}
            className="flex items-center gap-1 px-2 py-0.5 rounded-lg text-[9px] font-black uppercase tracking-wider border bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)] hover:opacity-90 shrink-0">
            <Eye size={11} /> {showPreview ? 'Hide' : 'Preview'}
          </button>
        ) : (
          <a href={attachment.url} target="_blank" rel="noreferrer"
            className="flex items-center gap-1 px-2 py-0.5 rounded-lg text-[9px] font-black uppercase tracking-wider border bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border-[var(--accent-indigo-border)] hover:opacity-90 shrink-0">
            <Eye size={11} /> Preview
          </a>
        ))}
        {onRemove && (
          <button type="button" onClick={onRemove} className="text-[var(--text-muted)] hover:text-[var(--accent-red)] shrink-0"><X size={13} /></button>
        )}
      </div>

      {kind === 'audio' && <audio className="mt-2 w-full h-9" controls src={attachment.url} />}
      {kind === 'image' && (
        <a href={attachment.url} target="_blank" rel="noreferrer">
          <img src={attachment.url} alt={attachment.name} className="mt-2 max-h-40 rounded-lg border border-[var(--border)]" />
        </a>
      )}
      {kind === 'pdf' && showPreview && (
        <iframe title={attachment.name} src={attachment.url}
          className="mt-2 w-full h-96 rounded-lg border border-[var(--border)] bg-white" />
      )}
    </div>
  );
};

export default AttachmentItem;
