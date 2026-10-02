import React, { useState, useEffect } from 'react';
import { Loader2 } from 'lucide-react';
import { getEmployeeAssignments } from '../../services/reportApi';
import { fmtDate } from './reportPeriods';

const STATUS_COLOR = {
  pending: 'var(--accent-orange)', accepted: 'var(--accent-indigo)', in_progress: 'var(--accent-indigo)',
  dependent_on_others: 'var(--accent-yellow)', blocked: 'var(--accent-red)',
  verification: 'var(--accent-yellow)', dependency_completed: 'var(--accent-indigo)',
  completed: 'var(--accent-green)',
};

// Per-employee task detail — real data via getEmployeeAssignments (filter/date-range aware).
// Responsive: table on desktop/tablet, cards on mobile. Shared by EmployeeTable (company modal
// row expand) and EmployeeWise (Employee Calendar Performance modal) — single source of truth.
const TaskRows = ({ employeeId, params }) => {
  const [tasks, setTasks] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    getEmployeeAssignments(employeeId, { ...params, limit: 50 })
      .then((r) => { if (alive) setTasks(r.items || []); })
      .catch(() => { if (alive) setTasks([]); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [employeeId, params]);

  if (loading) return <div className="flex items-center gap-2 py-4 px-4 text-[12px] font-bold text-[var(--text-muted)]"><Loader2 size={14} className="animate-spin" /> Loading tasks…</div>;
  if (!tasks || tasks.length === 0) return <p className="py-4 px-4 text-[12px] font-bold text-[var(--text-muted)]">No tasks in this period.</p>;

  const StatusPill = ({ t }) => (
    <span className="px-2 py-0.5 rounded-lg text-[9px] font-black uppercase tracking-wider shrink-0"
      style={{ color: STATUS_COLOR[t.status], background: 'var(--input-bg)' }}>{t.statusLabel}</span>
  );

  return (
    <div className="bg-[var(--bg-main)] rounded-xl border border-[var(--border)] m-2 p-1.5">
      {/* Desktop / tablet: task table (scroll contained here) */}
      <div className="hidden md:block overflow-x-auto rounded-lg">
        <table className="w-full text-left min-w-[880px]">
          <thead>
            <tr className="border-b border-[var(--border)]">
              {['Task Name', 'Module', 'Assigned Date', 'Due Date', 'Completed Date', 'Priority', 'Status', 'Assigned By', 'Score'].map((h) => (
                <th key={h} className="px-3 py-2 text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tasks.map((t) => (
              <tr key={t.id} className="border-b border-[var(--border)] last:border-0">
                <td className="px-3 py-2 text-[12px] font-bold text-[var(--text-main)] max-w-[220px] truncate">{t.title}</td>
                <td className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{t.module}</td>
                <td className="px-3 py-2 text-[11px] text-[var(--text-muted)] whitespace-nowrap">{fmtDate(t.assignedDate)}</td>
                <td className="px-3 py-2 text-[11px] text-[var(--text-muted)] whitespace-nowrap">{fmtDate(t.dueDate)}</td>
                <td className="px-3 py-2 text-[11px] text-[var(--text-muted)] whitespace-nowrap">{fmtDate(t.completedDate)}</td>
                <td className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{t.priority}</td>
                <td className="px-3 py-2"><StatusPill t={t} /></td>
                <td className="px-3 py-2 text-[11px] font-bold text-[var(--text-muted)]">{t.assignedBy || '—'}</td>
                <td className="px-3 py-2 text-[12px] font-black text-[var(--text-main)]">{t.score ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile: task cards (no wide table → no overflow) */}
      <div className="md:hidden space-y-2 p-1">
        {tasks.map((t) => (
          <div key={t.id} className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-3">
            <div className="flex items-start justify-between gap-2">
              <p className="text-[12px] font-black text-[var(--text-main)] min-w-0">{t.title}</p>
              <StatusPill t={t} />
            </div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 mt-2.5">
              {[
                ['Module', t.module], ['Priority', t.priority],
                ['Assigned', fmtDate(t.assignedDate)], ['Due', fmtDate(t.dueDate)],
                ['Completed', fmtDate(t.completedDate)], ['Assigned By', t.assignedBy || '—'],
                ['Score', t.score ?? '—'],
              ].map(([label, val]) => (
                <div key={label} className="min-w-0">
                  <p className="text-[8px] font-black text-[var(--text-muted)] uppercase tracking-wider">{label}</p>
                  <p className="text-[11px] font-bold text-[var(--text-main)] truncate">{val}</p>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default TaskRows;
