import React from 'react';
import { Plus, Trash2, MessageSquare, X } from 'lucide-react';

// Backend sends naive UTC timestamps (no 'Z'/offset). Browsers parse those as
// local time, skewing every entry by the user's UTC offset (e.g. +5:30 made
// recent chats read "5h ago"). Treat a tz-less string as UTC.
function parseUtc(iso) {
  if (typeof iso === 'string' && !/[zZ]|[+-]\d{2}:?\d{2}$/.test(iso)) {
    return new Date(`${iso}Z`).getTime();
  }
  return new Date(iso).getTime();
}

function relativeTime(iso) {
  if (!iso) return '';
  const then = parseUtc(iso);
  if (Number.isNaN(then)) return '';
  const diff = Math.max(0, Date.now() - then);
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return days < 7 ? `${days}d ago` : new Date(then).toLocaleDateString();
}

function Skeleton() {
  return (
    <div className="flex flex-col gap-1.5 px-2 py-2">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="animate-pulse rounded-lg bg-[var(--bg-main)] px-2.5 py-2">
          <div className="h-2.5 w-3/4 rounded bg-[var(--border)]" />
          <div className="mt-1.5 h-2 w-1/3 rounded bg-[var(--border)]" />
        </div>
      ))}
    </div>
  );
}

export default function ConversationSidebar({
  conversations,
  loading,
  activeId,
  onSelect,
  onNew,
  onDelete,
  onClose,
}) {
  return (
    <div className="flex h-full w-full flex-col bg-[var(--bg-card)]">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--border)] px-3 py-2.5">
        <span className="text-xs font-semibold text-[var(--text-main)]">Conversations</span>
        <button
          onClick={onClose}
          title="Close"
          className="flex h-6 w-6 items-center justify-center rounded-md text-[var(--text-muted)] hover:bg-[var(--bg-main)] md:hidden"
        >
          <X size={14} />
        </button>
      </div>

      {/* New chat */}
      <div className="px-2 pt-2">
        <button
          onClick={onNew}
          className="flex w-full items-center gap-2 rounded-xl bg-[var(--accent-indigo)] px-3 py-2 text-xs font-medium text-white transition hover:opacity-90"
        >
          <Plus size={14} /> New chat
        </button>
      </div>

      {/* List */}
      <div className="min-h-0 flex-1 overflow-y-auto no-scrollbar">
        {loading && conversations.length === 0 ? (
          <Skeleton />
        ) : conversations.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-1 px-4 py-10 text-center">
            <MessageSquare size={18} className="text-[var(--text-muted)]" />
            <p className="text-xs text-[var(--text-muted)]">No conversations yet</p>
          </div>
        ) : (
          <div className="flex flex-col gap-0.5 px-2 py-2">
            {conversations.map((c) => (
              <div
                key={c.id}
                className={`group flex items-center gap-1 rounded-lg px-2.5 py-2 transition ${
                  c.id === activeId
                    ? 'bg-[var(--accent-indigo-bg)]'
                    : 'hover:bg-[var(--bg-main)]'
                }`}
              >
                <button
                  onClick={() => onSelect(c.id)}
                  className="min-w-0 flex-1 text-left"
                  title={c.title}
                >
                  <p className="truncate text-xs font-medium text-[var(--text-main)]">
                    {c.title || 'New conversation'}
                  </p>
                  <p className="text-[10px] text-[var(--text-muted)]">{relativeTime(c.updated_at)}</p>
                </button>
                <button
                  onClick={() => onDelete(c.id)}
                  title="Delete"
                  className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[var(--text-muted)] opacity-0 transition hover:text-[var(--accent-red)] group-hover:opacity-100"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
