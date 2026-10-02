import React, { useState, useEffect, useCallback } from 'react';
import { Search, ArrowUpDown, ChevronRight, Layers } from 'lucide-react';
import { getLmsList } from '../../services/reportApi';

// LMS-wise landing view: all LMS (batches) grouped, with a performance table.
// Clicking a row drills into that LMS's full dashboard (LmsPanel).
const RATING = { active: 'var(--accent-green)', hold: 'var(--accent-orange)', inactive: 'var(--accent-red)' };

const fmtDate = (v) => {
  if (!v) return '—';
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString('en-US', { day: '2-digit', month: 'short', year: 'numeric' });
};

const LmsListPanel = ({ companyId, onSelect }) => {
  const [data, setData] = useState({ items: [], total: 0 });
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState('completionRate');
  const [order, setOrder] = useState('desc');
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const PAGE_SIZE = 12;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = { search, sort, order, skip: page * PAGE_SIZE, limit: PAGE_SIZE, ...(companyId ? { company_id: companyId } : {}) };
      const res = await getLmsList(params);
      setData(res);
    } catch (e) { /* handled globally */ }
    finally { setLoading(false); }
  }, [companyId, search, sort, order, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(0); }, [companyId, search]);

  const handleSort = (key) => {
    if (sort === key) setOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
    else { setSort(key); setOrder('desc'); }
  };

  const cols = [
    ['name', 'LMS'], ['company', 'Company'], ['totalUsers', 'Users'], ['activeUsers', 'Active'],
    ['coursesAssigned', 'Assigned'], ['coursesCompleted', 'Completed'], ['completionRate', 'Completion %'],
    ['avgScore', 'Avg Score'], ['lastActivity', 'Last Activity'], ['status', 'Status'],
  ];

  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-hidden shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 p-5 border-b border-[var(--border)]">
        <div>
          <h4 className="text-[15px] font-black text-[var(--text-main)] uppercase italic tracking-tight">LMS Performance</h4>
          <p className="text-[10px] text-[var(--text-muted)] font-bold uppercase tracking-wider opacity-60">Grouped by LMS — click a row for the full LMS dashboard</p>
        </div>
        <div className="relative min-w-[220px]">
          <Search size={13} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search LMS..."
            className="w-full pl-9 pr-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left min-w-[860px]">
          <thead>
            <tr className="border-b border-[var(--border)]">
              {cols.map(([key, label]) => (
                <th key={key} onClick={() => handleSort(key)}
                  className="px-4 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest cursor-pointer select-none hover:text-[var(--text-main)]">
                  <span className="inline-flex items-center gap-1">{label}{sort === key && <ArrowUpDown size={11} />}</span>
                </th>
              ))}
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={11} className="px-4 py-12 text-center text-[12px] font-bold text-[var(--text-muted)]">Loading…</td></tr>
            ) : (data.items || []).length === 0 ? (
              <tr><td colSpan={11} className="px-4 py-16 text-center">
                <Layers size={36} className="mx-auto mb-3 text-[var(--text-muted)] opacity-30" />
                <p className="text-[12px] font-bold text-[var(--text-muted)]">No LMS found{companyId ? ' for this company' : ''}.</p>
              </td></tr>
            ) : data.items.map((l) => (
              <tr key={l.id} onClick={() => onSelect(l.id)}
                className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)] transition-colors cursor-pointer">
                <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{l.name}</td>
                <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]">{l.company}</td>
                <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{l.totalUsers}</td>
                <td className="px-4 py-3 text-[13px] font-bold text-[var(--accent-green)]">{l.activeUsers}</td>
                <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{l.coursesAssigned}</td>
                <td className="px-4 py-3 text-[13px] font-bold text-[var(--accent-green)]">{l.coursesCompleted}</td>
                <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{l.completionRate}%</td>
                <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{l.avgScore}%</td>
                <td className="px-4 py-3 text-[12px] text-[var(--text-muted)]">{fmtDate(l.lastActivity)}</td>
                <td className="px-4 py-3">
                  <span className="px-2 py-1 rounded-lg text-[10px] font-black uppercase tracking-wider"
                    style={{ color: RATING[l.status] || 'var(--text-muted)', background: 'var(--input-bg)' }}>{l.status}</span>
                </td>
                <td className="px-4 py-3 text-[var(--text-muted)]"><ChevronRight size={16} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.total > PAGE_SIZE && (
        <div className="flex items-center justify-between p-4 border-t border-[var(--border)]">
          <p className="text-[11px] font-bold text-[var(--text-muted)]">
            {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, data.total)} of {data.total}
          </p>
          <div className="flex items-center gap-2">
            <button disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}
              className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Prev</button>
            <button disabled={(page + 1) * PAGE_SIZE >= data.total} onClick={() => setPage((p) => p + 1)}
              className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Next</button>
          </div>
        </div>
      )}
    </div>
  );
};

export default LmsListPanel;
