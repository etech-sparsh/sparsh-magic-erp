import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Search, ChevronDown, ArrowUpDown, Users, ExternalLink, Download, FileDown, FileSpreadsheet, FileText } from 'lucide-react';
import { getCompanyEmployees, exportCompanyEmployees } from '../../services/reportApi';
import TaskRows from './TaskRows';

// Columns match the reference layout: #, Name, Emp ID, Dept, Designation, Assigned, Completed,
// Pending, Overdue, Attendance %, Assessment, Courses, Actions.
const COLS = [
  ['name', 'Employee Name'], ['empId', 'Employee ID'], ['department', 'Department'], ['designation', 'Designation'],
  ['assigned', 'Assigned'], ['completed', 'Completed'], ['pending', 'Pending'], ['overdue', 'Overdue'],
  ['attendanceRate', 'Attendance %'], ['avgAssessment', 'Assessment'], ['coursesCompleted', 'Courses'],
];
const SORTABLE = new Set(['assigned', 'completed', 'pending', 'overdue', 'attendanceRate', 'avgAssessment']);

// Attendance-percentage color bands, consistent with the rest of the reports.
const attColor = (r) => {
  const v = Number(r) || 0;
  if (v >= 90) return 'var(--accent-green)';
  if (v >= 75) return 'var(--accent-yellow)';
  if (v >= 60) return 'var(--accent-orange)';
  return 'var(--accent-red)';
};

const EmployeeTable = ({ company, params, onOpenEmployee, embedded = false }) => {
  const [data, setData] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState('score');
  const [order, setOrder] = useState('desc');
  const [page, setPage] = useState(0);
  const [expandedEmp, setExpandedEmp] = useState(null);
  const PAGE_SIZE = 10;

  const load = useCallback(async () => {
    setLoading(true); setError(false);
    try {
      const res = await getCompanyEmployees(company.id, { ...params, search, sort, order, skip: page * PAGE_SIZE, limit: PAGE_SIZE });
      setData(res);
    } catch (e) { setError(true); }
    finally { setLoading(false); }
  }, [company.id, params, search, sort, order, page]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { setPage(0); setExpandedEmp(null); }, [company.id, params, search, sort, order]);

  const handleSort = (key) => {
    if (!SORTABLE.has(key)) return;
    if (sort === key) setOrder((o) => (o === 'asc' ? 'desc' : 'asc'));
    else { setSort(key); setOrder('desc'); }
  };

  const cell = 'px-3 py-3 text-[12px] font-bold text-[var(--text-main)] whitespace-nowrap';

  // Export this company's employees (CSV / Excel / PDF), respecting current filters/search.
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState('');
  const exportRef = useRef(null);
  useEffect(() => {
    if (!exportOpen) return undefined;
    const h = (e) => { if (exportRef.current && !exportRef.current.contains(e.target)) setExportOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, [exportOpen]);

  const doExport = async (format) => {
    setExportOpen(false); setExporting(format);
    try { await exportCompanyEmployees(company.id, { format, ...params, search, sort, order }); }
    catch (e) { /* handled globally */ }
    finally { setExporting(''); }
  };

  return (
    <div className={embedded ? '' : 'bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] overflow-hidden shadow-sm'}>
      <div className={`flex flex-wrap items-center justify-between gap-3 ${embedded ? 'pb-3' : 'p-5 border-b border-[var(--border)]'}`}>
        {embedded ? (
          <span className="text-[11px] font-black text-[var(--text-muted)] uppercase tracking-widest">{data.total} Employees</span>
        ) : (
          <h3 className="text-[15px] font-black text-[var(--text-main)] uppercase italic tracking-tight">
            Employee-wise Report · <span className="text-[var(--accent-indigo)]">{company.name}</span>
          </h3>
        )}
        <div className="flex items-center gap-2 flex-wrap w-full sm:w-auto">
          <div className="relative shrink-0" ref={exportRef}>
            <button onClick={() => setExportOpen((o) => !o)} disabled={!!exporting || (data.items || []).length === 0}
              className="flex items-center gap-1.5 px-4 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-sm hover:opacity-90 transition-all disabled:opacity-50">
              <Download size={14} /> {exporting ? 'Exporting…' : 'Export'} <ChevronDown size={13} className={`transition-transform ${exportOpen ? 'rotate-180' : ''}`} />
            </button>
            {exportOpen && (
              <div className="absolute right-0 mt-2 w-40 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-lg z-50 overflow-hidden">
                {[['csv', 'CSV', FileDown], ['xlsx', 'Excel', FileSpreadsheet], ['pdf', 'PDF', FileText]].map(([fmt, label, Icon]) => (
                  <button key={fmt} onClick={() => doExport(fmt)} className="w-full flex items-center gap-2 px-4 py-2.5 text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)] transition-all">
                    <Icon size={14} /> {label}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="relative flex-1 min-w-[150px]">
            <Search size={13} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search employee..."
              className="w-full pl-9 pr-3 py-2.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-xl text-[12px] font-bold outline-none focus:border-[var(--accent-indigo)]" />
          </div>
        </div>
      </div>

      {error ? (
        <p className="px-4 py-12 text-center text-[12px] font-bold text-[var(--accent-red)]">Failed to load employees.</p>
      ) : loading ? (
        <div className="p-5 space-y-2">{Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-10 rounded-xl bg-[var(--input-bg)] animate-pulse" />)}</div>
      ) : (data.items || []).length === 0 ? (
        <div className="py-14 text-center"><Users size={36} className="mx-auto mb-3 text-[var(--text-muted)] opacity-30" /><p className="text-[13px] font-bold text-[var(--text-muted)]">No employees found.</p></div>
      ) : (
        <>
          {/* Desktop / tablet: horizontal-scroll table (scroll contained inside this wrapper) */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full text-left min-w-[1040px]">
              <thead>
                <tr className="border-b border-[var(--border)] bg-[var(--input-bg)]">
                  <th className="sticky left-0 z-20 bg-[var(--input-bg)] w-[46px] min-w-[46px] px-3 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">#</th>
                  {COLS.map(([k, label]) => (
                    <th key={k} onClick={() => handleSort(k)} className={`px-3 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest whitespace-nowrap ${SORTABLE.has(k) ? 'cursor-pointer hover:text-[var(--text-main)]' : ''} ${k === 'name' ? 'sticky left-[46px] z-20 bg-[var(--input-bg)]' : ''}`}>
                      <span className="inline-flex items-center gap-1">{label}{sort === k && <ArrowUpDown size={10} />}</span>
                    </th>
                  ))}
                  <th className="sticky right-0 z-20 bg-[var(--input-bg)] border-l border-[var(--border)] px-3 py-3 text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest text-center">Actions</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((e, i) => {
                  const isOpen = expandedEmp === e.id;
                  const stickyBg = isOpen ? 'bg-[var(--accent-indigo-bg)]' : 'bg-[var(--bg-card)]';
                  return (
                    <React.Fragment key={e.id}>
                      <tr
                        onClick={() => setExpandedEmp(isOpen ? null : e.id)}
                        role="button" tabIndex={0} aria-expanded={isOpen}
                        onKeyDown={(ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); setExpandedEmp(isOpen ? null : e.id); } }}
                        className={`group border-b border-[var(--border)] cursor-pointer transition-colors outline-none focus-visible:bg-[var(--input-bg)] ${isOpen ? 'bg-[var(--accent-indigo-bg)]' : 'hover:bg-[var(--input-bg)]'}`}>
                        <td className={`sticky left-0 z-10 ${stickyBg} group-hover:bg-[var(--input-bg)] w-[46px] min-w-[46px] px-3 py-3 text-[12px] font-black text-[var(--text-muted)]`}>{page * PAGE_SIZE + i + 1}</td>
                        <td className={`${cell} font-black sticky left-[46px] z-10 ${stickyBg} group-hover:bg-[var(--input-bg)]`}>{e.name}</td>
                        <td className={`${cell} text-[var(--text-muted)]`}>—</td>
                        <td className={cell}>{e.department}</td>
                        <td className={`${cell} text-[var(--text-muted)]`}>—</td>
                        <td className={cell}>{e.assigned}</td>
                        <td className={`${cell} text-[var(--accent-green)]`}>{e.completed}</td>
                        <td className={`${cell} text-[var(--accent-orange)]`}>{e.pending}</td>
                        <td className={`${cell} text-[var(--accent-red)]`}>{e.overdue}</td>
                        <td className="px-3 py-3 text-[12px] font-black whitespace-nowrap" style={{ color: attColor(e.attendanceRate) }}>{e.attendanceRate}%</td>
                        <td className={cell}>{e.avgAssessment}%</td>
                        <td className={`${cell} text-[var(--text-muted)]`}>—</td>
                        <td className={`sticky right-0 z-10 ${stickyBg} group-hover:bg-[var(--input-bg)] border-l border-[var(--border)] px-3 py-3 text-center whitespace-nowrap`}>
                          <button onClick={(ev) => { ev.stopPropagation(); onOpenEmployee(e.id); }} title="Open full report" className="p-1 text-[var(--text-muted)] hover:text-[var(--accent-indigo)]"><ExternalLink size={14} /></button>
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="bg-[var(--bg-main)]">
                          <td colSpan={COLS.length + 2} className="p-0"><TaskRows employeeId={e.id} params={params} /></td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Mobile: stacked cards (tap card → task details below; no wide table → no overflow) */}
          <div className="md:hidden space-y-3">
            {data.items.map((e, i) => {
              const isOpen = expandedEmp === e.id;
              return (
                <div key={e.id} className="border border-[var(--border)] rounded-2xl bg-[var(--bg-card)] overflow-hidden">
                  <div
                    role="button" tabIndex={0} aria-expanded={isOpen}
                    onClick={() => setExpandedEmp(isOpen ? null : e.id)}
                    onKeyDown={(ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); setExpandedEmp(isOpen ? null : e.id); } }}
                    className="p-3 cursor-pointer outline-none focus-visible:bg-[var(--input-bg)]">
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-[13px] font-black text-[var(--text-main)] truncate">{page * PAGE_SIZE + i + 1}. {e.name}</p>
                        <p className="text-[11px] font-bold text-[var(--text-muted)] truncate">{e.department}</p>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <button onClick={(ev) => { ev.stopPropagation(); onOpenEmployee(e.id); }} title="Open full report"
                          className="p-2 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--accent-indigo)]"><ExternalLink size={14} /></button>
                        <ChevronDown size={18} className={`transition-transform ${isOpen ? 'rotate-180 text-[var(--accent-indigo)]' : 'text-[var(--text-muted)]'}`} />
                      </div>
                    </div>
                    <div className="grid grid-cols-3 gap-2 mt-3">
                      {[
                        ['Assigned', e.assigned, 'var(--text-main)'],
                        ['Completed', e.completed, 'var(--accent-green)'],
                        ['Pending', e.pending, 'var(--accent-orange)'],
                        ['Overdue', e.overdue, 'var(--accent-red)'],
                        ['Attendance', `${e.attendanceRate}%`, attColor(e.attendanceRate)],
                        ['Assessment', `${e.avgAssessment}%`, 'var(--text-main)'],
                      ].map(([label, val, color]) => (
                        <div key={label} className="bg-[var(--input-bg)] rounded-xl py-2 text-center">
                          <p className="text-[14px] font-black" style={{ color }}>{val}</p>
                          <p className="text-[8px] font-black text-[var(--text-muted)] uppercase tracking-wider">{label}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                  {isOpen && <div className="border-t border-[var(--border)]"><TaskRows employeeId={e.id} params={params} /></div>}
                </div>
              );
            })}
          </div>
        </>
      )}

      {data.total > PAGE_SIZE && (
        <div className="flex items-center justify-between p-4 border-t border-[var(--border)]">
          <p className="text-[11px] font-bold text-[var(--text-muted)]">Showing {page * PAGE_SIZE + 1} to {Math.min((page + 1) * PAGE_SIZE, data.total)} of {data.total} entries</p>
          <div className="flex items-center gap-2">
            <button disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Prev</button>
            <button disabled={(page + 1) * PAGE_SIZE >= data.total} onClick={() => setPage((p) => p + 1)} className="px-3 py-1.5 rounded-lg text-[11px] font-black uppercase tracking-widest bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] disabled:opacity-40">Next</button>
          </div>
        </div>
      )}
    </div>
  );
};

export default EmployeeTable;
