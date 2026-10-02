import React, { useState, useEffect, useCallback } from 'react';
import { ListChecks, CheckCircle2, Clock, AlertTriangle, Percent, Search, FileDown } from 'lucide-react';
import { getReportsOverview, getEmployeesWide, downloadCsv } from '../../services/reportApi';

const PAGE_SIZE = 12;

const RATING_COLOR = {
  Excellent: 'var(--accent-green)', Good: 'var(--accent-indigo)',
  Average: 'var(--accent-orange)', 'Needs Attention': 'var(--accent-red)',
};

const Kpi = ({ label, value, icon: Icon, color }) => (
  <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-4 shadow-sm">
    <div className="flex items-center gap-1.5 mb-2">
      <Icon size={14} style={{ color: color || 'var(--accent-indigo)' }} />
      <span className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-wider truncate">{label}</span>
    </div>
    <p className="text-2xl font-black text-[var(--text-main)]">{value ?? '—'}</p>
  </div>
);

// Task Report — org task KPIs (overview) + employee-wise task status (employees-wide). Real data.
const TaskReport = ({ params, onOpenEmployee }) => {
  const [kpi, setKpi] = useState({});
  const [data, setData] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ov, emp] = await Promise.all([
        getReportsOverview(params),
        getEmployeesWide({ ...params, search, skip: page * PAGE_SIZE, limit: PAGE_SIZE }),
      ]);
      setKpi(ov || {});
      setData(emp || { items: [], total: 0 });
    } catch (e) { /* handled globally */ }
    finally { setLoading(false); }
  }, [params, search, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(0); }, [params, search]);

  const items = data.items || [];

  const exportCsv = async () => {
    try {
      const res = await getEmployeesWide({ ...params, search, limit: 5000 });
      const headers = ['Employee', 'Company', 'Department', 'Assigned', 'Completed', 'Pending', 'Overdue', 'Completion %', 'Status'];
      const rows = (res.items || []).map((e) => [e.name, e.company, e.department, e.assigned, e.completed, e.pending, e.overdue, `${e.completionRate}%`, e.rating]);
      downloadCsv('task_report.csv', headers, rows);
    } catch (e) { /* handled globally */ }
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <Kpi label="Total Tasks" value={kpi.totalTasks} icon={ListChecks} />
        <Kpi label="Completed" value={kpi.completedTasks} icon={CheckCircle2} color="var(--accent-green)" />
        <Kpi label="Pending" value={kpi.pendingTasks} icon={Clock} color="var(--accent-orange)" />
        <Kpi label="Overdue" value={kpi.overdueTasks} icon={AlertTriangle} color="var(--accent-red)" />
        <Kpi label="Completion Rate" value={kpi.avgCompletionRate != null ? `${kpi.avgCompletionRate}%` : '—'} icon={Percent} />
      </div>

      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-hidden shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 p-5 border-b border-[var(--border)]">
          <h3 className="text-[15px] font-black text-[var(--text-main)] uppercase italic tracking-tight">Employee-wise Task Status</h3>
          <div className="flex items-center gap-2">
            <button onClick={exportCsv} disabled={!items.length}
              className="flex items-center gap-1.5 px-3 py-2.5 rounded-xl text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)] disabled:opacity-40">
              <FileDown size={13} /> CSV
            </button>
            <div className="relative min-w-[190px]">
              <Search size={13} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search employee..."
                className="w-full pl-9 pr-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
            </div>
          </div>
        </div>

        {loading ? (
          <div className="p-5 space-y-2">{Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-10 rounded-xl bg-[var(--input-bg)] animate-pulse" />)}</div>
        ) : items.length === 0 ? (
          <div className="py-16 text-center"><ListChecks size={38} className="mx-auto mb-3 text-[var(--text-muted)] opacity-30" /><p className="text-[13px] font-bold text-[var(--text-muted)]">No task data for these filters.</p></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[950px]">
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--input-bg)]">
                  {['Employee', 'Company', 'Department', 'Assigned', 'Completed', 'Pending', 'Overdue', 'Completion %', 'Status', 'Action'].map((h) => (
                    <th key={h} className={`px-4 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest whitespace-nowrap ${h === 'Action' ? 'text-center' : ''}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((e) => (
                  <tr key={e.id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)] transition-colors">
                    <td className="px-4 py-3 whitespace-nowrap">
                      <p className="text-[13px] font-bold text-[var(--text-main)]">{e.name}</p>
                      <p className="text-[10px] text-[var(--text-muted)]">{e.email}</p>
                    </td>
                    <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)] whitespace-nowrap">{e.company || '—'}</td>
                    <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)] whitespace-nowrap">{e.department}</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{e.assigned}</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--accent-green)]">{e.completed}</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--accent-orange)]">{e.pending}</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--accent-red)]">{e.overdue}</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{e.completionRate}%</td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-1 rounded-lg text-[10px] font-black uppercase tracking-wider" style={{ color: RATING_COLOR[e.rating], background: 'var(--input-bg)' }}>{e.rating}</span>
                    </td>
                    <td className="px-4 py-3 text-center">
                      <button onClick={() => onOpenEmployee?.(e.id)} title="View tasks"
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] transition-colors">
                        View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {data.total > PAGE_SIZE && (
          <div className="flex items-center justify-between p-4 border-t border-[var(--border)]">
            <p className="text-[11px] font-bold text-[var(--text-muted)]">{page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, data.total)} of {data.total}</p>
            <div className="flex items-center gap-2">
              <button disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Prev</button>
              <button disabled={(page + 1) * PAGE_SIZE >= data.total} onClick={() => setPage((p) => p + 1)} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Next</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default TaskReport;
