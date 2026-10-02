import React from 'react';
import { X, RotateCw, AlertCircle, Loader2, Check } from 'lucide-react';
import { iconForFile, formatSize } from '../utils/fileIcons';

/**
 * Preview strip shown above the composer for files being attached to the next
 * message. Renders each file's icon, name, size, upload/processing status, and
 * remove / retry controls.
 */
export default function AttachmentPreview({ items, onRemove, onRetry }) {
  if (!items || items.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 px-2.5 pt-2.5">
      {items.map((it) => {
        const Icon = iconForFile(it.kind || it.name);
        const failed = it.status === 'failed';
        return (
          <div
            key={it.localId}
            title={failed ? it.error : it.name}
            className={`group relative flex max-w-[200px] items-center gap-2 rounded-xl border px-2.5 py-1.5 ${
              failed
                ? 'border-[var(--accent-red-border)] bg-[var(--accent-red-bg)]'
                : 'border-[var(--border)] bg-[var(--bg-main)]'
            }`}
          >
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
              {failed ? (
                <AlertCircle size={15} className="text-[var(--accent-red)]" />
              ) : (
                <Icon size={15} />
              )}
            </div>
            <div className="min-w-0 flex-1 leading-tight">
              <p className="truncate text-xs font-medium text-[var(--text-main)]">{it.name}</p>
              <p className="flex items-center gap-1 text-[10px] text-[var(--text-muted)]">
                {it.status === 'uploading' && (
                  <>
                    <Loader2 size={10} className="animate-spin" /> {it.progress || 0}%
                  </>
                )}
                {it.status === 'processing' && (
                  <>
                    <Loader2 size={10} className="animate-spin" /> Processing…
                  </>
                )}
                {it.status === 'completed' && (
                  <>
                    <Check size={10} className="text-emerald-500" /> {formatSize(it.size)}
                  </>
                )}
                {failed && <span className="text-[var(--accent-red)]">{it.error || 'Failed'}</span>}
              </p>
            </div>
            {failed && onRetry && (
              <button
                type="button"
                onClick={() => onRetry(it.localId)}
                title="Retry"
                className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[var(--text-muted)] hover:text-[var(--text-main)]"
              >
                <RotateCw size={12} />
              </button>
            )}
            <button
              type="button"
              onClick={() => onRemove(it.localId)}
              title="Remove"
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[var(--text-muted)] hover:bg-[var(--bg-card)] hover:text-[var(--text-main)]"
            >
              <X size={12} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
