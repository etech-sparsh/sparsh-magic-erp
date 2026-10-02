import React from 'react';
import { Repeat, CalendarClock, Flag, AlertTriangle } from 'lucide-react';
import { formatDate, formatRecurrenceRule } from './taskDisplayUtils';

// The "recurring task detail" strip under a series row: the repeat rule, how far through the
// series the doer is, which occurrence is next, and when the series runs out. A recurring task
// is only meaningful as a series — a single occurrence's due date says nothing about whether
// the routine is being kept — so these numbers come from summarizeSeries over the whole group.

// Takes a rendered icon element rather than the component, so each call site keeps its own
// sizing and the icon stays a plain JSX child.
const Chip = ({ icon, children, tone }) => (
  <span
    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-black uppercase tracking-wider border whitespace-nowrap"
    style={{
      background: tone?.bg || 'var(--input-bg)',
      color: tone?.color || 'var(--text-muted)',
      borderColor: tone?.border || 'var(--border)',
    }}
  >
    {icon} {children}
  </span>
);

const RecurrenceDetail = ({ task, series, showProgress = true, showNextDue = true, showEnds = true }) => {
  if (!series || !series.total) return null;
  const { total, done, overdue, nextDue, seriesEnd, percent } = series;
  const complete = done === total;
  const barColor = complete ? 'var(--accent-green)' : overdue ? 'var(--accent-red)' : 'var(--accent-indigo)';

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
      <Chip
        icon={<Repeat size={10} />}
        tone={{ bg: 'var(--accent-indigo-bg)', color: 'var(--accent-indigo)', border: 'var(--accent-indigo-border)' }}
      >
        {formatRecurrenceRule(task)}
      </Chip>

      {/* Occurrence progress — only meaningful once the series has more than one document.
          Skipped when the caller already renders its own progress bar (the list view's
          dedicated Progress column), so the count isn't shown twice on one row. */}
      {showProgress && total > 1 && (
        <span className="inline-flex items-center gap-1.5">
          <span className="w-16 h-1.5 rounded-full overflow-hidden bg-[var(--input-bg)] border border-[var(--border)]">
            <span className="block h-full rounded-full transition-all" style={{ width: `${percent}%`, background: barColor }} />
          </span>
          <span className="text-[9px] font-black uppercase tracking-wider" style={{ color: barColor }}>
            {done}/{total} done
          </span>
        </span>
      )}

      {overdue > 0 && (
        <Chip
          icon={<AlertTriangle size={10} />}
          tone={{ bg: 'var(--accent-red-bg)', color: 'var(--accent-red)', border: 'var(--accent-red-border)' }}
        >
          {overdue} overdue
        </Chip>
      )}

      {showNextDue && nextDue && !complete && (
        <Chip icon={<CalendarClock size={10} />}>Next {formatDate(nextDue)}</Chip>
      )}

      {/* A one-occurrence series' end date IS its next due date — showing both would just read
          "Next 12/09 · Ends 12/09". Also skipped when the caller already shows the end date
          itself (the list view's Due Date column, or the card's own date badge), so it isn't
          shown twice. */}
      {showEnds && seriesEnd && formatDate(seriesEnd) !== formatDate(nextDue) && (
        <Chip icon={<Flag size={10} />}>Ends {formatDate(seriesEnd)}</Chip>
      )}
    </div>
  );
};

export default RecurrenceDetail;
