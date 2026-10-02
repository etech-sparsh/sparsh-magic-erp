import React from 'react';

/**
 * HRMS ▸ the tab strip inside a board.
 *
 * Attendance, Leave, Payroll and Movements each hold several sub-screens of one job —
 * "Payroll Runs / Salary Structure / Salary Advance / Variable Pay" are all payroll, so
 * they are tabs on one board rather than four sidebar entries. Each of those four boards
 * had hand-rolled a byte-identical strip of its own, which is four chances to drift.
 *
 * -- Why pills, not underlines -------------------------------------------------------
 * The hand-rolled copies drew underline tabs while the module's workspace strip
 * (common/HrmsWorkspaceBar) draws pills. Same idea — "these are the screens of this job,
 * you are on this one" — rendered two different ways on adjacent pages, so HRMS read as
 * two products stitched together. One idea gets one shape, and the workspace strip is the
 * one people meet first and most often, so it wins.
 *
 * Purely local state: a tab here selects a panel on the page it is already on. Nothing is
 * routed, so nothing is deep-linkable — that is the existing behaviour of all four boards
 * and changing it is a separate decision about URLs, not about how a tab looks.
 */
const BoardTabs = ({ tabs, value, onChange, label = 'Sections' }) => (
  <div
    role="tablist"
    aria-label={label}
    className="flex flex-wrap items-center gap-1 p-1 rounded-xl
      border border-[var(--border)] bg-[var(--bg-card)]"
  >
    {tabs.map((t) => {
      // A plain string stays a plain string, so no caller has to restate what it already
      // says; an object adds a count or an icon when the board has one worth showing.
      const key = typeof t === 'string' ? t : t.key;
      const text = typeof t === 'string' ? t : (t.label ?? t.key);
      const Icon = typeof t === 'string' ? null : t.icon;
      const count = typeof t === 'string' ? null : t.count;
      const active = value === key;

      return (
        <button
          key={key}
          type="button"
          role="tab"
          aria-selected={active}
          onClick={() => onChange(key)}
          className={`shrink-0 h-8 px-3.5 rounded-lg flex items-center gap-1.5
            text-[12px] font-bold tracking-tight transition-colors whitespace-nowrap
            ${active
              ? 'bg-[var(--accent-indigo)] text-white shadow-sm'
              : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)]'}`}
        >
          {Icon && <Icon size={13} />}
          {text}
          {count != null && (
            <span className={`ml-0.5 px-1.5 rounded-full text-[10.5px] tabular-nums ${
              active
                ? 'bg-white/20 text-white'
                : 'bg-[var(--input-bg)] text-[var(--text-muted)]'}`}>
              {count}
            </span>
          )}
        </button>
      );
    })}
  </div>
);

export default BoardTabs;
