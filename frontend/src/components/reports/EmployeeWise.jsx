import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Search, ArrowUpDown, ChevronRight, LayoutGrid, List as ListIcon,
  Download, FileDown, FileSpreadsheet, FileText, ChevronDown, Users,
} from 'lucide-react';
import { getEmployeesWide, exportEmployeesWide, downloadCsv } from '../../services/reportApi';
import { fmtDate } from './reportPeriods';
import { motion } from 'framer-motion';

const RATING_COLOR = {
  Excellent: 'var(--accent-green)', Good: 'var(--accent-indigo)',
  Average: 'var(--accent-orange)', 'Needs Attention': 'var(--accent-red)',
};

// Attendance-percentage color bands (matches LMS report): >=90 green, 75-89 yellow, 60-74 orange, <60 red.
const attColor = (r) => {
  const v = Number(r) || 0;
  if (v >= 90) return 'var(--accent-green)';
  if (v >= 75) return 'var(--accent-yellow)';
  if (v >= 60) return 'var(--accent-orange)';
  return 'var(--accent-red)';
};

const dt = (v) => (v ? fmtDate(v) : '—');

const PAGE_SIZE = 12;

const EmployeeWise = ({ params, onOpenEmployee }) => {
  const [view, setView] = useState('card'); // 'card' | 'list'
  const [data, setData] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState('score');
  const [order, setOrder] = useState('desc');
  const [page, setPage] = useState(0);
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getEmployeesWide({ ...params, search, sort, order, skip: page * PAGE_SIZE, limit: PAGE_SIZE });
      setData(res);
    } catch (e) { /* handled globally */ }
    finally { setLoading(false); }
  }, [params, search, sort, order, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(0); }, [params, search, sort, order]);

  const exportRef = useRef(null);
  useEffect(() => {
    if (!exportOpen) return undefined;
    const h = (e) => { if (exportRef.current && !exportRef.current.contains(e.target)) setExportOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, [exportOpen]);

  const handleSort = (key) => {
    if (sort === key) setOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
    else { setSort(key); setOrder('desc'); }
  };

  const doExport = async (format) => {
    setExportOpen(false);
    setExporting(format);
    try { await exportEmployeesWide({ format, ...params, search, sort, order }); }
    catch (e) { /* handled globally */ }
    finally { setExporting(''); }
  };

  const items = data.items || [];
  const cols = [
    ['name', 'Employee'], ['employeeId', 'Emp ID'], ['company', 'Company'], ['department', 'Dept'], ['designation', 'Designation'],
    ['assigned', 'Task Assigned'], ['completed', 'Task Done'], ['pending', 'Pending'], ['overdue', 'Overdue'],
    ['totalSessions', 'Sessions'], ['sessionsAttended', 'Attended'], ['sessionsMissed', 'Missed'], ['attendanceRate', 'Attendance %'],
    ['avgAssessment', 'Assessment'], ['completionRate', 'Completion %'],
    ['lastLogin', 'Last Login'], ['lastActivity', 'Last Activity'], ['rating', 'Status'],
  ];
  const NO_SORT = new Set(['name', 'employeeId', 'company', 'department', 'designation', 'lastLogin', 'lastActivity']);

  // Export the full employee dataset as CSV (all real fields) — respects current filters.
  const exportWideCsv = async () => {
    setExportOpen(false); setExporting('csv');
    try {
      const res = await getEmployeesWide({ ...params, search, sort, order, limit: 5000 });
      const headers = ['Employee', 'Email', 'Emp ID', 'Company', 'Department', 'Designation',
        'Task Assigned', 'Task Completed', 'Pending', 'Overdue',
        'Total Sessions', 'Sessions Attended', 'Sessions Missed', 'Attendance %',
        'Assessment %', 'Completion %', 'Total Logins', 'Last Login', 'Last Activity', 'Status'];
      const rows = (res.items || []).map((e) => [
        e.name, e.email, e.employeeId, e.company, e.department, e.designation,
        e.assigned, e.completed, e.pending, e.overdue,
        e.totalSessions, e.sessionsAttended, e.sessionsMissed, `${e.attendanceRate}%`,
        `${e.avgAssessment}%`, `${e.completionRate}%`, e.totalLogins, dt(e.lastLogin), dt(e.lastActivity), e.rating,
      ]);
      downloadCsv('employee_report.csv', headers, rows);
    } catch (e) { /* handled globally */ }
    finally { setExporting(''); }
  };

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search size={13} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search name, company..."
            className="w-full pl-9 pr-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
        </div>
        <div className="flex items-center gap-2">
          {/* View toggle */}
          <div className="flex items-center gap-1 bg-[var(--input-bg)] border border-[var(--border)] p-1 rounded-xl">
            <button onClick={() => setView('card')} title="Card view"
              className={`p-2 rounded-lg transition-all ${view === 'card' ? 'bg-[var(--accent-indigo)] text-white' : 'text-[var(--text-muted)]'}`}><LayoutGrid size={15} /></button>
            <button onClick={() => setView('list')} title="List view"
              className={`p-2 rounded-lg transition-all ${view === 'list' ? 'bg-[var(--accent-indigo)] text-white' : 'text-[var(--text-muted)]'}`}><ListIcon size={15} /></button>
          </div>
          {/* Export */}
          <div className="relative" ref={exportRef}>
            <button onClick={() => setExportOpen((o) => !o)} disabled={!!exporting}
              className="flex items-center gap-1.5 px-4 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-sm hover:opacity-90 transition-all disabled:opacity-50">
              <Download size={14} /> {exporting ? 'Exporting…' : 'Export'} <ChevronDown size={13} className={`transition-transform ${exportOpen ? 'rotate-180' : ''}`} />
            </button>
            {exportOpen && (
              <div className="absolute right-0 mt-2 w-40 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-lg z-50 overflow-hidden">
                {[['csv', 'CSV', FileDown], ['xlsx', 'Excel', FileSpreadsheet], ['pdf', 'PDF', FileText]].map(([fmt, label, Icon]) => (
                  <button key={fmt} onClick={() => (fmt === 'csv' ? exportWideCsv() : doExport(fmt))} className="w-full flex items-center gap-2 px-4 py-2.5 text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)] transition-all">
                    <Icon size={14} /> {label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-44 rounded-[24px] bg-[var(--input-bg)] animate-pulse" />)}
        </div>
      ) : items.length === 0 ? (
        <div className="py-16 text-center">
          <Users size={40} className="mx-auto mb-3 text-[var(--text-muted)] opacity-30" />
          <p className="text-[13px] font-bold text-[var(--text-muted)]">No employees for this period.</p>
        </div>
      ) : view === 'card' ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          {items.map((e, i) => (
            <motion.div key={e.id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i * 0.03, 0.3) }}
              onClick={() => onOpenEmployee(e.id)}
              className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] p-5 shadow-sm hover:shadow-md transition-all cursor-pointer">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-12 h-12 rounded-2xl flex items-center justify-center text-white font-black shrink-0" style={{ background: 'var(--avatar-bg)' }}>
                  {(e.name?.charAt(0) || 'U').toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="text-[14px] font-black text-[var(--text-main)] truncate">{e.name}</h3>
                  <p className="text-[11px] font-bold text-[var(--text-muted)] truncate">{e.company || '—'} · {e.department}</p>
                </div>
                <span className="text-[22px] font-black" style={{ color: RATING_COLOR[e.rating] }}>{e.score}</span>
              </div>
              <div className="grid grid-cols-4 gap-2 text-center">
                {[['Assigned', e.assigned, 'var(--text-main)'], ['Done', e.completed, 'var(--accent-green)'], ['Pending', e.pending, 'var(--accent-orange)'], ['Overdue', e.overdue, 'var(--accent-red)']].map(([l, v, c]) => (
                  <div key={l} className="bg-[var(--input-bg)] rounded-xl py-2">
                    <p className="text-[15px] font-black" style={{ color: c }}>{v}</p>
                    <p className="text-[8px] font-black text-[var(--text-muted)] uppercase tracking-wider">{l}</p>
                  </div>
                ))}
              </div>
              <div className="flex items-center justify-between mt-4 pt-3 border-t border-[var(--border)] text-[11px] font-bold">
                <span className="text-[var(--text-muted)]">Completion <span className="text-[var(--text-main)]">{e.completionRate}%</span></span>
                <span className="text-[var(--text-muted)]">Attendance <span style={{ color: attColor(e.attendanceRate) }}>{e.attendanceRate}%</span></span>
                <span className="text-[var(--accent-indigo)] flex items-center gap-1">View <ChevronRight size={13} /></span>
              </div>
            </motion.div>
          ))}
        </div>
      ) : (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left min-w-[1750px]">
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--input-bg)]">
                  {cols.map(([key, label]) => {
                    const sortable = !NO_SORT.has(key);
                    return (
                      <th key={key} onClick={() => sortable && handleSort(key)}
                        className={`px-4 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest whitespace-nowrap select-none ${sortable ? 'cursor-pointer hover:text-[var(--text-main)]' : ''} ${key === 'name' ? 'sticky left-0 z-20 bg-[var(--input-bg)]' : ''}`}>
                        <span className="inline-flex items-center gap-1">{label}{sort === key && <ArrowUpDown size={11} />}</span>
                      </th>
                    );
                  })}
                  <th className="sticky right-0 z-20 bg-[var(--input-bg)] border-l border-[var(--border)] px-4 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest text-center">Action</th>
                </tr>
              </thead>
              <tbody>
                {items.map((e) => (
                  <tr key={e.id} className="group border-b border-[var(--border)] last:border-0 hover:bg-[var(--input-bg)] transition-colors">
                    <td className="sticky left-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--input-bg)] px-4 py-3 whitespace-nowrap">
                      <p className="text-[13px] font-bold text-[var(--text-main)]">{e.name}</p>
                      <p className="text-[10px] text-[var(--text-muted)]">{e.email}</p>
                    </td>
                    <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)] whitespace-nowrap">{e.employeeId || '—'}</td>
                    <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)] whitespace-nowrap">{e.company || '—'}</td>
                    <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)] whitespace-nowrap">{e.department}</td>
                    <td className="px-4 py-3 text-[12px] font-bold text-[var(--text-muted)] whitespace-nowrap">{e.designation || '—'}</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{e.assigned}</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--accent-green)]">{e.completed}</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--accent-orange)]">{e.pending}</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--accent-red)]">{e.overdue}</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{e.totalSessions}</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--accent-green)]">{e.sessionsAttended}</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--accent-red)]">{e.sessionsMissed}</td>
                    <td className="px-4 py-3 text-[13px] font-black" style={{ color: attColor(e.attendanceRate) }}>{e.attendanceRate}%</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{e.avgAssessment}%</td>
                    <td className="px-4 py-3 text-[13px] font-bold text-[var(--text-main)]">{e.completionRate}%</td>
                    <td className="px-4 py-3 text-[11px] font-bold text-[var(--text-muted)] whitespace-nowrap">{dt(e.lastLogin)}</td>
                    <td className="px-4 py-3 text-[11px] font-bold text-[var(--text-muted)] whitespace-nowrap">{dt(e.lastActivity)}</td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-1 rounded-lg text-[10px] font-black uppercase tracking-wider" style={{ color: RATING_COLOR[e.rating], background: 'var(--input-bg)' }}>{e.rating}</span>
                    </td>
                    <td className="sticky right-0 z-10 bg-[var(--bg-card)] group-hover:bg-[var(--input-bg)] border-l border-[var(--border)] px-4 py-3 text-center">
                      <button onClick={() => onOpenEmployee(e.id)} title="View details"
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] transition-colors whitespace-nowrap">
                        View <ChevronRight size={13} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Pagination */}
      {data.total > PAGE_SIZE && (
        <div className="flex items-center justify-between">
          <p className="text-[11px] font-bold text-[var(--text-muted)]">{page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, data.total)} of {data.total}</p>
          <div className="flex items-center gap-2">
            <button disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Prev</button>
            <button disabled={(page + 1) * PAGE_SIZE >= data.total} onClick={() => setPage((p) => p + 1)} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Next</button>
          </div>
        </div>
      )}

    </div>
  );
};

export default EmployeeWise;
