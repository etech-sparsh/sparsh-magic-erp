import React from 'react';
import { CalendarDays, Users, ChevronRight } from 'lucide-react';

// Top-level split shown on every task list: a repeating series ("Daily report", tracked
// occurrence by occurrence) and a one-off delegation are different kinds of work and were
// previously interleaved in one flat list. These two banner cards separate them, and the
// counts stay visible on the inactive card so nothing looks lost.
//
// Module-local: exporting a non-component alongside the component breaks Fast Refresh
// (react-refresh/only-export-components), and nothing outside this file needs it.
const TASK_KINDS = [
  { key: 'recurring', label: 'Recurring Tasks', icon: CalendarDays },
  { key: 'onetime', label: 'Delegated Tasks', icon: Users },
];

// The same two tabs sit on every task page, so the sub-line has to say whose tasks these are —
// "assigned to you" is wrong on Delegated Tasks, and "you assigned" is wrong on My Tasks.
const HINTS = {
  my: {
    recurring: 'Stay on top of your recurring tasks and never miss a deadline.',
    onetime: 'One-time tasks assigned to you by others.',
  },
  delegated: {
    recurring: 'Recurring series you assigned to other people.',
    onetime: 'One-time tasks you assigned to other people.',
  },
  subscribed: {
    recurring: 'Recurring series you are kept in the loop on.',
    onetime: 'One-time tasks you are kept in the loop on.',
  },
  deleted: {
    recurring: 'Deleted recurring series — restore or leave archived.',
    onetime: 'Deleted one-time tasks — restore or leave archived.',
  },
  all: {
    recurring: 'Every recurring series across the organization.',
    onetime: 'Every one-time task across the organization.',
  },
};

const hintFor = (scope, key) => (HINTS[scope] || HINTS.all)[key];

const TaskKindTabs = ({ value, onChange, counts = {}, scope = 'all' }) => (
  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
    {TASK_KINDS.map(kind => {
      const Icon = kind.icon;
      const isActive = value === kind.key;
      return (
        <button
          key={kind.key}
          type="button"
          onClick={() => onChange(kind.key)}
          className={`group flex items-center gap-4 text-left px-5 py-4 rounded-[20px] border transition-all ${
            isActive ? 'shadow-sm' : 'hover:shadow-sm hover:-translate-y-0.5'
          }`}
          style={{
            background: isActive ? 'var(--accent-indigo-bg)' : 'var(--bg-card)',
            borderColor: isActive ? 'var(--accent-indigo-border)' : 'var(--border)',
          }}
        >
          <span
            className="w-11 h-11 rounded-2xl flex items-center justify-center shrink-0 transition-colors"
            style={{
              background: isActive ? 'var(--accent-indigo)' : 'var(--input-bg)',
              color: isActive ? '#fff' : 'var(--text-muted)',
              boxShadow: isActive ? '0 6px 16px -6px var(--accent-indigo)' : 'none',
            }}
          >
            <Icon size={20} />
          </span>

          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-2">
              <span
                className="text-[13px] font-black uppercase tracking-wider truncate"
                style={{ color: isActive ? 'var(--accent-indigo)' : 'var(--text-main)' }}
              >
                {kind.label}
              </span>
              <span
                className="min-w-[20px] px-1.5 py-0.5 rounded-md text-[10px] font-black text-center shrink-0"
                style={{
                  background: isActive ? 'var(--accent-indigo)' : 'var(--input-bg)',
                  color: isActive ? '#fff' : 'var(--text-muted)',
                }}
              >
                {counts[kind.key] ?? 0}
              </span>
            </span>
            <span className="block text-[11px] font-bold text-[var(--text-muted)] truncate mt-1">
              {hintFor(scope, kind.key)}
            </span>
          </span>

          <ChevronRight
            size={18}
            className="shrink-0 transition-transform group-hover:translate-x-0.5"
            style={{ color: isActive ? 'var(--accent-indigo)' : 'var(--text-muted)' }}
          />
        </button>
      );
    })}
  </div>
);

export default TaskKindTabs;
