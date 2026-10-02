import React from 'react';
import { motion } from 'framer-motion';
import { CalendarDays, Repeat, ChevronDown, Check, Eye } from 'lucide-react';
import { STATUS_CONFIG } from './statusConfig';
import {
  getInitials, formatRelativeTime, formatFrequencyLabel, formatDate, formatOccurrenceDate,
} from './taskDisplayUtils';
import { CategoryPill, PriorityPill } from './taskCells';
import RecurrenceDetail from './RecurrenceDetail';

// One task as a CARD, for the grid view.
//
// The grid toggle used to render the same full-width rows the table does, just without the
// column headers — which is why it still read as a table. A card has to stack: identity on
// top, the status control as the card's main action, and the metadata as a footer. That is
// what makes a multi-column layout scannable rather than just narrower.
const TaskCard = ({
  task, scope, userMap, checked, onToggleSelect, onOpenDetails, statusCell,
  series, group, isExpanded, onToggleExpand, onOccurrenceOpen, actions,
}) => {
  const counterpart = scope === 'delegated'
    ? `To: ${(task.assignedTo || []).map(id => userMap[id] || id).join(', ') || '—'}`
    : `From: ${userMap[task.assignedBy] || 'Someone'}`;
  const occurrences = group?.items || [];
  const isSeries = occurrences.length > 1;

  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
      className="group relative flex flex-col bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl overflow-hidden hover:shadow-md hover:border-[var(--accent-indigo-border)] transition-all">
      {/* Overdue spine, same signal the table row carries. */}
      {task.isOverdue && (
        <span className="absolute left-0 top-0 bottom-0 w-[3px]" style={{ background: 'var(--accent-red)' }} />
      )}

      <div className="flex items-start gap-2.5 px-4 pt-3.5 pb-2">
        {scope !== 'deleted' && (
          <input type="checkbox" checked={checked} onChange={onToggleSelect} className="mt-1 shrink-0" />
        )}
        <span className="w-9 h-9 rounded-full flex items-center justify-center text-white font-black text-[11px] shrink-0"
          style={{ background: 'var(--avatar-bg)' }}>
          {getInitials(userMap[task.assignedBy] || task.title)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-bold text-[var(--text-muted)] truncate">{counterpart}</p>
          <button type="button" onClick={onOpenDetails}
            className="block w-full text-left text-[13px] font-black text-[var(--text-main)] leading-snug line-clamp-2 hover:text-[var(--accent-indigo)] transition-colors">
            {task.title}
          </button>
        </div>
        <span className="shrink-0">{actions}</span>
      </div>

      {/* Recurring tab: the repeat rule + how far through the series this doer is. Same
          component the list rows used, so the two views state a series identically. Next-due
          and Ends are suppressed here — the footer badge below already carries the series' end
          date (see its own comment), so both chips would just repeat it. */}
      {series && (
        <div className="px-4 pb-2">
          <RecurrenceDetail task={task} series={series} showNextDue={false} showEnds={false} />
        </div>
      )}

      {(task.tags || []).length > 0 && (
        <div className="px-4 pb-2 flex flex-wrap gap-1">
          {task.tags.slice(0, 3).map(tag => (
            <span key={tag} className="px-2 py-0.5 rounded-full text-[8px] font-black uppercase tracking-wider bg-[var(--accent-green-bg)] text-[var(--accent-green)] border border-[var(--accent-green-border)]">
              {tag}
            </span>
          ))}
          {task.tags.length > 3 && (
            <span className="text-[9px] font-bold text-[var(--text-muted)] self-center">+{task.tags.length - 3}</span>
          )}
        </div>
      )}

      {/* The status control is the card's primary action, so it gets its own full-width band. */}
      <div className="px-4 pb-2.5">{statusCell}</div>

      {/* No tinted band here: the pills inside it are already neutral, and grey-on-grey just
          flattened them. A hairline rule separates the metadata from the action above it. */}
      <div className="mt-auto px-4 py-2.5 border-t border-[var(--border)] flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <CategoryPill name={task.category} />
        <PriorityPill priority={task.priority} />
        {/* Recurring tab: this card stands for the whole series, so this badge shows when the
            CHECKLIST itself ends (series.seriesEnd), not just the one occurrence happening to
            be primary right now — same substitution the list view's Due Date column makes. */}
        {(series ? series.seriesEnd : task.end) && (
          <span className={`inline-flex items-center gap-1 text-[10px] font-bold whitespace-nowrap ${!series && task.isOverdue ? 'text-[var(--accent-red)]' : 'text-[var(--text-muted)]'}`}>
            <CalendarDays size={11} /> {formatDate(series ? series.seriesEnd : task.end)}
          </span>
        )}
        {!series && (
          <span className="text-[9px] font-black uppercase tracking-wider text-[var(--text-muted)]">
            {formatFrequencyLabel(task.frequency)}
          </span>
        )}
        <span className="ml-auto text-[10px] font-bold text-[var(--text-muted)] opacity-70 whitespace-nowrap">
          {formatRelativeTime(task.end || task.start)}
        </span>
      </div>

      {/* A series expands INSIDE its own card — in a grid there is no row beneath to open
          into, so the occurrences have to live in the tile that owns them. */}
      {isSeries && (
        <>
          <button type="button" onClick={onToggleExpand}
            className="flex items-center justify-center gap-1.5 px-4 py-2 text-[10px] font-black uppercase tracking-wider text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border-t border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity">
            <Repeat size={11} /> {isExpanded ? 'Hide' : `Show all ${occurrences.length}`} occurrences
            <ChevronDown size={12} className={`transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
          </button>
          {isExpanded && (
            <div className="divide-y divide-[var(--border)] border-t border-[var(--border)] max-h-56 overflow-y-auto no-scrollbar">
              {occurrences.map((child, i) => {
                const done = child.status === 'completed';
                const cfg = STATUS_CONFIG[child.status] || STATUS_CONFIG.pending;
                const tone = done
                  ? { bg: 'var(--accent-green-bg)', color: 'var(--accent-green)', border: 'var(--accent-green-border)' }
                  : child.isOverdue
                    ? { bg: 'var(--accent-red-bg)', color: 'var(--accent-red)', border: 'var(--accent-red-border)' }
                    : { bg: 'var(--input-bg)', color: 'var(--text-muted)', border: 'var(--border)' };
                return (
                  <button type="button" key={child.id} onClick={() => onOccurrenceOpen(child.id)}
                    className="w-full flex items-center gap-2 px-4 py-2 text-left hover:bg-[var(--input-bg)] transition-colors">
                    <span className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-black shrink-0"
                      style={{ background: tone.bg, color: tone.color, border: `1px solid ${tone.border}` }}>
                      {done ? <Check size={10} /> : i + 1}
                    </span>
                    <span className={`text-[11px] font-bold whitespace-nowrap ${child.isOverdue ? 'text-[var(--accent-red)]' : 'text-[var(--text-main)]'}`}>
                      {formatOccurrenceDate(child.end || child.start)}
                    </span>
                    <span className="flex-1" />
                    <span className="text-[9px] font-black uppercase tracking-wider truncate max-w-[110px]"
                      style={{ color: cfg.color }}>
                      {cfg.label}
                    </span>
                    <Eye size={12} className="text-[var(--text-muted)] shrink-0" />
                  </button>
                );
              })}
            </div>
          )}
        </>
      )}
    </motion.div>
  );
};

export default TaskCard;
